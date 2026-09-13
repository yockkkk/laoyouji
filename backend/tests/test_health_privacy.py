"""红线 R6：/api/health 的越级防线。**这个文件是给那道闸门留的牙印。**

它挡的是一件实测发生过的事：``GET /api/health/readings`` 与 ``/overview`` 原先
既无 principal 依赖、也无 grant 过滤 —— 不带任何 Authorization 头就返回 200，换一个
``elder_id`` 就能读到任意老人的原始指标。而**默认姿态就是漏的**：
``privacy_permissions`` 里没有那一对绑定行时，档位落到 ``DEFAULT_HEALTH_LEVEL``
（summary），可 overview 的 ``headline`` 直接拼着 driver.reason，实测返回
"血压 178/105，中重度偏高……" —— 子女端嘴上说"看不到血压/血糖的数"，
屏幕上却印着 178/105，而演示台上走的正是这个默认档。

所以这里的断言不写"接口返回 200"，写的是"**这份响应里一个数字都不许有**"：
整段 ``json.dumps`` 后逐字符扫数字。逐字段断言（比如只看 headline）会随字段增减
而失效，扫全文是那种"多想加一个字段就得先想清楚它带不带数"的写法。

**一个刻意的例外：紧急档 advice 里那个 120。** 它是急救电话，不是任何健康读数，
却是 ``isdigit()`` 分不出来的那种数字 —— 上一版用它当"是不是明细"的判据，把家属在
最需要动作指引的那一档上唯一那句"打 120"整句砍掉了。所以现在的判据是"是不是原样
出自 ``health_rules._ADVICE`` 那张按档位写死的固定表"（来源，不是形态），那张表本身
不含读数这件事由 ``test_every_fixed_advice_is_free_of_health_readings`` 逐句钉住。
凡是"扫全文找数字"的断言，都得配一句"读数数字不许有、120 要有"，见下面
``test_child_summary_emergency_keeps_the_call_120_line_but_not_the_reading``。
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.api import deps, routes_health
from app.auth.security import create_access_token
from app.main import create_app
from app.safety.health_rules import _ADVICE
from app.safety.privacy import PrivacyGrant, denied, filter_health_overview
from app.tools.health_tools import triage_overview

DIGITS = tuple("0123456789")

# 演示主角数：178/105 是"建议就医"，headline 里会带上 "178/105" 这串数字
BP_SEVERE = {"metric_type": "bp", "systolic": 178, "diastolic": 105}

# 急症区间的血压：190/115 顶到"紧急"，那一档的 advice 里带着急救电话 120
BP_EMERGENCY = {"metric_type": "bp", "systolic": 190, "diastolic": 115}

# "健康读数形态"的数字：血压的 178/105、血糖的 8.5、体温的 38.5℃、心率的 92 次/分……
# **裸的整数不算** —— ``_ADVICE["紧急"]`` 里那句"拨打 120"就是裸整数，120 是急救电话
# 不是读数。这正是 digit-scan 分不出来、于是误伤的地方：按形态判才判得对。
_READING_SHAPES = (
    re.compile(r"\d+\s*/\s*\d+"),                                    # 178/105 血压
    re.compile(r"\d+\.\d+"),                                         # 8.5 血糖
    re.compile(r"\d+\s*(?:mmHg|mmolL?|次/分|bpm|mg|kg|克|度|℃|°C|%|％)"),
)


def _has_digit(payload) -> bool:
    """整段响应里有没有数字。**用 json.dumps 扫全文**，不是逐字段看 —— 数字可能
    藏在 headline、reason、display、note 任何一个自由文本里，列举是一定漏的。"""
    raw = json.dumps(payload, ensure_ascii=False)
    return any(ch in DIGITS for ch in raw)


def _grant(level: str) -> PrivacyGrant:
    """纯函数层的输入：一对有绑定关系的（老人, 子女）+ 指定健康档。"""
    return PrivacyGrant(elder_id="elder-1", child_id="child-1", health_level=level)


@pytest.fixture()
async def api(ctx, monkeypatch):
    """**不带默认身份**：这个文件测的就是"谁在问"，身份由每条测试自己带。"""
    monkeypatch.setattr(routes_health, "get_ctx", lambda: ctx)
    # 认证依赖走 deps.get_ctx → 模块全局名 get_app_context()，补这里才引到 tmp ctx
    monkeypatch.setattr(deps, "get_app_context", lambda: ctx)
    return TestClient(create_app())     # 不用 with：不跑 lifespan


@pytest.fixture()
def login(ctx):
    def _login(user: dict) -> dict:
        return {"Authorization": f"Bearer {create_access_token(user, ctx.settings)}"}
    return _login


async def _set_health_level(ctx, elder_id: str, child_id: str, level: str) -> None:
    """把这一对的健康档改成 ``level``。先清掉旧行 —— 同一对留两行的话，查出来是哪
    一行就变成了靠 list 的顺序，测试会时绿时红。"""
    for row in await ctx.repos.list("privacy_permissions",
                                    where={"elder_id": elder_id, "child_id": child_id}):
        await ctx.repos.delete("privacy_permissions", row["id"])
    await ctx.repos.insert("privacy_permissions", {
        "elder_id": elder_id, "child_id": child_id,
        "location_level": "realtime", "health_level": level})


async def _drop_health_level(ctx, elder_id: str, child_id: str) -> None:
    """把授权行删掉 —— 恢复成"老人从没细调过"的**默认姿态**。"""
    for row in await ctx.repos.list("privacy_permissions",
                                    where={"elder_id": elder_id, "child_id": child_id}):
        await ctx.repos.delete("privacy_permissions", row["id"])


async def _unbound_child(ctx, name: str = "王某某") -> dict:
    """一个**没有 family_bindings** 的子女：身份成立，关系不成立。"""
    return await ctx.repos.insert("users", {
        "username": f"unbound_{name}", "role": "child", "name": name,
        "status": "active", "relation_to_elder": "侄子"})


# --------------------------------------------------------------- 默认档（summary）

async def test_child_summary_overview_has_the_level_and_not_a_single_digit(
        api, ctx, elder, child, login):
    """(a) 默认档（**不写 privacy_permissions 行**）下，子女读到的是档位而不是数值。

    这就是演示台上的姿态，也是原先漏得最狠的那一支：档位该给（"建议就医"这四个字
    是知会），读数不该给（178/105 是明细）。
    """
    await _drop_health_level(ctx, elder["id"], child["id"])     # 回到默认档
    api.post("/api/health/readings", json={"elder_id": elder["id"], **BP_SEVERE},
             headers=login(elder))

    res = api.get("/api/health/overview", params={"elder_id": elder["id"]},
                  headers=login(child))
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["level"] == "建议就医", "档位是子女该知道的那一半"
    assert not _has_digit(body), f"summary 档不许出现任何数字：{json.dumps(body, ensure_ascii=False)}"
    assert body["readings"] == [], "readings 每条 display 都是 '178/105 mmHg'"
    assert body["latest"] == {} and body["trends"] == {} and body["conditions"] == []
    assert all("reason" not in d for d in body["drivers"]), "driver.reason 里就是那个 178/105"
    assert not body["drivers"], "drivers 整个去空：label 也在说'是哪一类指标越的界'"


async def test_child_summary_readings_and_conditions_endpoints_give_nothing(
        api, ctx, elder, child, login):
    """summary 档下，两个明细接口也不许吐数据 —— 闸门在后端，不在前端藏。"""
    await _drop_health_level(ctx, elder["id"], child["id"])
    api.post("/api/health/readings", json={"elder_id": elder["id"], **BP_SEVERE},
             headers=login(elder))
    api.post("/api/health/conditions", json={"elder_id": elder["id"], "name": "原发性高血压"},
             headers=login(elder))

    headers = login(child)
    assert api.get("/api/health/readings", params={"elder_id": elder["id"]},
                   headers=headers).json()["items"] == []
    assert api.get("/api/health/conditions", params={"elder_id": elder["id"]},
                   headers=headers).json()["items"] == []


async def test_child_summary_emergency_keeps_the_call_120_line_but_not_the_reading(
        api, ctx, elder, child, login):
    """(a2) 紧急档：家属要拿到"打 120"这句，但那个 190/115 一个都不能出现。

    上一版 ``any(ch.isdigit() for ch in advice)`` 把 120 当成读数，advice 整句砍空 ——
    子女在最需要动作指引的那一档上只看到一句"具体是哪条指标把它抬上去的"。这一档的
    响应里**本来就有数字**（120），所以断言不能再用整段扫 digit 的粗判，得分开说：
    读数数字不许有、急救电话必须有。
    """
    await _drop_health_level(ctx, elder["id"], child["id"])     # 回到默认 summary 档
    api.post("/api/health/readings", json={"elder_id": elder["id"], **BP_EMERGENCY},
             headers=login(elder))

    body = api.get("/api/health/overview", params={"elder_id": elder["id"]},
                   headers=login(child)).json()

    assert body["level"] == "紧急"
    assert "120" in body["advice"], "家属在最需要动作指引的档位上看不到'打 120'"
    blob = json.dumps(body, ensure_ascii=False)
    for reading in ("190", "115", "178"):
        assert reading not in blob, f"summary 档不许出现读数：{blob}"


async def test_child_summary_of_an_elder_with_no_readings_is_not_reassurance(
        api, ctx, elder, child, login):
    """(a3) 一条读数都没记过的老人：不许报"保健"、不许说"各项指标平稳"。

    分诊引擎对空输入落"保健"（``overall = … if drivers else "保健"``，保健优先的
    兜底）；那个"保健"说的是"没有哪条读数越界"，**不是"一切平稳"**。照着它编一句
    宽心话，就是把"没数据"说成"没事" —— 方向错了不可逆，也是 privacy.py 里那条
    "不许编'各项正常'来填空"的同一条规矩。降级这一层要把"根本没数据"识别出来。
    """
    await _drop_health_level(ctx, elder["id"], child["id"])     # 默认 summary 档
    # ctx 的种子（seed_demo）不写 health_metrics，所以这位老人一条读数都没有
    assert await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]}) == []

    body = api.get("/api/health/overview", params={"elder_id": elder["id"]},
                   headers=login(child)).json()

    assert body["level"] == "", "没数据就不报档位 —— 别拿兜底的'保健'当结论"
    blob = json.dumps(body, ensure_ascii=False)
    assert "保健" not in blob and "平稳" not in blob, blob
    assert not _has_digit(body), blob
    assert "还没记过" in body["headline"], blob


# ---------------------------------------------------------------- full 档

async def test_child_full_grant_sees_the_numbers(api, ctx, elder, child, login):
    """(b) 显式开到 full 档就该看得见数 —— 降级是"按档裁剪"，不是"一律不给"。"""
    await _set_health_level(ctx, elder["id"], child["id"], "full")
    api.post("/api/health/readings", json={"elder_id": elder["id"], **BP_SEVERE},
             headers=login(elder))

    headers = login(child)
    o = api.get("/api/health/overview", params={"elder_id": elder["id"]},
                headers=headers).json()
    assert o["level"] == "建议就医"
    assert "178/105" in o["headline"]
    assert any("178/105" in d.get("reason", "") for d in o["drivers"])

    r = api.get("/api/health/readings", params={"elder_id": elder["id"]},
                headers=headers).json()
    bp = next(x for x in r["items"] if x["metric_type"] == "bp")
    assert bp["display"] == "178/105 mmHg"


# ---------------------------------------------------------------- 没有绑定关系

async def test_unbound_child_gets_nothing_and_no_reassurance(api, ctx, elder, login):
    """(c) 身份成立、关系不成立 → 什么都拿不到。

    而且**不许**得到一个"保健"之类的宽心话：把"没数据"说成"没事"，方向错了不可逆。
    子女端自己有中性文案（dashboard.vue 的 triageLevel 走"暂未算出"），后端别抢着编。
    """
    api.post("/api/health/readings", json={"elder_id": elder["id"], **BP_SEVERE},
             headers=login(elder))
    stranger = await _unbound_child(ctx)
    headers = login(stranger)

    o = api.get("/api/health/overview", params={"elder_id": elder["id"]},
                headers=headers)
    assert o.status_code == 200, "降级是数据变形不是报错 —— 不该给红叉"
    body = o.json()
    assert body["level"] == ""
    assert "保健" not in json.dumps(body, ensure_ascii=False)
    assert not _has_digit(body)
    assert api.get("/api/health/readings", params={"elder_id": elder["id"]},
                   headers=headers).json()["items"] == []
    assert api.get("/api/health/conditions", params={"elder_id": elder["id"]},
                   headers=headers).json()["items"] == []


async def test_a_non_family_role_is_403(api, ctx, elder, login):
    """不是本人、也不是子女 → 403。少一个字段那叫降级，没这层关系那叫没有权利。"""
    outsider = await ctx.repos.insert("users", {
        "username": "volunteer_zhou", "role": "volunteer", "name": "周志愿者",
        "status": "active"})
    headers = login(outsider)
    for path in ("/api/health/overview", "/api/health/readings", "/api/health/conditions"):
        res = api.get(path, params={"elder_id": elder["id"]}, headers=headers)
        assert res.status_code == 403, f"{path} → {res.status_code}"


# ---------------------------------------------------------------- 老人本人

async def test_the_elder_reads_their_own_data_in_full(api, ctx, elder, login):
    """(d) 本人读自己的 → 全量。老人端 pages/elder/health.vue 读的就是这几个接口，
    这条路砍了，老人自己的页面就空了。"""
    api.post("/api/health/readings", json={"elder_id": elder["id"], **BP_SEVERE},
             headers=login(elder))
    headers = login(elder)

    o = api.get("/api/health/overview", params={"elder_id": elder["id"]},
                headers=headers).json()
    assert o["level"] == "建议就医"
    assert "178/105" in o["headline"]
    assert o["readings"], "本人拿全量：readings/latest/trends/conditions 一个不少"
    assert o["latest"] and o["disclaimer"], "R4：下档位判断就要带免责声明"
    assert api.get("/api/health/readings", params={"elder_id": elder["id"]},
                   headers=headers).json()["items"]
    assert api.get("/api/health/conditions", params={"elder_id": elder["id"]},
                   headers=headers).status_code == 200


async def test_the_elder_cannot_read_another_elders_page(api, ctx, elder, login):
    """本人也不等于通行证：换一个 elder_id 就是 403（原先这里能读到别人的数）。"""
    other = await ctx.repos.insert("users", {
        "username": "other_elder", "role": "elder", "name": "李大爷", "status": "active"})
    res = api.get("/api/health/overview", params={"elder_id": other["id"]},
                  headers=login(elder))
    assert res.status_code == 403


# ---------------------------------------------------------------- 缺 token

async def test_no_authorization_header_is_401(api, elder):
    """(e) 不带 token → 401，由认证依赖自己抛。"""
    for path in ("/api/health/overview", "/api/health/readings", "/api/health/conditions"):
        res = api.get(path, params={"elder_id": elder["id"]})
        assert res.status_code == 401, f"{path} → {res.status_code}"
    for path in ("/api/health/readings", "/api/health/conditions"):
        res = api.post(path, json={"elder_id": elder["id"], "metric_type": "bp",
                                   "systolic": 178, "diastolic": 105})
        assert res.status_code == 401, f"POST {path} → {res.status_code}"


# ---------------------------------------------------------------- 写入口

async def test_writing_for_someone_else_is_403_and_writes_nothing(api, ctx, elder, child, login):
    """(f) 替别人写指标 → 403，且**对方库里没多出行**。

    写入口原先的 elder_id 是请求体里说了算的，任何人可以替任何老人写一条 ——
    越级不只是"能读"，"能往病历里写"更糟。
    """
    before = len(await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]}))
    res = api.post("/api/health/readings", json={"elder_id": elder["id"], **BP_SEVERE},
                   headers=login(child))
    assert res.status_code == 403, res.text
    after = len(await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]}))
    assert after == before, "403 与'库里没有'必须是同一件事"

    before_c = len(await ctx.repos.list("health_conditions", where={"elder_id": elder["id"]}))
    res = api.post("/api/health/conditions",
                   json={"elder_id": elder["id"], "name": "原发性高血压"},
                   headers=login(child))
    assert res.status_code == 403, res.text
    after_c = len(await ctx.repos.list("health_conditions", where={"elder_id": elder["id"]}))
    assert after_c == before_c


async def test_a_child_writing_their_own_id_is_allowed(api, ctx, child, login):
    """归属校验**看 id，不看 role**：role=child 的用户写自己的 elder_id 是允许的。
    写成"必须是 elder 角色"会把这条既有用法一起堵死。"""
    res = api.post("/api/health/conditions",
                   json={"elder_id": child["id"], "name": "2 型糖尿病"},
                   headers=login(child))
    assert res.status_code == 200, res.text


# ------------------------------------------- 纯函数层：档位与字段的对应关系

def _overview_sample() -> dict:
    return {
        "level": "建议就医",
        "advice": "建议这两天去医院看看。我可以帮您就近挂个号、规划好怎么去，并把情况一并告诉家里人。",
        "headline": "血压 178/105，中重度偏高，且最近持续走高。分诊结论：建议就医。",
        "drivers": [{"metric": "bp", "level": "建议就医",
                     "reason": "血压 178/105，中重度偏高，且最近持续走高", "label": "血压"}],
        "readings": [{"metric_type": "bp", "display": "178/105 mmHg", "level": "建议就医"}],
        "latest": {"bp": {"systolic": 178, "diastolic": 105}},
        "trends": {"bp": "上升"},
        "conditions": [{"name": "原发性高血压"}],
        "symptom": "",
    }


def test_pure_full_passes_every_field_through():
    grant = _grant("full")
    src = _overview_sample()
    assert filter_health_overview(grant, src) == src


def test_pure_summary_keeps_the_level_and_drops_every_number():
    grant = _grant("summary")
    out = filter_health_overview(grant, _overview_sample())
    assert out["level"] == "建议就医"
    assert not _has_digit(out), json.dumps(out, ensure_ascii=False)
    assert out["readings"] == [] and out["latest"] == {} and out["trends"] == {}
    assert out["conditions"] == [] and out["drivers"] == []


def test_pure_off_gives_empty_values_not_missing_keys():
    """off/denied：值空、**键在**。响应形状随档位变的话，前端就得为"这个键这次
    有没有"写分支，漏一个分支就是白屏。"""
    for grant in (denied("e", "c"),
                  _grant("off")):
        out = filter_health_overview(grant, _overview_sample())
        assert set(out) == set(_overview_sample()), "键集一个都不能少"
        assert out["level"] == "" and "保健" not in json.dumps(out, ensure_ascii=False)


def test_pure_advice_is_kept_only_when_it_comes_from_the_fixed_table():
    """advice 放行的判据是**来源**，不是"句子里有没有数字"。

    放行的前提：``_ADVICE`` 四句是按档位写死的通用句、不含读数（下一支逐句钉住）。
    落在外面的（比如哪天有人把 driver.reason 拼进来，那里面就是"血压 178/105"）
    一律不给 —— 这条路靠白名单堵，不靠扫数字。
    """
    grant = _grant("summary")
    kept = filter_health_overview(grant, _overview_sample())
    assert kept["advice"] == _ADVICE["建议就医"], "表里的原句要原样留着"
    assert kept["advice"]

    leaky = _overview_sample()
    leaky["advice"] = "血压 178/105 偏高，建议这两天去医院。"
    assert filter_health_overview(grant, leaky)["advice"] == "", \
        "不在固定表里的 advice 一律不给 —— 数字长在自由文本里，抠是抠不干净的"


def test_every_fixed_advice_is_free_of_health_readings():
    """summary 档"原样透出 advice"这个做法的地基：那张固定表里没有读数字样的数字。

    按**形态**判，不按"有没有数字"判：``_ADVICE["紧急"]`` 里那个 120 是急救电话，
    必须留着。哪天有人往表里塞进"血压 178/105""血糖 8.5"这种，这条会当场红。
    """
    assert _ADVICE, "表空了这条断言就成了空转"
    for level, text in _ADVICE.items():
        for shape in _READING_SHAPES:
            assert not shape.search(text), f"{level} 的建议里混进了读数字样：{text}"


def test_pure_emergency_advice_with_the_120_help_line_is_kept_verbatim():
    """回归：紧急档那句"拨打 120"必须原样透到子女端，不能被 digit-scan 误杀。

    120 是急救电话、不是读数 —— 判"是不是明细"该看**来源**，不该看有没有数字。
    """
    grant = _grant("summary")
    src = _overview_sample()
    src["level"] = "紧急"
    src["advice"] = _ADVICE["紧急"]

    out = filter_health_overview(grant, src)
    assert out["level"] == "紧急"
    assert out["advice"] == _ADVICE["紧急"]
    assert "120" in out["advice"]
    # 读数那部分照旧一个不留
    assert out["readings"] == [] and out["latest"] == {} and out["drivers"] == []


def test_pure_summary_of_an_elder_with_no_readings_does_not_say_all_steady():
    """一条读数都没有：不许报档位、不许说"平稳"。

    这里喂的是**分诊引擎的真实输出**（``triage_overview({}, [])``），不是手捏的样本
    —— 引擎对空输入落"保健"是既有的"保健优先"兜底，本轮不动它；要修的是降级这一层：
    别把这个兜底当结论端给子女。
    """
    src = triage_overview({}, [])                          # 零读数、零慢病、零症状
    assert src["level"] == "保健", "引擎的兜底没变，变的是降级层怎么解释它"
    out = filter_health_overview(_grant("summary"), src)

    assert out["level"] == "", "没数据就不报档位"
    blob = json.dumps(out, ensure_ascii=False)
    assert "保健" not in blob and "平稳" not in blob, blob
    assert not _has_digit(out), blob
    assert "还没记过" in out["headline"], blob
    assert set(out) == set(src), "键集不能少 —— 前端按固定形状读"


def test_pure_summary_of_a_stable_elder_still_says_all_steady():
    """边界另一侧：**有读数**、都在保健区间 —— 这时"平稳"才是句真话，照给。

    钉住"没数据"与"数据平稳"的分界，防止修上一支时把正常这一支也一并打空。
    """
    src = triage_overview(
        {"bp": [{"metric_type": "bp", "systolic": 128, "diastolic": 78}]}, [])
    assert src["level"] == "保健", src["level"]
    out = filter_health_overview(_grant("summary"), src)

    assert out["level"] == "保健"
    assert "平稳" in out["headline"]
    assert out["advice"] == _ADVICE["保健"], "有读数就该拿得到保健这一档的建议"
