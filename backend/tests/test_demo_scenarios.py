"""演示数据的可信度：四个剧本各自落在声明的档位上，每个数都经得起当场追问。

这组测试与别处不同的是 —— **断言里没有一个手写的阈值**，档位一律问 ``health_rules``
本身（``classify_reading`` / ``triage`` / ``trend``）。在这里写死一份 140/90 的后果是：
哪天阈值一调，测试还绿着，而演示现场的分诊结论已经跟剧本名对不上了 —— 测试开始说谎。
用户对演示数据的硬要求就一句："可以是假的，但得经得起答辩现场追问"。

三件事分别对应三组测试：
1. **四个档位都切得出来**：每个剧本的展示数真的落在自己那一档，库里最新一条就是它；
2. **不像机器生成的**：日期相对"今天"、测量时刻不整齐、三十天里偶尔整天漏测；
3. **数值站得住**：生理上可能（收缩压 > 舒张压、血氧不超 100%），且每条读数的档位
   与数值自洽（不会出现 178/105 却标着"保健"）。
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pytest

from app.db.seed import (SCENARIOS, SCENARIO_BY_LEVEL, _readings_for_day,
                         resolve_scenario, seed_kangle_persona)
from app.safety import health_rules as hr
from app.tools.health_tools import (_active_conditions, _grouped_history,
                                    triage_overview)

SCENARIO_NAMES = list(SCENARIOS)
ARCHIVE_DAYS = 30


async def _overview(repos, elder_id: str) -> dict:
    """把库里的数读回来跑真分诊 —— 和老人端、子女端看到的是同一段代码。"""
    grouped = await _grouped_history(repos, elder_id)
    conditions = await _active_conditions(repos, elder_id)
    return triage_overview(grouped, conditions)


async def _bp_rows(ctx, elder_id: str) -> list[dict]:
    return await ctx.repos.list("health_metrics",
                                where={"elder_id": elder_id, "metric_type": "bp"},
                                order="measured_at")


# ================================================================ 四个档位都切得出来

def test_every_triage_level_has_a_demo_scenario():
    """四个档位各有一个剧本，且展示数真的落在自己那一档 —— 少一个就有一档切不出来。"""
    assert set(SCENARIO_BY_LEVEL) == set(hr.LEVELS), \
        f"这些档位没有演示剧本：{set(hr.LEVELS) - set(SCENARIO_BY_LEVEL)}"
    for name, sc in SCENARIOS.items():
        systolic, diastolic = sc["bp_tail"][0]
        level, reason = hr.classify_reading("bp", systolic=systolic, diastolic=diastolic)
        assert level == sc["level"], \
            f"{name} 的展示数 {systolic}/{diastolic} 现在落「{level}」而不是「{sc['level']}」（{reason}）"


@pytest.mark.parametrize("name", SCENARIO_NAMES)
async def test_each_scenario_lands_on_its_declared_level(ctx, elder, name):
    """灌进去 → 读回来 → 分诊，档位必须是剧本声明的那一档。"""
    info = await seed_kangle_persona(ctx.repos, elder, scenario=name)
    overview = await _overview(ctx.repos, elder["id"])
    assert overview["level"] == SCENARIOS[name]["level"], overview["headline"]
    assert info["level"] == overview["level"], "播种时算的档位与读回来重算的不一致"
    assert overview["advice"], "档位必须带一句人话建议"
    if name == "hypertension_spike":
        # 主线 A 的两条硬要求：趋势要读得出"上升"，建议要落到"就近挂号"
        assert overview["trends"]["bp"] == "上升"
        assert "持续走高" in overview["drivers"][0]["reason"]
        assert "就近挂个号" in overview["advice"]


@pytest.mark.parametrize("name", SCENARIO_NAMES)
async def test_showcase_number_is_the_latest_reading(ctx, elder, name):
    """库里最新一条血压 = 剧本的展示数，且就发生在今天 —— 现场翻到最后一页看到的是同一个数。"""
    await seed_kangle_persona(ctx.repos, elder, scenario=name)
    rows = await ctx.repos.list("health_metrics",
                                where={"elder_id": elder["id"], "metric_type": "bp"},
                                order="-measured_at", limit=1)
    systolic, diastolic = SCENARIOS[name]["bp_tail"][0]
    assert (rows[0]["systolic"], rows[0]["diastolic"]) == (float(systolic), float(diastolic))
    assert rows[0]["measured_at"].startswith(date.today().isoformat()), \
        "展示数必须是今天的 —— 演示时时间线上它得在最上面"


def test_resolve_scenario_accepts_keys_levels_and_rejects_junk():
    """命令行切档：ASCII 的 key 和中文档位都认；认不出的必须报错，不许默默换一份档案。"""
    assert resolve_scenario("emergency") == "emergency"
    assert resolve_scenario("紧急") == "emergency"
    assert resolve_scenario("保健") == "stable"
    for junk in ("包治百病", "", "  "):
        with pytest.raises(ValueError):
            resolve_scenario(junk)


# ================================================================ 不像机器生成的

async def test_the_archive_is_relative_to_today(ctx, elder):
    """不注入 today 时，档案必须收在今天。

    这是"演示那天数据全是几个月前的、一眼露馅"的正面防线：日期全部相对生成，
    注入只在测试和可复现性上使用。
    """
    await seed_kangle_persona(ctx.repos, elder, scenario="hypertension_spike",
                              days=ARCHIVE_DAYS)
    rows = await _bp_rows(ctx, elder["id"])
    assert rows[-1]["measured_at"].startswith(date.today().isoformat())
    oldest = date.today() - timedelta(days=ARCHIVE_DAYS - 1)
    assert rows[0]["measured_at"].startswith(oldest.isoformat())


async def test_measurement_times_look_human(ctx, elder):
    """测量时刻得散开：清一色 08:00 是"一眼假"的头号特征。"""
    await seed_kangle_persona(ctx.repos, elder, days=ARCHIVE_DAYS)
    rows = await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]})
    clocks = Counter(r["measured_at"][11:] for r in rows)
    assert len(clocks) >= 8, f"测量时刻只有这几种：{sorted(clocks)}"
    top, count = clocks.most_common(1)[0]
    assert count / len(rows) < 0.25, f"{top} 一个时刻占了 {count}/{len(rows)} 条"

    assert all("06:30" <= c <= "21:00" for c in clocks), \
        f"半夜或凌晨的测量不像真的：{[c for c in clocks if not '06:30' <= c <= '21:00']}"
    today = sorted(r["measured_at"][11:] for r in rows
                   if r["measured_at"].startswith(date.today().isoformat()))
    assert today, "今天得有读数（演示要看的就是今天的）"
    assert all(c < "08:00" for c in today), f"演示当天不该出现晚上的读数：{today}"


async def test_the_archive_occasionally_skips_a_whole_day(ctx, elder):
    """三十天里得有整天没量的：老人不是机器，天天一秒不差地量反而假。"""
    await seed_kangle_persona(ctx.repos, elder, days=ARCHIVE_DAYS)
    rows = await _bp_rows(ctx, elder["id"])
    measured = {r["measured_at"][:10] for r in rows}
    span = {(date.today() - timedelta(days=o)).isoformat() for o in range(ARCHIVE_DAYS)}
    missed = sorted(span - measured)
    assert missed, "30 天一天不缺，那份档案是机器产的"
    assert len(missed) <= ARCHIVE_DAYS // 8, f"缺得太多就不像档案了：{missed}"


# ================================================================ 数值站得住

@pytest.mark.parametrize("name", SCENARIO_NAMES)
async def test_readings_are_physiologically_possible_and_self_consistent(ctx, elder, name):
    """生理上可能，且档位与数值自洽 —— 不允许"178/105 却标着保健"这种行落库。"""
    await seed_kangle_persona(ctx.repos, elder, scenario=name)
    rows = await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]})
    assert rows, "档案不能是空的"
    for r in rows:
        mtype = r["metric_type"]
        if mtype == "bp":
            assert r["systolic"] > r["diastolic"], f"收缩压不高于舒张压：{r}"
        elif mtype == "glucose":
            assert 2 < r["value"] <= 25, r
        elif mtype == "heart_rate":
            assert 30 <= r["value"] <= 160, r
        elif mtype == "spo2":
            assert 60 <= r["value"] <= 100, r
        elif mtype == "temperature":
            assert 34 <= r["value"] <= 41, r
        elif mtype == "weight":
            assert 40 <= r["value"] <= 100, r
        else:
            pytest.fail(f"库里出现了没见过的指标：{mtype}")

        level, _ = hr.classify_reading(mtype, value=r.get("value"),
                                       systolic=r.get("systolic"),
                                       diastolic=r.get("diastolic"),
                                       context=r.get("context"))
        assert level == r["level"], f"这一行数与档位对不上：{r}"


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_no_reading_in_the_archive_exceeds_the_declared_level(name):
    """整份档案（不只是最后一天）都不许冒出比剧本更重的档。

    只看最后一条是不够的：中间某天蹦出一个"紧急"，演示时翻历史会翻出矛盾。
    这条不需要建库 —— 数据对不对取决于数本身，不取决于存储。
    """
    sc = SCENARIOS[name]
    top = hr.level_rank(sc["level"])
    today = date(2026, 9, 12)
    for offset in range(ARCHIVE_DAYS - 1, -1, -1):
        day = today - timedelta(days=offset)
        for row in _readings_for_day(sc, "zhangguifang", day, offset):
            assert hr.level_rank(row["level"]) <= top, \
                f"{name} 的 {day} 冒出了更重的一行：{row}"
