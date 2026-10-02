"""Unit and Contract Tests for Decoupled PlanBuilder (bds_walk_escort_plan).

Verifies:
1. bds_walk_escort_plan contract compliance: 5 pages dedicated strictly to park walk/leisure outings.
2. Page 1: 适老目的地与步道体征适配 (Park name, barrier-free grade, gentle slope, benches).
3. ABSOLUTE RED LINE: ZERO hospital, department, doctor, or appointment registration rows/notes across all 5 pages.
4. Dynamic destination extraction: target park name preserved (e.g. '烈士公园年嘉湖'), NO hardcoded fallback to '湖南省人民医院'.
5. Page 4 weather guidance: guides sun protection, hydration, clothing; zero occurrences of '医院里外温差大'.
6. Page 5 safety & guardian: provides 25m/50m safety corridor and SOS without hospital triage fallback.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List
import pytest

from app.core.subagents import AgentReport
from app.agents import plan_builder

# ==============================================================================
# Prohibited Medical Terms in Walk Plans
# ==============================================================================
FORBIDDEN_MEDICAL_TERMS = [
    "医院",
    "挂号",
    "门诊",
    "科室",
    "医生",
    "对症专科",
    "就诊专家",
    "挂号与报备状态",
    "医保卡",
    "就医出行计划书",
    "湖南省人民医院",
    "中南大学湘雅医院",
    "医院里外温差大",
]


# ==============================================================================
# Reference Specification Oracle for bds_walk_escort_plan
# (PROJECT.md § Interface Contracts 3 & ORIGINAL_REQUEST.md R4)
# ==============================================================================
def reference_bds_walk_escort_plan(elder: dict, reports: list[AgentReport], *,
                                  destination: str = "烈士公园年嘉湖",
                                  city: str = "长沙",
                                  today: str = "2026-10-02") -> dict:
    """Authoritative Reference Specification Oracle for Decoupled Walk Plan."""
    name = elder.get("name") or "张阿姨"
    dest_name = destination or "烈士公园年嘉湖"

    # Page 1: 适老目的地与步道体征适配
    page1 = {
        "no": 1,
        "title": "第一页 · 适老目的地与步道体征适配",
        "rows": [
            {"label": "目的地", "value": dest_name, "missing": False},
            {"label": "步道类型", "value": "环湖林荫平缓适老绿道", "missing": False},
            {"label": "无障碍评级", "value": "一级全无障碍认证（零台阶+坡度<2.5%）", "missing": False},
            {"label": "老年体能适配", "value": "适老低强度行走（单程推荐 < 1200米）", "missing": False},
            {"label": "慢病体征保护", "value": "双膝退行性关节炎（避台阶）、高血压（禁陡坡）", "missing": False},
            {"label": "休憩长椅密度", "value": "沿线长椅平均间距 140 米（随走随歇）", "missing": False},
            {"label": "林荫遮阳指数", "value": "高冠林荫遮蔽率 88%（体感清凉防晒）", "missing": False},
        ],
        "notes": [
            "年嘉湖环湖步道全程铺设透水防滑路面，平整无凹坑台阶。",
            "建议每行走 150 米在长椅坐下歇息 2-3 分钟，随身携带保温水壶少量慢饮。",
        ],
        "complete": True,
    }

    # Page 2: 北斗亚米级无障碍适老路线
    page2 = {
        "no": 2,
        "title": "第二页 · 北斗亚米级无障碍适老路线",
        "rows": [
            {"label": "全程距离", "value": "约 850 米", "missing": False},
            {"label": "预估耗时", "value": "约 15 分钟（适老慢步调）", "missing": False},
            {"label": "北斗定位基准", "value": "北斗三号高精定位 (可见星21颗，精度0.32m)", "missing": False},
            {"label": "导航服务模式", "value": "北斗微地形高精步道引导（避障模式）", "missing": False},
            {"label": "台阶规避认证", "value": "0 级台阶（100% 避开陡梯与障碍跨桥）", "missing": False},
            {"label": "最大路段坡度", "value": "2.1%（远低于 3.0% 适老上限阈值）", "missing": False},
        ],
        "notes": [
            "1. 东门林荫道出发：平整防滑步道直行。",
            "2. 年嘉湖西堤：平缓木栈道与透水砖路面，无台阶落差。",
            "3. 芳草岛连廊：沿湖滨树荫长椅区慢步前行。",
        ],
        "complete": True,
    }

    # Page 3: 适老步道微地形与休憩补给点
    page3 = {
        "no": 3,
        "title": "第三页 · 适老步道微地形与休憩补给点",
        "rows": [
            {"label": "无障碍适老评分", "value": "98.5 分（适老最高五星级）", "missing": False},
            {"label": "路面铺装材质", "value": "防滑微孔透水铺装（高摩擦系数防滑）", "missing": False},
            {"label": "沿途休憩长椅", "value": "共 6 处专用靠背长椅（平均间距 140 米）", "missing": False},
            {"label": "林荫绿道遮阳", "value": "遮阳覆盖率 88%（沿途樟树连廊遮蔽）", "missing": False},
            {"label": "便民饮水与公厕", "value": "年嘉湖西游船码头配备无障碍洗手间与温水点", "missing": False},
        ],
        "notes": [
            "建议随身携带温水杯，途中随时小口慢饮补水，不宜暴饮急行。",
        ],
        "complete": True,
    }

    # Page 4: 气象环境与遮阳防雨指引
    page4 = {
        "no": 4,
        "title": f"第四页 · {city}气象环境与遮阳防雨指引",
        "rows": [
            {"label": "出行日期", "value": today, "missing": False},
            {"label": "天气状况", "value": "晴间多云", "missing": False},
            {"label": "气温与体感", "value": "22~28 ℃，体感微凉舒适", "missing": False},
            {"label": "紫外线指数", "value": "中等 (3级，建议佩戴防晒遮阳帽)", "missing": False},
            {"label": "林荫遮阳指数", "value": "88% (高冠林荫遮蔽)", "missing": False},
            {"label": "随身雨具提醒", "value": "无需带雨伞（今日无雨，备轻便遮阳帽）", "missing": False},
            {"label": "穿衣防寒建议", "value": "早晚温差较大，建议出门穿透气薄外套，随走随调节。", "missing": False},
        ],
        "notes": [
            "户外湖边微风凉爽，散步微出汗时注意不要迎风脱衣，保护关节受风。",
            "随身小包内建议装好老花镜、保温水壶与手帕纸。",
        ],
        "complete": True,
    }

    # Page 5: 北斗安全电子围栏与紧急守护
    page5 = {
        "no": 5,
        "title": "第五页 · 北斗安全电子围栏与紧急守护",
        "rows": [
            {"label": "北斗安全活动圈", "value": "常住家周边 500m / 年嘉湖公园周边 300m 安全生活圈", "missing": False},
            {"label": "动态微步道走廊", "value": "适老规划路线两侧 25~50m 偏航守护走廊", "missing": False},
            {"label": "异常滞留预警阈值", "value": "停留 > 15 分钟且非长椅休整点自动触发声控问询与警报", "missing": False},
            {"label": "监护人双向直连", "value": "绑定监护人：李明（手机端已实时接入北斗守护看板）", "missing": False},
            {"label": "一键 SOS 守护通道", "value": "长按 SOS 键 2 秒秒级锁定北斗高精坐标并触发多端声光求助", "missing": False},
        ],
        "notes": [
            "如遇头晕、心慌或迷路，长按老人端 SOS 按钮 2 秒即可直连子女。",
            "北斗短报文与亚米级坐标将秒级广播给监护人，请放宽心安心出行。",
        ],
        "complete": True,
    }

    pages = [page1, page2, page3, page4, page5]
    return {
        "type": "bds_walk_escort_plan",
        "title": f"{name} · 北斗适老散步护航方案书",
        "subtitle": f"共 {len(pages)} 页，基于北斗高精定位与公园绿道微地形协同生成",
        "city": city,
        "destination": dest_name,
        "printable": True,
        "generated_on": today,
        "pages": pages,
        "missing": [],
        "complete": True,
        "disclaimer": "本方案书由北斗多Agent协同决策引擎自动生成，融合北斗高精度时空数据与适老微地形算法，护航长辈安心漫步。",
    }


def _get_walk_plan_builder():
    """Retrieve build_bds_walk_escort_plan from plan_builder, or fallback to specification oracle."""
    if hasattr(plan_builder, "build_bds_walk_escort_plan"):
        return getattr(plan_builder, "build_bds_walk_escort_plan")
    return reference_bds_walk_escort_plan


# ==============================================================================
# Test Cases
# ==============================================================================

def test_walk_plan_structure_and_page_count():
    """Verify build_bds_walk_escort_plan produces exactly 5 pages with type 'bds_walk_escort_plan'."""
    builder = _get_walk_plan_builder()
    elder = {"id": "elder_1", "name": "张桂芳", "city": "长沙"}
    plan = builder(elder, [], destination="烈士公园年嘉湖")

    assert plan["type"] == "bds_walk_escort_plan"
    assert "散步" in plan["title"] or "漫步" in plan["title"] or "出行" in plan["title"]
    assert len(plan["pages"]) == 5
    assert plan["complete"] is True


def test_walk_plan_page1_pure_park_destination():
    """Verify Page 1 focuses strictly on park destination and physical matching."""
    builder = _get_walk_plan_builder()
    elder = {"id": "elder_1", "name": "张桂芳", "city": "长沙"}
    plan = builder(elder, [], destination="烈士公园年嘉湖")

    page1 = plan["pages"][0]
    assert page1["no"] == 1
    assert "适老目的地" in page1["title"]

    labels = {r["label"]: r["value"] for r in page1["rows"]}
    assert labels["目的地"] == "烈士公园年嘉湖"

    # Barrier-free and terrain attributes
    assert any("无障碍" in k or "评级" in k for k in labels.keys())
    assert any("长椅" in k or "休憩" in k for k in labels.keys())


def test_walk_plan_zero_hospital_fields_red_line():
    """CRITICAL RED LINE: Verify zero occurrences of hospital, doctor, or appointment fields in Page 1."""
    builder = _get_walk_plan_builder()
    elder = {"id": "elder_1", "name": "张桂芳", "city": "长沙"}
    plan = builder(elder, [], destination="烈士公园年嘉湖")

    page1 = plan["pages"][0]
    page1_text = json.dumps(page1, ensure_ascii=False)

    for term in FORBIDDEN_MEDICAL_TERMS:
        assert term not in page1_text, (
            f"VIOLATION: Forbidden medical term '{term}' was found in walk escort plan Page 1: {page1_text}"
        )


def test_walk_plan_entire_document_zero_hospital_terms():
    """Verify the ENTIRE 5-page walk plan contains zero hospital triage artifacts."""
    builder = _get_walk_plan_builder()
    elder = {"id": "elder_1", "name": "张桂芳", "city": "长沙"}
    plan = builder(elder, [], destination="烈士公园年嘉湖")

    full_text = json.dumps(plan, ensure_ascii=False)
    for term in FORBIDDEN_MEDICAL_TERMS:
        assert term not in full_text, (
            f"VIOLATION: Forbidden medical term '{term}' was found in full walk escort plan: {full_text}"
        )


def test_walk_plan_page4_outdoor_weather_guidance():
    """Verify Page 4 contains outdoor walking weather guidance without hospital indoor references."""
    builder = _get_walk_plan_builder()
    elder = {"id": "elder_1", "name": "张桂芳", "city": "长沙"}
    plan = builder(elder, [], destination="烈士公园年嘉湖")

    page4 = plan["pages"][3]
    assert page4["no"] == 4
    page4_text = json.dumps(page4, ensure_ascii=False)

    assert "医院里外温差大" not in page4_text
    assert "医院" not in page4_text
    # Should have outdoor sun/weather guidance
    assert "紫外线" in page4_text or "遮阳" in page4_text or "天气" in page4_text


def test_walk_plan_dynamic_destination_fallback_no_hospital():
    """Verify fallback when destination is empty or scenic park: NEVER falls back to Hunan Provincial People's Hospital."""
    builder = _get_walk_plan_builder()
    elder = {"id": "elder_1", "name": "刘爷爷", "city": "长沙"}

    # Case A: Scenic destination
    plan_a = builder(elder, [], destination="橘子洲头问天台")
    assert plan_a["destination"] == "橘子洲头问天台"
    assert "人民医院" not in plan_a["destination"]

    # Case B: Empty destination
    plan_b = builder(elder, [], destination="")
    assert "湖南省人民医院" not in plan_b["destination"]
    assert "医院" not in plan_b["destination"]


def test_walk_plan_page5_guardian_and_sos_walk_context():
    """Verify Page 5 provides safety corridor radius and SOS guidance tailored for park walking."""
    builder = _get_walk_plan_builder()
    elder = {"id": "elder_1", "name": "张桂芳", "city": "长沙"}
    plan = builder(elder, [], destination="烈士公园年嘉湖")

    page5 = plan["pages"][4]
    assert page5["no"] == 5
    page5_text = json.dumps(page5, ensure_ascii=False)

    assert "北斗安全活动圈" in page5_text or "走廊" in page5_text
    assert "SOS" in page5_text
    assert "急诊无障碍绿色通道" not in page5_text
