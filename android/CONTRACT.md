# 康乐 Android 壳 + 原生提醒层 —— 接口契约（冻结版）

> 本文件是**唯一**的跨文件对齐依据。4 个实现者各写各的文件、彼此不通信，
> 凡本文件写死的类名 / 方法签名 / JSON 键名，**逐字照抄，不许改名、不许加参数、不许改返回形态**。
> 有异议先改本文件，再动代码。

版本：v1（2026-09-13 冻结）
仓库根：`C:/Users/lenovo/Desktop/develop/laoyouji`

---

## 0. 侦察事实锚点（已当场打开确认，实现时按这些写）

| 事实 | 位置 |
|---|---|
| 全局启动钩子（适配层唯一现成落点） | `frontend/laoyouji-app/src/App.vue:3-5` `onLaunch()` |
| 唯一需要改的 URL | `frontend/laoyouji-app/src/api/client.js:6` `const BASE_URL = 'http://127.0.0.1:8000'` |
| 用户 id 来源 | `frontend/laoyouji-app/src/store/user.js:8` `getCurrentUser()` → `.id` |
| token 存储 key | `store/user.js:5` `lyj_token` |
| 用药计划接口前缀 | `backend/app/api/routes_health.py:31` `prefix="/api/medications"` |
| 本人读取分支（要用的那支） | `routes_health.py:112-115`，`with_logs=false` 返回 `{"items":[<plan 原始行>]}` |
| 打卡接口 | `routes_health.py:191-228`，`POST /api/medications/{plan_id}/taken?scheduled_time=HH%3AMM` |
| `times` 形状 | `backend/app/db/schema.sql:159` jsonb `["08:00","20:00"]`，裸 `"HH:MM"` 字符串，无时区 |
| 种子真值（张桂芳） | `backend/app/db/seed.py:63-70`（08:00/20:00 与 09:00）、`seed.py:96-99`（07:00 与 08:00/18:00） |
| 晨间问候无后端 | `backend/app/**` 无 greeting 端点；文案在 `pages/elder/home.vue:112-119` 纯本地 |
| 引导页宿主 | `frontend/.../pages/elder/profile.vue:114`「退出当前登录」section 之前 |
| 打卡 UI 逻辑 | `frontend/.../pages/elder/medications.vue:113-127` |
| `times` 校验正则（照抄） | `pages/elder/medications.vue:172` |
| 麦克风链路 | `src/api/asr.js:82-83` `navigator.mediaDevices.getUserMedia({audio:true})` |

`times` 校验正则逐字为：`/^([01]?\d|2[0-3]):[0-5]\d$/`

---

## 1. 目录与文件清单（android/ 下一个不多一个不少）

```
android/
├── CONTRACT.md                          # 本文件（契约，非构建输入）
├── AndroidManifest.xml                  # 清单：包名/组件/权限/明文放行/theme
├── build_apk.sh                         # 无 Gradle 构建脚本（aapt→javac→d8→zipalign→apksigner）
├── res/
│   ├── values/strings.xml               # 仅 app_name（中文标签不写死在清单里）
│   ├── values/styles.xml                # AppTheme：窗口背景色，消掉 WebView 加载前白闪
│   └── xml/network_security_config.xml  # 明文流量放行（Android 9+ 白屏的根因）
└── src/com/kangle/app/
    ├── MainActivity.java                # 壳：WebView + WebViewClient + WebChromeClient + 权限回调
    ├── NativeBridge.java                # window.KangleNative 的实现，唯一 @JavascriptInterface 宿主
    ├── Reminder.java                    # 提醒模型 + JSON 编解码 + requestCode
    ├── ReminderStore.java               # SharedPreferences 持久化（原生侧唯一真值副本）
    ├── AlarmScheduler.java              # 取消全部 + 逐个武装，精确/不精确两级
    ├── ReminderReceiver.java            # 到点：弹通知 + 自排下一次
    ├── BootReceiver.java                # 开机/换包/改时区 → 从本地副本重新武装
    └── NotificationHelper.java          # channel 创建 + 通知构造 + 点击 PendingIntent
```

不存在的、不许创建：`assets/`（H5 在云端，**不内嵌**）、`build.gradle*`、`settings.gradle*`、
`gradle.properties`、`proguard-rules.pro`、`libs/`、任何 `*.aar` / `*.jar` 依赖。

唯一的二进制资源是启动图标那 5 个 PNG：`res/mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png`
（48/72/96/144/192），由 `tools/make_icons.py` 生成（纯标准库手写 PNG，无第三方依赖）。
**除此之外不许再加任何图片资源**；改图标改脚本后重跑，不要手改 PNG（见 §7.3）。

构建期生成、**不提交**、脚本自己清理：`android/gen/`（aapt 产出的 `R.java`）、`android/build/`（`classes/`、`*.dex`、未对齐 apk）。

**R.java 路径逐字为** `android/gen/com/kangle/app/R.java`（aapt `-J gen` 自动产生，不要手写）。

### 1.1 本轮由**前端实现者**新增/改动的文件（不由 android/ 实现者碰）

| 文件 | 动作 |
|---|---|
| `frontend/laoyouji-app/src/utils/native.js` | **新增**，JS 适配层，全部具名导出（见 §10） |
| `frontend/laoyouji-app/src/App.vue` | 改 `onLaunch()`（第 3-5 行）调用 `initNative()` |
| `frontend/laoyouji-app/src/pages/elder/profile.vue` | 在第 114 行 section **之前**插「提醒与保活引导」section |
| `frontend/laoyouji-app/src/api/client.js` | 第 6 行 `BASE_URL` 改为 `http://159.75.94.149:8000` |

---

## 2. 应用标识

| 项 | 值（冻结） |
|---|---|
| Java 包名 | `com.kangle.app` |
| `AndroidManifest.xml` 的 `package` 属性 | `com.kangle.app`（无 Gradle，aapt 直接读它） |
| applicationId | 等于包名 `com.kangle.app`（无构建变体概念，两者恒等） |
| `versionCode` | 默认 `2`，**必须 > 服务器上已装 APK 的 versionCode**，由 `build_apk.sh` 注入 |
| `versionName` | 默认 `"1.1.0"`，由 `build_apk.sh` 注入 |
| `minSdkVersion` | `21`（Android 5.0） |
| `targetSdkVersion` | `30`（Android 11） |
| 编译基准 | `android.jar` = API 30，见 §9 |

### 2.1 换包名的后果（必须写清，**本轮不许换**）

手机上同一个 `applicationId` 只能装一个。改成别的包名后：

- 新壳会与旧壳**并存**安装 —— 桌面出现**两个「康乐」图标**，用户分不清点哪个。
- **不是覆盖升级**：旧壳的 SharedPreferences、登录态、已排的闹钟全部留在旧壳里，新壳从零开始。
- 用户只能手动卸载旧壳，卸载会一并删掉旧壳数据。
- 服务器只托管**一个** `laoyouji.apk`，「并存」期间两个壳抢同一个下载链接。

因此：`com.kangle.app` 一旦定下就锁死。若确要换（比如旧壳包名未知），必须先在真机上卸载旧壳，
并在交付说明里明确写「需先卸载旧版」。

### 2.2 minSdk 21 / targetSdk 30 的后果

- `minSdk 21`：VectorDrawable、`PermissionRequest`、`android:usesCleartextTraffic` 之后才有的 API
  都要按 `Build.VERSION.SDK_INT` 分支。**但 API 30 的 android.jar 里根本没有 31+ 的符号**（见 §3.5）。
- `targetSdk 30`：在 Android 12/13/14/15 上跑，系统按 targetSdk 30 的兼容模式对待。两条直接后果：
  1. **通知权限**：Android 13+ 上，`targetSdk < 33` 的应用**不需要**显式申请 `POST_NOTIFICATIONS`——
     系统会在应用**第一次创建通知渠道**时自动弹权限框。所以 `NotificationHelper.ensureChannel()`
     必须尽早在主线程调用一次（见 §8）。
  2. **精确闹钟**：`SCHEDULE_EXACT_ALARM` 在 targetSdk 30 上于 Android 12 仍是**普通权限**（自动授予），
     Android 13 起才收紧为特殊权限。两级降级照做，两条路都要能跑（见 §6）。
- `targetSdk 30` 低于 31，因此 Android 12 的「必须显式声明 `android:exported`」硬性校验**不强制**；
  但我们仍然全部显式声明，免得日后 targetSdk 一升就崩。

---

## 3. JS 桥契约（最关键，逐字冻结）

### 3.1 注入

`MainActivity` 在 WebView 配置完成后、`loadUrl` **之前**执行：

```java
webView.addJavascriptInterface(new NativeBridge(this), "KangleNative");
```

- 注入名**逐字**为 `KangleNative`（JS 侧即 `window.KangleNative`）。
- 每个对外方法**必须**带 `@android.webkit.JavascriptInterface` 注解，漏一个该方法是隐形的。
- **桥方法运行在 WebView 私有的 "JavaBridge" 后台线程，不是主线程。**
  任何触碰 UI / 弹权限框 / `startActivity` / `Toast` 的动作，一律
  `activity.runOnUiThread(new Runnable(){ public void run(){ ... } });` 包一层。
  `AlarmManager`、`SharedPreferences`、`NotificationManager` 可在桥线程直调。
- 桥方法对 H5 可见性：`KangleNative` 只在**本 WebView 加载的页面**里存在（含错误兜底页）。

### 3.2 方法总表（**签名逐字照抄**）

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `boolean isSupported()` | — | 恒 `true` | 桥存在性探针 |
| `String getPlatformInfo()` | — | JSON 对象 | 版本/品牌/H5 地址 |
| `String syncReminders(String remindersJson)` | JSON 数组字符串 | JSON 对象 | **声明式全量覆盖**，核心方法 |
| `String getReminders()` | — | JSON 对象 | 回读原生侧已存的规范形态 |
| `String cancelAll()` | — | JSON 对象 | 清空存储 + 取消全部闹钟 |
| `String checkPermissions()` | — | JSON 对象 | 只读探测，不弹任何框 |
| `String requestPermission(String name)` | 见 §3.4 | JSON 对象 | 申请/跳设置页 |
| `String openSettings(String name)` | 见 §3.4 | JSON 对象 | 跳系统设置页 |
| `String getPendingAction()` | — | JSON 字符串，无则 `""` | 拉取「通知点击」待办，取走即清 |
| `String notifyNow(String json)` | Reminder JSON | JSON 对象 | 立刻发一条测试通知 |
| `void reload()` | — | — | 重载 H5（兜底页「重试」用） |
| `void toast(String text)` | — | — | 调试用，可在 release 里留 |

**铁律：任何 `String` 返回值一律是合法 JSON，UTF-8，不带首尾空白；永远不返回 `null`。**
出错时返回 `{"ok":false,"error":"<短码>"}`，短码取
`bad_json` / `no_activity` / `unsupported` / `io_error` 之一。

### 3.3 各方法返回形态（字段名逐字冻结）

`getPlatformInfo()` →
```json
{"ok":true,"package":"com.kangle.app","versionCode":2,"versionName":"1.1.0",
 "sdkInt":33,"brand":"Xiaomi","h5Url":"http://159.75.94.149:8000/"}
```

`syncReminders(json)` → 入参是 §3.6 的 Reminder 数组序列化（可为 `"[]"`）。
```json
{"ok":true,"received":5,"count":4,"armed":4,"mode":"exact","skipped":["bad#2"]}
```
- `received`：入参数组长度（解析失败即为 `ok:false`）。
- `count`：去重去非法后的合法条数。
- `armed`：其中 `enabled:true` 且成功排上的条数。
- `mode`：`"exact"` 或 `"inexact"`（见 §6.3）。
- `skipped`：被丢弃的条目标识 —— 非法对象用 `"#<下标>"`，非法 id 用该 id 原文。

`getReminders()` →
```json
{"ok":true,"items":[ /* Reminder 对象数组，见 §3.6 */ ]}
```

`cancelAll()` → `{"ok":true,"cancelled":4}`

`checkPermissions()` →
```json
{"ok":true,
 "notifications":{"granted":false,"required":true,"sdkMin":33},
 "exactAlarm":{"granted":false,"required":true,"sdkMin":31},
 "microphone":{"granted":true,"required":true,"sdkMin":23},
 "location":{"granted":false,"required":false,"sdkMin":23},
 "batteryOptimized":{"granted":false,"required":false,"sdkMin":23}}
```
- `granted` 语义 = 「这项能力当前可用」。
- `batteryOptimized.granted=true` 表示**已在白名单里**（即未被省电限制）。
- `required:false` 的项**本轮不申请**（location 留给 P4）。

`requestPermission(name)` / `openSettings(name)` →
```json
{"ok":true,"name":"notifications","result":"requested"}
```
`result` ∈ `"granted" | "denied" | "requested" | "settings_opened" | "unavailable" | "unsupported"`。

`getPendingAction()` → 有则返回 §3.7 的 payload JSON 字符串，无则返回**空字符串 `""`**（不是 `"null"`）。

`notifyNow(json)` → `{"ok":true}`；入参为单个 Reminder JSON（只用来做「测试提醒」按钮）。

### 3.4 `name` 取值表（逐字）

`requestPermission(name)`：

| name | 动作 | 典型 result |
|---|---|---|
| `"notifications"` | 已授权 → 直接 `"granted"`；**未授权 → 等价于 `openSettings("notification")`**，不调 `requestPermissions`（targetSdk<33 时它不弹框，会变成静默 no-op） | `"granted"` / `"settings_opened"` |
| `"exact_alarm"` | 等价于 `openSettings("exact_alarm")` | `"settings_opened"` |
| `"microphone"` | `requestPermissions(RECORD_AUDIO)` | `"requested"` / `"granted"` / `"denied"` |
| `"location"` | 本轮**不申请**，直接 | `"unsupported"` |
| `"battery"` | 等价于 `openSettings("battery")` | `"settings_opened"` |

`openSettings(name)`：

| name | Intent | 备注 |
|---|---|---|
| `"auto_start"` | `setClassName("com.miui.securitycenter","com.miui.permcenter.autostart.AutoStartManagementActivity")` | MIUI 自启动；`ActivityNotFoundException` → 退化为 `app_details`，result `"unavailable"` |
| `"battery"` | `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` + `data=package:com.kangle.app`；失败退 `ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS` | 需清单声明 `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` |
| `"notification"` | SDK≥26 用 `ACTION_APP_NOTIFICATION_SETTINGS` + `EXTRA_APP_PACKAGE`；否则 `app_details` | |
| `"exact_alarm"` | 字面量 `"android.settings.REQUEST_SCHEDULE_EXACT_ALARM"` + `data=package:...` | **不能用 `Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM` 符号**，API 30 jar 里没有，见 §3.5 |
| `"app_details"` | `ACTION_APPLICATION_DETAILS_SETTINGS` + `data=package:com.kangle.app` | 万能兜底，一定存在 |

`requestPermission` 中的 `exact_alarm` 与 `notifications` 走**异步**路径（跳设置页），
所以返回值只能是 `"requested"` / `"settings_opened"`。**H5 不在回调里等结果**，
统一在页面 `onShow` 时重新调 `checkPermissions()` 轮询（见 §10）。

> `notifications` 为什么**不**走 `requestPermissions`：本工程 `targetSdk=30`（<33），官方语义下
> targetSdk<33 的应用只有「首次创建通知渠道」那一次系统自动弹框，自己调 `requestPermissions`
> 不会弹；SDK≥33 且用户已点过「不允许」也不会二次弹框。结果是长辈点了引导页的「去开启」
> 什么都不会发生，且 App 内再也救不回来。所以未授权时统一跳通知设置页，让用户手动开启。
> 首次安装的自动弹框仍由 `NotificationHelper.ensureChannel()`（`onCreate` 第 2 步）负责。

### 3.5 编译期陷阱（**本机没有 SDK，只能照 API 30 签名手写，这几条一定踩**）

`android.jar` 是 **API 30**，**API 31+ 的符号一个都不存在**，直接写符号 = `javac` 编译失败：

| 想写 | 实际必须写 |
|---|---|
| `Manifest.permission.POST_NOTIFICATIONS` | 字符串字面量 `"android.permission.POST_NOTIFICATIONS"` |
| `Manifest.permission.SCHEDULE_EXACT_ALARM` | 字符串字面量 `"android.permission.SCHEDULE_EXACT_ALARM"` |
| `Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM` | 字符串字面量 `"android.settings.REQUEST_SCHEDULE_EXACT_ALARM"` |
| `AlarmManager.canScheduleExactAlarms()` | **反射**，见下 |
| `Build.VERSION_CODES.S` / `TIRAMISU` / `UPSIDE_DOWN_CAKE` | 整数 `31` / `33` / `34` |

`canScheduleExact()` 唯一合法写法（`AlarmScheduler` 内）：

```java
public boolean canScheduleExact() {
    if (Build.VERSION.SDK_INT < 31) return true;   // 31 之前没有这道限制
    try {
        java.lang.reflect.Method m = AlarmManager.class.getMethod("canScheduleExactAlarms");
        Object r = m.invoke(mAlarmManager);
        return Boolean.TRUE.equals(r);
    } catch (Throwable t) {
        return false;   // 拿不准就降级，宁可漂几分钟也不能崩
    }
}
```

同理，通知权限判定用 `activity.checkSelfPermission("android.permission.POST_NOTIFICATIONS")`
（`String` 重载，API 23 起有），**不要**用 `Manifest.permission.*` 常量。

### 3.6 Reminder JSON 形状（**跨语言唯一数据形态，冻结**）

```json
{
  "id": "med:0b0f3a2c-1111-2222-3333-444455556666:08:00",
  "kind": "medication",
  "title": "该吃硫酸氨基葡萄糖胶囊了",
  "body": "每次1粒 · 饭后温水送服，医生已开",
  "hour": 8,
  "minute": 0,
  "enabled": true,
  "planId": "0b0f3a2c-1111-2222-3333-444455556666",
  "elderId": "9a8b7c6d-0000-1111-2222-333344445555",
  "repeat": "daily"
}
```

| 键 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `id` | String | **是** | 非空，长度 ≤ 128，全局唯一 |
| `kind` | String | **是** | 只能是 `"medication"` 或 `"greeting"` |
| `title` | String | **是** | 非空，≤ 64 字符 |
| `body` | String | **是** | 可为空串 `""`，≤ 256 字符 |
| `hour` | int | **是** | 0–23 |
| `minute` | int | **是** | 0–59 |
| `enabled` | boolean | **是** | `false` 表示保留定义但不排闹钟 |
| `planId` | String / null | 否 | medication 时填 `medication_plans.id` |
| `elderId` | String / null | 否 | 统一填 `getCurrentUser().id` |
| `repeat` | String | 否 | 本轮**只支持** `"daily"`；缺省按 `"daily"` |

- **不合法即丢弃**（不进 `skipped` 报错，只把 id 列进 `skipped`）：`id` 空、`kind` 不在枚举、
  `hour`/`minute` 越界、`title` 空。
- **同 id 重复**：后者覆盖前者，不报错，不计入 `skipped`。
- 未列出的键一律忽略（前向兼容，不许因为多了个键就整条丢）。

`id` 生成规则（**逐字冻结**，两端必须算出同一个）：

```
medication:  "med:" + planId + ":" + pad2(hour) + ":" + pad2(minute)
greeting:    "greeting:morning"
```
`pad2(n)` = 两位零填充（`8` → `"08"`）。

`kind` 常量（Java）：`Reminder.KIND_MEDICATION = "medication"`、`Reminder.KIND_GREETING = "greeting"`。

### 3.7 原生 → H5 的唯一回调

原生侧在「通知被点击」和「H5 主动拉取」两条路上投递同一个 JSON：

```json
{"action":"open","route":"/pages/elder/medications","reminderId":"med:...:08:00","kind":"medication"}
```

- 推送：`webView.evaluateJavascript("window.__kangleNativeAction(" + JSONObject.quote(payload) + ");", null)`
  —— **必须用 `JSONObject.quote` 转义**，否则中文标题会把 JS 字符串打断。
- **`route` 映射（冻结）**：`kind=="medication"` → `"/pages/elder/medications"`；`kind=="greeting"` → `"/pages/elder/home"`。
- H5 侧必须注册 `window.__kangleNativeAction = function(payloadJson){ ... }`（见 §10）。
- 投递**只发生一次**：`getPendingAction()` 取走即清；推送成功后也清。两条路都通，不会重复弹窗。

### 3.8 桥不存在时的优雅降级（**前端适配层的义务，写死在 §10**）

`window.KangleNative === undefined` 时（纯浏览器 / 微信里打开 H5 / 服务器 APK 未更新），
`native.js` 的每个导出函数**必须**：

- **绝不抛异常**，绝不 `console.error` 刷屏；
- 返回该函数在该场景下的**空值形态**：
  - `nativeSupported()` → `false`
  - `syncReminders()` / `cancelAll()` / `requestPermission()` / `openSettings()` / `notifyNow()`
    → `{ok:false, reason:"no_bridge"}`
  - `getReminders()` / `buildMedicationReminders()` → `[]`
  - `checkPermissions()` → `{ok:false, reason:"no_bridge"}`
  - `openKeepAliveGuide()` → `{ok:false, reason:"no_bridge"}`
- 所有桥调用外面包 `try { } catch (e) { return 空值形态 }`，因为 `addJavascriptInterface` 在
  某些 ROM 上会抛 `TypeError`。

**调用点也不许因为降级而报错**：H5 页面照常渲染，「提醒与保活引导」section 在
`nativeSupported()===false` 时显示「当前在浏览器中打开，提醒功能需安装康乐 App」而不是隐藏。

---

## 4. Java 类的公开签名（**逐条照抄，不许改**）

包名一律 `package com.kangle.app;`。import 只能用 `java.*` 与 `android.*`（含框架自带的 `org.json.*`）。
**禁止**：`androidx.*`、`android.support.*`、`kotlin.*`、任何第三方坐标。

### 4.1 `Reminder`（模型，最先写，别人都依赖它）

```java
package com.kangle.app;

public class Reminder {
    public static final String KIND_MEDICATION = "medication";
    public static final String KIND_GREETING   = "greeting";

    public final String  id;
    public final String  kind;
    public final String  title;
    public final String  body;
    public final int     hour;
    public final int     minute;
    public final boolean enabled;
    public final String  planId;    // 可为 null
    public final String  elderId;   // 可为 null

    public Reminder(String id, String kind, String title, String body,
                    int hour, int minute, boolean enabled,
                    String planId, String elderId);

    /** 校验 §3.6 的全部约束（id/kind/hour/minute/title）。不合法返回 false。 */
    public boolean isValid();

    /** PendingIntent / 通知 id。恒为 id.hashCode() & 0x7fffffff。 */
    public int requestCode();

    /** 单个对象；字段缺失用默认值，不抛异常。抛 JSONException 由调用方兜。 */
    public static Reminder fromJson(org.json.JSONObject o) throws org.json.JSONException;

    public org.json.JSONObject toJson() throws org.json.JSONException;

    /** 解析数组；非法条目丢弃并把标识记进 skipped。永不返回 null。 */
    public static java.util.List<Reminder> listFromJson(String arrayJson, java.util.List<String> skipped);

    /** 序列化，输出 §3.6 的规范形态（键顺序不敏感）。 */
    public static String listToJson(java.util.List<Reminder> list);
}
```

**id 相同的去重在这里做**：`listFromJson` 内部用 `LinkedHashMap<String,Reminder>`，后者覆盖前者，
保留首次出现顺序。

### 4.2 `ReminderStore`（持久化）

```java
package com.kangle.app;

public class ReminderStore {
    public static final String PREFS_NAME   = "kangle_reminders";
    public static final String KEY_ITEMS    = "items_json";
    public static final String KEY_SYNCED_AT = "synced_at_ms";

    public ReminderStore(android.content.Context ctx);

    /** 读 §5 的 items_json 并解析；空/坏数据返回空 List（不抛）。 */
    public java.util.List<Reminder> load();

    /** 覆盖写：把 list 序列化成 §3.6 数组写进 KEY_ITEMS。 */
    public void save(java.util.List<Reminder> list);

    /** 按 id 取单条，用于 receiver 自排下一次。找不到返回 null。 */
    public Reminder find(String id);

    public void clear();

    public void setSyncedAt(long ms);

    public long syncedAt();
}
```

实现注意：**不做单例**。`AlarmScheduler`、`ReminderReceiver` 各自 `new ReminderStore(ctx)` 即可 ——
`SharedPreferences` 是进程级单例，多个包装实例读写同一份文件，安全。

### 4.3 `AlarmScheduler`（排期，链路的中间环）

```java
package com.kangle.app;

public class AlarmScheduler {
    public static final String MODE_EXACT   = "exact";
    public static final String MODE_INEXACT = "inexact";

    public AlarmScheduler(android.content.Context ctx);

    /**
     * 声明式全量覆盖，唯一入口。顺序写死：
     *   1) cancelAll()                    取消全部已排闹钟
     *   2) store.save(list)               写入原生副本
     *   3) store.setSyncedAt(now)
     *   4) 对每条 enabled==true 的 arm(r)
     *   5) 返回 mode()（"exact" / "inexact"）
     * 返回值为 §3.3 syncReminders 的 mode 字段。
     */
    public String apply(java.util.List<Reminder> list);

    /** 单条武装。receiver 自排下一次也走这个。先算 nextTriggerMillis，严格 > now。 */
    public void arm(Reminder r);

    /** 单条取消。 */
    public void cancel(Reminder r);

    /** 取消全部：对 store.load() 里每条 cancel()，再清空 store。 */
    public void cancelAll();

    /** 见 §3.5 的反射写法（API 30 的 android.jar 没有 canScheduleExactAlarms 符号）。 */
    public boolean canScheduleExact();

    /** 当前模式：canScheduleExact() ? MODE_EXACT : MODE_INEXACT。 */
    public String mode();

    /** 下一次触发毫秒数：设备本地时区，今天该时刻已过则顺延一天。 */
    public static long nextTriggerMillis(int hour, int minute);
}
```

`apply()` 里**先 cancelAll 再 save 再 arm**，顺序不能换 —— 反过来的话 `cancelAll()` 会把刚写的副本一起清掉。

**调用链冻结**：`NativeBridge.syncReminders` → `new AlarmScheduler(activity).apply(list)`；
`ReminderReceiver.onReceive` → `new AlarmScheduler(context).arm(r)`。

### 4.4 `NativeBridge`（JS 桥实现）

```java
package com.kangle.app;

public class NativeBridge {
    /** 构造签名冻结；MainActivity 必须传自己。 */
    public NativeBridge(MainActivity activity);

    @android.webkit.JavascriptInterface public boolean isSupported();
    @android.webkit.JavascriptInterface public String  getPlatformInfo();
    @android.webkit.JavascriptInterface public String  syncReminders(String remindersJson);
    @android.webkit.JavascriptInterface public String  getReminders();
    @android.webkit.JavascriptInterface public String  cancelAll();
    @android.webkit.JavascriptInterface public String  checkPermissions();
    @android.webkit.JavascriptInterface public String  requestPermission(String name);
    @android.webkit.JavascriptInterface public String  openSettings(String name);
    @android.webkit.JavascriptInterface public String  getPendingAction();
    @android.webkit.JavascriptInterface public String  notifyNow(String json);
    @android.webkit.JavascriptInterface public void    reload();
    @android.webkit.JavascriptInterface public void    toast(String text);
}
```

`syncReminders` 的实现骨架（**顺序写死**）：

```java
public String syncReminders(String remindersJson) {
    try {
        java.util.List<String> skipped = new java.util.ArrayList<String>();
        java.util.List<Reminder> list = Reminder.listFromJson(remindersJson, skipped);
        String mode = new AlarmScheduler(mActivity).apply(list);
        org.json.JSONObject o = new org.json.JSONObject();
        o.put("ok", true);
        o.put("received", countTopLevel(remindersJson));  // 用 JSONArray.length()，非 0 时即数组长度
        o.put("count", list.size());
        o.put("armed", countEnabled(list));
        o.put("mode", mode);
        o.put("skipped", new org.json.JSONArray(skipped));
        return o.toString();
    } catch (Throwable t) {
        return "{\"ok\":false,\"error\":\"bad_json\"}";
    }
}
```

### 4.5 `MainActivity`（壳）

```java
package com.kangle.app;

public class MainActivity extends android.app.Activity {
    public  static final String DEFAULT_H5_URL   = "http://159.75.94.149:8000/";
    public  static final String META_H5_URL      = "kangle.h5_url";
    public  static final String EXTRA_ROUTE      = "kangle.route";
    public  static final String EXTRA_REMINDER_ID = "kangle.reminder_id";
    public  static final String EXTRA_ACTION     = "kangle.action";
    public  static final String EXTRA_PAYLOAD    = "kangle.payload";
    public  static final int    RC_AUDIO         = 1001;
    public  static final int    RC_NOTIFICATIONS = 1002;

    protected void onCreate(android.os.Bundle savedInstanceState);
    protected void onResume();
    protected void onNewIntent(android.content.Intent intent);
    public    void onBackPressed();
    public    void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults);

    /** 从清单 meta-data 读 H5 地址；缺失/为空则回退 DEFAULT_H5_URL。 */
    public String h5Url();

    /** WebView 访问器，NativeBridge 用它 evaluateJavascript。 */
    public android.webkit.WebView webView();

    /** 有 pendingAction 就派发；**派发成功之后**才清空（WebView 未就绪 / 抛异常时保留，交给 getPendingAction 拉）。 */
    public void dispatchPendingAction();

    /** loadUrl(h5Url())；已加载过则 reload()。 */
    public void loadH5();

    /** 用 loadDataWithBaseURL(null, html, "text/html", "utf-8", null) 显示离线兜底页。 */
    public void showOfflinePage(String reason);
}
```

内部类（`private`，不进跨文件契约，但行为冻结）：

- `private class KangleWebViewClient extends android.webkit.WebViewClient`
  - `onPageFinished(WebView, String)` → 调 `dispatchPendingAction()`
  - `onReceivedError(WebView, int, String, String)` → **API 21/22 走这条**（23+ 由下面的 3 参版本负责）；仅当 `failingUrl` 等于主文档 URL 时 `showOfflinePage(...)`
  - `onReceivedError(WebView, WebResourceRequest, WebResourceError)` → **API 23+ 必须显式覆写**：`request.isForMainFrame()` 时 `showOfflinePage(...)`。不能只依赖框架里「3 参默认实现转发给 4 参」——那是 `WebViewClient` 自己的实现细节（AOSP 原注释即 `TODO: Remove this deprecated path`），一旦不再转发，主文档加载失败就永远不触发兜底页（§11.1 的白屏）。为此**不调 super**（调了会经 4 参版本把兜底页加载两遍；`showOfflinePage` 本身幂等）。`WebResourceError` 是 API 23 引入的类，API 30 的 `android.jar` 里必然存在
  - `onReceivedHttpError(WebView, WebResourceRequest, WebResourceResponse)` → 主文档 5xx/4xx 也走兜底页
  - `shouldOverrideUrlLoading(WebView, String)` → **`return false`**（站内跳转留在 WebView 里）
- `private class KangleChromeClient extends android.webkit.WebChromeClient`
  - `onPermissionRequest(android.webkit.PermissionRequest request)` → 见 §8.2
  - `onPermissionRequestCanceled(PermissionRequest)` → `request.deny()`
  - `onGeolocationPermissionsShowPrompt(String, GeolocationPermissions.Callback)` → `callback.invoke(origin, false, false)`，**地理资源一律 deny**（P4 再开，见 §8.2）

`onCreate` 执行顺序（**写死**）：

1. `super.onCreate`；`requestWindowFeature` 不需要；`setContentView(webView)`
2. `NotificationHelper.ensureChannel(this)` ← **必须在第一批通知之前**，Android 13 的权限框就是它触发的
3. 建 WebView → `configureWebView()` → `addJavascriptInterface(new NativeBridge(this), "KangleNative")`
4. `setWebViewClient(new KangleWebViewClient())` / `setWebChromeClient(new KangleChromeClient())`
5. `CookieManager.getInstance().setAcceptCookie(true)` + `setAcceptThirdPartyCookies(webView, true)`
6. 解析启动 Intent 存成 `pendingAction`（见 §3.7）
7. SDK≥23 时 `requestPermissions(new String[]{"android.permission.RECORD_AUDIO"}, RC_AUDIO)`
8. `loadH5()`

`onNewIntent` 必须 `setIntent(intent)`，再解析出新 `pendingAction`，再 `dispatchPendingAction()`。
`launchMode` 用 `singleTask`（见 §7.3），保证走 `onNewIntent` 而不是再开一个 Activity。

### 4.6 `ReminderReceiver`

```java
package com.kangle.app;

public class ReminderReceiver extends android.content.BroadcastReceiver {
    public static final String ACTION_REMIND = "com.kangle.app.ACTION_REMIND";
    public static final String EXTRA_ID      = "kangle.reminder_id";

    public void onReceive(android.content.Context context, android.content.Intent intent);
}
```

`onReceive` 逻辑（**顺序写死**）：

1. `String id = intent.getStringExtra(EXTRA_ID); if (id == null) return;`
2. `Reminder r = new ReminderStore(context).find(id); if (r == null || !r.enabled) return;`
3. `NotificationHelper.show(context, r);`
4. `new AlarmScheduler(context).arm(r);` ← **自排下一次，这条不能漏**（见 §6.1）

### 4.7 `BootReceiver`

```java
package com.kangle.app;

public class BootReceiver extends android.content.BroadcastReceiver {
    public void onReceive(android.content.Context context, android.content.Intent intent);
}
```

`onReceive` 逻辑：`new AlarmScheduler(context).apply(new ReminderStore(context).load());`
（`apply` 是幂等的「取消全部 + 重新武装」，直接复用，不要另写一份循环。）
用 `String a = intent.getAction()` 过滤，只认这 4 个（都不需要额外权限，且都是系统保护广播）：
`Intent.ACTION_BOOT_COMPLETED`、`Intent.ACTION_MY_PACKAGE_REPLACED`、
`Intent.ACTION_TIMEZONE_CHANGED`、`Intent.ACTION_TIME_CHANGED`。

`MY_PACKAGE_REPLACED` 是必需的：**应用升级会把所有已排闹钟清空**，不重排就从此不响。

### 4.8 `NotificationHelper`

```java
package com.kangle.app;

public class NotificationHelper {
    public static final String CHANNEL_ID   = "kangle_reminders";
    public static final CharSequence CHANNEL_NAME = "用药与问候提醒";
    public static final int    CHANNEL_IMPORTANCE = 4;   // = NotificationManager.IMPORTANCE_HIGH，写常量避免符号问题

    /** 幂等；SDK≥26 才真正建 channel。必须在主线程调用（Android 13 权限框由它触发）。 */
    public static void ensureChannel(android.content.Context ctx);

    /** 构造并 notify(r.requestCode(), n)。 */
    public static void show(android.content.Context ctx, Reminder r);

    /** 点击通知的 PendingIntent，见 §7.2。 */
    public static android.app.PendingIntent contentIntent(android.content.Context ctx, Reminder r);

    public static void cancel(android.content.Context ctx, int requestCode);
}
```

---

## 5. 持久化（原生侧才是真值副本）

| 项 | 值（冻结） |
|---|---|
| SharedPreferences 文件名 | `"kangle_reminders"`（`ReminderStore.PREFS_NAME`） |
| 模式 | `Context.MODE_PRIVATE` |
| 键 `items_json` | `String` —— §3.6 Reminder 对象的 **JSON 数组**，全量快照 |
| 键 `synced_at_ms` | `long` —— 上次成功 sync 的 `System.currentTimeMillis()` |

**存数组而不是逐条 key**：`syncReminders` 是声明式全量覆盖，一次 `putString` 就是原子替换，
不会出现「一半新一半旧」；逐条 key 还要自己做删除对账，纯属自找。

**为什么计划必须存在原生侧，而不是 WebView 里：**

- App 被杀 / 系统回收后，WebView 连同它的 `localStorage` **整体消失**；`AlarmManager` 的
  `PendingIntent` 到点会拉起一个**全新的进程**，那时没有 WebView、没有 H5、读不到 `localStorage`。
- `ReminderReceiver` / `BootReceiver` 的运行环境只有 `Context` + 应用私有存储。
  `BroadcastReceiver` 里拿不到 `localStorage`（那是 WebView 的 JS 世界）。
- 结论：**SharedPreferences 是闹钟唯一的可读真值**；`localStorage` 只用来存用户偏好
  （问候开关、问候时间），不存闹钟表。H5 每次同步时把「用户偏好 + 后端计划」合成出完整数组推给原生。

---

## 6. 重排语义（必须写死）

### 6.1 到点自排下一次

`AlarmManager` **没有「每天重复」的正确实现**：`setRepeating` 在 API 19+ 被系统降级为不精确，
且 `setExactAndAllowWhileIdle` 根本不支持 repeating。所以：

> **闹钟触发 → `ReminderReceiver` 弹通知 → 立刻调 `arm(r)` 排下一次。**

`arm()` 内部算 `nextTriggerMillis(hour, minute)`，它**严格大于当前时刻**，
所以刚到点的这次自然落到**明天同一 HH:MM**。于是「同步一次 → 天天响」，不需要 App 再打开。

### 6.2 开机 / 换包 / 改时区 → 重新武装

以上事件会清空或错位系统闹钟表。`BootReceiver` 收到后按 §4.7 无条件 `apply(store.load())`。
**这一条是「重启后还能不能响」的唯一保障**，测试时必须手工验证。

### 6.3 两级降级（都要有，不能只写一条）

`nextTriggerMillis` 算出来的时刻 `t`，按 SDK 分支武装：

| SDK_INT | 精确路径 | 拿不到精确权限时的退路 |
|---|---|---|
| ≥ 31 | `canScheduleExact()==true` → `setExactAndAllowWhileIdle(RTC_WAKEUP, t, pi)` | `setAndAllowWhileIdle(RTC_WAKEUP, t, pi)` |
| 23–30 | `setExactAndAllowWhileIdle(RTC_WAKEUP, t, pi)` | `setAndAllowWhileIdle(RTC_WAKEUP, t, pi)` |
| 21–22 | `setExact(RTC_WAKEUP, t, pi)` | `set(RTC_WAKEUP, t, pi)` |

（`setAndAllowWhileIdle` 是 API 23 起的，21/22 上不存在，所以那张表必须分三档。）

`mode()` 返回 `"exact"` 或 `"inexact"`，一路透传到 `syncReminders` 的返回值，
H5 据此在引导页显示「已开启精确提醒」或「提醒可能延迟几分钟」。

**PendingIntent 身份一致性（否则取消不掉）**：广播 PendingIntent 必须由
`new Intent(ctx, ReminderReceiver.class)` + `setAction(ACTION_REMIND)` + `putExtra(EXTRA_ID, r.id)`
+ `requestCode = r.requestCode()` 构成；flags 固定
`PendingIntent.FLAG_UPDATE_CURRENT | (SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0)`。
`cancel(r)` 用构造**完全相同**的 Intent + `FLAG_NO_CREATE` 取回再 `alarmManager.cancel(pi)`。
少一个 action 或换一个 requestCode，cancel 就是静默失败 —— 会积出一堆幽灵闹钟。

### 6.4 已知漂移

- `inexact` 路径在 Doze 下可能**漂移数分钟**（系统按窗口批量唤醒），这是设计内的代价，不是 bug。
- API 23+ 上 `setExactAndAllowWhileIdle` 对同一应用有**最短间隔节流**（历史约 9 分钟），
  用药时刻间隔远超它，不受影响。
- 极端 Doze 下即使是 exact 也可能被延后；**两级都不能保证秒级**。

---

## 7. 通知

### 7.1 channel 与重要性

```java
// NotificationHelper.ensureChannel，必须主线程
if (Build.VERSION.SDK_INT >= 26) {
    NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
    if (nm.getNotificationChannel(CHANNEL_ID) == null) {
        NotificationChannel ch = new NotificationChannel(CHANNEL_ID, CHANNEL_NAME, CHANNEL_IMPORTANCE);
        ch.setDescription("康乐的用药与晨间问候提醒");
        ch.enableVibration(true);
        ch.setShowBadge(true);
        // 不 setSound → 走 IMPORTANCE_HIGH 的默认提示音
        nm.createNotificationChannel(ch);
    }
}
```

- `CHANNEL_ID = "kangle_reminders"`、重要性 **`IMPORTANCE_HIGH`（值 4）**。
  **只有 HIGH 才会弹横幅（heads-up）**；DEFAULT 只出图标、不出横幅，长辈根本注意不到。
- 不设自定义提示音，用 channel 默认音 —— 少一个资源文件，也少一处出错点。

### 7.2 通知构造与点击

```java
// show()
Notification.Builder b;
if (Build.VERSION.SDK_INT >= 26) {
    b = new Notification.Builder(ctx, CHANNEL_ID);
} else {
    b = new Notification.Builder(ctx);
    b.setPriority(Notification.PRIORITY_HIGH);
    b.setDefaults(Notification.DEFAULT_ALL);
}
b.setSmallIcon(R.drawable.ic_notify)   // 工程自带的 VectorDrawable，不需要打包任何 PNG
 .setContentTitle(r.title)
 .setContentText(r.body)
 .setTicker(r.title)
 .setCategory(Notification.CATEGORY_REMINDER)
 .setVisibility(Notification.VISIBILITY_PUBLIC)
 .setShowWhen(true)
 .setWhen(System.currentTimeMillis())
 .setAutoCancel(true)
 .setOnlyAlertOnce(false)
 .setContentIntent(contentIntent(ctx, r));
((NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE))
    .notify(r.requestCode(), b.build());
```

`contentIntent`：

```java
Intent i = new Intent(ctx, MainActivity.class);
i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
i.putExtra(MainActivity.EXTRA_ACTION, "open");
i.putExtra(MainActivity.EXTRA_REMINDER_ID, r.id);
i.putExtra(MainActivity.EXTRA_ROUTE,
           Reminder.KIND_MEDICATION.equals(r.kind) ? "/pages/elder/medications" : "/pages/elder/home");
i.putExtra(MainActivity.EXTRA_PAYLOAD, payloadJson(r));   // §3.7 的完整 JSON
int flags = PendingIntent.FLAG_UPDATE_CURRENT;
if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;  // API 31+ 强制
return PendingIntent.getActivity(ctx, r.requestCode(), i, flags);
```

- 通知 id = `r.requestCode()`，同一条提醒重复触发是**替换**不是堆叠。
- `FLAG_IMMUTABLE` 必须带（API 31+ 对着可变 PendingIntent 直接抛 `IllegalArgumentException`）；
  `FLAG_IMMUTABLE` 是 API 23 常量，minSdk 21 所以要分支。

### 7.3 图标：应用图标（自适应 + PNG 兜底）与通知小图标

| 用途 | 取值 | 理由 |
|---|---|---|
| 通知小图标 | `R.drawable.ic_notify`（`res/drawable/ic_notify.xml`） | 工程自带的 VectorDrawable，API 21+ 原生支持；纯白 + 透明底，系统按通知栏样式着色 |
| 应用图标（API 26+） | `res/mipmap-anydpi-v26/ic_launcher.xml` —— 自适应图标：底 `@color/ic_launcher_background`（`#FF6B35`）+ 前景 `@drawable/ic_launcher_foreground`（白心，108dp viewport；心形实占 44×40.4、居 54,54，最大外扩 22 < 中心 66dp 安全圆的内接方半宽 23.3） | 演示机 MIUI（Android 11+）走这条；任何形状的启动器遮罩都切不到心形 |
| 应用图标（API 21–25 兜底） | `res/mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png`（48/72/96/144/192） | 自适应图标是 API 26 才有的；少这几档 PNG，API<26 上 `@mipmap/ic_launcher` 就解析不到 |

仓库里那 5 个 PNG 是**生成物**，不是手画的：`tools/make_icons.py`（纯标准库 `zlib`+`struct` 手写 PNG，
无第三方依赖）按品牌色 `$lyj-primary #FF6B35`（`uni.scss:16`）画圆角方块 + 白心，3×3 超采样消锯齿。
**改图标改脚本后重跑，不要手改 PNG。**

> **实测订正（2026-09-13，本机真实构建）。** 本节早先写过「图标**一律不打包 PNG / `mipmap-*dpi`** —— 那正是
> 无 Gradle 链最容易翻车的地方」。这条**被实测否掉了**：本机用 aapt → javac → d8 → zipalign → apksigner
> 整条链跑通，5 个密度 PNG 正常打包，`aapt dump badging` 退出码 **0**，`zipalign -c -p 4` 通过；
> aapt 把 RGBA 重编码成调色板 PNG（colortype 3，245 色 / 109 项 `tRNS`）后 **alpha 完好**，
> 圆角处仍是 `(0,0,0,0)`。**无 Gradle 链真正会翻车的不是 PNG，是下面这条框架资源引用。**

**唯一的雷：框架资源引用。** 写 `android:icon="@android:drawable/sym_def_app_icon"` 这类**框架资源**时，
`aapt` 编包只给 warning，但 `aapt dump badging` 会以退出码 1 结束（`ERROR getting 'android:icon' attribute:
attribute value reference does not exist` —— android.jar 的资源表里那个 id 只是桩字符串），
会让 `build_apk.sh` 第 8 步误判成构建失败。**只用本工程自己的资源**（`@mipmap/` `@drawable/` `@color/`
`@xml/`），不要用 `@android:` 下的资源。改通知小图标则同步改 `NotificationHelper.show()` 里的
`setSmallIcon(...)` 常量。

---

## 8. 权限矩阵

### 8.1 总表

| 权限 | 写清单？ | 申请方式 | 在哪一步做 |
|---|---|---|---|
| `INTERNET` | ✅ | 无需（安装即授予） | 清单即可；WebView 联网靠它 |
| `RECORD_AUDIO` | ✅ | **运行时**（API 23+） | ①`MainActivity.onCreate` 第 7 步先要一次；②`KangleChromeClient.onPermissionRequest` 里发现未授予时再要并当场 `deny()`，H5 下次点击重试 |
| `ACCESS_FINE_LOCATION` | ✅ **仅预留** | **本轮不申请** | 留给 P4 途中守护。本轮不请求、不在 `onPermissionRequest` 里 grant 地理资源 |
| `ACCESS_COARSE_LOCATION` | ✅ **仅预留** | **本轮不申请** | 同上 |
| `POST_NOTIFICATIONS` | ✅（字面量） | Android 13+ 且 targetSdk<33 → **建 channel 时系统自动弹框**；`requestPermission("notifications")` 里 SDK≥33 再显式要一次兜底 | `NotificationHelper.ensureChannel()`（onCreate 第 2 步）+ `NativeBridge.requestPermission` |
| `SCHEDULE_EXACT_ALARM` | ✅（字面量） | **特殊权限，无运行时弹框**，只能跳设置页人工授予 | `AlarmScheduler.canScheduleExact()`（反射）+ `NativeBridge.openSettings("exact_alarm")` |
| `RECEIVE_BOOT_COMPLETED` | ✅ | 无需（普通权限） | `BootReceiver` 的 `onReceive` |
| `VIBRATE` | ✅ | 无需（普通权限） | `Notification` 的 `DEFAULT_ALL` / channel 振动要用 |
| `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` | ✅ | 特殊访问，跳设置页 | `NativeBridge.openSettings("battery")`；判定用 `PowerManager.isIgnoringBatteryOptimizations(pkg)`（API 23） |
| `FOREGROUND_SERVICE` | ✅ **仅预留** | 无需 | **本轮不实现任何 Service**，只占位，注释写明 `<!-- P4: 途中守护 -->` |
| `WAKE_LOCK` | ❌ 不声明 | — | `RTC_WAKEUP` 闹钟本身就能唤醒设备，通知也不需要它。多声明一个就是多一份解释成本 |

`android:exported` 全部**显式声明**（虽然 targetSdk 30 不强制，但 Android 12+ 安装校验会警告，
且日后升 targetSdk 就是硬错）：

| 组件 | exported | 理由 |
|---|---|---|
| `MainActivity` | `true` | 带 LAUNCHER intent-filter；通知点击也要能进 |
| `ReminderReceiver` | `false` | 只由**本应用**自己的 PendingIntent 触发（显式 Intent，同应用身份），外部不该唤起 |
| `BootReceiver` | `true` | 要收系统广播；这几条都是**保护广播**，第三方应用无法伪造 |

### 8.2 WebView 权限（麦克风，H5 录音链路的命门）

`src/api/asr.js:82-83` 用的是 `navigator.mediaDevices.getUserMedia({audio:true})`。
WebView 里这条**必须先经 `WebChromeClient.onPermissionRequest` 放行**，否则 promise 直接 reject，
`LyjMic.vue` 会弹「麦克风不可用」。

```java
// KangleChromeClient
@Override
public void onPermissionRequest(final android.webkit.PermissionRequest request) {
    // 必须回主线程
    mActivity.runOnUiThread(new Runnable() {
        public void run() {
            boolean wantsAudio = false;
            for (String res : request.getResources()) {
                if (android.webkit.PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(res)) wantsAudio = true;
            }
            if (wantsAudio && hasRecordAudio(mActivity)) {          // checkSelfPermission("android.permission.RECORD_AUDIO") == GRANTED
                request.grant(new String[]{ android.webkit.PermissionRequest.RESOURCE_AUDIO_CAPTURE });
            } else {
                if (wantsAudio) mActivity.requestPermissions(
                        new String[]{"android.permission.RECORD_AUDIO"}, MainActivity.RC_AUDIO);
                request.deny();   // 本轮 GPS 不涉及；地理资源一律 deny（P4 再开）
            }
        }
    });
}
```

`window.SpeechRecognition` / `speechSynthesis`（`asr.js:197,225`）在 Android WebView 里通常不存在，
H5 已有降级（`webSpeechAvailable()` 返 false），**不需要**为它们放行任何权限。

### 8.3 明文流量（Android 9+ 白屏的根因，**两条都要**）

H5 是 `http://` 明文，Android 9(API 28) 起默认禁止，不处理就是**纯白屏**。
两条一起上，覆盖 API 21–35：

1. `<application android:usesCleartextTraffic="true" ...>` —— API 23+ 生效（21/22 本就允许）。
2. `android:networkSecurityConfig="@xml/network_security_config"` —— API 24+ 起它是权威配置，
   会**覆盖**上面那个属性的宽泛放行，所以这里也必须放行。

`res/xml/network_security_config.xml`（**内容照抄**）：

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <!-- 康乐 H5 由 159.75.94.149:8000 明文托管；壳不内嵌 H5，必须放行 -->
    <base-config cleartextTrafficPermitted="true" />
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="true">159.75.94.149</domain>
    </domain-config>
</network-security-config>
```

同时 WebView 侧：`settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW)`（API 21+），
免得 H5 里的 http 子资源被拦。

### 8.4 `AndroidManifest.xml` 骨架（**照抄，只改注释**）

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.kangle.app"
    android:versionCode="2"
    android:versionName="1.1.0">

    <uses-sdk android:minSdkVersion="21" android:targetSdkVersion="30" />

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.VIBRATE" />
    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
    <uses-permission android:name="android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
    <uses-permission android:name="android.permission.SCHEDULE_EXACT_ALARM" />
    <!-- P4: 途中守护预留，本轮不申请、不实现 -->
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />

    <application
        android:icon="@mipmap/ic_launcher"
        android:label="@string/app_name"
        android:theme="@style/AppTheme"
        android:allowBackup="false"
        android:hardwareAccelerated="true"
        android:usesCleartextTraffic="true"
        android:networkSecurityConfig="@xml/network_security_config">
        <!-- 图标只用本工程资源。绝不要写 @android:drawable/... 这类框架资源引用：
             那会让 aapt dump badging 以退出码 1 结束，见 §7.3 -->

        <meta-data android:name="kangle.h5_url" android:value="http://159.75.94.149:8000/" />

        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:launchMode="singleTask"
            android:configChanges="orientation|screenSize|smallestScreenSize|screenLayout|keyboardHidden|locale|layoutDirection|uiMode">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <receiver android:name=".ReminderReceiver" android:exported="false" android:enabled="true" />

        <receiver android:name=".BootReceiver" android:exported="true" android:enabled="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
                <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />
                <action android:name="android.intent.action.TIMEZONE_CHANGED" />
                <action android:name="android.intent.action.TIME_SET" />
            </intent-filter>
        </receiver>
    </application>
</manifest>
```

`android:configChanges` 那一长串是**有意的**：不写的话屏幕一转 Activity 就重建，
WebView 重载 = 聊天上下文全丢。`launchMode="singleTask"` 保证通知点击走 `onNewIntent`
而不是再开一个壳。

`res/values/strings.xml`：只有 `<string name="app_name">康乐</string>`。
`res/values/styles.xml`：

```xml
<resources>
    <style name="AppTheme" parent="@android:style/Theme.Material.Light.NoActionBar">
        <!-- 与 H5 的浅色底接近，消掉 WebView 首帧白闪 -->
        <item name="android:windowBackground">#FFFBF7F2</item>
    </style>
</resources>
```

---

## 9. 构建脚本变量块（`build_apk.sh` 顶部）

```sh
#!/usr/bin/env bash
set -euo pipefail

# ===== 可改变量 =====
PKG_NAME="com.kangle.app"
APP_LABEL="康乐"
VERSION_CODE="${KANGLE_VERSION_CODE:-2}"     # 必须 > 服务器上已装 APK 的 versionCode（脚本 0/9 会读旧包强制校验）
VERSION_NAME="${KANGLE_VERSION_NAME:-1.1.0}"
H5_URL="http://159.75.94.149:8000/"

# ===== 签名（绝不写口令明文，只读环境变量）=====
KEYSTORE_PATH="${KANGLE_KEYSTORE:-/opt/laoyouji/keys/kangle.keystore}"
KEY_ALIAS="${KANGLE_KEY_ALIAS:-kangle}"
# 口令从环境变量读，apksigner 的 env: 语法直接引用变量名，脚本里不出现任何口令值
STORE_PASS_ENV="KANGLE_STORE_PASS"
KEY_PASS_ENV="KANGLE_KEY_PASS"

# ===== 工具链（本机没有 SDK，全部在服务器上）=====
ANDROID_JAR="${ANDROID_JAR:-/opt/android-sdk/platforms/android-30/android.jar}"
BUILD_TOOLS="${BUILD_TOOLS:-/opt/android-sdk/build-tools/30.0.3}"
AAPT="$BUILD_TOOLS/aapt"
D8="$BUILD_TOOLS/d8"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"

# ===== 产物 =====
OUT_APK="${OUT_APK:-/opt/laoyouji/backend/static_dist/laoyouji.apk}"
```

### 9.1 必须先做的两件事（写进脚本开头的注释，**人工执行**）

1. **确认旧壳的 versionCode**（决定 `VERSION_CODE` 取几）：
   ```sh
   aapt dump badging "$OUT_APK" | head -1     # 看 versionCode='N'
   ```
   然后 `export KANGLE_VERSION_CODE=$((N+1))`。**不得小于等于 N**，否则覆盖安装被系统拒绝。
   这条现在由脚本的 `0/9` **强制**（它自己读 `$OUT_APK` 里的 versionCode，不通过直接 `exit 1`
   并提示该 export 成几）；这里人工看一眼只是为了提前知道要 export 几。
2. **复用服务器上已有的 keystore**（换 key = 覆盖安装被拒 + 只能先卸载 + 丢数据）：
   ```sh
   cat /opt/laoyouji/build_apk.sh            # 旧脚本里的 keystore 路径/别名就是真值
   find /opt/laoyouji -name '*.keystore' -o -name '*.jks' 2>/dev/null
   ```
   把真实路径/别名写进 `KANGLE_KEYSTORE` / `KANGLE_KEY_ALIAS`（或改脚本默认值），**口令只进环境变量**：
   ```sh
   export KANGLE_STORE_PASS='...'   # 只在 shell 里，不进仓库、不进脚本、不进输出
   export KANGLE_KEY_PASS='...'
   ```

### 9.2 构建步骤（工具链顺序冻结）

```sh
# 0) 校验口令、工具链存在、以及 versionCode 相对线上旧包严格递增，缺什么立刻报错退出（不要静默继续）
: "${!STORE_PASS_ENV:?请先 export $STORE_PASS_ENV}"
: "${!KEY_PASS_ENV:?请先 export $KEY_PASS_ENV}"
for t in "$AAPT" "$D8" "$ZIPALIGN" "$APKSIGNER" "$ANDROID_JAR"; do
  [ -e "$t" ] || { echo "缺少工具链: $t" >&2; exit 1; }
done
# OUT_APK 已存在时读它的 versionCode；VERSION_CODE <= 旧值 直接 exit 1（否则覆盖安装必被系统拒绝）
OLD_VERSION_CODE="$( ( "$AAPT" dump badging "$OUT_APK" 2>/dev/null || true ) \
    | sed -n "s/^package:.*versionCode='\([0-9]*\)'.*/\1/p" | sed -n '1p' )"
[ -z "$OLD_VERSION_CODE" ] || [ "$VERSION_CODE" -gt "$OLD_VERSION_CODE" ] \
  || { echo "VERSION_CODE 必须 > $OLD_VERSION_CODE" >&2; exit 1; }

# 1) 版本号与 H5 地址注入到 build 副本（不动仓库里的源文件）
rm -rf build gen && mkdir -p build gen
sed -e "s/android:versionCode=\"[0-9]*\"/android:versionCode=\"$VERSION_CODE\"/" \
    -e "s/android:versionName=\"[^\"]*\"/android:versionName=\"$VERSION_NAME\"/" \
    -e "s#\(name=\"kangle.h5_url\" android:value=\"\)[^\"]*#\1$H5_URL#" \
    AndroidManifest.xml > build/AndroidManifest.xml

# 2) aapt：编资源 + 生成 R.java + 打未对齐 apk（先生成 R.java，javac 要用）
"$AAPT" package -f -m \
  -M build/AndroidManifest.xml -S res -I "$ANDROID_JAR" \
  -J gen -F build/app.unaligned.apk

# 3) javac：-encoding UTF-8 是硬需求（源码含中文文案），否则编译期乱码
javac -source 8 -target 8 -encoding UTF-8 -Xlint:-options \
  -bootclasspath "$ANDROID_JAR" -classpath "$ANDROID_JAR" \
  -d build/classes \
  $(find src gen -name '*.java')

# 4) d8：class → classes.dex（--min-api 21）
"$D8" --lib "$ANDROID_JAR" --min-api 21 --output build \
  $(find build/classes -name '*.class')

# 5) 把 dex 塞进 apk
( cd build && "$AAPT" add app.unaligned.apk classes.dex )

# 6) 4 字节对齐
"$ZIPALIGN" -p -f 4 build/app.unaligned.apk build/app.aligned.apk

# 7) 签名 v1+v2+v3，**签进 build/ 里的临时文件**（口令经 env: 引用，脚本里零明文）
"$APKSIGNER" sign \
  --ks "$KEYSTORE_PATH" --ks-key-alias "$KEY_ALIAS" \
  --ks-pass "env:$STORE_PASS_ENV" --key-pass "env:$KEY_PASS_ENV" \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out build/app.signed.apk build/app.aligned.apk

# 8) 自检：签名可验 + 包名/versionCode 合预期 + 证书与线上旧包同源（不一致 = 换了 key，exit 1）
"$APKSIGNER" verify --print-certs build/app.signed.apk
"$AAPT" dump badging build/app.signed.apk > build/badging.txt || true   # 退出码不作判据，见 §9.3
grep -E "^package:" build/badging.txt
grep -Eq "versionCode='$VERSION_CODE'" build/badging.txt

# 9) 原子落盘：旧包先备份，再把通过第 8 步的包 mv 到对外路径；中间产物此时才清理
if [ -f "$OUT_APK" ]; then cp -f "$OUT_APK" "$OUT_APK.bak"; fi
mv -f build/app.signed.apk "$OUT_APK"
rm -rf gen build
```

### 9.3 脚本纪律

- **仓库里不许出现任何 : 口令、token、密码的真实值**（含本文件、`.sh`、`.java`、提交信息）。
  口令只以 `env:KANGLE_STORE_PASS` / `env:KANGLE_KEY_PASS` 的**变量名**出现。
- `zipalign -p` 在 build-tools 35+ 已被移除；若服务器上是新工具链报 `unknown option -p`，
  去掉 `-p`（`-f 4` 保留）。
- `-encoding UTF-8` 不能省；漏了会在 `CHANNEL_NAME = "用药与问候提醒"` 这类字面量上报编码错。
- `aapt dump badging` 在清单出现**框架资源引用**（如 `android:icon="@android:drawable/..."`）时会以
  退出码 1 结束（`ERROR getting 'android:icon' attribute: attribute value reference does not exist`，
  android.jar 的资源表里那个 id 只是桩字符串）。本工程已把图标改成本地 `@mipmap/ic_launcher`，
  当前清单实测退出码 **0**；但 `|| true` 这一层仍然保留，它是针对"日后又引入框架资源引用"的兜底。
  **成败判据始终是对 `^package:` 与 `versionCode='N'` 的 grep，不是 badging 的退出码。**
  图标别写框架资源引用（见 §7.3）。
- **产物不在签名那一步就地覆盖**：先落到 `build/app.signed.apk`，第 8 步全部通过后第 9 步才
  `mv` 到 `OUT_APK`（旧包先备份成 `laoyouji.apk.bak`）。这样任何一步失败，线上那个还能用的旧包
  都不会被毁掉，也不会出现「脚本报失败、线上却已经换成坏包」。
- `versionCode` 必须**严格大于** `$OUT_APK` 里已有的值；`0/9` 会读旧包强制校验，不通过直接退出
  （此前只写在注释里，忘 export 就会签出同版本的包，直到手机上装不上才发现）。
- 产物最终覆盖 `/opt/laoyouji/backend/static_dist/laoyouji.apk`，
  对外地址 `http://159.75.94.149:8000/laoyouji.apk` 不变（H5 与 APK 同机托管）。
  **H5 是另一条下发链**：改了 `frontend/` 的桥调用就必须重新 `npm run build:h5` 并覆盖到
  同一个 static 目录，只重发 APK 会让壳停在「没有任何代码调用 `window.KangleNative`」的白页状态。

---

## 10. 前端适配层公开 API（`frontend/laoyouji-app/src/utils/native.js`）

**全部具名导出**，风格与 `src/utils/amap.js` 一致（该文件 `export default` 计数为 0）。
内部所有桥调用走一个私有 `call(name, ...args)`，包 `try/catch`，桥不存在时统一降级。

| 导出 | 签名 | 语义 | 桥不存在时返回 |
|---|---|---|---|
| `nativeSupported()` | `() => boolean` | `typeof window.KangleNative !== 'undefined' && KangleNative.isSupported()` | `false` |
| `getPlatformInfo()` | `() => object\|null` | 透传 `getPlatformInfo()` 解析结果 | `null` |
| `syncReminders(list)` | `(list: Reminder[]) => object` | **声明式全量覆盖**，内部 `JSON.stringify(list)` 后调桥 | `{ok:false, reason:'no_bridge'}` |
| `getReminders()` | `() => Reminder[]` | 读原生侧副本 | `[]` |
| `cancelAll()` | `() => object` | 退出登录 / 关闭全部提醒时调用 | `{ok:false, reason:'no_bridge'}` |
| `checkPermissions()` | `() => object` | 只读探测，**不弹框** | `{ok:false, reason:'no_bridge'}` |
| `requestPermission(name)` | `(string) => object` | name 取 §3.4 左表 | `{ok:false, reason:'no_bridge'}` |
| `openSettings(name)` | `(string) => object` | name 取 §3.4 右表 | `{ok:false, reason:'no_bridge'}` |
| `openKeepAliveGuide()` | `() => object` | **纯 UI 触发**：打开 profile.vue 的引导弹层（自启动/省电白名单/通知/精确闹钟四步） | `{ok:false, reason:'no_bridge'}` |
| `notifyNow(reminder)` | `(Reminder) => object` | 立刻发一条测试通知，供引导页「试一下」按钮 | `{ok:false, reason:'no_bridge'}` |
| `buildMedicationReminders(items)` | `(plans[]) => Reminder[]` | **纯函数**，见 §10.1 | `[]` |
| `buildGreetingReminder(user)` | `(user) => Reminder[]` | **纯函数**，见 §10.2 | `[]` |
| `buildAllReminders(opts)` | `({user, meds, prefs}) => Reminder[]` | 合并去重，见 §10.4 | `[]` |
| `greetTextForHour(h)` | `(int) => string` | 与 `home.vue:112-119` 完全同桶 | `''` |
| `onNativeAction(handler)` | `(fn) => void` | 把 `window.__kangleNativeAction` 挂到 `handler(payload)` | 注册空实现 |
| `initNative()` | `() => void` | **App.vue onLaunch 唯一入口** | 立即返回 |
| `syncAll()` | `() => Promise<object>` | 「拉计划 + 合成 + syncReminders」的编排，见 §10.3 | `Promise.resolve({ok:false})` |

### 10.1 `buildMedicationReminders(items)` 算法（**逐字冻结**）

输入是 `GET /api/medications?elder_id=<id>&with_logs=false` 的 `items`（`routes_health.py:112-115`），
成功时每项形如 `{id, elder_id, drug_name, dose, times, notes, active}`。

```
result = []
for (const p of items || []) {
  if (p.active === false) continue                       // 软删的跳过
  for (const t of (p.times || [])) {
    if (!/^([01]?\d|2[0-3]):[0-5]\d$/.test(t)) continue   // 正则逐字同上
    const hour = Number(t.split(':')[0])
    const minute = Number(t.split(':')[1])
    result.push({
      id: `med:${p.id}:${pad2(hour)}:${pad2(minute)}`,
      kind: 'medication',
      title: `该吃${p.drug_name}了`,
      body: [p.dose, p.notes].filter(Boolean).join(' · ') || '记得按时吃药',
      hour, minute, enabled: true,
      planId: p.id,
      elderId: p.elder_id,
      repeat: 'daily',
    })
  }
}
```
`pad2(n)` = `String(n).padStart(2, '0')`。

### 10.2 `buildGreetingReminder(user)`（**逐字冻结**）

后端**没有**问候接口，纯本地定时；文案桶照抄 `home.vue:112-119`：

```
greetTextForHour(h): h<6 → '夜深了'; h<11 → '早上好'; h<14 → '中午好'; h<18 → '下午好'; 否则 '晚上好'

buildGreetingReminder(user) 返回长度为 1 的数组：
[{
  id: 'greeting:morning',
  kind: 'greeting',
  title: `${greetTextForHour(hour)}，${(user && user.name) || ''}`.trim(),
  body: '今天也要好好照顾自己',
  hour, minute,          // 来自本地偏好，默认 8 / 0
  enabled: true,         // 来自本地偏好，默认 true
  planId: null,
  elderId: (user && user.id) || null,
  repeat: 'daily',
}]
```
注意 `title` 的时段桶按**配置的 hour** 算，不是按当前时间算（否则 08:00 排的闹钟
在 20:00 同步时会变成「晚上好」，第二天早上弹出来就是错的）。
本地偏好存 key：`lyj_greeting_enabled`（`'1'`/`'0'`）、`lyj_greeting_time`（`"08:00"`）。

### 10.3 `syncAll()` 编排与调用时机（**冻结**）

```
syncAll():
  1. user = getCurrentUser();  if (!user) return {ok:false, reason:'not_logged_in'}
  2. if (Date.now() - lastSyncAt < 30000) return lastResult        // 30 秒防抖
  3. res = await get('/api/medications', { elder_id: user.id, with_logs: false })
  4. list = buildAllReminders({ user, meds: res.items, prefs: readLocalPrefs() })
  5. out = syncReminders(list)
  6. lastSyncAt = Date.now(); lastResult = out; return out
```
第 3 步复用 `src/api/client.js` 导出的 `get`（自动带 `Authorization: Bearer`）。

**必须在这些时刻调用**（`syncReminders` 是声明式全量覆盖，重复调是安全的）：

> 落点一律**按符号名找，不要按行号找** —— 这几个文件在并行改动中，行号每次提交都在漂
> （上一轮就发生过「照行号去看，结果指到了隔壁函数」）。

| 时机 | 落点 |
|---|---|
| App 启动 | `App.vue` 的 `onLaunch()` → `initNative()`，内部 `if (getCurrentUser()) syncAll()` |
| 登录成功后 | `login.vue` 按 `res.user.role` 分叉 `reLaunch` 之前，`if (role === 'elder') syncAll()` |
| 回到「我的」 | `profile.vue` 的 `onShow()` → `refreshReminders()` → `syncAll()`（顺带刷新 `checkPermissions()` 驱动引导页状态） |
| 回到「首页」「吃药」 | `home.vue` / `medications.vue` 的 `onShow` 各调一次 `syncAll()`（有 30 秒防抖兜底） |
| 用药计划变动后 | `medications.vue` 新增/删除计划成功后（`load()` 的成功回调里）调 `syncAll()` |
| 退出登录 | `store/user.js` 的 `clearCurrentUser()` 之后调 `cancelAll()` |

**只在长辈端（`role === 'elder'`）同步**；子女端不排任何闹钟。

### 10.4 合并与去重（`buildAllReminders`）

`buildAllReminders` = `buildMedicationReminders(meds)` 拼接 `buildGreetingReminder(user)`，
然后按 `id` 去重（后者覆盖前者），最后按 `hour*60+minute` 升序排序再返回 —— 排序只是让日志好读，
原生侧不依赖顺序。

### 10.5 通知点击回流

`initNative()` 里：

```js
onNativeAction((payload) => {          // payload 即 §3.7 的对象
  const url = payload.route || '/pages/elder/home'
  const tabs = ['/pages/elder/home', '/pages/elder/chat', '/pages/elder/medications', '/pages/elder/profile']
  if (tabs.includes(url)) uni.switchTab({ url })
  else uni.navigateTo({ url })
})
const pending = window.KangleNative && KangleNative.getPendingAction && KangleNative.getPendingAction()
if (pending) { try { onNativeAction._dispatch(JSON.parse(pending)) } catch (e) {} }
```

**冷启动的时序**：原生在 `onPageFinished` 派发 `__kangleNativeAction`，可能早于 uni 的
`onLaunch`。所以两条路都要有：`getPendingAction()` 是**拉**（onLaunch 时补课），
`__kangleNativeAction` 是**推**（原生侧静置后的正常路径）。原生侧投递一次即清，不会双触发。

---

## 11. 诚实边界（写进引导页文案，也写进交付说明）

**能力边界**

1. **必须先打开过一次 App 并完成登录**，闹钟才会被排上。纯装完不开、或装了没登录 → 一条都不会响。
   后端没有调度器、不会主动推送，提醒 100% 由手机本地排。
2. **MIUI（演示机）是决定成败的一环**。不授予**自启动**、不加**省电白名单**，
   系统会在清理后台时顺手清掉闹钟 —— 表现为「前几天还响，突然就不响了」。
   引导页的四步（自启动 / 省电白名单 / 通知允许 / 精确闹钟）**和代码同等重要**，
   演示前必须逐项走一遍并截图留证。
3. **不求精确就可能漂移**。拿不到 `SCHEDULE_EXACT_ALARM` 时走 `setAndAllowWhileIdle`，
   在 Doze 下可能晚几分钟。`syncReminders` 的 `mode` 字段就是用来如实展示这件事的 ——
   引导页写「可能延迟几分钟」，**不要**粉饰成「到点必响」。
4. **服务器不可达时壳是白屏**。H5 与 APK 同机托管在 `159.75.94.149:8000`，后端一挂，
   WebView 就加载不出东西。兜底页见 §11.1。
5. **只支持「每天一次」这一种重复**，没有工作日/按周、没有「稍后提醒（snooze）」、
   没有「跳过今天」。这是本轮明确不做的范围。
6. **换手机 / 清数据 = 全部丢失**。计划存在手机本地，不在账号里；
   换机后要重新打开 App 同步一次。
7. **别人改了用药计划，本机不会立刻知道**。要等本机下次打开 App 触发 `syncAll()` 才会更新。
8. **时间是设备本地时区解释的**。后端 `times` 是裸 `"HH:MM"` 字符串（`schema.sql:159`），
   从不换算成瞬时；服务器时区与本机不一致也不影响，因为根本没用服务器时间排闹钟。
   但**跨时区飞行**后闹钟会跟着当地时间走，这是预期行为（`TIMEZONE_CHANGED` 会重排）。
9. **通知横幅可能被 ROM 静音**。channel 已是 `IMPORTANCE_HIGH`，但 MIUI 仍可能把通知
   降级为「只在通知栏」。引导页要引导用户去确认这个 channel 没被手动调成「静默」。
10. **明文 HTTP 意味着桥可被中间人利用**。WebView 加载 `http://`，同网段的攻击者理论上
    能篡改页面后调用 `KangleNative`。这是演示环境的已知取舍，**不要**在对外材料里
    声称「安全」。生产化必须先上 HTTPS。

**范围边界（本轮明确不做，别顺手加）**

- 后台定位 / 途中守护的**前台服务** —— 清单里占了 `FOREGROUND_SERVICE` 和定位权限位，
  但**不写任何 Service 类**。没人验证过的半成品服务，能编译通过反而更危险。
- 服务端推送（FCM/长连接）。服务器不排、不推。
- 通知里的「已吃药」快捷按钮 —— 打卡仍走 H5（`medications.vue:119-127` 的
  `POST /api/medications/{id}/taken`）。原生侧只负责响。

### 11.1 WebView 加载失败的兜底页设计

`KangleWebViewClient` 在**主文档**失败时（`onReceivedError` 的 `failingUrl` 等于主 URL，
或 `onReceivedHttpError` 的请求是主文档）调 `showOfflinePage(reason)`：

```java
String html =
  "<!doctype html><html lang=\"zh\"><head><meta charset=\"utf-8\">" +
  "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">" +
  "<style>body{margin:0;padding:48px 24px;font:20px/1.7 system-ui,sans-serif;" +
  "background:#FBF7F2;color:#3B322C;text-align:center}" +
  "h1{font-size:26px;margin:0 0 12px}p{color:#7A6E66;margin:0 0 32px}" +
  "button{font-size:22px;padding:16px 40px;border:0;border-radius:12px;" +
  "background:#C96F4A;color:#fff}</style></head><body>" +
  "<h1>连不上康乐服务</h1>" +
  "<p>请检查手机网络后重试。<br>如果反复失败，可能是服务端暂时不可用。</p>" +
  "<button onclick=\"KangleNative.reload()\">重新加载</button>" +
  "</body></html>";
webView.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
```

关键点：

- **必须用 `loadDataWithBaseURL(null, ...)`**，不要 `loadData`（后者在部分实现下会走错 baseURL）。
- 兜底页里的 `KangleNative.reload()` **能调到** —— `addJavascriptInterface` 对整个 WebView 生效，
  不限于原始 URL 的页面。这是「重试」按钮能工作的全部原因。
- `reload()` 内部调 `loadH5()`；若用户此时已在兜底页，重试即重新拉 H5。
- 兜底页不显示技术错误码给长辈看；`reason` 只写日志（或只放进 `<meta>` 供调试）。
- 子资源失败（图片、字体）**不触发**兜底页，只有主文档失败才触发，否则页面会莫名其妙变成错误页。

<!--CONTRACT-END-->


