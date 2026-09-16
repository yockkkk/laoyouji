#!/bin/bash
set -e

echo "==== 1. Preparing directories ===="
BUILD_DIR=/opt/laoyouji/apk_project
TOOLS_DIR=/opt/laoyouji/build_tools
DIST_DIR=/opt/laoyouji/backend/static_dist
OUT_APK=/opt/laoyouji/backend/static_dist/laoyouji.apk
KEYSTORE_FILE=/opt/laoyouji/release.keystore
KEY_PASS="laoyouji123"

# 自动递增版本号：确保每次构建 versionCode 严格递增，Android 系统可直接覆盖安装，绝无需先卸载
VERSION_FILE=/opt/laoyouji/version_code.txt
if [ -f "$VERSION_FILE" ]; then
    VERSION_CODE=$(cat "$VERSION_FILE" | tr -d ' \r\n')
    VERSION_CODE=$((VERSION_CODE + 1))
else
    VERSION_CODE=101
fi
echo "$VERSION_CODE" > "$VERSION_FILE"
VERSION_NAME="1.0.$((VERSION_CODE - 100))"
echo "==== Building LaoYouJi APK: versionCode=$VERSION_CODE, versionName=$VERSION_NAME ===="

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/src/com/laoyouji/app"
mkdir -p "$BUILD_DIR/res/values"
mkdir -p "$BUILD_DIR/res/drawable"
mkdir -p "$BUILD_DIR/bin/classes"

echo "==== 2. Creating app icon ===="
python3 -c '
import struct, zlib

def make_png(w, h, r, g, b):
    def chunk(tag, data):
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xffffffff)
    ihdr = struct.pack("!IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw.extend([r, g, b])
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")

with open("'"$BUILD_DIR"'/res/drawable/icon.png", "wb") as f:
    f.write(make_png(128, 128, 37, 99, 235))
'

echo "==== 3. Writing strings.xml and AndroidManifest.xml ===="
cat << 'XML' > "$BUILD_DIR/res/values/strings.xml"
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">老友记</string>
</resources>
XML

cat << XML > "$BUILD_DIR/AndroidManifest.xml"
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.laoyouji.app"
    android:versionCode="$VERSION_CODE"
    android:versionName="$VERSION_NAME">

    <uses-sdk android:minSdkVersion="21" android:targetSdkVersion="30" />

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />

    <application
        android:label="@string/app_name"
        android:icon="@drawable/icon"
        android:usesCleartextTraffic="true"
        android:hardwareAccelerated="true">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|keyboardHidden|screenSize"
            android:windowSoftInputMode="adjustResize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
XML

echo "==== 4. Writing MainActivity.java ===="
cat << 'JAVA' > "$BUILD_DIR/src/com/laoyouji/app/MainActivity.java"
package com.laoyouji.app;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.Window;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

public class MainActivity extends Activity {
    private WebView webView;
    private static final String APP_URL = "https://sdad.hynu.site/";
    private PermissionRequest pendingAudioRequest = null;
    private static final int RC_AUDIO_PERM = 201;
    private long lastBackPressTime = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);

        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#F7FAFC"));
        setContentView(webView);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setGeolocationEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        webView.setWebViewClient(new WebViewClient() {
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
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    view.loadUrl(url);
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

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                String errorHtml = "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'></head><body style='display:flex;flex-direction:column;align-items:center;justify-content:center;height:90vh;font-family:sans-serif;text-align:center;padding:20px;background:#f8fafc;'>"
                    + "<div style='font-size:48px;margin-bottom:16px;'>📶</div>"
                    + "<h2 style='color:#1e293b;margin-bottom:8px;'>网络连接异常</h2>"
                    + "<p style='color:#64748b;font-size:16px;line-height:1.6;'>请检查手机网络设置后重试</p>"
                    + "<button onclick='window.location.reload()' style='margin-top:24px;background:#2563eb;color:white;border:none;padding:14px 32px;font-size:18px;border-radius:12px;font-weight:bold;cursor:pointer;box-shadow:0 4px 12px rgba(37,99,235,0.3);'>点击重新加载</button>"
                    + "</body></html>";
                view.loadDataWithBaseURL(null, errorHtml, "text/html", "utf-8", null);
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                callback.invoke(origin, true, false);
            }

            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                    boolean wantsAudio = false;
                    for (String res : request.getResources()) {
                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(res)) {
                            wantsAudio = true;
                            break;
                        }
                    }
                    if (wantsAudio && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        if (checkSelfPermission("android.permission.RECORD_AUDIO") != PackageManager.PERMISSION_GRANTED) {
                            pendingAudioRequest = request;
                            requestPermissions(new String[]{"android.permission.RECORD_AUDIO"}, RC_AUDIO_PERM);
                            return;
                        }
                    }
                    request.grant(request.getResources());
                }
            }
        });

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            String[] permissions = {
                "android.permission.RECORD_AUDIO",
                "android.permission.ACCESS_FINE_LOCATION",
                "android.permission.ACCESS_COARSE_LOCATION"
            };
            boolean needRequest = false;
            for (String p : permissions) {
                if (checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) {
                    needRequest = true;
                    break;
                }
            }
            if (needRequest) {
                requestPermissions(permissions, 100);
            }
        }

        webView.loadUrl(APP_URL);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == RC_AUDIO_PERM) {
            boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            if (pendingAudioRequest != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                if (granted) {
                    pendingAudioRequest.grant(pendingAudioRequest.getResources());
                } else {
                    pendingAudioRequest.deny();
                    Toast.makeText(this, "需要麦克风权限才能进行语音对讲，请在系统设置中开启", Toast.LENGTH_LONG).show();
                    try {
                        Intent intent = new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
                        intent.setData(Uri.parse("package:" + getPackageName()));
                        startActivity(intent);
                    } catch (Throwable ignored) {}
                }
            }
            pendingAudioRequest = null;
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT && webView != null) {
                webView.evaluateJavascript(
                    "(function() {" +
                    "  try {" +
                    "    if (window.__lyjHandleBack && typeof window.__lyjHandleBack === 'function') {" +
                    "      return window.__lyjHandleBack() ? '1' : '0';" +
                    "    }" +
                    "  } catch (e) {}" +
                    "  return '0';" +
                    "})()",
                    new ValueCallback<String>() {
                        @Override
                        public void onReceiveValue(String value) {
                            if ("\"1\"".equals(value) || "1".equals(value) || "\"true\"".equals(value) || "true".equals(value)) {
                                return;
                            }
                            handleNativeBack();
                        }
                    }
                );
                return true;
            } else {
                handleNativeBack();
                return true;
            }
        }
        return super.onKeyDown(keyCode, event);
    }

    private void handleNativeBack() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        long now = System.currentTimeMillis();
        if (now - lastBackPressTime < 2000) {
            finish();
        } else {
            lastBackPressTime = now;
            Toast.makeText(this, "再按一次退出老友记", Toast.LENGTH_SHORT).show();
        }
    }
}
JAVA

echo "==== 5. Running aapt to generate R.java ===="
aapt package -f -m \
    -J "$BUILD_DIR/src" \
    -M "$BUILD_DIR/AndroidManifest.xml" \
    -S "$BUILD_DIR/res" \
    -I "$TOOLS_DIR/android.jar"

echo "==== 6. Compiling Java sources ===="
javac -encoding UTF-8 \
    -cp "$TOOLS_DIR/android.jar" \
    -d "$BUILD_DIR/bin/classes" \
    "$BUILD_DIR"/src/com/laoyouji/app/*.java

echo "==== 7. Running D8 to create classes.dex ===="
java -cp "$TOOLS_DIR/r8.jar" com.android.tools.r8.D8 \
    --lib "$TOOLS_DIR/android.jar" \
    --min-api 21 \
    --output "$BUILD_DIR/bin" \
    "$BUILD_DIR"/bin/classes/com/laoyouji/app/*.class

echo "==== 8. Packaging resources with aapt ===="
cd "$BUILD_DIR"
aapt package -f \
    -M AndroidManifest.xml \
    -S res \
    -I "$TOOLS_DIR/android.jar" \
    -F bin/app.unsigned.apk

cd "$BUILD_DIR/bin"
aapt add app.unsigned.apk classes.dex

echo "==== 9. Aligning APK with zipalign (Fix for Android 11+ error -124) ===="
cd "$BUILD_DIR"
zipalign -p -f -v 4 bin/app.unsigned.apk bin/app.aligned.apk
zipalign -c -v 4 bin/app.aligned.apk

echo "==== 10. Ensuring permanent keystore and signing APK ===="
if [ ! -f "$KEYSTORE_FILE" ]; then
    echo "Creating persistent release keystore at $KEYSTORE_FILE..."
    keytool -genkey -v -keystore "$KEYSTORE_FILE" -alias laoyouji \
        -keyalg RSA -keysize 2048 -validity 10000 \
        -storepass "$KEY_PASS" -keypass "$KEY_PASS" \
        -dname "CN=LaoYouJi, OU=Dev, O=App, L=Nanjing, ST=Jiangsu, C=CN"
fi

cd "$BUILD_DIR"
apksigner sign --ks "$KEYSTORE_FILE" --ks-pass "pass:$KEY_PASS" \
    --v1-signing-enabled true \
    --v2-signing-enabled true \
    --v3-signing-enabled true \
    --out "$OUT_APK" \
    bin/app.aligned.apk

echo "==== 11. Verifying APK alignment and signature ===="
zipalign -c -v 4 "$OUT_APK"
apksigner verify --verbose "$OUT_APK"
ls -lh "$OUT_APK"

echo "==== 12. Writing version.json metadata ===="
UPDATE_TIME=$(date '+%Y-%m-%d %H:%M:%S')
cat << JSON > "$DIST_DIR/version.json"
{
  "versionCode": $VERSION_CODE,
  "versionName": "$VERSION_NAME",
  "apkUrl": "https://sdad.hynu.site/laoyouji.apk",
  "updateTime": "$UPDATE_TIME",
  "changelog": "优化卡片布局排版，修复拨打电话拉起原生拨号盘，优化高德全屏大图返回手势，支持免卸载无缝覆盖安装"
}
JSON
cat "$DIST_DIR/version.json"

echo "==== SUCCESS: APK BUILT, ZIPALIGNED AND SIGNED AT $OUT_APK ===="
