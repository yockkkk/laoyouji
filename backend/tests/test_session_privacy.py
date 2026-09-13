"""红线 R6：健康数据与对话内容剩下的几条**匿名出口**的牙印。

这些口子是终检时真发请求量出来的，四条串成一条**零凭证链**：

1. ``GET /api/demo/family`` —— 公开（登录页要它渲染演示卡片），原先"整行抄一遍、
   只剔 password_hash"，于是把 ``phone`` 一起挂了出去，还顺手给出 elder_id/child_id；
2. ``GET /api/chat/sessions?user_id=<任意 id>`` —— 不带头就 200 返回那个人的**全部
   会话**，每行带 ``title`` 与 ``last_text``（实测就是"我血压 178/105，"）；
3. ``GET /api/sessions/{id}`` 与 ``/events`` —— **完全无鉴权**，events 里原样是老人
   那句"我血压 178/105，胸口有点闷"，``/events`` 还连 tool_call/tool_result 里的
   医院、路线、剂量一起给；
4. ``/api/medications`` 四条 —— 无鉴权、无 grant、无 audit，无头就能读任意老人的
   药名剂量，还能真替别人入库/停用。

单看每一条都"勉强"，合起来是全量健康数据外泄。所以这里钉的不是"接口返回 401"，
而是**整段响应 json.dumps 后搜**：换别人的 id、或者干脆不打头，响应里不许出现
血压读数、精确地址、药名、手机号。逐字段断言会随字段增减失效，扫全文是那种
"多想加一个字段就得先想清楚它带不带"的写法。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api import deps, routes_health, routes_misc
from app.auth.security import create_access_token
from app.core.events import TOOL_CALL, TOOL_RESULT, USER_MESSAGE
from app.main import create_app
from app.safety.privacy import MASKED

# 老人真说过的那句话，以及会话里那条工具结果带的医院与门牌号。
HEALTH_TEXT = "我血压 178/105，胸口有点闷"
HOSPITAL_NAME = "南京市第一医院"
HOSPITAL_ADDRESS = "南京市秦淮区长乐路68号"
PHONE = "13800000001"

# 整段响应里**一个都不许出现**的东西：血压读数、精确地址、手机号。
FORBIDDEN_LEAKS = ("178/105", "长乐路", "秦淮区", PHONE)

# 种子数据里的两味药（张桂芳的用药方案）。summary 档不许出现任何一个。
SEED_DRUGS = ("硫酸氨基葡萄糖胶囊", "钙片")


def _dumped(payload) -> str:
    """把响应摊平成字符串 —— 断言"某个字眼一个角落都没剩下"。"""
    return json.dumps(payload, ensure_ascii=False)


def _leaks(raw: str) -> list[str]:
    return [needle for needle in FORBIDDEN_LEAKS if needle in raw]


@pytest.fixture()
def api(ctx, monkeypatch):
    """**不带默认身份**：本文件测的就是"谁在问"，身份由每条测试自己带。

    ``get_ctx`` 的补丁分两处下：路由体里直接调的是各自模块名下的那个符号；
    而 ``Depends(get_ctx)`` / 认证依赖走的是 ``deps.get_app_context``。
    少补一处，那条路径就会去打真库。
    """
    for mod in (routes_misc, routes_health):
        monkeypatch.setattr(mod, "get_ctx", lambda: ctx)
    monkeypatch.setattr(deps, "get_app_context", lambda: ctx)
    return TestClient(create_app())     # 不用 with：不跑 lifespan


@pytest.fixture()
def login(ctx):
    def _login(user: dict) -> dict:
        return {"Authorization": f"Bearer {create_access_token(user, ctx.settings)}"}
    return _login


async def _elder_session_with_health(ctx, elder) -> str:
    """造一段**真有过健康内容**的会话：老人的原话 + 一条带医院地址的工具结果。

    直接调 ``event_log`` 而不是跑整轮智能体：要的是"会话里确实躺着这些东西"，
    这是断言"别人读到的响应里没有它"的前提。
    """
    session = await ctx.event_log.create_session(elder["id"], HEALTH_TEXT[:12])
    sid = session["id"]
    ctx.event_log.append(sid, elder["id"], USER_MESSAGE, {"text": HEALTH_TEXT})
    ctx.event_log.append(
        sid, elder["id"], TOOL_CALL,
        {"call_id": "c1", "tool": "search_hospitals", "agent": "health",
         "args": {"city": "南京"}},
        agent_id="health")
    ctx.event_log.append(
        sid, elder["id"], TOOL_RESULT,
        {"call_id": "c1", "tool": "search_hospitals", "agent": "health", "ok": True,
         "data": {"items": [{"name": HOSPITAL_NAME,
                             "address": HOSPITAL_ADDRESS}]}},
        agent_id="health")
    return sid


async def _other_elder(ctx, name: str = "李大爷") -> dict:
    return await ctx.repos.insert("users", {
        "username": f"other_{name}", "role": "elder", "name": name,
        "status": "active", "phone": "13700000009", "city": "南京"})


async def _set_health_level(ctx, elder_id: str, child_id: str, level: str) -> None:
    """把这一对的健康档改成 ``level``（先清旧行，免得留两行靠 list 顺序）。"""
    for row in await ctx.repos.list("privacy_permissions",
                                    where={"elder_id": elder_id, "child_id": child_id}):
        await ctx.repos.delete("privacy_permissions", row["id"])
    await ctx.repos.insert("privacy_permissions", {
        "elder_id": elder_id, "child_id": child_id,
        "location_level": "realtime", "health_level": level})


# ---------------------------------------------------------------- ①会话读取面：无头 401

async def test_session_routes_are_401_without_any_token(api, ctx, elder):
    """不带任何 Authorization 头 → 401。原先这两条是 200，且原样吐对话全文。"""
    sid = await _elder_session_with_health(ctx, elder)
    for path in (f"/api/sessions/{sid}", f"/api/sessions/{sid}/events"):
        res = api.get(path)
        assert res.status_code == 401, f"{path} → {res.status_code}：{res.text}"
        assert not _leaks(res.text), f"{path} 401 的响应体里还带着敏感内容：{res.text}"


async def test_chat_sessions_is_401_without_a_token(api, ctx, elder):
    """``?user_id=<任意 id>`` 这条旁路关掉：无头 → 401，不再替他端数据。"""
    await _elder_session_with_health(ctx, elder)
    res = api.get("/api/chat/sessions", params={"user_id": elder["id"]})
    assert res.status_code == 401, res.text
    assert "我血压" not in res.text and elder["id"] not in res.text


async def test_the_owner_still_reads_their_own_session(api, ctx, elder, login):
    """别为了关闸把本人一起关掉：老人端断线轮询拉的就是这条。"""
    sid = await _elder_session_with_health(ctx, elder)
    headers = login(elder)

    detail = api.get(f"/api/sessions/{sid}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["events"], "主人应该拿到自己的事件"

    events = api.get(f"/api/sessions/{sid}/events", headers=headers)
    assert events.status_code == 200, events.text
    assert events.json()["items"], "断线轮询要有东西可拉"


# ------------------------------------------------- ②别人的会话：拿不到，且一个字段都不漏

async def test_a_stranger_cannot_read_the_elder_session(api, ctx, elder, child, login):
    """绑定子女也不行：会话是老人**私域**，不是"家属能看"的那一类。

    给 404 不给 403 —— 403 等于确认"这个会话存在，只是不归你"。
    """
    sid = await _elder_session_with_health(ctx, elder)
    headers = login(child)

    for path in (f"/api/sessions/{sid}", f"/api/sessions/{sid}/events"):
        res = api.get(path, headers=headers)
        assert res.status_code == 404, f"{path} → {res.status_code}：{res.text}"
        assert not _leaks(res.text), f"{path} 的响应里漏了东西：{res.text}"


async def test_another_elder_cannot_read_it_either(api, ctx, elder, login):
    """同样带 elder 角色的另一个老人也不行（少一个字段叫降级，没这层关系叫没权利）。"""
    sid = await _elder_session_with_health(ctx, elder)
    other = await _other_elder(ctx)

    res = api.get(f"/api/sessions/{sid}", headers=login(other))
    assert res.status_code == 404, res.text
    assert not _leaks(res.text), res.text


async def test_a_vanished_session_still_404s_for_its_owner(api, elder, login):
    """别把"不存在"和"不是你的"搅在一起后连正常的 404 都丢了（前端靠它自愈）。"""
    gone = "8f14e45f-ceea-467a-9c1e-000000000000"
    res = api.get(f"/api/sessions/{gone}", headers=login(elder))
    assert res.status_code == 404, res.text


# ------------------------------------------------------- ③会话列表：只认 token，不认参数

async def test_chat_sessions_will_not_take_someone_elses_user_id(api, ctx, elder, child, login):
    """拿自己的 token 去要别人的会话 → 403；无头 → 401。"""
    await _elder_session_with_health(ctx, elder)

    as_attacker = api.get("/api/chat/sessions", params={"user_id": elder["id"]},
                          headers=login(child))
    assert as_attacker.status_code == 403, as_attacker.text
    assert "我血压" not in as_attacker.text

    assert api.get("/api/chat/sessions",
                   params={"user_id": elder["id"]}).status_code == 401


async def test_chat_sessions_returns_only_the_callers_own(api, ctx, elder, child, login):
    """有 token 的本人照常拿自己的列表 —— 前端 ``chat.vue`` 就带着 ``?user_id``。"""
    await _elder_session_with_health(ctx, elder)

    own = api.get("/api/chat/sessions", params={"user_id": elder["id"]},
                  headers=login(elder))
    assert own.status_code == 200, own.text
    assert own.json()["items"], "本人的会话列表不该是空的"

    other = api.get("/api/chat/sessions", headers=login(child))
    assert other.status_code == 200, other.text
    assert other.json()["items"] == [], "别人的列表里不许出现老人的会话"


# ------------------------------------------------ ④演示家庭：公开到"几个字段"为止

async def test_demo_family_stays_public_but_never_carries_a_phone(api, ctx, elder):
    """登录页要靠它渲染卡片 → 必须公开；公开的口子到 id/username/name/role 为止。

    黑名单（"整行减 password_hash"）的毛病是以后加一列敏感字段就默认漏，所以
    这里断言的是**白名单键集**加"全文无手机号"。
    """
    res = api.get("/api/demo/family")
    assert res.status_code == 200, "登录页还没登录就要读它，加鉴权等于登录页打不开"
    body = res.json()
    assert body["elders"] and body["children"], "演示卡片要有内容"

    allowed = {"id", "username", "name", "role"}
    for row in body["elders"] + body["children"]:
        assert set(row) <= allowed, f"多给了字段：{set(row) - allowed}"
    assert "13800000001" not in _dumped(body), "手机号就是这条口子原先漏出去的那一半"
    assert "13900000002" not in _dumped(body)


# --------------------------------------------------- ⑤用药：无头 401 / 子女按档裁剪

async def test_medications_are_401_without_a_token(api, ctx, elder):
    """四条用药路由全要身份 —— 无头一律 401，不再 200 直出药名。"""
    plans = await ctx.repos.list("medication_plans", where={"elder_id": elder["id"]})
    plan_id = plans[0]["id"]

    assert api.get("/api/medications",
                   params={"elder_id": elder["id"]}).status_code == 401
    assert api.post("/api/medications", json={
        "elder_id": elder["id"], "drug_name": "钙片", "times": ["09:00"],
    }).status_code == 401
    assert api.delete(f"/api/medications/{plan_id}").status_code == 401
    assert api.post(f"/api/medications/{plan_id}/taken").status_code == 401


async def test_a_child_sees_the_schedule_but_not_the_drug_name(api, ctx, elder, child, login):
    """种子档位是 summary：子女该拿到"今天吃了没"，拿不到药名。

    降级发生在**后端出库那一刻** —— 前端没机会看到药名，也就没机会藏不住。
    """
    await _set_health_level(ctx, elder["id"], child["id"], "summary")
    res = api.get("/api/medications", params={"elder_id": elder["id"]},
                  headers=login(child))
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert items, "有绑定关系的子女该看到条目（降级不是空手而归）"
    for item in items:
        assert item["drug"] == MASKED, f"summary 档给药名就是越级：{item}"
        assert item["dose"] == ""
        assert "taken_today" in item, "该给的那一半（吃了没）要留着"
    raw = _dumped(res.json())
    for drug in SEED_DRUGS:
        assert drug not in raw, f"药名漏出去了：{drug}"


async def test_a_full_grant_child_sees_the_drug_name(api, ctx, elder, child, login):
    """显式开到 full 就该看得见药名 —— 按档裁剪，不是一律不给。"""
    await _set_health_level(ctx, elder["id"], child["id"], "full")
    res = api.get("/api/medications", params={"elder_id": elder["id"]},
                  headers=login(child))
    assert res.status_code == 200, res.text
    drugs = [item["drug"] for item in res.json()["items"]]
    assert any(d in SEED_DRUGS for d in drugs), drugs


async def test_an_unbound_child_gets_nothing_and_an_outsider_is_403(
        api, ctx, elder, child, login):
    """没绑定的子女 → 空列表（降级不是红叉）；不是子女角色 → 403（根本没这层关系）。"""
    binding = await ctx.repos.find_one(
        "family_bindings", {"elder_id": elder["id"], "child_id": child["id"]})
    await ctx.repos.delete("family_bindings", binding["id"])

    res = api.get("/api/medications", params={"elder_id": elder["id"]},
                  headers=login(child))
    assert res.status_code == 200, "降级是数据变形不是报错"
    assert res.json()["items"] == []
    assert not any(d in _dumped(res.json()) for d in SEED_DRUGS)

    other = await _other_elder(ctx)
    assert api.get("/api/medications", params={"elder_id": elder["id"]},
                   headers=login(other)).status_code == 403


async def test_the_elder_reads_their_own_medications_in_full(api, ctx, elder, login):
    """本人全量：老人端"我的用药"读的就是它，一个字段都不许被裁掉。"""
    res = api.get("/api/medications", params={"elder_id": elder["id"]},
                  headers=login(elder))
    assert res.status_code == 200, res.text
    names = [item.get("drug_name") for item in res.json()["items"]]
    assert any(n in SEED_DRUGS for n in names), names


# ------------------------------------------------------- ⑥写入口：替别人写必须失败

async def test_writing_medication_for_someone_else_is_403_and_writes_nothing(
        api, ctx, elder, child, login):
    """替别人建方案 → 403，且**对方库里行数一条不变**（连 before/after 一起看）。"""
    before = len(await ctx.repos.list("medication_plans",
                                      where={"elder_id": elder["id"]}))
    res = api.post("/api/medications", json={
        "elder_id": elder["id"], "drug_name": "不该出现的药", "times": ["09:00"]},
        headers=login(child))
    assert res.status_code == 403, res.text

    after = len(await ctx.repos.list("medication_plans",
                                     where={"elder_id": elder["id"]}))
    assert (before, after) == (before, before), \
        f"403 与'库里没多出行'必须是同一件事：{before} → {after}"


async def test_stopping_someone_elses_medication_is_403_and_leaves_it_active(
        api, ctx, elder, child, login):
    """停别人的药 = 改变他吃不吃，比读药名更重：403，且那条计划仍是 active。"""
    plans = await ctx.repos.list("medication_plans",
                                 where={"elder_id": elder["id"], "active": True})
    plan_id = plans[0]["id"]

    res = api.delete(f"/api/medications/{plan_id}", headers=login(child))
    assert res.status_code == 403, res.text

    still = await ctx.repos.get("medication_plans", plan_id)
    assert still["active"] is True, "403 之后那条计划不该被停用"


async def test_marking_someone_elses_medication_taken_is_403_and_logs_nothing(
        api, ctx, elder, child, login):
    """替别人打卡 = 伪造他的服药记录：403，且 medication_logs 行数不变。"""
    plans = await ctx.repos.list("medication_plans", where={"elder_id": elder["id"]})
    plan_id = plans[0]["id"]

    before = len(await ctx.repos.list("medication_logs", where={"plan_id": plan_id}))
    res = api.post(f"/api/medications/{plan_id}/taken", headers=login(child))
    assert res.status_code == 403, res.text

    after = len(await ctx.repos.list("medication_logs", where={"plan_id": plan_id}))
    assert after == before, f"403 之后不该多出一条服药记录：{before} → {after}"
