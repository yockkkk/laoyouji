"""红线 R6：行程守护面的越级防线。**这个文件是给那片闸门留的牙印。**

它挡的是一件终检真起后端实测过的事：整片行程守护接口原先**没有身份这一层**，
隐私分级是调用方自己拿 query 参数开的 —— ``trip_detail`` 里写着"没传 child_id 就
return 全量"、``realtime`` 里写着"带了 child_id 才过滤"。于是：

- ``GET /api/trips`` 不带 elder_id → 200，把**全库行程**连 elder_id / 目的地 /
  事由一起吐出来；
- ``GET /api/trips/{id}`` 不带 child_id → 200，返回 precision="owner" 的**未降级**
  上报："南京鼓楼区汉口路22号" + 经纬度 + 偏航告警；
- ``POST /api/trips/{id}/checkpoints`` → 200，**能把任意坐标写进别人家老人的行程**，
  并顺手把一条伪造的 off_route 告警推给他的子女。

前两条同一个根子：把闸门交给调用方，比没有闸门更糟 —— 它看起来是管着的。

所以这里的断言分两类。一类是**身份**：不带 token 必须 401，拿别人的 id 必须拿不到。
另一类是**降级真的发生在后端出库那一刻**：city 档下响应里不许出现门牌号与经纬度，
而且用整段 ``json.dumps`` 扫全文的办法验 —— 逐字段断言会随字段增减失效，漏一个
新字段就是一个新出口。只出不进那一半也要验：库里始终是全量事实。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api import deps, routes_guardian
from app.auth.security import create_access_token
from app.main import create_app

# 精确到门牌号的真实上报：防线要挡的就是它
_ADDRESS = "南京鼓楼区汉口路22号"
_LNG, _LAT = 118.7745, 32.0594

# 响应全文里一旦出现这些片段，就是位置没降级（经纬度、以及演示家的坐标）
_COORD_MARKERS = ("118.77", "32.059", "32.0618", "116.45", "39.93")


# ------------------------------------------------------------------------ 夹具


@pytest.fixture()
async def api(ctx, monkeypatch):
    """真 app + TestClient。**不带默认身份**：这个文件测的就是"谁在问"。"""
    monkeypatch.setattr(routes_guardian, "get_ctx", lambda: ctx)
    # 认证依赖走 deps.get_ctx → 模块全局名 get_app_context()，补这里才引到 tmp ctx
    monkeypatch.setattr(deps, "get_app_context", lambda: ctx)
    return TestClient(create_app())     # 不用 with：不跑 lifespan


@pytest.fixture()
def login(ctx):
    def _login(user: dict) -> dict:
        return {"Authorization": f"Bearer {create_access_token(user, ctx.settings)}"}
    return _login


# ------------------------------------------------------------------------ 素材


async def _user(ctx, role: str, name: str) -> dict:
    """一个身份成立、关系不一定成立的人。"""
    return await ctx.repos.insert("users", {
        "username": f"{role}_{name}", "password_hash": "x", "role": role,
        "name": name, "status": "active", "phone": "13800000009"})


async def _trip(ctx, elder_id: str, *, destination: str = "南京鼓楼医院",
                status: str = "ongoing") -> dict:
    return await ctx.repos.insert("trips", {
        "elder_id": elder_id, "purpose": f"前往{destination}就医出行",
        "status": status, "origin": "家（南京鼓楼区）", "destination": destination})


async def _checkpoint(ctx, trip_id: str, *, status: str = "off_route") -> dict:
    """一条真实形状的上报：备注里带着门牌号（守护逻辑就是这么拼的）。"""
    return await ctx.repos.insert("trip_checkpoints", {
        "trip_id": trip_id, "location": _ADDRESS, "lng": _LNG, "lat": _LAT,
        "status": status, "note": f"位置偏离规划路线：{_ADDRESS}，请关注"})


async def _set_location_level(ctx, elder_id: str, child_id: str, level: str) -> None:
    """把这一对的位置档改成 ``level``。先清旧行 —— 同一对留两行的话，查出来是
    哪一行就变成了靠 list 的顺序，测试会时绿时红。"""
    for row in await ctx.repos.list("privacy_permissions",
                                    where={"elder_id": elder_id, "child_id": child_id}):
        await ctx.repos.delete("privacy_permissions", row["id"])
    await ctx.repos.insert("privacy_permissions", {
        "elder_id": elder_id, "child_id": child_id,
        "location_level": level, "health_level": "summary"})


async def _count_checkpoints(ctx, trip_id: str) -> int:
    return len(await ctx.repos.list("trip_checkpoints", where={"trip_id": trip_id}))


def _dumped(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _assert_no_precise_location(payload, why: str = "") -> None:
    """整段响应里不许有门牌号、不许有经纬度。**扫全文**，不逐字段看。"""
    text = _dumped(payload)
    assert "汉口路22号" not in text, f"响应里带着门牌号（{why}）：{text}"
    for marker in _COORD_MARKERS:
        assert marker not in text, f"响应里带着坐标 {marker}（{why}）：{text}"


# -------------------------------------------------------- ① 没有 token 就 401

# 七条行程路由：一条都不许匿名可打（checkpoints 是写入口，同样要门）
_ROUTES: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/trips", None),
    ("GET", "/api/trips/route/direct", None),
    ("POST", "/api/trips/quick",
     {"origin": "家（南京鼓楼区）", "destination": "南京鼓楼医院", "elder_id": "someone"}),
    ("GET", "/api/trips/{tid}", None),
    ("GET", "/api/trips/{tid}/route", None),
    ("GET", "/api/trips/{tid}/realtime", None),
    ("POST", "/api/trips/{tid}/checkpoints",
     {"location": "北京天安门", "lng": 116.397, "lat": 39.909}),
]


async def test_every_guardian_route_401s_without_a_token(api, ctx, elder):
    """不带 Authorization 头打每一条 —— 必须是 401，不是 200。

    401 由 ``Depends(get_current_principal)`` 自己抛，路由体一行都不执行：
    这也是"没有 token 的请求根本走不到数据层"的证明。
    """
    trip = await _trip(ctx, elder["id"])
    before = await _count_checkpoints(ctx, trip["id"])

    for method, path, body in _ROUTES:
        url = path.format(tid=trip["id"])
        res = api.request(method, url, json=body)
        assert res.status_code == 401, f"{method} {url} -> {res.status_code} {res.text[:200]}"
        assert "trips" not in res.text, f"{method} {url} 的 401 回包里不该有任何行程数据"

    assert await _count_checkpoints(ctx, trip["id"]) == before, "匿名写入不许落库"


# ------------------------------------------------- ② 列表：不许再端全库

async def test_trip_list_never_hands_out_other_peoples_trips(api, ctx, elder, child, login):
    """没传 elder_id 不再是"全库" —— 那正是实测里最刺眼的一屏。"""
    mine = await _trip(ctx, elder["id"], destination="南京鼓楼医院")
    stranger = await _user(ctx, "elder", "王老太")
    other_trip = await _trip(ctx, stranger["id"], destination="北京积水潭医院")

    res = api.get("/api/trips", headers=login(child))
    assert res.status_code == 200, res.text
    ids = [t["id"] for t in res.json()["trips"]]
    assert mine["id"] in ids, "绑定子女要能看到自家老人的行程"
    assert other_trip["id"] not in ids, "没传 elder_id 也不许把别人家老人的行程端出来"

    # 老人端：只看自己，一行都不多
    own = api.get("/api/trips", headers=login(stranger)).json()
    assert [t["id"] for t in own["trips"]] == [other_trip["id"]]

    # elder_id 从"查询条件"降成"收窄过滤器"：传别人家的 id 直接 403
    res = api.get("/api/trips", params={"elder_id": elder["id"]}, headers=login(stranger))
    assert res.status_code == 403, res.text


async def test_a_child_with_no_binding_sees_an_empty_list(api, ctx, elder, login):
    """没绑定关系的子女：列表是空的，不是 403 —— 他问的是"我能看什么"，答案是"没有"。"""
    await _trip(ctx, elder["id"])
    outsider = await _user(ctx, "child", "侄子")
    res = api.get("/api/trips", headers=login(outsider))
    assert res.status_code == 200
    assert res.json() == {"trips": [], "count": 0}


# ------------------------------------------- ③ 行程详情：身份决定拿什么

async def test_another_elder_cannot_read_my_trip(api, ctx, elder, login):
    """另一个老人的 token 打这条行程 —— 403，不是"未降级的 200"。"""
    trip = await _trip(ctx, elder["id"])
    await _checkpoint(ctx, trip["id"])
    other = await _user(ctx, "elder", "李大爷")

    res = api.get(f"/api/trips/{trip['id']}", headers=login(other))
    assert res.status_code == 403, res.text
    _assert_no_precise_location(res.json(), "403 回包")


async def test_unbound_child_gets_nothing_precise(api, ctx, elder, login):
    """没有 family_bindings 的子女：降级是**数据变形不是报错**，变形到底就是什么都不给。

    行程壳子留着（前端在 off 档有现成的文案位置），内容一项不留 —— 连
    "这趟去哪"都不该让陌生人知道。
    """
    trip = await _trip(ctx, elder["id"])
    await _checkpoint(ctx, trip["id"])
    outsider = await _user(ctx, "child", "远房侄子")

    res = api.get(f"/api/trips/{trip['id']}", headers=login(outsider))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["precision"] == "off"
    assert body["checkpoints"] == []
    assert body["privacy"]["bound"] is False
    assert body["route"]["polyline"] == [] and body["route"]["points"] == []
    assert "南京鼓楼医院" not in _dumped(body), "没这层关系，连去哪都不该知道"
    _assert_no_precise_location(body, "无绑定子女")

    # 实时接口同样：位置没有，"有异常"这件事也没有
    rt = api.get(f"/api/trips/{trip['id']}/realtime", headers=login(outsider)).json()
    assert rt["latest_checkpoint"] is None
    assert rt["is_off_route"] is False and rt["alert"] == ""
    _assert_no_precise_location(rt, "无绑定子女·实时")


async def test_child_id_must_match_the_token(api, ctx, elder, child, login):
    """``child_id`` 只剩"我是谁"的冗余提示：与 token 不一致就是 403。

    它不再参与裁剪 —— 改之前"不带它就给全量"，等于这把钥匙插在锁的外侧。
    """
    trip = await _trip(ctx, elder["id"])
    await _checkpoint(ctx, trip["id"])
    other_child = await _user(ctx, "child", "大女儿")

    res = api.get(f"/api/trips/{trip['id']}", params={"child_id": other_child["id"]},
                  headers=login(child))
    assert res.status_code == 403, res.text

    # 一致时照常放行（前端 pages/child/guardian.vue 就是带着自己的 id 打的）
    ok = api.get(f"/api/trips/{trip['id']}", params={"child_id": child["id"]},
                 headers=login(child))
    assert ok.status_code == 200, ok.text


# ------------------------------------------- ④ 降级发生在后端出库那一刻

async def test_bound_child_city_grade_loses_address_and_coordinates(
        api, ctx, elder, child, login):
    """city 档：地址粗到区、经纬度砍掉、航迹不出坐标 —— 且库里仍是全量事实。"""
    trip = await _trip(ctx, elder["id"])
    cp = await _checkpoint(ctx, trip["id"])
    await _set_location_level(ctx, elder["id"], child["id"], "city")

    res = api.get(f"/api/trips/{trip['id']}", params={"child_id": child["id"]},
                  headers=login(child))
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["precision"] == "city"
    assert body["privacy"]["location_level"] == "city"
    assert len(body["checkpoints"]) == 1
    graded = body["checkpoints"][0]
    assert graded["location"] == "南京鼓楼区", "粗化到区就停，不是整条吞掉"
    assert graded["lng"] is None and graded["lat"] is None
    assert graded["note"] != cp["note"], "备注是重建的：洗自由文本洗不干净"
    # 航迹的起点是老人家坐标（elder_homes 那份），city 档一样不能出
    assert body["route"]["polyline"] == [] and body["route"]["points"] == []
    assert body["route"]["steps"] == []
    _assert_no_precise_location(body, "city 档")

    # 只出不进：裁的是出库那一份，库里的门牌号和坐标都还在
    stored = await ctx.repos.get("trip_checkpoints", cp["id"])
    assert stored["lng"] == _LNG and _ADDRESS in stored["location"]

    # 审计记下了"谁在读、当时哪一档"—— 老人端"谁看过我"要用它
    rows = await ctx.repos.list("audit_log", where={"action": "privacy_read"})
    assert any(r["actor_id"] == child["id"] and r["target"] == elder["id"]
               and r["detail"]["scope"] == "trip_detail" for r in rows)


async def test_realtime_respects_the_grade_and_keeps_the_alarm(
        api, ctx, elder, child, login):
    """实时轮询三档：realtime 给坐标、city 砍坐标、off 整条不给。

    但 off 档下"有一次异常"这件事仍然送达 —— 把告警也藏掉，守护功能就等于没有。
    """
    trip = await _trip(ctx, elder["id"])
    await _checkpoint(ctx, trip["id"], status="off_route")
    url = f"/api/trips/{trip['id']}/realtime"

    # 种子默认就是 realtime 档：这一档本来就该看得见，否则守护功能名存实亡
    body = api.get(url, params={"child_id": child["id"]}, headers=login(child)).json()
    assert body["latest_checkpoint"]["lng"] == _LNG
    assert body["is_off_route"] is True and _ADDRESS in body["alert"]

    await _set_location_level(ctx, elder["id"], child["id"], "city")
    body = api.get(url, params={"child_id": child["id"]}, headers=login(child)).json()
    assert body["latest_checkpoint"]["lng"] is None
    assert body["latest_checkpoint"]["location"] == "南京鼓楼区"
    assert body["is_off_route"] is True
    _assert_no_precise_location(body, "city 档·实时")

    await _set_location_level(ctx, elder["id"], child["id"], "off")
    body = api.get(url, params={"child_id": child["id"]}, headers=login(child)).json()
    assert body["latest_checkpoint"] is None
    assert body["is_off_route"] is True, "位置关了也得让子女知道有异常"
    assert body["alert"] and "汉口路22号" not in body["alert"]
    _assert_no_precise_location(body, "off 档·实时")


async def test_the_elder_reads_their_own_trip_in_full(api, ctx, elder, login):
    """老人端要在自己手机上看自己的行程 —— 这条路必须留，且是全量。

    降级是对着"别人"的，本人读自己没有降级可言。
    """
    trip = await _trip(ctx, elder["id"])
    await _checkpoint(ctx, trip["id"])

    body = api.get(f"/api/trips/{trip['id']}", headers=login(elder)).json()
    assert body["precision"] == "owner"
    assert body["checkpoints"][0]["lng"] == _LNG
    assert _ADDRESS in _dumped(body)

    rt = api.get(f"/api/trips/{trip['id']}/realtime", headers=login(elder)).json()
    assert rt["latest_checkpoint"]["lng"] == _LNG

    route = api.get(f"/api/trips/{trip['id']}/route", headers=login(elder)).json()
    assert route["ok"] is True and "route" in route

    own = api.get("/api/trips", headers=login(elder)).json()
    assert [t["id"] for t in own["trips"]] == [trip["id"]]

    # 本人自读不落审计 —— 审计记的是"别人看了我什么"
    audits = await ctx.repos.list("audit_log", where={"action": "privacy_read"})
    assert all(r["actor_id"] != elder["id"] for r in audits)


# ------------------------------------------------- ⑤ 写入口：位置上报

async def test_reporting_a_position_for_someone_else_is_refused(api, ctx, elder, login):
    """替别人上报位置必须失败，而且**对方库里一行都不许多**（before/after 一起报）。

    这就是实测里那条"能把北京天安门 116.39/39.9 灌进别人家老人的行程、顺手伪造
    一条偏航告警推给他子女"的路。
    """
    trip = await _trip(ctx, elder["id"])
    before = await _count_checkpoints(ctx, trip["id"])

    other_elder = await _user(ctx, "elder", "赵大爷")
    unbound_child = await _user(ctx, "child", "邻居")

    for who in (other_elder, unbound_child):
        res = api.post(f"/api/trips/{trip['id']}/checkpoints",
                       json={"location": "北京天安门", "lng": 116.397, "lat": 39.909},
                       headers=login(who))
        assert res.status_code == 403, f"{who['name']} 越权写入 -> {res.status_code}"

    after = await _count_checkpoints(ctx, trip["id"])
    assert before == after, f"被拒的写入留下了行：before={before} after={after}"
    rows = await ctx.repos.list("trip_checkpoints", where={"trip_id": trip["id"]})
    assert all("天安门" not in str(r.get("location")) for r in rows)


async def test_the_demo_simulation_still_works_for_a_bound_child(
        api, ctx, elder, child, login):
    """演示能力不许被一起掐死：子女端那两个"模拟行进 / 模拟偏航"按钮是**有绑定关系**
    的子女在打（pages/child/guardian.vue 的 simElderMove）。

    这条路留的是"明确授权"，不是"匿名可打" —— 老人本人上报自己的位置同样通。
    """
    trip = await _trip(ctx, elder["id"])
    before = await _count_checkpoints(ctx, trip["id"])

    res = api.post(f"/api/trips/{trip['id']}/checkpoints",
                   json={"location": "北京市朝阳区三里屯太古里", "lng": 116.455, "lat": 39.937},
                   headers=login(child))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "off_route" and body["alert_sent"] is True
    assert await _count_checkpoints(ctx, trip["id"]) == before + 1

    # 老人本人上报自己的位置：一路全量
    res = api.post(f"/api/trips/{trip['id']}/checkpoints",
                   json={"location": "家（南京鼓楼区）", "lng": 118.7732, "lat": 32.0618},
                   headers=login(elder))
    assert res.status_code == 200, res.text
    assert await _count_checkpoints(ctx, trip["id"]) == before + 2

    # 子女那次写入留下了一条审计：谁替谁报了位置
    audits = await ctx.repos.list("audit_log", where={"action": "guardian_report"})
    assert any(r["actor_id"] == child["id"] and r["target"] == elder["id"] for r in audits)


async def test_quick_trip_cannot_be_created_for_someone_else(api, ctx, elder, child, login):
    """``/api/trips/quick`` 是"进路线规划时自动建行程"，只能建给自己的。

    替别人建 = 那位老人的子女会在看板上看到一趟他家老人从没安排过的出行。
    """
    other_elder = await _user(ctx, "elder", "赵大爷")
    before = len(await ctx.repos.list("trips", where={"elder_id": other_elder["id"]}))

    res = api.post("/api/trips/quick",
                   json={"origin": "家（南京鼓楼区）", "destination": "南京鼓楼医院",
                         "elder_id": other_elder["id"]},
                   headers=login(elder))
    assert res.status_code == 403, res.text
    after = len(await ctx.repos.list("trips", where={"elder_id": other_elder["id"]}))
    assert before == after, "被拒的建程不该在别人名下留下行程"

    # 给自己建：放行（老人端 route-map.vue 走的就是这条）
    mine = api.post("/api/trips/quick",
                    json={"origin": "家（南京鼓楼区）", "destination": "南京鼓楼医院",
                          "elder_id": elder["id"]},
                    headers=login(elder))
    assert mine.status_code == 200, mine.text
    assert mine.json()["trip"]["elder_id"] == elder["id"]
