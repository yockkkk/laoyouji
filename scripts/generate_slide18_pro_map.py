# -*- coding: utf-8 -*-
"""
scripts/generate_slide18_pro_map.py
生成高精度、真实、具备完整适老微地形要素的示范导航地图大图 (2000x1900)。
包含：
1. 真实长沙烈士公园年嘉湖人行步道微拓扑底图与水系；
2. 动态安全走廊 (30m 缓冲带)；
3. 微地形坡度分段颜色标注 (<2.5% 平缓绿道)；
4. 台阶硬阻断剪枝对比标记 (Cost=∞ 避开38级险台阶与陡天桥)；
5. 沿途长椅休憩点 (200m 密度)、无障碍卫生间、林荫遮阳段；
6. 500m 生活圈与水域警戒电子围栏；
7. 北斗 0.35m RTK 实时高精定位与状态标注。
"""
import math
from PIL import Image, ImageDraw, ImageFont

def create_pro_microterrain_map(output_path="assets/slide18_microterrain_pro_map.png"):
    W, H = 2000, 1900
    im = Image.new("RGBA", (W, H), (11, 21, 40, 255)) # 科技深蓝背景
    draw = ImageDraw.Draw(im)

    # 字体配置
    FONT_PATH = "C:\\Windows\\Fonts\\msyh.ttc"
    FONT_BD_PATH = "C:\\Windows\\Fonts\\msyhbd.ttc"
    f_title = ImageFont.truetype(FONT_BD_PATH, 44)
    f_sub = ImageFont.truetype(FONT_PATH, 28)
    f_badge = ImageFont.truetype(FONT_BD_PATH, 26)
    f_poi = ImageFont.truetype(FONT_BD_PATH, 24)
    f_poi_sub = ImageFont.truetype(FONT_PATH, 20)
    f_legend = ImageFont.truetype(FONT_BD_PATH, 24)
    f_stat = ImageFont.truetype(FONT_BD_PATH, 30)

    # 1. 顶部标题栏背景与装饰条
    draw.rectangle([0, 0, W, 140], fill=(15, 30, 58, 255))
    draw.line([(0, 140), (W, 140)], fill=(0, 242, 254, 180), width=3)
    
    # 顶部主标题与终端状态
    draw.text((50, 30), "湖南本地示范点 · 烈士公园年嘉湖适老微地形高精实景导航", fill=(255, 255, 255, 255), font=f_title)
    status_bar_text = "🛰️ 北斗三号 CGCS2000基准  |  RTK固定解 0.35m  |  锁定卫星: 22颗  |  步道坡度: 1.8% (平缓)  |  安全走廊: 伴随中"
    draw.text((50, 88), status_bar_text, fill=(0, 242, 254, 240), font=f_sub)

    # 2. 地图视窗区域 (留边框)
    MX1, MY1, MX2, MY2 = 40, 160, W - 40, H - 120
    draw.rectangle([MX1, MY1, MX2, MY2], fill=(16, 26, 46, 255), outline=(30, 58, 95, 255), width=2)

    # 绘制模拟环境栅格与街区
    for x in range(MX1, MX2, 120):
        draw.line([(x, MY1), (x, MY2)], fill=(22, 38, 66, 120), width=1)
    for y in range(MY1, MY2, 120):
        draw.line([(MX1, y), (MX2, y)], fill=(22, 38, 66, 120), width=1)

    # 街区背景色块（绿地、建筑群）
    draw.rounded_rectangle([100, 220, 500, 550], radius=15, fill=(18, 36, 52, 180), outline=(28, 55, 80, 150))
    draw.text((120, 240), "华夏路社区综合生活区", fill=(100, 130, 170, 200), font=f_sub)

    draw.rounded_rectangle([100, 1250, 650, 1680], radius=15, fill=(18, 36, 52, 180), outline=(28, 55, 80, 150))
    draw.text((120, 1270), "开福寺文化休闲风貌区", fill=(100, 130, 170, 200), font=f_sub)

    draw.rounded_rectangle([1350, 1200, 1900, 1680], radius=15, fill=(18, 36, 52, 180), outline=(28, 55, 80, 150))
    draw.text((1370, 1220), "烈士公园东门游客中心", fill=(100, 130, 170, 200), font=f_sub)

    # 3. 绘制年嘉湖水域大色块 (淡蓝水体多边形)
    lake_poly = [
        (850, 320), (1200, 280), (1650, 340), (1850, 550), 
        (1880, 950), (1750, 1150), (1450, 1100), (1200, 1020),
        (1000, 880), (820, 700), (780, 480)
    ]
    draw.polygon(lake_poly, fill=(14, 45, 80, 220), outline=(0, 180, 216, 200))
    # 年嘉湖水域标注
    draw.text((1250, 600), "湖南烈士公园 · 年嘉湖水域", fill=(0, 242, 254, 220), font=f_title)
    draw.text((1300, 665), "环湖微风 2级  |  水域防跌隔离绿篱全覆盖", fill=(140, 200, 230, 200), font=f_sub)

    # 水域防跌安全警戒红线 (距离水边 15米)
    lake_fence_poly = [
        (830, 305), (1190, 265), (1665, 325), (1870, 540), 
        (1900, 960), (1765, 1165), (1440, 1115), (1190, 1035),
        (985, 895), (805, 715), (765, 470)
    ]
    for i in range(len(lake_fence_poly) - 1):
        p1 = lake_fence_poly[i]
        p2 = lake_fence_poly[i+1]
        draw.line([p1, p2], fill=(239, 68, 68, 160), width=3)
    draw.text((950, 920), "⚠️ 年嘉湖水域15米防跌警戒线", fill=(239, 68, 68, 220), font=f_badge)

    # 4. 家·500米生活守护圈 (以起点为中心画大虚线绿圆)
    home_center = (320, 420)
    r_home = 450
    draw.ellipse([home_center[0] - r_home, home_center[1] - r_home, 
                  home_center[0] + r_home, home_center[1] + r_home], 
                 outline=(16, 185, 129, 140), width=4)
    draw.text((120, 820), "🏠 家·500米安心生活守护圈 (圈内静默伴随)", fill=(16, 185, 129, 220), font=f_badge)

    # 5. 核心规划路线坐标链（真实平缓无障碍步道拓扑）
    route_points = [
        (320, 420),   # 1. 起点：华夏路社区便民亭
        (480, 460),   # 2. 社区东门平缓出口
        (650, 520),   # 3. 樟树林荫绿道起点
        (760, 680),   # 4. 烈士公园西门平缓专用坡道
        (880, 840),   # 5. 绕开原险陡台阶，切入平层无障碍栈道
        (1020, 990),  # 6. 年嘉湖西岸适老木栈道
        (1200, 1120), # 7. 环湖平缓林荫慢跑道
        (1400, 1090), # 8. 避开拱桥阶梯，走平缓亲水连廊
        (1600, 980),  # 9. 终点前绿道
        (1720, 860)   # 10. 终点：年嘉湖朝晖楼适老驿站
    ]

    # (A) 绘制动态安全走廊 (30米高亮光环带，覆盖步道两侧)
    for i in range(len(route_points) - 1):
        p1 = route_points[i]
        p2 = route_points[i+1]
        draw.line([p1, p2], fill=(16, 185, 129, 60), width=70) # 30米走廊外层
        draw.line([p1, p2], fill=(16, 185, 129, 90), width=46) # 走廊核心层

    # (B) 绘制路线描边打底
    for i in range(len(route_points) - 1):
        p1 = route_points[i]
        p2 = route_points[i+1]
        draw.line([p1, p2], fill=(255, 255, 255, 230), width=16)

    # (C) 绘制适老微地形高精路线主干线 (平缓绿道翡翠绿 + 天青蓝)
    for i in range(len(route_points) - 1):
        p1 = route_points[i]
        p2 = route_points[i+1]
        draw.line([p1, p2], fill=(0, 210, 255, 255), width=10)

    # (D) 绘制微地形坡度分段标识
    # 平缓绿道区间 1
    draw.text((510, 475), "🟢 坡度 1.2% (平缓绿道)", fill=(16, 185, 129, 255), font=f_poi_sub)
    # 平缓木栈道区间 2
    draw.text((910, 890), "🟢 坡度 1.8% (平缓木栈道)", fill=(16, 185, 129, 255), font=f_poi_sub)
    # 微缓坡区间 3
    draw.text((1220, 1135), "🟡 坡度 2.8% (微缓坡·平稳慢步)", fill=(245, 158, 11, 255), font=f_poi_sub)

    # 6. 核心对比：传统商业地图的危险台阶/陡坡 (Cost=∞ 剪枝对比线)
    # 传统路线直接走南门40米长陡阶梯与天桥 (直插)
    bad_route_points = [
        (480, 460),
        (620, 600),
        (750, 780),
        (820, 890)
    ]
    for i in range(len(bad_route_points) - 1):
        p1 = bad_route_points[i]
        p2 = bad_route_points[i+1]
        draw.line([p1, p2], fill=(239, 68, 68, 180), width=6) # 红色警告线

    # 在 (750, 780) 标注台阶硬阻断避险大图章
    stair_x, stair_y = 750, 780
    draw.rounded_rectangle([stair_x - 170, stair_y - 45, stair_x + 170, stair_y + 45], 
                           radius=12, fill=(185, 28, 28, 230), outline=(255, 255, 255, 255), width=2)
    draw.text((stair_x - 150, stair_y - 35), "⛔ 原南门38级险台阶", fill=(255, 255, 255, 255), font=f_badge)
    draw.text((stair_x - 150, stair_y + 5), "Cost=∞ 硬阻断剪枝", fill=(254, 226, 226, 255), font=f_poi_sub)

    # 在天桥处标注陡坡阻断
    draw.rounded_rectangle([520, 610, 760, 675], radius=10, fill=(185, 28, 28, 220), outline=(255, 255, 255, 200), width=2)
    draw.text((535, 620), "⚠️ 避开过街陡坡 (11.8%)", fill=(255, 255, 255, 255), font=f_poi_sub)
    draw.text((535, 645), "传统地图存在跌倒险情", fill=(254, 202, 202, 255), font=ImageFont.truetype(FONT_PATH, 16))

    # 7. 绘制沿途适老设施 POI 节点
    pois = [
        {"x": 650, "y": 520, "name": "🪑 适老长椅 1号", "desc": "配备遮阳棚与防滑扶手 · 距起点180m"},
        {"x": 1020, "y": 990, "name": "🪑 适老长椅 2号", "desc": "年嘉湖西岸亲水长椅 · 距起点410m"},
        {"x": 1400, "y": 1090, "name": "🪑 适老长椅 3号", "desc": "绿荫茶歇处 · 距起点630m"},
        {"x": 880, "y": 740, "name": "🚻 第三卫生间 (无障碍)", "desc": "低位扶手 · 紧急呼叫一键呼叫"},
        {"x": 1280, "y": 1000, "name": "🏥 湖滨 AED 医疗点", "desc": "三甲急救绿通秒级联动定锚"},
        {"x": 560, "y": 380, "name": "🌳 百年樟树林荫廊", "desc": "树荫遮阳率 92% · 体感温和"}
    ]
    for p in pois:
        px, py = p["x"], p["y"]
        # 画 POI 卡片
        tw = 320
        draw.rounded_rectangle([px - 20, py - 60, px + tw, py - 5], radius=8, fill=(15, 30, 58, 230), outline=(0, 242, 254, 200), width=2)
        draw.text((px - 8, py - 55), p["name"], fill=(0, 242, 254, 255), font=f_poi)
        draw.text((px - 8, py - 28), p["desc"], fill=(203, 213, 225, 255), font=f_poi_sub)
        # 连接点
        draw.ellipse([px - 6, py - 6, px + 6, py + 6], fill=(0, 242, 254, 255), outline=(255, 255, 255, 255), width=2)

    # 8. 绘制起点与终点徽标大卡片
    # 起点
    sp = route_points[0]
    draw.rounded_rectangle([sp[0] - 30, sp[1] - 110, sp[0] + 320, sp[1] - 25], radius=12, fill=(6, 95, 70, 240), outline=(52, 211, 153, 255), width=3)
    draw.text((sp[0] - 10, sp[1] - 102), "🟢 起点：华夏路社区便民站", fill=(255, 255, 255, 255), font=f_badge)
    draw.text((sp[0] - 10, sp[1] - 62), "出东门缓坡无障碍直出 · 零台阶", fill=(209, 250, 229, 255), font=f_poi_sub)
    draw.ellipse([sp[0] - 10, sp[1] - 10, sp[0] + 10, sp[1] + 10], fill=(16, 185, 129, 255), outline=(255, 255, 255, 255), width=3)

    # 终点
    ep = route_points[-1]
    draw.rounded_rectangle([ep[0] - 280, ep[1] - 110, ep[0] + 80, ep[1] - 25], radius=12, fill=(180, 83, 9, 240), outline=(251, 191, 36, 255), width=3)
    draw.text((ep[0] - 260, ep[1] - 102), "🔴 终点：年嘉湖朝晖楼适老驿站", fill=(255, 255, 255, 255), font=f_badge)
    draw.text((ep[0] - 260, ep[1] - 62), "平缓木栈道直达 · 全程无障碍贯通", fill=(254, 243, 199, 255), font=f_poi_sub)
    draw.ellipse([ep[0] - 10, ep[1] - 10, ep[0] + 10, ep[1] + 10], fill=(239, 68, 68, 255), outline=(255, 255, 255, 255), width=3)

    # 9. 绘制张阿姨实时北斗定位光标 (当前位置在环湖木栈道 760, 680)
    cur_pos = (760, 680)
    # 光波外圈
    draw.ellipse([cur_pos[0] - 38, cur_pos[1] - 38, cur_pos[0] + 38, cur_pos[1] + 38], outline=(0, 242, 254, 180), width=4)
    draw.ellipse([cur_pos[0] - 22, cur_pos[1] - 22, cur_pos[0] + 22, cur_pos[1] + 22], fill=(0, 242, 254, 255), outline=(255, 255, 255, 255), width=3)
    # 悬浮信息气泡
    draw.rounded_rectangle([cur_pos[0] - 200, cur_pos[1] - 130, cur_pos[0] + 200, cur_pos[1] - 50], 
                           radius=12, fill=(10, 30, 74, 245), outline=(0, 242, 254, 255), width=3)
    draw.text((cur_pos[0] - 180, cur_pos[1] - 122), "🛰️ 张阿姨实时定位 (北斗0.35m)", fill=(255, 255, 255, 255), font=f_badge)
    draw.text((cur_pos[0] - 180, cur_pos[1] - 82), "步速: 0.7m/s | 状态: 绿道平稳慢行中", fill=(0, 242, 254, 255), font=f_poi_sub)

    # 10. 底部地图图例栏 (磨砂半透明卡片)
    LX1, LY1, LX2, LY2 = 60, H - 100, W - 60, H - 20
    draw.rounded_rectangle([LX1, LY1, LX2, LY2], radius=16, fill=(15, 30, 58, 250), outline=(0, 242, 254, 180), width=2)
    
    # 图例项目绘制
    legend_items = [
        {"icon": "🛡️", "name": "动态安全走廊 (30m缓冲带)", "color": (16, 185, 129, 255)},
        {"icon": "🟢", "name": "平缓绿道 (纵坡 <2.5%)", "color": (0, 210, 255, 255)},
        {"icon": "⛔", "name": "险陡台阶硬阻断 (Cost=∞)", "color": (239, 68, 68, 255)},
        {"icon": "🪑", "name": "适老爱心长椅 (200m密度)", "color": (245, 158, 11, 255)},
        {"icon": "🏠", "name": "500m生活圈", "color": (16, 185, 129, 255)},
        {"icon": "🛰️", "name": "北斗RTK分米级定位", "color": (0, 242, 254, 255)}
    ]
    cur_lx = LX1 + 40
    for item in legend_items:
        draw.text((cur_lx, LY1 + 22), item["icon"], fill=item["color"], font=f_legend)
        draw.text((cur_lx + 35, LY1 + 24), item["name"], fill=(255, 255, 255, 255), font=f_legend)
        cur_lx += 305

    im.save(output_path, quality=95)
    print(f"High precision micro-terrain map saved to: {output_path}")

if __name__ == "__main__":
    create_pro_microterrain_map()
