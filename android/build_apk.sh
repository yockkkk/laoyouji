#!/usr/bin/env bash
# =============================================================================
# 康乐（老友记）Android 壳 —— 无 Gradle 构建脚本
#
# 链路（工具链顺序冻结，见 CONTRACT.md §9.2）：
#   aapt 编资源 + 生成 R.java + 打未对齐 apk
#     → javac 编源码（-encoding UTF-8）
#     → d8 class 转 classes.dex（--min-api 21）
#     → aapt add 把 dex 塞进 apk
#     → zipalign -p -f 4 对齐
#     → apksigner 签名（v1+v2+v3）
#
# 环境：部署机 Ubuntu 24.04（/opt/laoyouji）。本机（开发机）没有 Android SDK，
#       不要在本机跑这个脚本 —— 它只会在“缺少工具链”这一步报错退出。
#
# 用法：
#   cd <脚本所在目录>
#   export KANGLE_STORE_PASS='...'   # 口令只在 shell 里，绝不写进任何文件
#   export KANGLE_KEY_PASS='...'
#   bash build_apk.sh
#
# 详见同目录 README.md。构建前必读：必须复用服务器上已有的 keystore，且
# versionCode 必须递增，否则覆盖安装会被系统拒绝（只能先卸载，且丢数据）。
# =============================================================================
set -euo pipefail

# 所有相对输入（AndroidManifest.xml / res / src / gen / build）都以本脚本所在目录为基准，
# 这样无论从哪个 cwd 调用都一致。
cd "$(dirname "$0")"

log() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }

# ===== 可改变量 ==============================================================
PKG_NAME="com.kangle.app"
APP_LABEL="康乐"
VERSION_CODE="${KANGLE_VERSION_CODE:-2}"     # 必须 > 服务器上已装 APK 的 versionCode
VERSION_NAME="${KANGLE_VERSION_NAME:-1.1.0}"
H5_URL="http://159.75.94.149:8000/"          # 换 H5 地址就改这里（注入到清单 meta-data）

# ===== 签名（绝不写口令明文，只读环境变量）==================================
KEYSTORE_PATH="${KANGLE_KEYSTORE:-/opt/laoyouji/keys/kangle.keystore}"
KEY_ALIAS="${KANGLE_KEY_ALIAS:-kangle}"
# 口令从环境变量读；apksigner 的 env: 语法直接引用变量名，脚本里不出现任何口令值
STORE_PASS_ENV="KANGLE_STORE_PASS"
KEY_PASS_ENV="KANGLE_KEY_PASS"

# ===== 工具链（本机没有 SDK，全部在服务器上）=================================
ANDROID_JAR="${ANDROID_JAR:-/opt/android-sdk/platforms/android-30/android.jar}"
BUILD_TOOLS="${BUILD_TOOLS:-/opt/android-sdk/build-tools/30.0.3}"
AAPT="$BUILD_TOOLS/aapt"
D8="$BUILD_TOOLS/d8"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"

# ===== 产物 ==================================================================
OUT_APK="${OUT_APK:-/opt/laoyouji/backend/static_dist/laoyouji.apk}"

# ===== 构建中间目录（构建期生成，不提交，脚本自己清理）=======================
BUILD_DIR="build"
GEN_DIR="gen"
KEEP_BUILD="${KANGLE_KEEP_BUILD:-0}"         # =1 则保留 build/ gen/ 供排查，默认清掉

# -----------------------------------------------------------------------------
# 0) 前置校验：缺什么立刻报错退出，绝不静默继续
# -----------------------------------------------------------------------------
log "0/9 校验工具链、口令与 versionCode"
: "${!STORE_PASS_ENV:?请先 export KANGLE_STORE_PASS=<keystore 口令>（不写进任何文件）}"
: "${!KEY_PASS_ENV:?请先 export KANGLE_KEY_PASS=<key 口令>（不写进任何文件）}"

for t in "$AAPT" "$D8" "$ZIPALIGN" "$APKSIGNER" "$ANDROID_JAR"; do
  [ -e "$t" ] || { echo "缺少工具链: $t（用 ANDROID_JAR / BUILD_TOOLS 覆盖默认路径）" >&2; exit 1; }
done
[ -f "$KEYSTORE_PATH" ] || {
  echo "找不到 keystore: $KEYSTORE_PATH" >&2
  echo "必须复用服务器上已有的签名（换 key = 覆盖安装被拒 + 只能先卸载 + 丢数据）。" >&2
  echo "用 KANGLE_KEYSTORE / KANGLE_KEY_ALIAS 指定真实路径与别名，见 README.md。" >&2
  exit 1
}
command -v javac >/dev/null 2>&1 || { echo "缺少 javac" >&2; exit 1; }

# versionCode 必须是整数，且**严格大于**线上已存在的那个包 —— 否则手机上覆盖安装会被系统
# 直接拒绝（INSTALL_FAILED_UPDATE_INCOMPATIBLE），只能先卸载（丢登录态与已排闹钟）。
# 脚本本来就能读到旧包（OUT_APK 就在本机），所以这里提前拦，而不是等装包时报错。
case "$VERSION_CODE" in
  ''|*[!0-9]*) echo "KANGLE_VERSION_CODE 必须是整数，当前为 '$VERSION_CODE'" >&2; exit 1 ;;
esac
if [ -f "$OUT_APK" ]; then
  # aapt dump badging 在个别资源引用上会以非 0 退出，所以整段包在 subshell 里 || true 吞掉退出码，
  # 只看输出（set -o pipefail 下不能让它把脚本带走）。末段用 sed -n '1p' 而不是 head：
  # head 会在收到一行后提前退出，上游 sed 吃到 SIGPIPE 时 pipefail 会把整条管道判成失败。
  OLD_VERSION_CODE="$( ( "$AAPT" dump badging "$OUT_APK" 2>/dev/null || true ) \
      | sed -n "s/^package:.*versionCode='\([0-9]*\)'.*/\1/p" | sed -n '1p' )"
  if [ -n "$OLD_VERSION_CODE" ] && [ "$VERSION_CODE" -le "$OLD_VERSION_CODE" ]; then
    echo "versionCode=$VERSION_CODE 不大于 $OUT_APK 里已有的 $OLD_VERSION_CODE，覆盖安装会被系统拒绝。" >&2
    echo "请 export KANGLE_VERSION_CODE=$((OLD_VERSION_CODE + 1)) 后重试。" >&2
    exit 1
  fi
  echo "    线上旧包 versionCode=${OLD_VERSION_CODE:-读不到（跳过递增校验）}，本次 $VERSION_CODE"
fi
echo "    工具链 OK; keystore=$KEYSTORE_PATH alias=$KEY_ALIAS; label=$APP_LABEL"

# -----------------------------------------------------------------------------
# 1) 版本号 / H5 地址注入到 build 副本（绝不动仓库里的源文件）
# -----------------------------------------------------------------------------
log "1/9 注入 versionCode=$VERSION_CODE versionName=$VERSION_NAME h5=$H5_URL"
rm -rf "$BUILD_DIR" "$GEN_DIR"
mkdir -p "$BUILD_DIR" "$GEN_DIR"

sed -e "s/android:versionCode=\"[0-9]*\"/android:versionCode=\"$VERSION_CODE\"/" \
    -e "s/android:versionName=\"[^\"]*\"/android:versionName=\"$VERSION_NAME\"/" \
    -e "s#\(name=\"kangle.h5_url\" android:value=\"\)[^\"]*#\1$H5_URL#" \
    AndroidManifest.xml > "$BUILD_DIR/AndroidManifest.xml"

# 注入自检：三项都必须命中。命中不了说明清单被改坏，继续跑只会打出一个版本号不对的包。
grep -q "android:versionCode=\"$VERSION_CODE\"" "$BUILD_DIR/AndroidManifest.xml" \
  || { echo "注入 versionCode 失败：清单里的 android:versionCode=\"N\" 写法被改动了？" >&2; exit 1; }
grep -q "android:versionName=\"$VERSION_NAME\"" "$BUILD_DIR/AndroidManifest.xml" \
  || { echo "注入 versionName 失败：清单里的 android:versionName=\"...\" 写法被改动了？" >&2; exit 1; }
grep -qF "android:value=\"$H5_URL\"" "$BUILD_DIR/AndroidManifest.xml" \
  || { echo "注入 kangle.h5_url 失败：清单里的 meta-data 那一行写法被改动了？" >&2; exit 1; }

# -----------------------------------------------------------------------------
# 2) aapt：编资源 + 生成 R.java + 打未对齐 apk（先生成 R.java，javac 要用）
# -----------------------------------------------------------------------------
log "2/9 aapt 编资源并生成 R.java"
"$AAPT" package -f -m \
  -M "$BUILD_DIR/AndroidManifest.xml" -S res -I "$ANDROID_JAR" \
  -J "$GEN_DIR" -F "$BUILD_DIR/app.unaligned.apk"
[ -f "$GEN_DIR/com/kangle/app/R.java" ] \
  || { echo "aapt 未生成 $GEN_DIR/com/kangle/app/R.java（检查 package 属性与 res/）" >&2; exit 1; }

# -----------------------------------------------------------------------------
# 3) javac：-encoding UTF-8 是硬需求（源码含中文文案），漏了会在
#    CHANNEL_NAME = "用药与问候提醒" 这类字面量上报编码错
# -----------------------------------------------------------------------------
log "3/9 javac 编译源码（android.jar 作为 bootclasspath）"
mkdir -p "$BUILD_DIR/classes"
# android.jar = API 30，是唯一的编译基准。新版 JDK 若已移除 -bootclasspath，
# 自动降级为只给 -classpath（android.jar 仍在类路径上，符号照样解析）。
# 探测命令必须与下面真实调用**写法一致**（同样带 -source 8 -target 8 -Xlint:-options）：
# JDK 9+ 只在给出 -source/-target 8 时才接受 -bootclasspath，少了这两个开关，
# 探测的判据跟真实编译根本不是一回事 —— 一旦探测误判成"不支持"而静默清空，
# 下面那次 javac 就是拿 JDK 自带的 java.* 编的，编译期不再拦「用了 API 21 没有的 java.* API」。
JAVAC_BOOT_ARGS=(-bootclasspath "$ANDROID_JAR")
if ! javac -source 8 -target 8 -Xlint:-options -bootclasspath "$ANDROID_JAR" -version >/dev/null 2>&1; then
  echo "    提示: 当前 javac 不支持 -bootclasspath，降级为仅 -classpath" >&2
  JAVAC_BOOT_ARGS=()
fi
javac -source 8 -target 8 -encoding UTF-8 -Xlint:-options "${JAVAC_BOOT_ARGS[@]}" \
  -classpath "$ANDROID_JAR" \
  -d "$BUILD_DIR/classes" \
  $(find src gen -name '*.java')

# -----------------------------------------------------------------------------
# 4) d8：class → classes.dex（--min-api 21）
# -----------------------------------------------------------------------------
log "4/9 d8 转 classes.dex"
"$D8" --lib "$ANDROID_JAR" --min-api 21 --output "$BUILD_DIR" \
  $(find "$BUILD_DIR/classes" -name '*.class')
[ -f "$BUILD_DIR/classes.dex" ] || { echo "d8 未产出 $BUILD_DIR/classes.dex" >&2; exit 1; }

# -----------------------------------------------------------------------------
# 5) 把 dex 塞进 apk（aapt add 必须在 apk 所在目录执行，包内条目名就是 classes.dex）
# -----------------------------------------------------------------------------
log "5/9 把 classes.dex 写入 apk"
( cd "$BUILD_DIR" && "$AAPT" add app.unaligned.apk classes.dex )

# -----------------------------------------------------------------------------
# 6) 4 字节对齐
# -----------------------------------------------------------------------------
log "6/9 zipalign -p -f 4 对齐"
if ! "$ZIPALIGN" -p -f 4 "$BUILD_DIR/app.unaligned.apk" "$BUILD_DIR/app.aligned.apk" 2>/dev/null; then
  echo "    提示: 当前 zipalign 不支持 -p（build-tools 35+ 已移除），改用 -f 4" >&2
  "$ZIPALIGN" -f 4 "$BUILD_DIR/app.unaligned.apk" "$BUILD_DIR/app.aligned.apk"
fi

# -----------------------------------------------------------------------------
# 7) 签名 v1+v2+v3（口令经 env: 引用，脚本里零明文）
#    先签到 build/ 里的**临时文件**，绝不直接写对外下载路径：第 8 步全部校验通过、
#    第 9 步才原子替换。否则一旦后续任一步失败，线上那个还能用的旧包已经被销毁了。
# -----------------------------------------------------------------------------
log "7/9 apksigner 签名 (v1+v2+v3) -> 临时文件"
SIGNED_APK="$BUILD_DIR/app.signed.apk"
"$APKSIGNER" sign \
  --ks "$KEYSTORE_PATH" --ks-key-alias "$KEY_ALIAS" \
  --ks-pass "env:$STORE_PASS_ENV" --key-pass "env:$KEY_PASS_ENV" \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out "$SIGNED_APK" "$BUILD_DIR/app.aligned.apk"

# -----------------------------------------------------------------------------
# 8) 自检：签名可通过校验 + 包名/versionCode 核对 + 证书必须与线上旧包同源
# -----------------------------------------------------------------------------
log "8/9 校验签名、版本与签名证书"
"$APKSIGNER" verify --print-certs "$SIGNED_APK"
# aapt dump badging 在个别资源引用（如框架图标）上会以非 0 退出 —— 这里容错，
# 退出码不当作成败判据，真正的判定交给下面几条 grep。
# 先落盘再 grep —— 直接 `aapt dump badging ... | head -1` 会在 head 提前退出时让 aapt
# 吃到 SIGPIPE，配合 pipefail 会误判成构建失败。
"$AAPT" dump badging "$SIGNED_APK" > "$BUILD_DIR/badging.txt" || true
grep -E "^package:" "$BUILD_DIR/badging.txt" \
  || { echo "badging 里没有 package 行，清单可能被改坏" >&2; exit 1; }
grep -Eq "versionCode='$VERSION_CODE'" "$BUILD_DIR/badging.txt" \
  || { echo "打出的包 versionCode 不是注入的 $VERSION_CODE" >&2; exit 1; }
grep -q "launchable-activity" "$BUILD_DIR/badging.txt" \
  || echo "    警告: badging 里没有 launchable-activity 行（图标/清单可能有问题，但仍继续）" >&2

# 与线上旧包比对签名证书摘要：不一致 = 换了 key，覆盖安装会被拒（只能卸载重装并丢数据）。
# 只比摘要，不打印口令；旧包不存在（首次部署）时跳过。
if [ -f "$OUT_APK" ]; then
  NEW_CERT="$( "$APKSIGNER" verify --print-certs "$SIGNED_APK" 2>/dev/null \
      | grep -i 'certificate SHA-256 digest' | head -n 1 || true )"
  OLD_CERT="$( "$APKSIGNER" verify --print-certs "$OUT_APK" 2>/dev/null \
      | grep -i 'certificate SHA-256 digest' | head -n 1 || true )"
  if [ -n "$NEW_CERT" ] && [ -n "$OLD_CERT" ] && [ "$NEW_CERT" != "$OLD_CERT" ]; then
    echo "签名证书与线上旧包不一致！换 key 会让覆盖安装被系统拒绝（只能卸载重装并丢数据）。" >&2
    echo "  新: $NEW_CERT" >&2
    echo "  旧: $OLD_CERT" >&2
    exit 1
  fi
  if [ -n "$OLD_CERT" ]; then
    echo "    签名证书与线上旧包同源"
  fi
fi

# -----------------------------------------------------------------------------
# 9) 原子落盘（先备份旧包）+ 清理构建中间产物
# -----------------------------------------------------------------------------
log "9/9 落盘到 $OUT_APK 并清理中间产物"
mkdir -p "$(dirname "$OUT_APK")"
if [ -f "$OUT_APK" ]; then
  cp -f "$OUT_APK" "$OUT_APK.bak"
  echo "    旧包已备份: $OUT_APK.bak"
fi
mv -f "$SIGNED_APK" "$OUT_APK"
if [ "$KEEP_BUILD" = "1" ]; then
  echo "    保留中间产物（KANGLE_KEEP_BUILD=1）: ./$GEN_DIR ./$BUILD_DIR"
else
  rm -rf "$GEN_DIR" "$BUILD_DIR"
fi

log "构建完成"
echo "    应用    : $APP_LABEL ($PKG_NAME)"
echo "    version : $VERSION_CODE / $VERSION_NAME"
echo "    H5      : $H5_URL"
echo "    产物    : $OUT_APK"
ls -lh "$OUT_APK"
echo "    对外    : http://159.75.94.149:8000/laoyouji.apk"
echo
echo "    装到演示机（小米 MIUI）后，务必走一遍保活四步："
echo "      自启动授权 / 省电白名单 / 通知允许 / 精确闹钟（见 README.md）"
