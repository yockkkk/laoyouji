"""数据隐私分级 —— 红线 R6"不越级"的门禁。

改造前这块只有 ``routes_privacy.py`` 在**存**授权等级，没有任何地方**用**它：
老人在设置页把位置调成"只给城市"，子女端看板照样端出实时坐标、用药明细、
体检解读原文。存了不用的开关比没有开关更糟 —— 它让人以为已经管住了。

所以这里断言的是三条设计各自成立：

- **降级是数据变形，不是报错**：``city`` 档下位置还在（"北京市朝阳区"），
  只是坐标没了、备注是重建的。功能不消失，精度消失 —— 这样老人才敢真去调开关。
- **fail-closed 在身份那一层**：授权行缺失只是"没细调过"，取粗档默认；
  ``family_bindings`` 缺失是"没这层关系"，一个字段都不给。两者不能混。
- **只出不进**：裁的是离开后端那一份，库里始终是全量事实 ——
  老人把开关调回去，历史照样看得见。

裁剪函数都是纯函数，所以大半测试不需要 ``ctx``；但最后一组是实地验收：
让守护逻辑真跑一遍，证明这些防线防的**不是假想敌** —— ``process_checkpoint``
自己拼的备注里就带着门牌号。
"""
from __future__ import annotations

import json
import logging

from app.api.routes_guardian import CheckpointIn, process_checkpoint
from app.safety.privacy import (
    DEFAULT_HEALTH_LEVEL,
    DEFAULT_LOCATION_LEVEL,
    HEALTH_LEVELS,
    LOCATION_LEVELS,
    MASKED,
    PrivacyGrant,
    PrivacyService,
    _CITY_NOTE,
    _normalize,
    _rank,
    coarse_place,
    denied,
    filter_alert,
    filter_checkpoint,
    filter_health_text,
    filter_medication,
)


# ------------------------------------------------------------------------ 素材


def _grant(location: str = "realtime", health: str = "full", *,
           bound: bool = True) -> PrivacyGrant:
    return PrivacyGrant(elder_id="e-1", child_id="c-1", location_level=location,
                        health_level=health, bound=bound)


def _checkpoint(**over) -> dict:
    """一条真实形状的位置上报：备注里带着门牌号（守护逻辑就是这么拼的）。"""
    base = {"id": "cp-1", "trip_id": "t-1",
            "location": "北京市朝阳区三里屯太古里",
            "lng": 116.455, "lat": 39.937, "status": "off_route",
            "note": "位置偏离规划路线：北京市朝阳区三里屯太古里，请关注"}
    base.update(over)
    return base


def _medication(**over) -> dict:
    base = {"drug": "硫酸氨基葡萄糖胶囊", "dose": "每次1粒",
            "times": ["08:00", "20:00"],
            "taken_today": {"08:00": "taken", "20:00": "pending"}}
    base.update(over)
    return base


def _dumped(value) -> str:
    """把出库的那一份摊平成字符串 —— 断言"某个字眼一个角落都没剩下"。"""
    return json.dumps(value, ensure_ascii=False)


class _BrokenRepo:
    """写审计就抛的仓储。"""

    async def insert(self, table: str, data: dict) -> dict:
        raise RuntimeError("audit_log 写不进去")


# -------------------------------------------------------------------- 等级词表


def test_the_vocabularies_run_from_fine_to_coarse_and_default_to_the_middle():
    """顺序即权限强弱，所以词表的顺序本身是契约，不是排版。"""
    assert LOCATION_LEVELS == ("realtime", "city", "off")
    assert HEALTH_LEVELS == ("full", "summary", "off")
    assert [_rank(LOCATION_LEVELS, x) for x in LOCATION_LEVELS] == [0, 1, 2]

    # 默认取中间那一格：off 会让绑定失去意义，最细档等于默认全开
    assert DEFAULT_LOCATION_LEVEL == LOCATION_LEVELS[1]
    assert DEFAULT_HEALTH_LEVEL == HEALTH_LEVELS[1]


def test_normalize_keeps_known_levels_and_replaces_everything_else():
    """库里的脏值不该让子女端 500，也不该被当成"更细档"。"""
    assert _normalize(LOCATION_LEVELS, "realtime", "city") == "realtime"
    for junk in ("超清", "REALTIME", "", None, 0, ["city"]):
        assert _normalize(LOCATION_LEVELS, junk, "city") == "city", junk


# ---------------------------------------------------------------- 授权判定矩阵


def test_the_location_matrix_only_gives_what_the_elder_opened():
    """"够不够细"的完整矩阵。``off`` 作为需求没人会问，所以不列。"""
    matrix = {
        ("realtime", "realtime"): True, ("realtime", "city"): True,
        ("city", "realtime"): False, ("city", "city"): True,
        ("off", "realtime"): False, ("off", "city"): False,
    }
    for (have, need), expected in matrix.items():
        assert _grant(location=have).allows_location(need) is expected, (have, need)


def test_the_health_matrix_only_gives_what_the_elder_opened():
    matrix = {
        ("full", "full"): True, ("full", "summary"): True,
        ("summary", "full"): False, ("summary", "summary"): True,
        ("off", "full"): False, ("off", "summary"): False,
    }
    for (have, need), expected in matrix.items():
        assert _grant(health=have).allows_health(need) is expected, (have, need)


def test_an_unbound_child_is_refused_even_with_the_finest_levels_on_the_row():
    """``bound=False`` 一票否决：授权行写得再细也不作数（fail-closed 在身份层）。"""
    grant = _grant("realtime", "full", bound=False)

    assert grant.location_off is True and grant.health_off is True
    assert grant.allows_location("city") is False
    assert grant.allows_health("summary") is False
    # 前端开关不能显示"实时"而后端其实不给 —— 对外那份必须自洽
    assert grant.to_dict()["location_level"] == "off"
    assert grant.to_dict()["health_level"] == "off"
    assert grant.to_dict()["bound"] is False


def test_an_unrecognised_request_is_refused_rather_than_waved_through():
    """两侧都宁可少给：需求侧的生词直接不给，存储侧的生词按最粗算。

    需求侧那半是防笔误 —— 哪天调用点写成 ``allows_health("detail")``，
    它不该悄悄把闸门打开。
    """
    grant = _grant("city", "summary")
    assert grant.allows_location("gps") is False
    assert grant.allows_health("detail") is False

    assert _rank(LOCATION_LEVELS, "超清") == len(LOCATION_LEVELS) - 1
    assert _rank(HEALTH_LEVELS, None) == len(HEALTH_LEVELS) - 1
    assert _grant("超清").allows_location("city") is False


def test_denied_is_the_shape_a_stranger_gets():
    grant = denied("e-1", "c-1")
    assert (grant.location_level, grant.health_level) == ("off", "off")
    assert grant.bound is False


# ------------------------------------------------------------------- 查授权


async def test_a_bound_child_reads_the_grades_the_elder_set(ctx, elder, child):
    grant = await ctx.privacy.grant_for(elder["id"], child["id"])

    assert grant.bound is True
    assert (grant.location_level, grant.health_level) == ("realtime", "summary")
    assert grant.allows_location("realtime") is True
    assert grant.allows_health("full") is False, "种子数据的健康档是 summary"
    # 子女端设置页的开关就读这份形状，``bound`` 一定在
    assert grant.to_dict() == {"elder_id": elder["id"], "child_id": child["id"],
                               "location_level": "realtime",
                               "health_level": "summary", "bound": True}


async def test_a_missing_permission_row_means_untuned_not_unbound(ctx, elder, child):
    """没细调过 ≠ 没关系：取粗档默认，功能照常，只是精度不到顶。"""
    row = await ctx.repos.find_one(
        "privacy_permissions", {"elder_id": elder["id"], "child_id": child["id"]})
    assert await ctx.repos.delete("privacy_permissions", row["id"]) is True

    grant = await ctx.privacy.grant_for(elder["id"], child["id"])
    assert grant.bound is True, "关系还在"
    assert (grant.location_level, grant.health_level) == (DEFAULT_LOCATION_LEVEL,
                                                          DEFAULT_HEALTH_LEVEL)
    assert grant.allows_location("realtime") is False, "默认档给不到最细"
    assert grant.allows_location("city") is True


async def test_an_unbound_child_gets_nothing_even_with_a_permission_row(
        ctx, elder, child):
    """身份不成立就是 ``denied()`` —— 授权行留在库里也一概不作数。"""
    binding = await ctx.repos.find_one(
        "family_bindings", {"elder_id": elder["id"], "child_id": child["id"]})
    assert await ctx.repos.delete("family_bindings", binding["id"]) is True
    row = await ctx.repos.find_one(
        "privacy_permissions", {"elder_id": elder["id"], "child_id": child["id"]})
    assert row["location_level"] == "realtime", "授权行还在，而且是最细档"

    grant = await ctx.privacy.grant_for(elder["id"], child["id"])
    assert grant.bound is False
    assert grant.to_dict()["location_level"] == "off"
    # 四条出库路径一条都不通
    assert filter_checkpoint(grant, _checkpoint()) is None
    assert filter_alert(grant, _checkpoint()) is None
    assert filter_medication(grant, _medication()) is None
    assert filter_health_text(grant, "白细胞偏高一点") == ""


async def test_a_junk_level_in_the_database_degrades_instead_of_crashing(
        ctx, elder, child):
    """脏值退到默认档 —— 默认档比最细档粗，所以"退回去"就是收紧。"""
    row = await ctx.repos.find_one(
        "privacy_permissions", {"elder_id": elder["id"], "child_id": child["id"]})
    await ctx.repos.update("privacy_permissions", row["id"],
                           {"location_level": "超清", "health_level": None})

    grant = await ctx.privacy.grant_for(elder["id"], child["id"])
    assert (grant.location_level, grant.health_level) == (DEFAULT_LOCATION_LEVEL,
                                                          DEFAULT_HEALTH_LEVEL)
    assert grant.allows_location("realtime") is False


async def test_the_dashboard_hands_out_exactly_the_grades_the_elder_set(
        ctx, elder, child):
    """看板是隐私分级的**主要出口**：老人存了 (city, summary)，看板就得给
    (city, summary)，用药字段也确实被裁 —— 后端不许替他改答案。

    这条测的是出口而不是 filter_* 本身：旧实现把 bound 家庭的等级强制抬到
    realtime/full，老人在"我的位置/我的健康"里的选择被无声忽略，而
    filter 层的测试全绿 —— 因为被架空的是看板这一步。
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_ctx
    from app.auth.security import create_access_token
    from app.main import app

    row = await ctx.repos.find_one(
        "privacy_permissions", {"elder_id": elder["id"], "child_id": child["id"]})
    await ctx.repos.update("privacy_permissions", row["id"],
                           {"location_level": "city", "health_level": "summary"})

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        token = create_access_token(child, ctx.settings)
        headers = {"Authorization": f"Bearer {token}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport,
                               base_url="http://test") as ac:
            res = await ac.get(f"/api/child/{child['id']}/dashboard",
                               headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert data["privacy"]["location_level"] == "city"
            assert data["privacy"]["health_level"] == "summary"
            assert data["medications"], "种子数据里有用药计划"
            for med in data["medications"]:
                assert med["drug"] == MASKED, \
                    "summary 档给药名就是越级 —— 老人的选择被架空了"
                assert med["dose"] == ""
    finally:
        app.dependency_overrides.clear()


# ------------------------------------------------------------------- 地名粗化


def test_an_address_is_cut_at_the_first_administrative_suffix():
    assert coarse_place("北京市海淀区新街口外大街31号") == "北京市海淀区"
    assert coarse_place("南京市秦淮区中华路68号") == "南京市秦淮区"
    assert coarse_place("上海市黄浦江边") == "上海市"       # 没有区一级就停在市


def test_a_place_with_no_administrative_suffix_keeps_only_three_characters():
    """取不出行政区划就只留前三个字：够子女知道"在哪一片"，不够找到门口。"""
    assert coarse_place("积水潭医院骨科门诊楼") == "积水潭"
    assert coarse_place("三里屯太古里") == "三里屯"


def test_coarsening_never_returns_the_original_string():
    for place in ("北京市海淀区新街口外大街31号", "积水潭医院骨科门诊楼",
                  "三里屯太古里"):
        assert len(coarse_place(place)) < len(place), place


def test_an_empty_place_stays_empty():
    assert coarse_place("") == ""
    assert coarse_place("   ") == ""
    assert coarse_place(None) == ""            # type: ignore[arg-type]


# --------------------------------------------------------------- 位置上报裁剪


def test_the_realtime_grade_passes_the_point_through_and_stamps_it():
    """最细档原样给，但仍然是**副本** —— 库里那份不许被下游改。"""
    cp = _checkpoint()
    out = filter_checkpoint(_grant("realtime"), cp)

    assert out is not cp
    assert (out["lng"], out["lat"]) == (cp["lng"], cp["lat"])
    assert out["location"] == "北京市朝阳区三里屯太古里"
    assert out["precision"] == "realtime"

    out["location"] = "改了"
    assert cp["location"] == "北京市朝阳区三里屯太古里"


def test_the_city_grade_drops_the_coordinates_because_they_are_the_address():
    """留着坐标就等于没降级 —— 地图上一样能戳到门牌号。"""
    out = filter_checkpoint(_grant("city"), _checkpoint())

    assert out["location"] == "北京市朝阳区"
    assert out["lng"] is None and out["lat"] is None
    assert out["precision"] == "city"


def test_the_city_grade_rebuilds_the_note_instead_of_scrubbing_it():
    """备注是**重建**的：洗自由文本是漏的，地址就藏在冒号后面。"""
    out = filter_checkpoint(_grant("city"), _checkpoint())

    assert out["note"] == _CITY_NOTE["off_route"]
    assert "三里屯" not in _dumped(out)
    assert out["status"] == "off_route", "有没有异常照样告诉子女，只是不给在哪"


def test_every_status_gets_a_note_that_names_no_place():
    for status in ("normal", "arrived", "off_route"):
        out = filter_checkpoint(_grant("city"), _checkpoint(
            status=status, note="途经 北京市朝阳区三里屯太古里，一切正常"))
        assert out["note"] == _CITY_NOTE[status], status
        assert "三里屯" not in _dumped(out), status


def test_an_unknown_status_still_gets_a_placeless_note():
    """状态词表哪天扩了一项，也不会因为查不到映射就把原文放出去。"""
    out = filter_checkpoint(_grant("city"), _checkpoint(
        status="谁知道这是什么", note="在 三里屯太古里 附近徘徊"))

    assert out["note"] == "有一条位置更新。"
    assert "三里屯" not in _dumped(out)


def test_a_point_without_a_note_does_not_get_one_invented():
    assert filter_checkpoint(_grant("city"), _checkpoint(note=""))["note"] == ""


def test_the_off_grade_drops_the_point_entirely():
    assert filter_checkpoint(_grant("off"), _checkpoint()) is None


# ----------------------------------------------------------------- 守护告警


def test_an_alert_survives_the_location_being_off_because_the_fact_matters():
    """位置关了也要给"有异常"这件事，只是不给在哪。

    刻意的取舍：把告警本身也藏掉，守护功能就等于没有；
    而"有异常"不含位置信息，不构成越级。
    """
    alert = {**_checkpoint(), "purpose": "去北京看骨科"}
    out = filter_alert(_grant("off"), alert)

    assert out is not None
    assert out["location"] == MASKED
    assert "lng" not in out and "lat" not in out, "键都不留，不是留个 None"
    assert out["precision"] == "off"
    assert out["status"] == "off_route" and out["purpose"] == "去北京看骨科"
    assert "三里屯" not in _dumped(out)


def test_an_unbound_child_gets_no_alert_at_all():
    """位置关了还给"有异常"；关系没了连这个都不给 —— 两层严厉程度不同。"""
    assert filter_alert(_grant("off", bound=False), _checkpoint()) is None
    assert filter_alert(denied("e-1", "c-1"), _checkpoint()) is None


def test_a_bound_alert_at_city_grade_takes_the_same_coarsening_path():
    """告警不另写一套裁剪逻辑，直接走位置那条 —— 少一份实现就少一处走样。"""
    out = filter_alert(_grant("city"), _checkpoint())

    assert out["precision"] == "city"
    assert out["lng"] is None
    assert out["location"] == "北京市朝阳区"
    assert out["note"] == _CITY_NOTE["off_route"]


# ------------------------------------------------------------------- 健康数据


def test_the_full_health_grade_hands_over_the_drug_name():
    med = _medication()
    out = filter_medication(_grant(health="full"), med)
    assert out == med and out is not med


def test_the_summary_grade_keeps_whether_she_took_it_and_hides_what_it_was():
    """子女最需要的是"我妈今天按时吃药了吗"，药名才是敏感的那一半。"""
    out = filter_medication(_grant(health="summary"), _medication())

    assert out["drug"] == MASKED and out["dose"] == ""
    assert out["times"] == ["08:00", "20:00"]
    assert out["taken_today"] == {"08:00": "taken", "20:00": "pending"}
    assert out["precision"] == "summary"
    assert "氨基葡萄糖" not in _dumped(out)


def test_the_summary_grade_copies_the_nested_values_it_hands_out():
    """出库的是副本：上层怎么改都改不到库里的事实（只出不进）。"""
    med = _medication()
    out = filter_medication(_grant(health="summary"), med)

    out["times"].append("12:00")
    out["taken_today"]["08:00"] = "missed"

    assert med["times"] == ["08:00", "20:00"]
    assert med["taken_today"]["08:00"] == "taken"


def test_a_medication_row_with_nothing_logged_yet_still_renders_at_summary():
    """今天还没到点、一条服药记录都没有 —— 该显示"待服"，不是崩掉。"""
    out = filter_medication(_grant(health="summary"),
                            _medication(taken_today=None, times=None))
    assert out["times"] == [] and out["taken_today"] == {}


def test_the_off_health_grade_drops_the_entry():
    assert filter_medication(_grant(health="off"), _medication()) is None


def test_a_report_reading_is_full_grade_only():
    """体检解读**原文**只有 full 档能看；summary 只知道"有这么一份"。"""
    text = "血脂偏高一点，医生建议少油少盐，三个月后复查。"

    assert filter_health_text(_grant(health="full"), text) == text
    summary = filter_health_text(_grant(health="summary"), text)
    assert summary == "老人有一份体检解读记录，具体内容未开放。"
    assert "血脂" not in summary, "连指标名都不给 —— 那本身就是健康信息"
    assert filter_health_text(_grant(health="off"), text) == ""


# --------------------------------------------------------------------- 审计


async def test_the_audit_row_records_the_grade_it_was_read_under(ctx, elder, child):
    """老人端"谁看过我"要用它：谁、读了哪一块、当时是哪一档。"""
    grant = await ctx.privacy.grant_for(elder["id"], child["id"])
    await ctx.privacy.audit(grant, "child_dashboard")

    rows = await ctx.repos.list("audit_log", where={"action": "privacy_read"})
    assert len(rows) == 1
    assert rows[0]["actor_id"] == child["id"]
    assert rows[0]["target"] == elder["id"]
    assert rows[0]["detail"] == {"scope": "child_dashboard",
                                 "location_level": "realtime",
                                 "health_level": "summary", "bound": True}


async def test_an_audit_failure_never_blanks_the_child_screen(caplog):
    """审计写不进去是运维问题，不该变成子女端白屏 —— 咽掉，但留一条日志。"""
    service = PrivacyService(_BrokenRepo())

    with caplog.at_level(logging.WARNING, logger="app.safety.privacy"):
        await service.audit(_grant(), "child_dashboard")

    assert any("审计写入失败" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- 实地验收


async def test_the_guardian_note_carries_the_address_until_the_filter_takes_it(
        ctx, elder, child):
    """让守护逻辑真跑一遍：备注里**确实**有门牌号，city 档之后**确实**没了。

    这条不是上面纯函数测试的重复 —— 它证明那些断言防的不是假想敌：
    ``process_checkpoint`` 自己拼出来的备注就是"位置偏离规划路线：XX，请关注"。
    """
    trip = await ctx.repos.insert("trips", {
        "elder_id": elder["id"], "purpose": "去北京看骨科", "status": "planned"})

    result = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="北京市朝阳区三里屯太古里", lng=116.455, lat=39.937))
    raw = result["checkpoint"]

    assert result["status"] == "off_route" and result["alert_sent"] is True
    assert "三里屯太古里" in raw["note"], "防线防的是真实存在的泄漏"

    # 种子数据是最细档：这一档本来就该看得见，否则守护功能名存实亡
    grant = await ctx.privacy.grant_for(elder["id"], child["id"])
    assert grant.location_level == "realtime"
    assert "三里屯太古里" in _dumped(filter_checkpoint(grant, raw))

    # 老人把开关调到"只给城市"之后
    city = PrivacyGrant(elder_id=elder["id"], child_id=child["id"],
                        location_level="city", health_level="summary")
    graded = filter_checkpoint(city, raw)
    assert graded["location"] == "北京市朝阳区"
    assert graded["lng"] is None and graded["lat"] is None
    assert "三里屯" not in _dumped(graded)

    # 只出不进：裁的是出库那一份，库里始终是全量事实（调回去照样看得见）
    stored = await ctx.repos.get("trip_checkpoints", raw["id"])
    assert stored["lng"] == 116.455
    assert "三里屯太古里" in stored["note"]
