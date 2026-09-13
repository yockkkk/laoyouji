"""康乐左翼·身体核心的 REST 层：/api/health 的指标/概览/慢病。

这一层**自己不写分诊**（判断全在 ``app/safety/health_rules``），它存在的意义是让
"手机上点一下记血压"和"跟康乐说一句血压 178/105"落在同一段代码上。所以这里测的
重点不是"接口能返回 200"，而是两条入口**同源**：

- 记的数与聊天的 ``log_vital`` 落进同一个库、同一档位；
- 概览的 readings 与聊天的 ``get_health_summary`` 口径一致（display 一字不差）；
- 失败（血压缺一半、指标不认识）映射成 4xx，而不是"200 + 一条没入库的记录"。

测试用一个 AsyncClient 之外的取巧：TestClient **不进上下文管理器**就不跑 lifespan，
于是不会构建全局 AppContext、不碰真实 data 目录；再把路由里的 ``get_ctx`` 换成夹具里
那个 tmp_path 上的 ctx，读写都落在临时目录里。

**身份**：/api/health 的读写都要 Bearer 头（本文件里每条测试说的都是"老人自己记自己
的数"），所以夹具默认就带上老人的 token —— 测试体不必逐条写 headers，断言强度不变。
要换身份的测试自己传 ``headers=bearer(child)``（同名的键会覆盖掉默认头）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import deps, routes_health
from app.auth.security import create_access_token
from app.core.context import TurnContext
from app.main import create_app


def _auth_header(ctx, user: dict) -> dict:
    """给某个用户签一个 Bearer 头。夹具与测试体共用这一段，别各写一遍。"""
    return {"Authorization": f"Bearer {create_access_token(user, ctx.settings)}"}


@pytest.fixture()
def bearer(ctx):
    """按用户签一个 Bearer 头。每条测试自己选 elder / child 身份。"""
    def _bearer(user: dict) -> dict:
        return _auth_header(ctx, user)
    return _bearer


@pytest.fixture()
async def client(ctx, elder, monkeypatch):
    # 路由体里是 `ctx = get_ctx()`（模块全局名），补丁打在 routes_health 上最稳。
    # 打在 deps 上没用 —— 导入时名字已经被绑进这个模块了。
    monkeypatch.setattr(routes_health, "get_ctx", lambda: ctx)
    # 认证那条依赖是 deps.get_current_principal，它自己走 `Depends(get_ctx)`，
    # 而 deps.get_ctx 调的是**模块全局名** get_app_context()。补在这里，token
    # 解析（查 users 表）就引到同一个 tmp 夹具的 ctx 上，而不是去 build 真上下文。
    monkeypatch.setattr(deps, "get_app_context", lambda: ctx)
    # 默认身份是老人本人：本文件多数测试说的都是"老人自己记自己的数"。
    return TestClient(create_app(), headers=_auth_header(ctx, elder))


# ---------------------------------------------------------------- 记录 → 分诊

async def test_bp_178_105_reaches_see_doctor(client, elder):
    """演示主角数：REST 记下来的 178/105，概览必须落"建议就医"。"""
    r = client.post("/api/health/readings", json={
        "elder_id": elder["id"], "metric_type": "bp",
        "systolic": 178, "diastolic": 105})
    assert r.status_code == 200, r.text
    assert r.json()["level"] == "建议就医"
    assert r.json()["display"] == "178/105 mmHg", "格式跟聊天那边一套"

    o = client.get("/api/health/overview", params={"elder_id": elder["id"]}).json()
    assert o["level"] == "建议就医"
    assert o["disclaimer"], "R4：概览会下档位判断，必须带免责声明"


async def test_bp_138_86_stays_health_care(client, elder):
    """**保健优先**在 REST 这条路上同样成立：老人常态不许撵去医院。"""
    client.post("/api/health/readings", json={
        "elder_id": elder["id"], "metric_type": "bp",
        "systolic": 138, "diastolic": 86})
    o = client.get("/api/health/overview", params={"elder_id": elder["id"]}).json()
    assert o["level"] == "保健"
    assert "不用特意往医院跑" in o["advice"]


async def test_reading_carries_the_disclaimer(client, elder):
    """R4：报档位就是在对老人的身体下判断，回执上必须带声明。"""
    r = client.post("/api/health/readings", json={
        "elder_id": elder["id"], "metric_type": "glucose",
        "value": 6.5, "context": "空腹"})
    assert r.status_code == 200
    assert "遵医嘱" in r.json()["disclaimer"]


async def test_emergency_reading_is_not_softened_by_the_health_care_bias(client, elder):
    client.post("/api/health/readings", json={
        "elder_id": elder["id"], "metric_type": "bp",
        "systolic": 190, "diastolic": 115})
    o = client.get("/api/health/overview", params={"elder_id": elder["id"]}).json()
    assert o["level"] == "紧急"
    assert "120" in o["advice"]


# ---------------------------------------------------------------- 乱填 → 4xx

async def test_half_a_blood_pressure_is_4xx_not_200(client, elder):
    """没记上就是没记上。返回 200 会让前端把一条空记录当成功弹给老人看。"""
    r = client.post("/api/health/readings", json={
        "elder_id": elder["id"], "metric_type": "bp", "systolic": 170})
    assert 400 <= r.status_code < 500, r.text
    # 而且真的没落库 —— 4xx 与"库里没有"必须是同一件事
    o = client.get("/api/health/overview", params={"elder_id": elder["id"]}).json()
    assert o["readings"] == []


async def test_a_completely_empty_reading_is_4xx(client, elder):
    r = client.post("/api/health/readings", json={
        "elder_id": elder["id"], "metric_type": "glucose"})
    assert 400 <= r.status_code < 500, r.text


async def test_unknown_metric_is_4xx(client, elder):
    r = client.post("/api/health/readings", json={
        "elder_id": elder["id"], "metric_type": "骨密度", "value": 1})
    assert 400 <= r.status_code < 500, r.text


async def test_missing_elder_id_is_4xx(client):
    r = client.post("/api/health/readings", json={"elder_id": "  ", "metric_type": "bp",
                                                  "systolic": 178, "diastolic": 105})
    assert 400 <= r.status_code < 500, r.text


async def test_condition_needs_a_name(client, elder):
    r = client.post("/api/health/conditions", json={"elder_id": elder["id"], "name": "  "})
    assert 400 <= r.status_code < 500, r.text


# ------------------------------------------------------- REST 与聊天的口径一致

async def test_rest_and_chat_agree_on_the_same_reading(client, ctx, elder):
    """**本次最核心的不变量**：REST 记的数，聊天工具读到的是同一档、同一 display。

    这一条要挡的是一种很具体的事故：两边各写一遍取数与分诊，于是同一个 178/105
    在聊天里是"建议就医"、在页面上是别的档 —— 老人看着两个屏幕，不知道信哪个。
    """
    client.post("/api/health/readings", json={
        "elder_id": elder["id"], "metric_type": "bp", "systolic": 178, "diastolic": 105})

    rest = client.get("/api/health/overview", params={"elder_id": elder["id"]}).json()

    # 走 dispatcher 的聊天侧工具，读的是同一个 ctx.repos
    turn = TurnContext(ctx=ctx, session_id="s-health-api", user=elder)
    chat = await ctx.dispatcher.execute(turn, "get_health_summary", {})

    assert chat["data"]["level"] == rest["level"] == "建议就医"
    rest_bp = next(x for x in rest["readings"] if x["metric_type"] == "bp")
    chat_bp = next(x for x in chat["data"]["readings"] if x["metric_type"] == "bp")
    assert rest_bp["display"] == chat_bp["display"]
    assert rest_bp["level"] == chat_bp["level"]
    assert rest_bp["reason"] == chat_bp["reason"]


async def test_a_reading_recorded_through_chat_shows_up_on_the_page(client, ctx, elder):
    """反向也成立：聊天里记的数，页面上要看得见 —— 同源不是单向的。"""
    turn = TurnContext(ctx=ctx, session_id="s-health-api-2", user=elder)
    await ctx.dispatcher.execute(turn, "log_vital",
                                 {"metric_type": "heart_rate", "value": 72})

    items = client.get("/api/health/readings", params={"elder_id": elder["id"]}).json()["items"]
    hr_item = next(x for x in items if x["metric_type"] == "heart_rate")
    assert hr_item["display"] == "72 次/分"
    assert hr_item["level"] == "保健"


# ---------------------------------------------------------------- 分组历史/趋势

async def test_readings_are_grouped_with_a_trend_per_metric(client, elder):
    """VitalTrend 要的是"每类指标一串点 + 一个走向"，不是一坨平铺的流水。"""
    for value in (140, 145, 155, 170, 178):
        client.post("/api/health/readings", json={
            "elder_id": elder["id"], "metric_type": "bp",
            "systolic": value, "diastolic": 95})

    data = client.get("/api/health/readings", params={"elder_id": elder["id"]}).json()
    bp = next(x for x in data["items"] if x["metric_type"] == "bp")
    assert len(bp["points"]) == 5
    assert bp["trend"] == "上升"
    assert [p["value"] for p in bp["points"]] == [140, 145, 155, 170, 178], \
        "点要按时间正序，图才画得出走向"
    assert bp["display"] == "178/95 mmHg"


async def test_readings_only_keep_the_requested_window(client, elder):
    """趋势看的是"最近这几天"，不是三年前那本流水账。"""
    for value in (130, 132, 134, 136, 138, 140, 142, 144):
        client.post("/api/health/readings", json={
            "elder_id": elder["id"], "metric_type": "bp",
            "systolic": value, "diastolic": 85})
    data = client.get("/api/health/readings",
                      params={"elder_id": elder["id"], "window": 3}).json()
    bp = next(x for x in data["items"] if x["metric_type"] == "bp")
    assert [p["value"] for p in bp["points"]] == [140, 142, 144]
    assert data["window"] == 3


async def test_a_metric_never_recorded_does_not_show_up_as_a_blank_row(client, elder):
    """没记过的指标不该在页面上占一行空读数 —— 那看着像"这项是 0"。"""
    client.post("/api/health/readings", json={
        "elder_id": elder["id"], "metric_type": "bp", "systolic": 128, "diastolic": 78})
    items = client.get("/api/health/readings", params={"elder_id": elder["id"]}).json()["items"]
    assert [x["metric_type"] for x in items] == ["bp"]


# ---------------------------------------------------------------- 慢病登记

async def test_conditions_roundtrip(client, elder):
    assert client.get("/api/health/conditions",
                      params={"elder_id": elder["id"]}).json()["items"] == []
    r = client.post("/api/health/conditions", json={
        "elder_id": elder["id"], "name": "原发性高血压", "diagnosed_at": "2021-03-18"})
    assert r.status_code == 200, r.text
    items = client.get("/api/health/conditions",
                       params={"elder_id": elder["id"]}).json()["items"]
    assert [c["name"] for c in items] == ["原发性高血压"]
    assert items[0]["active"] is True


async def test_a_condition_feeds_the_triage(client, elder):
    """登记的慢病要真的进分诊的输入，不是只躺在列表里。"""
    client.post("/api/health/conditions", json={"elder_id": elder["id"], "name": "原发性高血压"})
    o = client.get("/api/health/overview", params={"elder_id": elder["id"]}).json()
    assert [c["name"] for c in o["conditions"]] == ["原发性高血压"]


async def test_conditions_are_scoped_to_the_elder_who_asked(client, elder, child, bearer):
    """老人的慢病列表里不许混进别人登记的。

    这里用**child 自己的身份**去登记 child 自己的 elder_id —— 归属校验看的是 id
    而不是 role，所以这条是允许的；被挡的是"替别人写"（见 test_health_privacy）。
    """
    r = client.post("/api/health/conditions",
                    json={"elder_id": child["id"], "name": "2 型糖尿病"},
                    headers=bearer(child))
    assert r.status_code == 200, r.text
    assert client.get("/api/health/conditions",
                      params={"elder_id": elder["id"]}).json()["items"] == []


# ---------------------------------------------------------------- 症状 → 分诊

async def test_a_symptom_can_drive_the_level_on_its_own(client, elder):
    """宁可漏、不可扩：但真报出危险信号时要顶到"紧急"。"""
    o = client.get("/api/health/overview",
                   params={"elder_id": elder["id"], "symptom": "胸口疼，喘不上气"}).json()
    assert o["level"] == "紧急"


async def test_blank_symptom_is_not_a_symptom(client, elder):
    """空串不算报症状，否则每次打开页面都会凭空多一条"观察"。"""
    o = client.get("/api/health/overview",
                   params={"elder_id": elder["id"], "symptom": "   "}).json()
    assert o["level"] == "保健"
    assert o["drivers"] == []


# ---------------------------------------------------------------- 指标表

async def test_metrics_list_is_the_rules_table(client):
    """表单的选项来自 health_rules，前端不另抄一份 —— 抄了就会漂。"""
    items = client.get("/api/health/metrics").json()["items"]
    assert {i["metric_type"] for i in items} == {
        "bp", "glucose", "heart_rate", "spo2", "temperature", "weight"}
    bp = next(i for i in items if i["metric_type"] == "bp")
    assert bp["label"] == "血压" and bp["unit"] == "mmHg"
    assert "90–140" in bp["normal"]


# -------------------------------------------- 守 router 改名（既有路径不许动坏）

async def test_medications_paths_survive_the_router_rename(client, elder):
    """用药那四条路径靠改名后的 medication_router 挂在同一层 include 上。

    改名是这次为了给 /api/health 腾地方做的手术，手术不能碰到既有的胳膊腿。
    """
    r = client.get("/api/medications", params={"elder_id": elder["id"]})
    assert r.status_code == 200 and "items" in r.json()

    created = client.post("/api/medications", json={
        "elder_id": elder["id"], "drug_name": "钙片", "dose": "每次1片",
        "times": ["09:00"]})
    assert created.status_code == 200
    plan_id = created.json()["id"]
    assert client.post(f"/api/medications/{plan_id}/taken").status_code == 200
    assert client.delete(f"/api/medications/{plan_id}").status_code == 200


def test_both_prefixes_hang_off_the_same_router_symbol():
    """main.py 只 include 了 ``routes_health.router`` 这一个符号。

    两条前缀都必须挂在它下面，否则新增的 /api/health 在装配上就是隐形的
    —— 单测里直接打路由没事，跑起来却是 404。所以这一条看的是**装好的 app**
    的路径表，不是那个 router 对象本身（这一版 FastAPI 的 include_router 是惰性的，
    router.routes 里只有一层 ``_IncludedRouter``，读不出路径）。
    """
    paths = set(create_app().openapi()["paths"])
    assert {"/api/medications", "/api/medications/{plan_id}",
            "/api/medications/{plan_id}/taken"} <= paths
    assert {"/api/health/metrics", "/api/health/readings",
            "/api/health/overview", "/api/health/conditions"} <= paths
