# 康乐 Android 壳 + 原生提醒层

这是「康乐」长辈端的 Android 外壳工程：**一个全屏 WebView 装载云端 H5**，
外加一层**原生提醒**（到点闹钟 → 系统通知），覆盖两类提醒：

- **用药提醒**：由后端用药计划（`GET /api/medications`）合成，一天几次就几条。
- **晨间问候**：后端没有这个接口，纯本地定时（默认 08:00）。

**壳不内嵌 H5**（没有 `assets/`）：H5 与 APK 同机托管在 `http://159.75.94.149:8000/`，
所以 APK 体积极小，但**服务器一挂，壳就是白屏**（有离线兜底页，可点「重新加载」）。

跨文件接口（类名、JS 桥方法、JSON 键名）一律以 `CONTRACT.md` 为准，本文件只讲**怎么构建、怎么改、为什么这么写**。

---

## 1. 目录

```
android/
├── CONTRACT.md                 # 冻结的接口契约（先读它，本文件不重复）
├── AndroidManifest.xml         # 清单：包名/权限/明文放行/主题/组件 exported
├── build_apk.sh                # 无 Gradle 构建脚本（唯一的构建入口）
├── README.md                   # 本文件
├── res/
│   ├── values/strings.xml      # app_name（中文标签不写死在清单里）
│   ├── values/styles.xml       # AppTheme：框架主题 + 窗口背景色，消掉首帧白闪
│   ├── xml/network_security_config.xml   # 明文流量放行（Android 9+ 白屏的根因）
│   └── drawable/ic_notify.xml  # 通知小图标（VectorDrawable，无 PNG；NotificationHelper 用它）
└── src/com/kangle/app/         # Java 源码（MainActivity / NativeBridge / 提醒四件套…）
```

构建期生成、**不提交**、脚本自己清理：`gen/`（aapt 产出的 `R.java`）、`build/`（classes / dex / 未对齐 apk）。

> 提醒：仓库根 `.gitignore` 目前**没有** `android/gen/` 与 `android/build/` 两条。
> 脚本每次运行都会先 `rm -rf` 再重建（所以不会带上陈旧产物），但如果你在构建机上
> 执行过 `KANGLE_KEEP_BUILD=1`，记得别把这两个目录提交上去。

---

## 2. 在服务器上构建

构建**只能在部署机**（Ubuntu 24.04，`159.75.94.149`）上做：本机没有 Android SDK，
没有任何依赖仓库，工具链是服务器上的 `aapt / javac / d8 / zipalign / apksigner`。

### 2.0 一次性准备：确认两件事（**每次改版本前都要看一眼**）

**(a) 旧壳的 versionCode** —— 决定新的 `VERSION_CODE` 取几：

```sh
aapt dump badging /opt/laoyouji/backend/static_dist/laoyouji.apk | head -1
# 形如：package: name='com.kangle.app' versionCode='2' versionName='1.1.0'
export KANGLE_VERSION_CODE=$((N+1))   # N 是上面看到的数字，必须严格大于它
```

**(b) 旧的 keystore 路径与别名** —— 见 §4，**这是最容易搞砸的一步**：

```sh
cat /opt/laoyouji/build_apk.sh                                   # 旧脚本里的真实路径/别名
find /opt/laoyouji -name '*.keystore' -o -name '*.jks' 2>/dev/null
```

### 2.1 同步源码并构建

> **前置（最容易被漏掉的一步）：H5 也必须重新构建并下发。**
> 壳**不内嵌** H5，它加载的是服务器上 `http://159.75.94.149:8000/` 那份产物。
> 本轮新增的 JS 桥调用（`frontend/laoyouji-app/src/utils/native.js` 的 `syncAll()`、
> `App.vue` 的 `initNative()` 等）只有 H5 重新打包覆盖到服务器之后才存在 ——
> 不重发 H5，APK 装上去只是一个白页外壳：`window.KangleNative` 没有任何代码调用，
> 一条闹钟都排不上，而下面所有构建/安装步骤都会显示成功。
>
> **APK 与 H5 是两条独立的下发链，改任一侧都要各自构建 + 各自下发。**

```sh
# 0) 在开发机上：重新构建 H5，并把产物覆盖到后端 static 目录（即 /laoyouji.apk 同级的 H5 根）
cd frontend/laoyouji-app
npm run build:h5
# 产物目录按该工程的 build 配置（见 package.json / vite.config），同步到
# root@159.75.94.149:/opt/laoyouji/backend/static_dist/ 覆盖同名文件

# 在开发机上：把 android/ 整个目录同步到服务器
scp -r android root@159.75.94.149:/opt/laoyouji/android/

# 在服务器上：
cd /opt/laoyouji/android
export KANGLE_STORE_PASS='<keystore 口令>'   # 只在 shell 里！
export KANGLE_KEY_PASS='<key 口令>'          # 只在 shell 里！
export KANGLE_VERSION_CODE=3                 # 必须 > 旧壳
export KANGLE_VERSION_NAME=1.2.0
export KANGLE_KEYSTORE=/opt/laoyouji/keys/kangle.keystore   # 用 (b) 查到的真实路径
export KANGLE_KEY_ALIAS=kangle                              # 用 (b) 查到的真实别名
bash build_apk.sh
```

脚本每一步都会打印进度（`0/9`…`9/9`），任何一步失败立刻退出，**不会静默打出一个错包**。
`0/9` 会先校验工具链、keystore、两个口令环境变量，并**读线上旧包的 versionCode**，
`VERSION_CODE` 不大于它就直接退出（省得覆盖安装被系统拒绝时才发现）；
`7/9` 只把签名写到 `build/` 里的临时文件，`8/9` 校验签名、包名/versionCode 与**签名证书是否与
线上旧包同源**，全部通过后 `9/9` 才原子落盘（旧包先备份成 `laoyouji.apk.bak`）——
所以任何一步失败，线上那个还能用的旧包都不会被毁掉。

### 2.2 产物与对外地址

| 项 | 值 |
|---|---|
| 产物路径 | `/opt/laoyouji/backend/static_dist/laoyouji.apk` |
| 下载地址 | `http://159.75.94.149:8000/laoyouji.apk` |
| H5 地址 | `http://159.75.94.149:8000/` |

路径和地址都**不变**——覆盖同一个文件，用户从同一个链接下载，`versionCode` 递增后是覆盖升级。

---

## 3. 怎么改 H5 地址

**只改 `build_apk.sh` 顶部的 `H5_URL`**，重新构建即可：

```sh
H5_URL="http://159.75.94.149:8000/"   # ← 改这里
```

脚本会用 `sed` 把 `AndroidManifest.xml` 里 `<meta-data android:name="kangle.h5_url" ...>` 的
`android:value` 整段替换掉，注入到 `build/AndroidManifest.xml` 的**副本**里（**不动仓库里的源文件**）。
`MainActivity.h5Url()` 从清单读这个值，读不到才回退 `MainActivity.DEFAULT_H5_URL`。

三个注意点：

1. **清单里那一行的属性写法被脚本按字面量匹配**（`name="kangle.h5_url" android:value="`，
   单空格、这个顺序）。把它拆成多行或调换属性顺序，注入就会失败——好在脚本的 `1/9` 有自检，
   命中不了会直接报错退出，不会打出一个还指着旧地址的包。
2. **H5 自己那份地址是另一处独立配置**：`frontend/laoyouji-app/src/api/client.js` 里的
   `const BASE_URL = 'http://159.75.94.149:8000'`。它是 H5 请求后端的地址，和壳加载哪个页面
   是两件事，两边都要指到同一台服务器。**按变量名找，不要按行号找**——那个文件正在被并行改动，
   行号会漂。
3. 改完**必须重新构建并重新下发**：**APK 与 H5 都要**。已经装在手机上的旧 APK 不会自己变；
   而改了 H5 侧的桥调用（`native.js` / `App.vue`）却没重发 H5，壳就只是一个白页外壳（见 §2.1）。

---

## 4. 换版本号 / 为什么必须复用旧 keystore

### 4.1 换版本号

```sh
export KANGLE_VERSION_CODE=3      # 默认 2
export KANGLE_VERSION_NAME=1.2.0  # 默认 1.1.0
```

- `versionCode` **必须严格大于**服务器上已装 APK 的 versionCode（查法见 §2.0a）。
  等于或小于它，系统的覆盖安装会被直接拒绝。
  **这条现在已经由脚本强制**：`0/9` 会读 `$OUT_APK` 里已有的 versionCode，
  `VERSION_CODE <= 旧值` 时直接 `exit 1` 并提示该 export 成几（此前只是注释里的一句提醒，
  忘 export 就会照常签出一个同版本的包，直到手机上装不上才发现）。
- `versionName` 只是给人看的字符串，随便改，不影响安装。

### 4.2 必须复用旧 keystore（**换 key = 只能卸载重装 + 丢数据**）

Android 只允许**同一签名**的 APK 覆盖安装。换一把 key 的后果是链式的：

1. 覆盖安装被系统拒绝（`INSTALL_FAILED_UPDATE_INCOMPATIBLE`），只能**先卸载旧壳**。
2. 卸载会一并删掉旧壳的应用私有数据 —— **登录态（`lyj_token`）、已排的闹钟、
   `SharedPreferences` 全没**，用户得重新登录、重新同步一次提醒。
3. 服务器只托管**一个** `laoyouji.apk`，「并存」期间两个壳会抢同一个下载链接。

所以：**服务器上第一次装上去的那把 keystore 就是唯一真值**，本轮及以后都复用它。
脚本顶部把 `KEYSTORE_PATH` / `KEY_ALIAS` 做成了可覆盖的变量（`KANGLE_KEYSTORE` / `KANGLE_KEY_ALIAS`），
默认值是占位路径；**口令一律只从环境变量读**，`apksigner` 用 `env:KANGLE_STORE_PASS` /
`env:KANGLE_KEY_PASS` 的**变量名**引用，`build_apk.sh` 里**没有任何口令值**。

> 纪律：口令不进仓库、不进脚本、不进 shell 历史（`export` 前先 `set +o history` 或前面加空格）、
> 不进聊天记录。发现口令被写进任何文件，按泄露处理、立刻换 key —— 但那意味着所有人要卸载重装。

**不要改包名**（`com.kangle.app` 已冻结）：换包名 = 新旧壳并存（桌面两个「康乐」图标）+
数据全部留在旧壳里 + 只能手动卸载，理由同 §4.2，详见 `CONTRACT.md §2.1`。

---

## 5. 这套工程为什么长这样（复核会逐条查）

| 约束 | 落地方式 |
|---|---|
| **不许用 AndroidX / support library** | 构建链只有 `android.jar`，没有任何依赖仓库。通知用框架 `Notification.Builder`，并按 `Build.VERSION.SDK_INT` 分支（≥26 用带 channel 的构造器 + `setPriority/setDefaults`；<26 用旧构造器）。权限判定用 `Activity.checkSelfPermission(String)`，不用 `ContextCompat`。 |
| **不许有 Gradle 工程文件 / 注解处理器 / 依赖坐标** | 目录里没有 `build.gradle*`、`settings.gradle*`、`gradle.properties`、`libs/`、`*.aar`、`*.jar`。`R.java` 由 `aapt -J gen` 生成。只用 `java.*` 与 `android.*`（含框架自带的 `org.json.*`）。 |
| **明文流量必须显式放行** | 两条一起上：清单 `android:usesCleartextTraffic="true"`（API 23+ 生效）+ `android:networkSecurityConfig="@xml/network_security_config"`（API 24+ 起是权威配置，会**覆盖**前者的宽泛放行，所以这里也必须写）。少了任一条，Android 9+ 打开就是纯白屏。 |
| **组件 `android:exported` 显式声明** | `MainActivity=true`（带 LAUNCHER，通知点击也要能进）、`ReminderReceiver=false`（只由本应用的显式 PendingIntent 触发）、`BootReceiver=true`（要收系统保护广播）。targetSdk 30 不强制，但升上去就是硬错，先写好。 |
| **主题用框架主题** | `@android:style/Theme.Material.Light.NoActionBar`（API 21 起），不用 AppCompat。窗口背景 `#FFFBF7F2` 接近 H5 浅色底，消掉 WebView 首帧白闪。 |
| **图标：只用本工程资源，避开框架引用** | 应用图标 `@mipmap/ic_launcher` —— `mipmap-anydpi-v26/ic_launcher.xml`（自适应，API 26+，演示机 MIUI 走这条）+ `mipmap-{mdpi..xxxhdpi}/ic_launcher.png` 五档兜底（48/72/96/144/192，API 21–25）；通知小图标 `res/drawable/ic_notify.xml`（`NotificationHelper.show()` 里 `setSmallIcon(R.drawable.ic_notify)`）。**唯一要避开的是 `@android:drawable/...` 这类框架资源引用**：写 `sym_def_app_icon` 会让 `aapt dump badging` 以退出码 1 结束、把构建误判成失败（`CONTRACT.md §7.3`）。至于 PNG / `mipmap-*dpi` 本身**实测没问题** —— 本机整链跑通、badging 退出码 0、`zipalign -c -p 4` 通过、aapt 转调色板 PNG 后 alpha 完好；早先"无 Gradle 链不能用 PNG"的说法已被实测否掉。图标由 `tools/make_icons.py` 生成，改图标改脚本后重跑。 |
| **通知权限走设置页，不靠 `requestPermissions`** | 本工程 `targetSdk=30`（<33），自己调 `requestPermissions(POST_NOTIFICATIONS)` 不会弹框（只有「首次建 channel」那一次系统自动弹），会变成静默 no-op。所以 `requestPermission("notifications")` 未授权时直接跳系统通知设置页（返回 `settings_opened`）；首次安装的自动弹框仍由 `ensureChannel()` 负责。 |
| **API 30 的 `android.jar` 里没有 31+ 符号** | `POST_NOTIFICATIONS` / `SCHEDULE_EXACT_ALARM` / `Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM` 一律写**字符串字面量**；`canScheduleExactAlarms()` 走**反射**；`S/TIRAMISU/UPSIDE_DOWN_CAKE` 写整数 `31/33/34`。直接写符号 = `javac` 编译失败。见 `CONTRACT.md §3.5`。 |
| **精确闹钟两级降级** | 拿不到 `SCHEDULE_EXACT_ALARM`（Android 12+ 特殊权限，用户手动授予）时退回 `setAndAllowWhileIdle`（不精确，Doze 下可能漂移数分钟），`syncReminders` 的 `mode` 字段如实回报 `exact` / `inexact`。**两级都要有**，不能只写一条然后崩。 |

`build_apk.sh` 的链路与工具链顺序和 `CONTRACT.md §9.2` 一致，另有几处小的健壮性处理，
都写在注释里：`0/9` 的 versionCode 递增强制校验；`1/9` 的注入自检；`3/9` 在 javac 不支持
`-bootclasspath` 时自动降级；`6/9` 在 `zipalign` 不支持 `-p`（build-tools 35+ 已移除）时自动改用
`-f 4`；`7/9`–`9/9` 的「先签到临时文件 → 校验 → 原子落盘」。

---

## 6. 装到演示机（小米 MIUI）之后：保活四步

MIUI 是杀后台最凶的 ROM。**不授予自启动、不加省电白名单，系统会在清理后台时顺手清掉闹钟** ——
表现就是「前几天还响，突然就不响了」。代码写得再对也没用，所以这四步和代码同等重要，
演示前必须逐项走一遍并截图留证：

1. **自启动**：设置 → 应用设置 → 康乐 → 自启动 → 允许（`openSettings("auto_start")` 会跳到 MIUI 这个页面）。
2. **省电白名单**：设置 → 应用设置 → 康乐 → 省电策略 → 无限制（等价于「忽略电池优化」）。
3. **通知允许**：允许康乐发通知；进通知渠道确认「用药与问候提醒」**没有被手动调成静默**
   （渠道已是 `IMPORTANCE_HIGH`，但 ROM 仍可能降级为「只在通知栏」，那就不会弹横幅，长辈注意不到）。
   引导页的「去开启」会**直接跳到系统通知设置页**（`requestPermission("notifications")` 未授权时
   返回 `settings_opened`）—— 本工程 targetSdk<33，自己发权限框不会弹，只有这条设置页的路走得通。
   万一第一次误点了「不允许」，也在这里手动开、App 内救得回来。
4. **精确闹钟**：Android 12+ 的「闹钟和提醒」特殊权限，跳设置页人工授予；
   没授予也能响，只是会漂移几分钟。

在 App 里，「我的」页有「提醒与保活引导」入口，会实时读 `checkPermissions()` 显示这四项的状态，
并提供「试一下」按钮（`notifyNow`）当场验证通知能不能弹出来。

---

## 7. 已知边界（如实说明，别在对外材料里粉饰）

1. **必须先打开过一次 App 并完成登录**，闹钟才会被排上。后端没有调度器、不会主动推送，
   提醒 100% 由手机本地排。装了不开、开了不登录 → 一条都不会响。
2. **换手机 / 清数据 = 全部丢失**。计划存在手机本地（`SharedPreferences`），不在账号里，
   换机后要重新打开 App 同步一次。
3. **别人改了用药计划，本机不会立刻知道**。要等本机下次打开 App 触发 `syncAll()` 才更新。
4. **不求精确就可能漂移**。拿不到精确闹钟权限时走不精确路径，Doze 下可能晚几分钟。
   引导页写「提醒可能延迟几分钟」，不要写成「到点必响」。
5. **服务器不可达时壳是白屏**（有兜底页可重试）。H5 和 APK 同机托管，后端一挂就加载不出来。
6. **只支持「每天一次」**：没有工作日/按周、没有「稍后提醒」、没有「跳过今天」。
7. **明文 HTTP 意味着桥可被同网段中间人利用**。这是演示环境的已知取舍，
   **不要**在对外材料里声称「安全」；生产化必须先上 HTTPS。
8. **本轮不做后台定位 / 途中守护的前台服务**。清单里预留了 `FOREGROUND_SERVICE`
   和两个定位权限位，但**没写任何 Service 类** —— 没人真机验证过的半成品服务，能编译通过反而更危险。

---

## 本机自测：开发机上也能真编一次

部署机才有完整 SDK，但**开发机也能真编**，用来在推服务器之前就抓住编译错。
做法是把 build-tools 下到临时目录，再补几个无扩展名的壳脚本 —— 因为 d8 / apksigner
在 build-tools 里只提供 `.bat`，而 `build_apk.sh` 调的是 `$BUILD_TOOLS/d8`：

```bash
S=/tmp/sdk30/android-11        # 放 android.jar 与 build-tools 的目录
T=/tmp/kangle-test
mkdir -p $T/tools $T/out
printf '#!/usr/bin/env bash\nexec %s/aapt.exe "$@"\n'     "$S" > $T/tools/aapt
printf '#!/usr/bin/env bash\nexec %s/zipalign.exe "$@"\n' "$S" > $T/tools/zipalign
printf '#!/usr/bin/env bash\nexec java -cp "%s/lib/d8.jar" com.android.tools.r8.D8 "$@"\n' "$S" > $T/tools/d8
printf '#!/usr/bin/env bash\nexec java -cp "%s/lib/apksigner.jar" com.android.apksigner.ApkSignerTool "$@"\n' "$S" > $T/tools/apksigner
chmod +x $T/tools/*

# 一次性测试签名。**不是服务器那把**，只为让本地编得过。
keytool -genkeypair -keystore $T/test.keystore -alias kangle -keyalg RSA -keysize 2048 \
  -validity 10000 -storepass testpass -keypass testpass -dname "CN=local test"

cd android
KANGLE_STORE_PASS=testpass KANGLE_KEY_PASS=testpass \
KANGLE_KEYSTORE=$T/test.keystore KANGLE_KEY_ALIAS=kangle \
ANDROID_JAR=$S/android.jar BUILD_TOOLS=$T/tools \
OUT_APK=$T/out/laoyouji.apk \
bash build_apk.sh
```

编完建议顺手验一遍产物（对齐是 Android 11+ 那个 `-124` mmap 崩溃的关键）：

```bash
$S/zipalign.exe -c -p -v 4 "$T/out/laoyouji.apk"      # resources.arsc 必须是 (OK)，退出码 0
$S/aapt.exe dump badging "$T/out/laoyouji.apk" | grep -E '^(package|launchable-activity)'
```

> **本地编出来的包绝不能上线。** 它是用测试 keystore 签的。一旦这种包装进演示机，
> 以后就没法再用服务器那把 key 覆盖升级了 —— 只能先卸载重装，且丢数据。
> 本机自测只解决「能不能编过」，上线一律走服务器。
