package com.kangle.app;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * window.KangleNative 的唯一实现（契约 §3、§4.4）。
 *
 * 三条铁律，改代码前先读一遍：
 *
 * 1. **本类的每个 @JavascriptInterface 方法都跑在 WebView 私有的 "JavaBridge" 后台线程，
 *    不是主线程。** 任何触碰 UI / 弹权限框 / Toast / WebView 自身的动作，
 *    一律 activity.runOnUiThread(...) 包一层；AlarmManager、SharedPreferences、
 *    NotificationManager 可以在桥线程直调。**startActivity 也在桥线程直调**（见
 *    openWithFallback）：它是 AMS 的同步调用，目标不存在 / 不可导出时当场抛异常，
 *    只有同步调用才拿得到「这一跳到底跳没跳成」，回主线程异步发就失去了降级依据。
 *
 * 2. **所有 String 返回值必须是合法 JSON（UTF-8、不带首尾空白）、永远不返回 null。**
 *    出错返回 {"ok":false,"error":"<短码>"}，短码只取 bad_json / no_activity /
 *    unsupported / io_error。
 *
 * 3. **只暴露契约里写的方法。** 这里多一个方法，就是给明文 http 页面多开一扇调用系统能力的门
 *    （H5 是 http:// 明文托管，见 §11 第 10 条）。所有辅助方法一律 private static。
 *
 * 本类不引用任何 AndroidX / support library / 第三方坐标：只有 java.*、android.*、org.json.*。
 */
public class NativeBridge {

    private final MainActivity mActivity;

    /** 构造签名冻结；MainActivity 必须传自己（§4.4）。 */
    public NativeBridge(MainActivity activity) {
        mActivity = activity;
    }

    // =========================================================================
    // 探针 / 平台信息
    // =========================================================================

    /** 桥存在性探针，恒 true。不需要回主线程。 */
    @JavascriptInterface
    public boolean isSupported() {
        return true;
    }

    /** 版本/品牌/H5 地址，供 H5 做兼容分支与问题排查。 */
    @JavascriptInterface
    public String getPlatformInfo() {
        try {
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("package", mActivity.getPackageName());
            o.put("versionCode", versionCode());
            o.put("versionName", versionName());
            o.put("sdkInt", Build.VERSION.SDK_INT);
            o.put("brand", String.valueOf(Build.BRAND));
            o.put("h5Url", mActivity.h5Url());
            return o.toString();
        } catch (Throwable t) {
            return err("io_error");
        }
    }

    // =========================================================================
    // 提醒同步核心
    // =========================================================================

    /**
     * 声明式全量覆盖：H5 每次推全量数组，原生侧算差集并重排全部闹钟。
     * 顺序写死（§4.4）：解析 -> AlarmScheduler.apply（内部 cancelAll -> save -> arm）。
     */
    @JavascriptInterface
    public String syncReminders(String remindersJson) {
        try {
            java.util.List<String> skipped = new java.util.ArrayList<String>();
            java.util.List<Reminder> list = Reminder.listFromJson(remindersJson, skipped);
            String mode = new AlarmScheduler(mActivity).apply(list);

            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("received", countTopLevel(remindersJson));
            o.put("count", list.size());
            o.put("armed", countEnabled(list));
            o.put("mode", mode);
            o.put("skipped", new JSONArray(skipped));
            return o.toString();
        } catch (Throwable t) {
            // JSONArray 解析失败、SharedPreferences 写失败、排闹钟被系统拒绝，都归到这里
            return err("bad_json");
        }
    }

    /** 回读原生侧已存的规范形态（原生副本才是闹钟唯一可读真值，见 §5）。 */
    @JavascriptInterface
    public String getReminders() {
        try {
            java.util.List<Reminder> list = new ReminderStore(mActivity).load();
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("items", new JSONArray(Reminder.listToJson(list)));
            return o.toString();
        } catch (Throwable t) {
            return err("io_error");
        }
    }

    /** 清空存储 + 取消全部闹钟（退出登录 / 关闭全部提醒时调用）。 */
    @JavascriptInterface
    public String cancelAll() {
        try {
            // 先数再清：AlarmScheduler.cancelAll() 会把副本一起清掉，之后再数就是 0
            int n = new ReminderStore(mActivity).load().size();
            new AlarmScheduler(mActivity).cancelAll();
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("cancelled", n);
            return o.toString();
        } catch (Throwable t) {
            return err("io_error");
        }
    }

    // =========================================================================
    // 权限：探测 / 申请 / 跳设置页
    // =========================================================================

    /** 只读探测，**不弹任何框**。H5 在页面 onShow 时反复调它来驱动引导页状态。 */
    @JavascriptInterface
    public String checkPermissions() {
        try {
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("notifications",    permInfo(notificationsGranted(), true,  33));
            o.put("exactAlarm",       permInfo(canScheduleExact(),     true,  31));
            o.put("microphone",       permInfo(mAudioGranted(),        true,  23));
            o.put("location",         permInfo(mLocationGranted(),     false, 23));
            o.put("batteryOptimized", permInfo(mBatteryIgnoring(),     false, 23));
            return o.toString();
        } catch (Throwable t) {
            return err("io_error");
        }
    }

    /**
     * 申请 / 跳设置页。返回值是**即时的**（"granted" / "requested" / "settings_opened" /
     * "unavailable" / "unsupported"），弹框与跳页本身是异步的，H5 不在回调里等结果 ——
     * 统一在页面 onShow 时重新 checkPermissions() 轮询（§3.4）。
     */
    @JavascriptInterface
    public String requestPermission(String name) {
        final String n = (name == null) ? "" : name;
        try {
            if ("notifications".equals(n)) {
                // 已授权（SDK≥33 看运行时权限；24~32 看系统总开关）直接回报 granted。
                if (notificationsGranted()) return res(n, "granted");
                // 未授权时**不调 requestPermissions**：本工程 targetSdk=30（<33），对
                // POST_NOTIFICATIONS 调它根本不会弹框（官方语义：targetSdk<33 的应用只有
                // 「首次建 channel」那一次系统自动弹框）；SDK≥33 且用户已点过「不允许」时
                // 也不会二次弹框。结果就是长辈点了引导页的「去开启」什么都不发生，
                // 而 onShow 轮询 checkPermissions() 永远显示未开启，App 内救不回来。
                // 所以这里统一跳系统通知设置页，让用户手动开（result = settings_opened，
                // H5 在 onShow 里重新 checkPermissions 就能看到状态变化）。见 §3.4。
                // onCreate/onResume 里的 ensureChannel 保留不动：首次安装的自动弹框仍靠它。
                // 借 openSettings("notification") 的实现，只把回包的 name 改回入参名（§3.4 的 name = 入参）
                JSONObject r = new JSONObject(openSettings("notification"));
                r.put("name", n);
                return r.toString();
            }

            // exact_alarm 没有运行时弹框，等价于跳设置页
            if ("exact_alarm".equals(n)) return openSettings("exact_alarm");

            if ("microphone".equals(n)) {
                if (Build.VERSION.SDK_INT < 23) return res(n, "granted");
                if (mActivity.hasPermission("android.permission.RECORD_AUDIO")) return res(n, "granted");
                mActivity.runOnUiThread(new Runnable() {
                    public void run() {
                        try {
                            mActivity.requestPermissions(
                                    new String[]{"android.permission.RECORD_AUDIO"}, MainActivity.RC_AUDIO);
                        } catch (Throwable t) {
                            // 忽略
                        }
                    }
                });
                return res(n, "requested");
            }

            // 定位本轮明确不申请（P4 途中守护再说）
            if ("location".equals(n)) return res(n, "unsupported");

            if ("battery".equals(n)) return openSettings("battery");

            return res(n, "unsupported");
        } catch (Throwable t) {
            return err("no_activity");
        }
    }

    /** 跳系统设置页（§3.4 右表）。 */
    @JavascriptInterface
    public String openSettings(String name) {
        final String n = (name == null) ? "" : name;
        try {
            if ("auto_start".equals(n)) {
                // MIUI 自启动：演示机是小米，这一项决定"清理后台后提醒还响不响"
                Intent mi = new Intent();
                mi.setClassName("com.miui.securitycenter",
                                "com.miui.permcenter.autostart.AutoStartManagementActivity");
                mi.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                return openWithFallback(n, mi, appDetailsIntent(), "settings_opened", "unavailable");
            }

            if ("battery".equals(n)) {
                Intent mi = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                mi.setData(Uri.parse("package:" + mActivity.getPackageName()));
                mi.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                Intent fb = new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
                fb.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                return openWithFallback(n, mi, fb, "settings_opened", "settings_opened");
            }

            if ("notification".equals(n)) {
                if (Build.VERSION.SDK_INT >= 26) {
                    Intent mi = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
                    mi.putExtra(Settings.EXTRA_APP_PACKAGE, mActivity.getPackageName());
                    mi.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    return openWithFallback(n, mi, appDetailsIntent(), "settings_opened", "settings_opened");
                }
                return openWithFallback(n, appDetailsIntent(), null, "settings_opened", "unavailable");
            }

            if ("exact_alarm".equals(n)) {
                // 必须用字符串字面量：API 30 的 android.jar 里没有
                // Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM 这个符号（§3.5）
                Intent mi = new Intent("android.settings.REQUEST_SCHEDULE_EXACT_ALARM");
                mi.setData(Uri.parse("package:" + mActivity.getPackageName()));
                mi.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                return openWithFallback(n, mi, appDetailsIntent(), "settings_opened", "settings_opened");
            }

            if ("app_details".equals(n)) {
                // 万能兜底，一定存在
                return openWithFallback(n, appDetailsIntent(), null, "settings_opened", "unavailable");
            }

            return res(n, "unsupported");
        } catch (Throwable t) {
            return err("no_activity");
        }
    }

    // =========================================================================
    // 通知点击回流 / 测试通知 / 工具
    // =========================================================================

    /**
     * 拉取"通知点击"待办，取走即清。
     * 无待办返回**空字符串 ""**，不是 "null"（§3.3）—— H5 用 `if (pending)` 判断。
     */
    @JavascriptInterface
    public String getPendingAction() {
        try {
            String p = mActivity.takePendingAction();
            return (p == null) ? "" : p;
        } catch (Throwable t) {
            return "";
        }
    }

    /** 立刻发一条通知，只给引导页的"试一下"按钮用；不排闹钟。 */
    @JavascriptInterface
    public String notifyNow(String json) {
        try {
            JSONObject o = new JSONObject(json == null ? "{}" : json);
            final Reminder r = Reminder.fromJson(o);
            if (!r.isValid()) return err("bad_json");
            // notify 本身可以在桥线程调，但 ensureChannel 必须在主线程（Android 13 权限框由它触发），
            // 且通知最好和渠道创建在同一线程次序里，所以整块回主线程
            mActivity.runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        NotificationHelper.ensureChannel(mActivity);
                        NotificationHelper.show(mActivity, r);
                    } catch (Throwable t) {
                        // 发不出来就算了，不能让桥线程崩
                    }
                }
            });
            JSONObject out = new JSONObject();
            out.put("ok", true);
            return out.toString();
        } catch (Throwable t) {
            return err("bad_json");
        }
    }

    /** 重载 H5（兜底页"重新加载"按钮用）。WebView.loadUrl 必须在主线程。 */
    @JavascriptInterface
    public void reload() {
        mActivity.runOnUiThread(new Runnable() {
            public void run() {
                try {
                    mActivity.loadH5();
                } catch (Throwable t) {
                    // 忽略
                }
            }
        });
    }

    /** 调试用 Toast。Toast 必须在主线程。 */
    @JavascriptInterface
    public void toast(String text) {
        if (text == null) return;
        final String msg = text.length() > 200 ? text.substring(0, 200) : text;
        mActivity.runOnUiThread(new Runnable() {
            public void run() {
                try {
                    Toast.makeText(mActivity, msg, Toast.LENGTH_SHORT).show();
                } catch (Throwable t) {
                    // 忽略
                }
            }
        });
    }

    // =========================================================================
    // 私有辅助（绝不加 @JavascriptInterface，绝不 public）
    // =========================================================================

    /** 入参数组长度；解析失败返回 0（此时 syncReminders 已经返回 ok:false 了）。 */
    private static int countTopLevel(String arrayJson) {
        try {
            return new JSONArray(arrayJson == null ? "[]" : arrayJson).length();
        } catch (Throwable t) {
            return 0;
        }
    }

    private static int countEnabled(java.util.List<Reminder> list) {
        if (list == null) return 0;
        int n = 0;
        for (int i = 0; i < list.size(); i++) {
            Reminder r = list.get(i);
            if (r != null && r.enabled) n++;
        }
        return n;
    }

    private static JSONObject permInfo(boolean granted, boolean required, int sdkMin) throws org.json.JSONException {
        JSONObject o = new JSONObject();
        o.put("granted", granted);
        o.put("required", required);
        o.put("sdkMin", sdkMin);
        return o;
    }

    /** {"ok":true,"name":..., "result":...} */
    private static String res(String name, String result) {
        try {
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("name", (name == null) ? "" : name);
            o.put("result", result);
            return o.toString();
        } catch (Throwable t) {
            return err("io_error");
        }
    }

    /** {"ok":false,"error":"<短码>"}；短码只取 bad_json / no_activity / unsupported / io_error。 */
    private static String err(String code) {
        return "{\"ok\":false,\"error\":\"" + code + "\"}";
    }

    /** 应用详情页：所有跳转的最终兜底。 */
    private Intent appDetailsIntent() {
        Intent i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
        i.setData(Uri.parse("package:" + mActivity.getPackageName()));
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return i;
    }

    /**
     * 依次**真正**尝试派发，失败再退次选；两个都不行返回 "unavailable"。
     *
     * **不要**用 resolveActivity 做前置闸门：targetSdk 30（Android 11+）上它的结果受包可见性
     * 过滤（AppsFilter）影响，「查不到」不等于「没有」—— 拿它当闸门，可跳的页面也会被静默跳过
     * （一次 startActivity 都不发，用户点了按钮什么都不会发生）。
     *
     * 改用 startActivity 本身判成败：它是 AMS 的同步调用，目标 Activity 不存在时抛
     * ActivityNotFoundException、对外不可导出（exported=false）时抛 SecurityException ——
     * 正是这里要降级的两类失败，且必须同步调用才拿得到。
     */
    private String openWithFallback(String name, Intent primary, Intent fallback,
                                    String primaryResult, String fallbackResult) {
        if (tryStart(primary)) return res(name, primaryResult);
        if (tryStart(fallback)) return res(name, fallbackResult);
        // 两个都没跳成：不要静默 —— 自启动/通知这类关键项，长辈会以为已经打开了
        toastOnUi("请到系统设置手动开启");
        return res(name, "unavailable");
    }

    /** 同步派发一个带 FLAG_ACTIVITY_NEW_TASK 的 Intent；跳成功返回 true，抛异常返回 false。 */
    private boolean tryStart(Intent intent) {
        if (intent == null) return false;
        try {
            mActivity.startActivity(intent);
            return true;
        } catch (Throwable t) {
            // ActivityNotFoundException（没有这个页面）/ SecurityException（不可导出）都归这里
            return false;
        }
    }

    private void toastOnUi(final String msg) {
        mActivity.runOnUiThread(new Runnable() {
            public void run() {
                try {
                    Toast.makeText(mActivity, msg, Toast.LENGTH_LONG).show();
                } catch (Throwable t) {
                    // 忽略
                }
            }
        });
    }

    private int versionCode() {
        try {
            return mActivity.getPackageManager()
                    .getPackageInfo(mActivity.getPackageName(), 0).versionCode;
        } catch (Throwable t) {
            return -1;
        }
    }

    private String versionName() {
        try {
            String v = mActivity.getPackageManager()
                    .getPackageInfo(mActivity.getPackageName(), 0).versionName;
            return (v == null) ? "" : v;
        } catch (Throwable t) {
            return "";
        }
    }

    /** notifications.currently-available：SDK>=33 看运行时权限，24~32 看系统总开关，更低恒 true。 */
    private boolean notificationsGranted() {
        try {
            if (Build.VERSION.SDK_INT >= 33) {
                return mActivity.hasPermission("android.permission.POST_NOTIFICATIONS");
            }
            if (Build.VERSION.SDK_INT >= 24) {
                android.app.NotificationManager nm = (android.app.NotificationManager)
                        mActivity.getSystemService(Context.NOTIFICATION_SERVICE);
                return nm == null || nm.areNotificationsEnabled();
            }
            return true;
        } catch (Throwable t) {
            return true;
        }
    }

    private boolean canScheduleExact() {
        try {
            return new AlarmScheduler(mActivity).canScheduleExact();
        } catch (Throwable t) {
            return false;
        }
    }

    private boolean mAudioGranted() {
        return mActivity.hasPermission("android.permission.RECORD_AUDIO");
    }

    private boolean mLocationGranted() {
        return mActivity.hasPermission("android.permission.ACCESS_FINE_LOCATION");
    }

    /** granted=true 表示**已在省电白名单里**（即未被省电限制）。 */
    private boolean mBatteryIgnoring() {
        if (Build.VERSION.SDK_INT < 23) return true;
        try {
            PowerManager pm = (PowerManager) mActivity.getSystemService(Context.POWER_SERVICE);
            if (pm == null) return true;
            return pm.isIgnoringBatteryOptimizations(mActivity.getPackageName());
        } catch (Throwable t) {
            return false;
        }
    }
}
