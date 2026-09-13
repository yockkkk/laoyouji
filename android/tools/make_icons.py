#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成康乐 App 的启动图标。纯标准库（zlib + struct 手写 PNG），无第三方依赖。

为什么要有这个脚本：图标本来是 PNG/矢量二进制，无法在仓库里"读"出它是怎么来的。
放一个生成器进来，配色与图形就有据可查、可复跑、可改。

产物（都在 android/res/ 下）：
  mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png   旧版图标，API 21–25 兜底
  drawable/ic_launcher_foreground.xml                        自适应图标前景（白心）
  values/ic_launcher_background.xml                          自适应图标底色
  mipmap-anydpi-v26/ic_launcher.xml                          自适应图标（API 26+，演示机 MIUI 走这条）

配色取自 frontend/laoyouji-app/src/uni.scss 的品牌 token，不要另行造色：
  $lyj-primary  #FF6B35   底色
  $lyj-primary-light #ff7a3d  渐变上端
  $lyj-primary-dark  #E85D04  渐变下端
图形语义：暖橙底 + 白心 —— 与"康乐=健康"这条基线一致，不放文字（小尺寸下汉字必糊）。

用法：
    cd android && python tools/make_icons.py
前提：本机有 python3。不依赖 Android SDK，产物是纯文本 XML + PNG。
"""
import math
import os
import struct
import zlib

# ===== 品牌色 =====
C_TOP = (0xFF, 0x7A, 0x3D)   # $lyj-primary-light
C_BOTTOM = (0xE8, 0x5D, 0x04)  # $lyj-primary-dark
WHITE = (0xFF, 0xFF, 0xFF)

# 旧版图标各密度边长（Android 官方尺寸表）
LEGACY_SIZES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}

HEART_FILL = 0.56      # 心形宽占图标边长的比例
CORNER_RATIO = 0.20    # 圆角半径占图标边长
BLEED = 0.04           # 四周留白（透明）占边长，避免贴边

SS = 3                 # 每像素 3x3 超采样，消锯齿


# --------------------------------------------------------------------------- #
# 心形：隐式方程 (x²+y²-1)³ - x²y³ < 0 为内部，y 轴向上
# --------------------------------------------------------------------------- #
def heart_inside(x, y):
    a = x * x + y * y - 1.0
    return a * a * a - x * x * y * y * y < 0.0


def heart_bbox(n=600, lo=-1.6, hi=1.6):
    """数值扫出心形的紧包围盒，避免手算常数写错。"""
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    step = (hi - lo) / n
    for i in range(n + 1):
        x = lo + step * i
        for j in range(n + 1):
            y = lo + step * j
            if heart_inside(x, y):
                if x < xmin:
                    xmin = x
                if x > xmax:
                    xmax = x
                if y < ymin:
                    ymin = y
                if y > ymax:
                    ymax = y
    return xmin, ymin, xmax, ymax


HB = heart_bbox()
HW = HB[2] - HB[0]   # 心形宽（方程单位）
HH = HB[3] - HB[1]   # 心形高


def heart_at(u, v, fill):
    """
    图标归一化坐标 (u,v) ∈ [0,1]²（v 向下）是否落在心形内。
    心形按 fill（占边长比例）等比居中放置。
    """
    fw = fill
    fh = fill * (HH / HW)          # 图标是正方形，等比即同比例
    # 屏幕坐标 → 方程坐标；v 向下，心形 y 向上，故减号
    x = HB[0] + (u - (0.5 - fw / 2.0)) / fw * HW
    y = HB[3] - (v - (0.5 - fh / 2.0)) / fh * HH
    return heart_inside(x, y)


def inside_round_rect(u, v, bleed, radius):
    """(u,v) ∈ [0,1]² 是否落在带圆角的方块内（四周留 bleed 的透明边）。"""
    x0 = y0 = bleed
    x1 = y1 = 1.0 - bleed
    r = radius
    cx = min(max(u, x0 + r), x1 - r)
    cy = min(max(v, y0 + r), y1 - r)
    if u < x0 or u > x1 or v < y0 or v > y1:
        return False
    return (u - cx) ** 2 + (v - cy) ** 2 <= r * r


def make_legacy(size):
    """旧版启动图标：暖橙竖向渐变圆角方块 + 白心，带 alpha。"""
    px = bytearray(size * size * 4)
    inv = 1.0 / (SS * SS)
    for py in range(size):
        for pxi in range(size):
            a_acc = 0.0   # 落在圆角方块内的采样数 → 决定 alpha
            h_acc = 0.0   # 落在心形内的采样数 → 决定白心覆盖率
            for sy in range(SS):
                for sx in range(SS):
                    u = (pxi + (sx + 0.5) / SS) / size
                    v = (py + (sy + 0.5) / SS) / size
                    if not inside_round_rect(u, v, BLEED, CORNER_RATIO):
                        continue
                    a_acc += 1.0
                    if heart_at(u, v, HEART_FILL):
                        h_acc += 1.0
            # 只有"整像素都在圆角方块之外"才是全透明。注意不能拿 covariance 为 0 提前
            # continue —— 心形之外的像素正是橙色底，跳过它们会把整个底写成透明。
            if a_acc <= 0.0:
                continue
            cov = h_acc / a_acc          # 方块内的白心占比（在方块内归一，避免边缘发暗）
            g = (py + 0.5) / size
            bg = tuple(
                int(round(C_TOP[i] + (C_BOTTOM[i] - C_TOP[i]) * g)) for i in range(3)
            )
            col = tuple(
                int(round(bg[i] + (WHITE[i] - bg[i]) * cov)) for i in range(3)
            )
            o = (py * size + pxi) * 4
            px[o] = col[0]
            px[o + 1] = col[1]
            px[o + 2] = col[2]
            px[o + 3] = int(round(255 * a_acc * inv))
    return px


# --------------------------------------------------------------------------- #
# 最小 PNG 编码器（RGBA，8bit，无隔行）
# --------------------------------------------------------------------------- #
def _chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path, size, rgba):
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)  # 每行的 filter 字节：0 = None
        raw += rgba[y * stride:(y + 1) * stride]
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


# --------------------------------------------------------------------------- #
# 自适应图标（API 26+）：108x108 viewport，安全区是中心 66dp 圆
# --------------------------------------------------------------------------- #
# Material "favorite" 心形路径，24x24 viewport
HEART_PATH = (
    "M12,21.35l-1.45,-1.32C5.4,15.36 2,12.28 2,8.5 2,5.42 4.42,3 7.5,3"
    "c1.74,0 3.41,0.81 4.5,2.09C13.09,3.81 14.76,3 16.5,3 19.58,3 22,5.42 22,8.5"
    "c0,3.78 -3.4,6.86 -8.55,11.54L12,21.35z"
)

FOREGROUND_XML = """<?xml version="1.0" encoding="utf-8"?>
<!-- 由 tools/make_icons.py 生成，勿手改；改图标请改脚本后重跑。 -->
<!-- 108x108 viewport，安全区为中心 66dp 圆。心形实占 44x40.4，居 54,54，
     最大外扩 22 < 圆内接方半宽 23.3，任何遮罩下都不会被切到。 -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
    <group
        android:translateX="27.6"
        android:translateY="27.215"
        android:scaleX="2.2"
        android:scaleY="2.2">
        <path
            android:fillColor="#FFFFFF"
            android:pathData="%s" />
    </group>
</vector>
""" % HEART_PATH

BACKGROUND_XML = """<?xml version="1.0" encoding="utf-8"?>
<!-- 由 tools/make_icons.py 生成，勿手改。 -->
<resources>
    <!-- 品牌主色 $lyj-primary (#FF6B35)，与 uni.scss 一致 -->
    <color name="ic_launcher_background">#FF6B35</color>
</resources>
"""

ADAPTIVE_XML = """<?xml version="1.0" encoding="utf-8"?>
<!-- 由 tools/make_icons.py 生成，勿手改。API 26+ 用这条（演示机 MIUI 走这里）。 -->
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground android:drawable="@drawable/ic_launcher_foreground" />
</adaptive-icon>
"""


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return len(text.encode("utf-8"))


def main():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "res")
    root = os.path.normpath(root)

    print(
        "心形包围盒(方程单位): x[%.4f,%.4f] y[%.4f,%.4f] (宽 %.4f 高 %.4f)"
        % (HB[0], HB[2], HB[1], HB[3], HW, HH)
    )

    for dens, size in LEGACY_SIZES.items():
        d = os.path.join(root, "mipmap-" + dens)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "ic_launcher.png")
        n = write_png(p, size, make_legacy(size))
        print("  %-28s %3dpx  %6d bytes" % ("mipmap-%s/ic_launcher.png" % dens, size, n))

    files = [
        (os.path.join(root, "drawable", "ic_launcher_foreground.xml"), FOREGROUND_XML),
        (os.path.join(root, "values", "ic_launcher_background.xml"), BACKGROUND_XML),
        (os.path.join(root, "mipmap-anydpi-v26", "ic_launcher.xml"), ADAPTIVE_XML),
    ]
    for p, t in files:
        n = write_text(p, t)
        print("  %-28s %6d bytes" % (os.path.relpath(p, root).replace("\\", "/"), n))

    print("完成。清单里用 android:icon=\"@mipmap/ic_launcher\" 引用。")


if __name__ == "__main__":
    main()
