package com.kangle.app;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

/**
 * 康乐 Android 壳（无 Gradle / 无 AndroidX，只用 android.jar API 30 的框架 API）。
 *
 * 职责：
 *   1. 全屏硬件加速 WebView 承载云端 H5（http://159.75.94.149:8000/），壳**不内嵌** H5；
 *   2. 放行明文流量（清单 + network_security_config 两条一起上）；
 *   3. 放行麦克风（H5 录音链路）与地理定位回调；
 *   4. 注入唯一的 JS 桥 window.KangleNative（KangleNative 只在**本 WebView** 里存在）；
 *   5. 主文档加载失败时显示本地兜底错误页（绝不白屏）；
 *   6. 承载通知点击回流（onNewIntent -> pendingAction -> __kangleNativeAction）。
 *
 * 本文件只依赖 CONTRACT.md §4.5 冻结的公开签名，不引用任何第三方坐标。
 */
public class MainActivity extends Activity {

    /* ===== 契约冻结的公开常量（§4.5，逐字照抄，不许改名） ===== */

    public  static final String DEFAULT_H5_URL    = "https://sdad.hynu.site/";
    public  static final String META_H5_URL       = "kangle.h5_url";
    public  static final String EXTRA_ROUTE       = "kangle.route";
    public  static final String EXTRA_REMINDER_ID = "kangle.reminder_id";
    public  static final String EXTRA_ACTION      = "kangle.action";
    public  static final String EXTRA_PAYLOAD     = "kangle.payload";
    public  static final int    RC_AUDIO          = 1001;
    public  static final int    RC_NOTIFICATIONS  = 1002;

    /** JS 侧注入名，逐字为 KangleNative（§3.1）。 */
    private static final String JS_INTERFACE_NAME = "KangleNative";

    /** §3.7 冻结的 route 映射。 */
    private static final String ROUTE_MEDICATIONS = "/pages/elder/medications";
    private static final String ROUTE_HOME        = "/pages/elder/home";

    /* ===== 实例状态 ===== */

    private WebView mWebView;

    /** 待派发给 H5 的通知点击 payload（§3.7）；取走即清，保证只投递一次。 */
    private String mPendingAction;

    /** 是否已经 loadUrl 过 H5 主地址（决定 loadH5 走 loadUrl 还是 reload）。 */
    private boolean mH5EverLoaded;

    /** 当前是否停在兜底错误页上（此时 loadH5 必须重新 loadUrl，不能 reload）。 */
    private boolean mOfflineShown;

    // =========================================================================
    // 生命周期
    // =========================================================================

    /**
     * 执行顺序按契约 §4.5 写死：
     * 1) super.onCreate + setContentView(webView)
     * 2) NotificationHelper.ensureChannel —— 必须在第一批通知之前（Android 13 权限框由它触发）
     * 3) 建 WebView -> configureWebView() -> addJavascriptInterface
     * 4) setWebViewClient / setWebChromeClient
     * 5) CookieManager 放行
     * 6) 解析启动 Intent 存成 pendingAction
     * 7) SDK>=23 先要一次 RECORD_AUDIO
     * 8) loadH5()
     */
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // 2) 通知渠道：必须在任何通知之前，且在主线程（这就是 Android 13 弹权限框的时机）
        NotificationHelper.ensureChannel(this);

        // 3) WebView：先配置再注入桥，注入必须在 loadUrl 之前
        mWebView = new WebView(this);
        mWebView.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        configureWebView();
        mWebView.addJavascriptInterface(new NativeBridge(this), JS_INTERFACE_NAME);

        // 4) 客户端
        mWebView.setWebViewClient(new KangleWebViewClient());
        mWebView.setWebChromeClient(new KangleChromeClient());

        // 5) Cookie：H5 的登录态依赖它
        try {
            CookieManager.getInstance().setAcceptCookie(true);
            CookieManager.getInstance().setAcceptThirdPartyCookies(mWebView, true);
        } catch (Throwable t) {
            // 个别 ROM 上 CookieManager 可能不可用，不影响主链路
        }

        // 1) 内容视图
        setContentView(mWebView);

        // 6) 启动 Intent（通知点击冷启动走这条路）
        handleIntent(getIntent());

        // 7) 麦克风权限：H5 录音链路的第一道闸
        if (Build.VERSION.SDK_INT >= 23 && !hasPermission("android.permission.RECORD_AUDIO")) {
            try {
                requestPermissions(new String[]{"android.permission.RECORD_AUDIO"}, RC_AUDIO);
            } catch (Throwable t) {
                // 拿不到就算了，H5 在 onPermissionRequest 里还有第二次机会
            }
        }

        // 8) 载入 H5
        loadH5();
    }

    @Override
    protected void onResume() {
        super.onResume();
        // 幂等补建：渠道必须在主线程存在，否则 Android 13+ 上通知一条都发不出去
        try {
            NotificationHelper.ensureChannel(this);
        } catch (Throwable t) {
            // ensureChannel 内部已幂等，这里只是兜底
        }
    }

    /**
     * launchMode=singleTask（清单 §8.4），通知点击不会新开一个壳，而是走这里。
     * 必须 setIntent，否则后续 getIntent() 拿到的还是旧的启动 Intent。
     */
    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
        dispatchPendingAction();
    }

    @Override
    protected void onDestroy() {
        try {
            if (mWebView != null) {
                mWebView.removeJavascriptInterface(JS_INTERFACE_NAME);
                mWebView.stopLoading();
                mWebView.destroy();
                mWebView = null;
            }
        } catch (Throwable t) {
            // WebView 销毁在某些 ROM 上会抛，忽略即可，不要因此崩掉退出流程
        }
        super.onDestroy();
    }

    /** 返回键先退网页历史，退无可退才退出 App。 */
    @Override
    public void onBackPressed() {
        if (mWebView != null && mWebView.canGoBack()) {
            mWebView.goBack();
            return;
        }
        super.onBackPressed();
    }

    /**
     * 权限结果**不在这里回推**：H5 在页面 onShow 时统一用 checkPermissions() 轮询（§3.4）。
     * 保留覆盖只是为了在部分 ROM 上让框架的回调链完整。
     */
    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
    }

    // =========================================================================
    // 契约公开方法（§4.5）
    // =========================================================================

    /**
     * 从清单 meta-data 读 H5 地址；缺失/为空/读取失败一律回退 DEFAULT_H5_URL。
     * 用 getPackageManager().getApplicationInfo(pkg, GET_META_DATA) 取，避免依赖
     * 不同 API 级别下 getApplicationInfo() 是否自动带 metaData 的差异。
     */
    public String h5Url() {
        try {
            ApplicationInfo ai = getPackageManager().getApplicationInfo(
                    getPackageName(), PackageManager.GET_META_DATA);
            if (ai != null && ai.metaData != null) {
                Object v = ai.metaData.get(META_H5_URL);
                if (v != null) {
                    String s = String.valueOf(v).trim();
                    if (s.length() > 0) return s;
                }
            }
        } catch (Throwable t) {
            // 读取失败就走默认地址
        }
        return DEFAULT_H5_URL;
    }

    /** WebView 访问器，NativeBridge 用它 evaluateJavascript。 */
    public WebView webView() {
        return mWebView;
    }

    /**
     * 有 pendingAction 就 evaluateJavascript 派发，**派发成功之后**才清空；无则什么都不做。
     * 必须用 JSONObject.quote 转义 payload，否则中文标题会把 JS 字符串打断（§3.7）。
     *
     * 取值与清空必须分开：WebView 还没就绪（null）或 evaluateJavascript 抛异常时**保留** payload，
     * H5 侧的 getPendingAction()（拉路径）才拿得到。取走即清会让兜底变成空话（§3.7 / §10.5）。
     */
    public void dispatchPendingAction() {
        String payload = mPendingAction;          // 先读，不消费
        if (payload == null || payload.length() == 0) return;
        WebView wv = mWebView;
        if (wv == null) return;                   // 保留 payload，等下一次 onPageFinished / onNewIntent
        try {
            wv.evaluateJavascript(
                    "window.__kangleNativeAction(" + JSONObject.quote(payload) + ");", null);
            mPendingAction = null;                // 派发成功才清（契约 §3.7：推送成功后也清）
        } catch (Throwable t) {
            // 派发失败不抛给调用方；payload 原样保留，H5 侧仍可在 onShow 时走 getPendingAction 兜底
        }
    }

    /**
     * loadUrl(h5Url())；已加载过则 reload()。
     * 例外：当前停在兜底错误页时必须重新 loadUrl —— reload 只会把错误页再刷一遍（§11.1）。
     */
    public void loadH5() {
        WebView wv = mWebView;
        if (wv == null) return;
        if (mH5EverLoaded && !mOfflineShown) {
            wv.reload();
            return;
        }
        mH5EverLoaded = true;
        mOfflineShown = false;
        try {
            wv.loadUrl(h5Url());
        } catch (Throwable t) {
            showOfflinePage("load_url_failed");
        }
    }

    /**
     * 主文档加载失败时的本地兜底页，绝不白屏。
     * 必须用 loadDataWithBaseURL(null, ...)，不要用 loadData。
     * 兜底页里的 KangleNative.reload() 能调到 —— addJavascriptInterface 对整个 WebView 生效。
     */
    public void showOfflinePage(String reason) {
        WebView wv = mWebView;
        if (wv == null) return;
        mOfflineShown = true;

        String safeReason = (reason == null) ? "" : reason.replace("\"", "").replace("<", "").replace(">", "");

        String html =
                "<!doctype html><html lang=\"zh\"><head><meta charset=\"utf-8\">" +
                "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">" +
                "<meta name=\"kangle-offline-reason\" content=\"" + safeReason + "\">" +
                "<style>body{margin:0;padding:48px 24px;font:20px/1.7 system-ui,sans-serif;" +
                "background:#FBF7F2;color:#3B322C;text-align:center}" +
                "h1{font-size:26px;margin:0 0 12px}p{color:#7A6E66;margin:0 0 32px}" +
                "button{font-size:22px;padding:16px 40px;border:0;border-radius:12px;" +
                "background:#C96F4A;color:#fff}</style></head><body>" +
                "<h1>连不上康乐服务</h1>" +
                "<p>请检查手机网络后重试。<br>如果反复失败，可能是服务端暂时不可用。</p>" +
                "<button onclick=\"KangleNative.reload()\">重新加载</button>" +
                "</body></html>";

        try {
            wv.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
        } catch (Throwable t) {
            // 连兜底页都放不出来时什么都不做，至少不能崩
        }
    }

    // =========================================================================
    // 内部辅助（不进跨文件契约）
    // =========================================================================

    /** WebView 常用开关一次性配齐；缩放关掉（长辈端字号由 H5 自己控制）。 */
    private void configureWebView() {
        WebSettings s = mWebView.getSettings();

        s.setJavaScriptEnabled(true);           // H5 是 uni-app 产物，没它全白
        s.setDomStorageEnabled(true);           // localStorage：登录态与用户偏好
        s.setDatabaseEnabled(true);             // 部分老 ROM 的 WebSQL/IndexedDB 需要
        s.setGeolocationEnabled(true);          // 允许走 onGeolocationPermissionsShowPrompt
        s.setMediaPlaybackRequiresUserGesture(false); // 语音播报不能被"先点一下"卡住
        s.setJavaScriptCanOpenWindowsAutomatically(true);
        s.setLoadsImagesAutomatically(true);
        s.setAllowFileAccess(false);            // H5 在云端，不需要 file://

        // 缩放：一律关闭（长辈端误触双指会把页面放大到不可用）
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);

        // http 子资源：H5 本身是明文，子资源也不能被拦
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);

        // 加载首帧前的底色与 H5 浅色底接近，消掉白闪
        mWebView.setBackgroundColor(0xFFFBF7F2);
        mWebView.setOverScrollMode(View.OVER_SCROLL_NEVER);
        mWebView.setHorizontalScrollBarEnabled(false);
        mWebView.setVerticalScrollBarEnabled(false);
    }

    /**
     * 解析 Intent -> mPendingAction（§3.7 的 payload）。
     * 优先用 NotificationHelper 塞进来的 EXTRA_PAYLOAD（完整 JSON）；
     * 缺失时用 EXTRA_ACTION / EXTRA_REMINDER_ID / EXTRA_ROUTE 现拼一份，保证两条路都能回流。
     */
    private void handleIntent(Intent intent) {
        if (intent == null) return;

        String payload = intent.getStringExtra(EXTRA_PAYLOAD);
        if (payload != null && payload.trim().length() > 0) {
            mPendingAction = payload.trim();
            return;
        }

        String action = intent.getStringExtra(EXTRA_ACTION);
        if (action == null || action.length() == 0) return;

        String reminderId = intent.getStringExtra(EXTRA_REMINDER_ID);
        String kind = kindOf(reminderId);

        String route = intent.getStringExtra(EXTRA_ROUTE);
        if (route == null || route.length() == 0) {
            route = ROUTE_HOME;
            if (Reminder.KIND_MEDICATION.equals(kind)) route = ROUTE_MEDICATIONS;
        }

        try {
            JSONObject o = new JSONObject();
            o.put("action", action);
            o.put("route", route);
            if (reminderId != null && reminderId.length() > 0) o.put("reminderId", reminderId);
            if (kind != null) o.put("kind", kind);
            mPendingAction = o.toString();
        } catch (Throwable t) {
            // 拼不出来就不派发，宁可少跳一次也不要把坏 JSON 丢给 H5
        }
    }

    /** 由 id 前缀反推 kind（id 生成规则见 §3.6，两端必须算出同一个）。 */
    private static String kindOf(String reminderId) {
        if (reminderId == null) return null;
        if (reminderId.startsWith("med:")) return Reminder.KIND_MEDICATION;
        if (reminderId.startsWith("greeting:")) return Reminder.KIND_GREETING;
        return null;
    }

    /**
     * 取走即清：只给 getPendingAction（拉路径）用 —— H5 主动来拿，拿到就算投递完成。
     * 推路径（dispatchPendingAction）**不用它**：那条路必须先派发成功再清，否则
     * WebView 未就绪时会把 payload 丢掉，而"拉"的兜底此时已经被清空了。
     */
    String takePendingAction() {
        String p = mPendingAction;
        mPendingAction = null;
        return p;
    }

    /**
     * 统一权限判定。用 String 重载的 checkSelfPermission（API 23 起），
     * 绝不用 Manifest.permission.* 常量 —— API 30 的 android.jar 里没有 31+ 的那些常量（§3.5）。
     */
    boolean hasPermission(String permission) {
        if (Build.VERSION.SDK_INT < 23) return true;   // 安装即授予
        try {
            return checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
        } catch (Throwable t) {
            return false;   // 拿不准就当作没授权，走"再申请一次"的路径
        }
    }

    /** 主文档 URL 比对：忽略首尾差异（末尾斜杠、查询串、锚点），子资源一律不算。 */
    private boolean isMainDocument(String failingUrl, String mainUrl) {
        if (failingUrl == null || mainUrl == null) return false;
        String a = normalizeUrl(failingUrl);
        String b = normalizeUrl(mainUrl);
        if (a.length() == 0 || b.length() == 0) return false;
        return a.equals(b);
    }

    private static String normalizeUrl(String u) {
        if (u == null) return "";
        String s = u.trim();
        int cut = s.length();
        int q = s.indexOf('?');
        if (q >= 0 && q < cut) cut = q;
        int h = s.indexOf('#');
        if (h >= 0 && h < cut) cut = h;
        s = s.substring(0, cut);
        if (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }

    // =========================================================================
    // 内部类（private，不进跨文件契约，行为按 §4.5 冻结）
    // =========================================================================

    private class KangleWebViewClient extends WebViewClient {

        @Override
        public void onPageFinished(WebView view, String url) {
            super.onPageFinished(view, url);
            // H5 主地址加载成功 -> 不再是兜底页状态
            if (isMainDocument(url, h5Url())) {
                mOfflineShown = false;
            }
            // 页面就绪，通知点击的 payload 这时候派发才有 JS 接收方（§3.7）
            dispatchPendingAction();
        }

        /**
         * 只认主文档。子资源（图片/字体/接口）失败不触发兜底页，
         * 否则页面会莫名其妙被替换成错误页（§11.1）。
         */
        @Override
        public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
            super.onReceivedError(view, errorCode, description, failingUrl);
            try {
                if (isMainDocument(failingUrl, h5Url())) {
                    showOfflinePage("net_" + errorCode);
                }
            } catch (Throwable t) {
                // 判定过程出错也不要把异常抛回 WebView 线程
            }
        }

        /**
         * API 23+ 的主文档错误回调。**必须显式覆写**，不能只靠已废弃的 4 参版本：
         * 框架里「3 参默认实现在 isForMainFrame 时转调 4 参」是 WebViewClient 自己的实现细节
         * （AOSP 原注释即 TODO: Remove this deprecated path），一旦某版本不再转发，
         * 断网 / 服务器挂掉时主文档失败就永远不触发兜底页 —— 正是 §11.1 明令不许出现的白屏。
         *
         * WebResourceError 是 API 23 引入的类，构建基准是 API 30 的 android.jar，符号必然存在
         * （真正 31+ 才有的那一类见 §3.5）。两个签名行为一致：不调 super（默认实现会转调我们
         * 覆写的 4 参版本，调了会把兜底页加载两遍）；showOfflinePage 本身是幂等的
         * loadDataWithBaseURL，21/22 上仍由 4 参版本负责。
         */
        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            try {
                if (request != null && request.isForMainFrame()) {
                    showOfflinePage("net_" + (error == null ? 0 : error.getErrorCode()));
                }
            } catch (Throwable t) {
                // 判定过程出错也不要把异常抛回 WebView 线程
            }
        }

        /** 主文档 5xx/4xx 也走兜底页（API 21+ 签名：第三个参数是 WebResourceResponse）。 */
        @Override
        public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse errorResponse) {
            super.onReceivedHttpError(view, request, errorResponse);
            try {
                if (request == null || errorResponse == null) return;
                if (!request.isForMainFrame()) return;
                if (errorResponse.getStatusCode() >= 400) {
                    showOfflinePage("http_" + errorResponse.getStatusCode());
                }
            } catch (Throwable t) {
                // 同上
            }
        }

        /** 站内跳转留在 WebView 里：拦截 tel/sms/mailto 打开系统拨号/短信应用，其余 return false */
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            if (url == null) return false;
            if (url.startsWith("tel:")) {
                try {
                    Intent intent = new Intent(Intent.ACTION_DIAL, Uri.parse(url));
                    view.getContext().startActivity(intent);
                } catch (Throwable t) {}
                return true;
            }
            if (url.startsWith("sms:") || url.startsWith("mailto:") || url.startsWith("geo:")) {
                try {
                    Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    view.getContext().startActivity(intent);
                } catch (Throwable t) {}
                return true;
            }
            return false;
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            if (request != null && request.getUrl() != null) {
                return shouldOverrideUrlLoading(view, request.getUrl().toString());
            }
            return false;
        }
    }

    private class KangleChromeClient extends WebChromeClient {

        /**
         * 麦克风放行的命门：H5 用 navigator.mediaDevices.getUserMedia({audio:true}) 录音，
         * 不在这里 grant，promise 直接 reject，长辈端会弹"麦克风不可用"。
         * 回调可能在非主线程上触发，且 request 必须尽快应答，所以统一回主线程处理。
         */
        @Override
        public void onPermissionRequest(final PermissionRequest request) {
            if (request == null) return;
            final MainActivity activity = MainActivity.this;
            activity.runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        boolean wantsAudio = false;
                        String[] resources = request.getResources();
                        if (resources != null) {
                            for (int i = 0; i < resources.length; i++) {
                                if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resources[i])) {
                                    wantsAudio = true;
                                }
                            }
                        }
                        if (wantsAudio && activity.hasPermission("android.permission.RECORD_AUDIO")) {
                            request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                        } else {
                            if (wantsAudio && Build.VERSION.SDK_INT >= 23) {
                                try {
                                    activity.requestPermissions(
                                            new String[]{"android.permission.RECORD_AUDIO"}, RC_AUDIO);
                                } catch (Throwable t) {
                                    // 申请失败就走 deny，H5 下次点击会重试
                                }
                            }
                            // 地理资源一律 deny（P4 途中守护再开），保持本轮语义简单
                            request.deny();
                        }
                    } catch (Throwable t) {
                        try {
                            request.deny();
                        } catch (Throwable t2) {
                            // 忽略：request 已失效
                        }
                    }
                }
            });
        }

        @Override
        public void onPermissionRequestCanceled(PermissionRequest request) {
            if (request == null) return;
            try {
                request.deny();
            } catch (Throwable t) {
                // 已取消的请求再 deny 会抛，忽略
            }
        }

        /**
         * H5 侧的地理定位回调。**一律 deny**（契约 §8.2）。
         *
         * 本轮清单里的两个定位权限只是 P4 的占位，没有申请运行时权限，所以这里 grant 也不会
         * 真的给到位置；但 grant 会让 WebView 记名「该来源已获准」—— 等 P4 补上定位运行时权限，
         * H5 无需任何新的确认就会静默拿到位置，本轮刻意保留的那道闸就形同虚设了。
         * P4 开放时改成：allow = checkSelfPermission(ACCESS_FINE_LOCATION) == GRANTED。
         */
        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
            if (callback == null) return;
            try {
                boolean allow = hasPermission("android.permission.ACCESS_FINE_LOCATION")
                        || hasPermission("android.permission.ACCESS_COARSE_LOCATION");
                callback.invoke(origin, allow, false);   // (origin, allow, retain)
            } catch (Throwable t) {
                // 忽略
            }
        }
    }
}
