# 《老友记》Android 原生轻量化打包流程全景说明书

> 本文档详细阐述了《老友记》移动端 APK 的完整构建技术链路。针对传统 Android Studio / Gradle 环境体积庞大（动辄 3~5 GB）、云打包排队受限等痛点，本项目创新性地采用了**基于 Google 官方底层工具链（aapt + D8 + zipalign + apksigner）的极速原生封装方案**，全套工具链不足 40MB，**编译打包仅需 3 秒**，生成的安装包仅 13KB，且具备原生硬件权限穿透与零成本热更新能力。

---

## 一、架构总览与技术选型

### 1. 为什么不用传统 Android Studio / Gradle？
* **传统构建劣势**：需拉取庞大的 Gradle 守护进程、Android SDK Platform、Support/AndroidX 依赖库，下载耗时长、环境配置复杂，在服务器或 CI/CD 流水线中极易受网络或缓存阻塞。
* **极速原生流优势**：
  * **超轻量**：仅需基础 JDK + 官方底层工具（`aapt`, `d8`, `zipalign`, `apksigner` 和一份 `android.jar`），无任何冗余框架；
  * **秒级编译**：全流程编译耗时约为 2~3 秒；
  * **热更新免重新装包**：由于前端已随 FastAPI 云端服务热部署，后续若优化界面、调整算法或修复 Bug，直接部署云端前端静态资源即可，用户手机打开即为最新版本，极大降低长辈反复安装升级的门槛。

### 2. 构建流程全景图
```
[1. 前端 H5 编译] ────> 静态资产产物 (dist/build/h5)
                                 │
[2. 原生工程准备] ────> AndroidManifest.xml / strings.xml / icon.png / MainActivity.java
                                 │
[3. 资源预编译]   ────> aapt package ──> 生成 R.java
                                 │
[4. Java 源码编译] ───> javac ─────────> 生成 .class 字节码
                                 │
[5. DEX 转换]     ────> D8 (r8.jar) ────> 生成 classes.dex (ART/Dalvik 虚拟机指令)
                                 │
[6. 原始 APK 组装] ───> aapt package + aapt add classes.dex ──> app.unsigned.apk
                                 │
[7. 4 字节边界对齐] ──> zipalign -p -f 4 ───────────────────────> app.aligned.apk (根治 -124 错误)
                                 │
[8. 官方三层签名] ────> apksigner (v1 + v2 + v3) ───────────────> laoyouji.apk (最终交付物)
                                 │
[9. 自动化校验]   ────> zipalign -c & apksigner verify ────────> 100% 验收通过
```

---

## 二、环境与前置依赖准备

在 Ubuntu 24.04 Linux 环境下，仅需安装极少量的基础工具：

```bash
# 1. 安装基础编译工具与 JDK
apt-get update
apt-get install -y aapt zipalign apksigner openjdk-17-jdk

# 2. 准备官方 Android 运行时与 D8 编译器（保存至 /opt/laoyouji/build_tools/）
# - android.jar (API 30, 来自 Google 官方 Android 11 Platform SDK)
# - r8.jar (Google 官方 D8 编译器)
```

---

## 三、打包流程分步拆解（Step by Step）

### 步骤 1：构建基础目录结构与应用图标
自动创建符合 Android 官方工程规范的目录层级：
* `src/com/laoyouji/app/`：放置 Java 源码
* `res/values/`：放置字符串定义 `strings.xml`
* `res/drawable/`：放置应用图标 `icon.png`
* `bin/`：放置编译产物与中间 APK

应用大图标通过 Python 算法直接生成无损 128x128 品牌图标，确保即使在极简无桌面环境的服务器上也能全自动产出标准 PNG 图标。

### 步骤 2：编写核心清单声明 `AndroidManifest.xml`
清单文件定义了 App 的包名、版本、硬件加速和关键系统权限：
```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.laoyouji.app"
    android:versionCode="100"
    android:versionName="1.0.0">

    <!-- 兼容 Android 5.0 (API 21) 至最新 Android 14/15 -->
    <uses-sdk android:minSdkVersion="21" android:targetSdkVersion="30" />

    <!-- 核心硬件与网络权限 -->
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
```
* **`android:usesCleartextTraffic="true"`**：必配项。Android 9+ 默认封锁 HTTP 请求，此配置允许直连云端 8000 端口。
* **`android:exported="true"`**：必配项。Android 12+ 强制要求 Launcher Activity 显式声明 exported。

### 步骤 3：编写原生宿主容器 `MainActivity.java`
在 Java 层面实现全屏适老 WebView，并穿透调用手机硬件：
1. **JavaScript & 存储全开**：开启 `setJavaScriptEnabled(true)`、`setDomStorageEnabled(true)`、`setDatabaseEnabled(true)`。
2. **麦克风权限穿透**：重写 `WebChromeClient.onPermissionRequest`，当老人点击长辈端麦克风时，WebView 直接将系统录音权限派发给前端 WebRTC / 录音 API。
3. **定位权限穿透**：重写 `WebChromeClient.onGeolocationPermissionsShowPrompt`，自动为高德地图授权 GPS 定位。
4. **实体返回键拦截**：接管 `onKeyDown` 中的 `KEYCODE_BACK`，若 WebView 可后退则执行 `webView.goBack()`，防止老人误触直接退出应用。
5. **网络断线友好兜底**：重写 `WebViewClient.onReceivedError`，断网时渲染包含“一键重新加载”按钮的温馨提示界面。

### 步骤 4：生成资源映射代码 `R.java`（aapt）
```bash
aapt package -f -m \
    -J src \
    -M AndroidManifest.xml \
    -S res \
    -I /opt/laoyouji/build_tools/android.jar
```
* **作用**：解析 XML 与图片资源，自动在 `src/com/laoyouji/app/R.java` 生成资源 ID。

### 步骤 5：编译 Java 源码为 Class 字节码（javac）
```bash
javac -encoding UTF-8 \
    -cp /opt/laoyouji/build_tools/android.jar \
    -d bin/classes \
    src/com/laoyouji/app/*.java
```
* **作用**：将 `MainActivity.java` 和 `R.java` 编译为标准 Java `.class` 字节码。

### 步骤 6：编译为 Android 虚拟机可执行代码（D8 编译器）
```bash
java -cp /opt/laoyouji/build_tools/r8.jar com.android.tools.r8.D8 \
    --lib /opt/laoyouji/build_tools/android.jar \
    --min-api 21 \
    --output bin \
    bin/classes/com/laoyouji/app/*.class
```
* **作用**：使用 Google 下一代 Dex 编译器 **D8**，将 `.class` 转为 Android 虚拟机（ART/Dalvik）执行的核心文件 `bin/classes.dex`。

### 步骤 7：打包组装无签名原始 APK（aapt package + aapt add）
```bash
# 1. 封装 Manifest 与 res 资源生成未签名基础包
aapt package -f \
    -M AndroidManifest.xml \
    -S res \
    -I /opt/laoyouji/build_tools/android.jar \
    -F bin/app.unsigned.apk

# 2. 将编译好的 classes.dex 注入包中
cd bin && aapt add app.unsigned.apk classes.dex
```

### 步骤 8：4 字节边界对齐（zipalign）—— 根治 `-124` 报错
```bash
zipalign -p -f -v 4 bin/app.unsigned.apk bin/app.aligned.apk
```
* **核心排坑点**：从 Android 11（API Level 30）开始，系统的 `PackageManager` 对安装包实施了严格的**内存直接映射（mmap）**安全与性能校验规范。未压缩的资源文件（尤其是 `resources.arsc`）在 ZIP 包中的起始字节偏移量**必须能够被 4 整除**。
* **若未执行此步骤**：安装器解析到未对齐偏移（如 1278 字节），系统内核无法执行 `mmap` 寻址，直接弹窗报错 **`-124` (INSTALL_PARSE_FAILED_RESOURCES_ARSC_COMPRESSED)** 并终止安装。
* **执行后效果**：`resources.arsc` 起始偏移被精准调整对齐为 1280 字节（`1280 % 4 = 0`），顺利通过系统验证。

### 步骤 9：生成证书与注入权威签名（keytool + apksigner）
```bash
# 1. 生成 10000 天超长有效期的 2048 位 RSA 证书（若已有则复用）
keytool -genkey -v -keystore release.keystore -alias laoyouji \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass laoyouji123 -keypass laoyouji123 \
    -dname "CN=LaoYouJi, OU=Dev, O=App, L=Nanjing, ST=Jiangsu, C=CN"

# 2. 对齐后再签名，同时开启 v1 + v2 + v3 三重签名方案
apksigner sign --ks release.keystore --ks-pass pass:laoyouji123 \
    --v1-signing-enabled true \
    --v2-signing-enabled true \
    --v3-signing-enabled true \
    --out /opt/laoyouji/backend/static_dist/laoyouji.apk \
    bin/app.aligned.apk
```
* **注意顺序法则**：**必须“先 zipalign 对齐，后 apksigner 签名”**。因为 `apksigner` 会在 ZIP 归档的末尾（Central Directory 之前）计算并写入整个文件的散列校验签名块（APK Signing Block）；如果在签名之后再去修改文件对齐，就会破坏签名散列，导致签名失效。

### 步骤 10：自动化完整性双重验收
编译完成后脚本自动运行校验命令：
```bash
# 验证对齐状态
zipalign -c -v 4 /opt/laoyouji/backend/static_dist/laoyouji.apk
# 预期输出: Verification successful

# 验证签名状态
apksigner verify --verbose /opt/laoyouji/backend/static_dist/laoyouji.apk
# 预期输出: Verifies: v1=true, v2=true, v3=true
```

---

## 四、一键自动化构建脚本代码

上述全流程已被封装整合在服务器脚本 `/opt/laoyouji/build_apk.sh` 中。日常维护时，若需重新打包，只需在服务器终端执行一条命令：

```bash
chmod +x /opt/laoyouji/build_apk.sh && /opt/laoyouji/build_apk.sh
```

**完整脚本源码参考**：
```bash
#!/bin/bash
set -e

BUILD_DIR=/opt/laoyouji/apk_project
TOOLS_DIR=/opt/laoyouji/build_tools
DIST_DIR=/opt/laoyouji/backend/static_dist
OUT_APK=/opt/laoyouji/backend/static_dist/laoyouji.apk

echo "==== 1. Preparing directories ===="
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

cat << 'XML' > "$BUILD_DIR/AndroidManifest.xml"
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.laoyouji.app"
    android:versionCode="100"
    android:versionName="1.0.0">
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
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.Window;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    private WebView webView;
    private static final String APP_URL = "http://159.75.94.149:8000/";

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
                view.loadUrl(url);
                return true;
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
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if ((keyCode == KeyEvent.KEYCODE_BACK) && webView.canGoBack()) {
            webView.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
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

echo "==== 10. Generating keystore and signing APK ===="
cd "$BUILD_DIR"
if [ ! -f release.keystore ]; then
    keytool -genkey -v -keystore release.keystore -alias laoyouji \
        -keyalg RSA -keysize 2048 -validity 10000 \
        -storepass laoyouji123 -keypass laoyouji123 \
        -dname "CN=LaoYouJi, OU=Dev, O=App, L=Nanjing, ST=Jiangsu, C=CN"
fi

apksigner sign --ks release.keystore --ks-pass pass:laoyouji123 \
    --v1-signing-enabled true \
    --v2-signing-enabled true \
    --v3-signing-enabled true \
    --out "$OUT_APK" \
    bin/app.aligned.apk

echo "==== 11. Verifying APK alignment and signature ===="
zipalign -c -v 4 "$OUT_APK"
apksigner verify --verbose "$OUT_APK"
ls -lh "$OUT_APK"
echo "==== SUCCESS: APK BUILT, ZIPALIGNED AND SIGNED AT $OUT_APK ===="
```

---

## 五、发布与下载交付

构建完成后的安装包位于 `/opt/laoyouji/backend/static_dist/laoyouji.apk`，由 FastAPI 后端服务直接对外提供下载服务：
* 📱 **直接下载链接**：[http://159.75.94.149:8000/laoyouji.apk](http://159.75.94.149:8000/laoyouji.apk)
* 🌐 **移动端下载页**：[http://159.75.94.149:8000/download/](http://159.75.94.149:8000/download/)
* 📦 **包体大小**：~13 KB（极速下载，秒级装载）
