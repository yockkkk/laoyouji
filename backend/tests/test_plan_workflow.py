"""Tests for plan deduplication, family notifications, train routes, and child approval workflow."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents import plan_builder
from app.agents.main_agent import compose_deliverable
from app.auth.security import create_access_token
from app.core.context import TurnContext
from app.core.events import AGENT_REPORT
from app.core.guard import GuardResult, GuardVerdict
from app.core.subagents import AgentReport
from app.main import app
from app.providers.external.train_12306 import MockTrainProvider
from app.shared.plan_helpers import (
    deduplicate_trips_for_elder,
    dispatch_plan_created_notification,
    extract_destination,
    is_same_plan,
    upsert_trip_plan,
)


@pytest.fixture
def mock_reports():
    return [
        AgentReport(
            agent="health",
            ok=True,
            summary="北京协和医院骨科已查到",
            data={
                "appointment": {
                    "hospital": "北京协和医院",
                    "department": "骨科",
                    "doctor": "张医生",
                    "date": "2026-09-10",
                    "time": "上午 09:00",
                    "fee": 100,
                    "address": "东城区帅府园1号",
                }
            },
        ),
        AgentReport(
            agent="travel",
            ok=True,
            summary="G102次高铁已查到",
            data={
                "ticket": {
                    "train_no": "G102",
                    "date": "2026-09-09",
                    "from_station": "南京南站",
                    "to_station": "北京南站",
                    "depart": "08:00",
                    "arrive": "12:18",
                    "seat": "05车厢 12A",
                    "price": 553.5,
                },
                "hotel": {
                    "hotel": "北京王府井希尔顿酒店",
                    "address": "王府井东街8号",
                    "phone": "010-58128888",
                    "checkin": "2026-09-09",
                    "nights": 2,
                    "total": 800,
                },
                "weather": {
                    "city": "北京",
                    "date": "2026-09-09",
                    "condition": "晴",
                    "temp_range": "18℃~28℃",
                    "umbrella": False,
                },
            },
        ),
    ]


async def test_extract_destination():
    assert extract_destination({"title": "张桂芳 · 北京就医出行计划书"}) == "北京"
    assert extract_destination({"purpose": "西湖两日游玩计划书"}) == "杭州"
    assert extract_destination({"plan": {"city": "上海"}}) == "上海"
    assert extract_destination({"plan": {"body": {"天气与穿衣/城市": "南京"}}}) == "南京"


async def test_plan_upsert_and_deduplication(ctx, elder):
    elder_id = elder["id"]

    card1 = {
        "title": f"{elder['name']} · 北京就医出行计划书",
        "city": "北京",
        "type": "medical_plan",
        "pages": [{"no": 1, "title": "第一页"}],
    }

    # 第一次落库：新建
    trip1, created1 = await upsert_trip_plan(ctx.repos, elder_id, card1)
    assert created1 is True
    assert trip1["purpose"] == card1["title"]
    assert trip1["status"] == "planned"

    trips = await ctx.repos.list("trips", where={"elder_id": elder_id})
    assert len(trips) == 1

    # 第二次落库（同目的地的更新）：更新已有记录，不增加行
    card2 = dict(card1)
    card2["subtitle"] = "更新版本"
    trip2, created2 = await upsert_trip_plan(ctx.repos, elder_id, card2)
    assert created2 is False
    assert trip2["id"] == trip1["id"]
    assert trip2["plan"]["subtitle"] == "更新版本"

    trips = await ctx.repos.list("trips", where={"elder_id": elder_id})
    assert len(trips) == 1

    # 人为插入重复行测试 clean up
    dup = await ctx.repos.insert("trips", {
        "elder_id": elder_id,
        "purpose": card1["title"],
        "plan": card1,
        "status": "planned",
    })
    trips_before = await ctx.repos.list("trips", where={"elder_id": elder_id})
    assert len(trips_before) == 2

    # 执行清理
    cleaned = await deduplicate_trips_for_elder(ctx.repos, elder_id)
    assert len(cleaned) == 1

    trips_after = await ctx.repos.list("trips", where={"elder_id": elder_id})
    assert len(trips_after) == 1


async def test_dispatch_notification_on_plan_creation(ctx, elder, child, mock_reports):
    card = plan_builder.build("medical_plan", elder, mock_reports, city="北京")
    notifs = await dispatch_plan_created_notification(
        ctx.repos, elder, card, "trip-123", "medical_plan"
    )
    assert len(notifs) == 1
    notif = notifs[0]
    assert notif["user_id"] == child["id"]
    assert notif["elder_id"] == elder["id"]
    assert notif["is_read"] is False
    assert f"老人{elder['name']}已规划" in notif["title"]


async def test_compose_deliverable_creates_notification(ctx, elder, child, mock_reports):
    turn = TurnContext(ctx=ctx, session_id="s-plan-1", user=elder)
    # 模拟日志中的子智能体回报
    for r in mock_reports:
        ctx.event_log.append("s-plan-1", elder["id"], AGENT_REPORT, r.to_dict())

    result = await compose_deliverable(turn, {"kind": "medical_plan", "city": "北京"})
    assert result["ok"] is True

    # 验证 trips 插入成功且唯一
    trips = await ctx.repos.list("trips", where={"elder_id": elder["id"]})
    assert len(trips) == 1

    # 验证通知表中有给子女的未读通知
    notifs = await ctx.repos.list("notifications", where={"user_id": child["id"]})
    assert len(notifs) >= 1
    latest_notif = notifs[0]
    assert latest_notif["is_read"] is False
    assert f"老人{elder['name']}已规划" in latest_notif["title"]


async def test_train_search_nanjing_hangzhou():
    provider = MockTrainProvider()
    trains = await provider.search("南京", "杭州", "tomorrow")
    assert len(trains) > 0
    assert any(t["train_no"] == "G7615" for t in trains)
    assert trains[0]["from_station"] == "南京南站"
    assert trains[0]["to_station"] == "杭州东站"

    # 查杭州到上海
    trains_hz_sh = await provider.search("杭州", "上海", "tomorrow")
    assert len(trains_hz_sh) > 0
    assert any(t["train_no"] == "G7302" for t in trains_hz_sh)

    # 订票成功
    book_res = await provider.book("G7615", "tomorrow", "张桂芳", "二等座")
    assert book_res["ok"] is True
    assert book_res["price"] == 117.5


async def test_child_dashboard_and_notification_endpoints(ctx, elder, child):
    # 创建一条待确认任务
    turn = TurnContext(ctx=ctx, session_id="s-confirm-test", user=elder)
    tool = ctx.tools.get("book_ticket")
    suspend_res = await ctx.confirmation.suspend(
        turn,
        tool,
        {"train_no": "G102", "date": "tomorrow", "seat_type": "二等座", "price": 553.5},
        GuardResult(GuardVerdict.INTERCEPT, reason="金额超限", risk_level="high", amount=553.5),
    )
    task_id = suspend_res["confirmation_id"]

    from app.api.deps import get_ctx

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        token = create_access_token(child, ctx.settings)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. 访问看板接口
            res = await client.get(
                f"/api/child/{child['id']}/dashboard",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 200
            data = res.json()
            assert any(t["id"] == task_id for t in data["pending_confirmations"])
            assert "notifications" in data

            # 2. 审批通过
            approve_res = await client.post(
                f"/api/confirmations/{task_id}/approve?child_id={child['id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert approve_res.status_code == 200
            approve_data = approve_res.json()
            assert approve_data["status"] == "executed"

            # 再次查看板，已不再是 pending
            res2 = await client.get(
                f"/api/child/{child['id']}/dashboard",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert not any(t["id"] == task_id for t in res2.json()["pending_confirmations"])

            # 3. 再创建一个任务测试拒绝
            suspend_res2 = await ctx.confirmation.suspend(
                turn,
                tool,
                {"train_no": "G104", "date": "tomorrow", "seat_type": "二等座", "price": 553.5},
                GuardResult(GuardVerdict.INTERCEPT, reason="金额超限", risk_level="high", amount=553.5),
            )
            task_id2 = suspend_res2["confirmation_id"]

            reject_res = await client.post(
                f"/api/confirmations/{task_id2}/reject?child_id={child['id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert reject_res.status_code == 200
            assert reject_res.json()["status"] == "rejected"

            # 4. 测试子女通知接口与已读标记
            notif_insert = await ctx.repos.insert(
                "notifications",
                {
                    "user_id": child["id"],
                    "elder_id": elder["id"],
                    "title": f"老人{elder['name']}已规划《西湖两日游玩计划书》",
                    "summary": "已生成共 5 页计划书",
                    "type": "plan_created",
                    "is_read": False,
                    "created_at": "2026-09-06T12:00:00Z",
                },
            )
            notifs_res = await client.get(
                f"/api/child/{child['id']}/notifications",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert notifs_res.status_code == 200
            notif_items = notifs_res.json()["items"]
            assert any(n["id"] == notif_insert["id"] for n in notif_items)

            read_res = await client.post(
                f"/api/child/notifications/{notif_insert['id']}/read",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert read_res.status_code == 200
            assert read_res.json()["ok"] is True
            updated_notif = await ctx.repos.get("notifications", notif_insert["id"])
            assert updated_notif["is_read"] is True

            # 5. 测试防重复审批：已处理任务再次点击报错 409
            dup_approve = await client.post(
                f"/api/confirmations/{task_id}/approve?child_id={child['id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert dup_approve.status_code == 409

            # 6. 未绑定长辈时看板返回 notifications 列表字段
            unbound_child = await ctx.repos.insert("users", {
                "name": "孤立子女", "username": "unbound_child", "role": "child",
            })
            unbound_token = create_access_token(unbound_child, ctx.settings)
            unbound_res = await client.get(
                f"/api/child/{unbound_child['id']}/dashboard",
                headers={"Authorization": f"Bearer {unbound_token}"},
            )
            assert unbound_res.status_code == 200
            unbound_data = unbound_res.json()
            assert "notifications" in unbound_data
            assert isinstance(unbound_data["notifications"], list)
    finally:
        app.dependency_overrides.clear()


async def test_extract_destination_edge_cases():
    assert extract_destination(None) == ""
    assert extract_destination({}) == ""
    assert extract_destination({"title": ""}) == ""
    # 从 plan.pages 天气页提取
    plan_with_pages = {
        "plan": {
            "pages": [
                {"title": "第一页 · 挂号信息", "rows": []},
                {"title": "第五页 · 杭州天气与穿衣", "rows": []},
            ]
        }
    }
    assert extract_destination(plan_with_pages) == "杭州"

    # 从 plan.pages 车票到达站提取
    plan_with_ticket = {
        "plan": {
            "pages": [
                {"title": "第二页 · 车票", "rows": [{"label": "到达", "value": "上海虹桥站"}]}
            ]
        }
    }
    assert extract_destination(plan_with_ticket) == "上海"


async def test_dispatch_notification_deduplication(ctx, elder, child):
    # 人为插入重复的家庭绑定
    await ctx.repos.insert("family_bindings", {
        "elder_id": elder["id"], "child_id": child["id"], "status": "active"
    })
    card = {"title": "张桂芳 · 西湖两日游玩计划书", "pages": []}
    notifs = await dispatch_plan_created_notification(
        ctx.repos, elder, card, "trip-dup-test", "trip_plan"
    )
    # 虽然有两个绑定行，同一个子女只收到一条通知
    assert len(notifs) == 1
    assert notifs[0]["user_id"] == child["id"]


async def test_extract_destination_city_suffix():
    assert extract_destination({"city": "杭州市"}) == "杭州"
    assert extract_destination({"city": "南京市"}) == "南京"
    assert extract_destination({"destination": "北京市"}) == "北京"
    assert extract_destination({"plan": {"city": "上海市"}}) == "上海"
    assert extract_destination({"title": "张桂芳 · 杭州市就医出行计划书"}) == "杭州"

    # 验证带"市"和不带"市"判定为同一计划
    t1 = {"purpose": "张桂芳 · 杭州市就医出行计划书", "plan": {"type": "medical_plan", "city": "杭州市"}}
    t2 = {"purpose": "张桂芳 · 杭州就医出行计划书", "plan": {"type": "medical_plan", "city": "杭州"}}
    assert is_same_plan(t1, t2) is True


async def test_extract_destination_scenic_and_hospitals():
    # 验证景区与名胜能够正确解析归属城市
    assert extract_destination({"title": "张桂芳 · 西湖两日游玩计划书"}) == "杭州"
    assert extract_destination({"title": "张桂芳 · 杭州两日游玩计划书"}) == "杭州"
    assert extract_destination({"title": "张桂芳 · 故宫一日游玩计划书"}) == "北京"
    assert extract_destination({"title": "张桂芳 · 东方明珠游玩计划书"}) == "上海"
    assert extract_destination({"title": "张桂芳 · 夫子庙出行计划书"}) == "南京"

    # 验证医院能够正确解析归属城市
    assert extract_destination({"title": "张桂芳 · 协和就医计划书"}) == "北京"
    assert extract_destination({"title": "张桂芳 · 积水潭就医计划书"}) == "北京"
    assert extract_destination({"title": "张桂芳 · 鼓楼医院就医计划书"}) == "南京"

    # 验证不同标题表述但同一城市同类型的计划判定为同一计划并正确去重
    t1 = {"purpose": "张桂芳 · 西湖两日游玩计划书", "plan": {"type": "trip_plan"}}
    t2 = {"purpose": "张桂芳 · 杭州出行计划书", "plan": {"type": "trip_plan"}}
    assert is_same_plan(t1, t2) is True


async def test_is_same_plan_treats_trip_and_medical_as_one_bucket():
    """trip_plan 与 medical_plan 是同一个语义桶。

    模型这一轮报 trip_plan、下一轮报 medical_plan（别名表正说明它会飘），
    按 kind 相等去重，同一份"去北京"的计划书就存了两条 —— 去重的本意是一条。
    """
    t1 = {"purpose": "张桂芳 · 北京出行计划书 v1", "plan": {"type": "trip_plan"}}
    t2 = {"purpose": "张桂芳 · 北京就医出行计划书 v2", "plan": {"type": "medical_plan"}}
    assert is_same_plan(t1, t2) is True


async def test_same_city_different_trips_are_not_duplicates(ctx, elder):
    """同城的两趟不同行程不是重复：北京·心内科 3/10 和北京·骨科 5/22 都得留着。

    旧判据只有"目的地 + 类型"，挂在 GET 看板里每 5 秒跑一次 ——
    骨科那趟会被永久删掉。收紧判据后，宁可显示重复也别删真数据。
    """
    elder_id = elder["id"]
    t1 = await ctx.repos.insert("trips", {
        "elder_id": elder_id,
        "purpose": "北京 · 协和医院心内科复查 3月10日",
        "plan": {"type": "medical_plan", "title": "北京 · 协和医院心内科复查 3月10日"},
        "status": "planned",
    })
    t2 = await ctx.repos.insert("trips", {
        "elder_id": elder_id,
        "purpose": "北京 · 积水潭医院骨科就诊 5月22日",
        "plan": {"type": "medical_plan", "title": "北京 · 积水潭医院骨科就诊 5月22日"},
        "status": "planned",
    })

    cleaned = await deduplicate_trips_for_elder(ctx.repos, elder_id)
    assert len(cleaned) == 2, "同城不同行程不许判重删除"
    remaining = await ctx.repos.list("trips", where={"elder_id": elder_id})
    assert len(remaining) == 2


async def test_display_folding_never_deletes_rows(ctx, elder):
    """看板读路径只在内存里折叠，绝不删库 —— GET 必须无副作用。"""
    from app.shared.plan_helpers import list_trips_for_display

    elder_id = elder["id"]
    card = {"title": f"{elder['name']} · 北京就医出行计划书",
            "city": "北京", "type": "medical_plan"}
    for _ in range(2):  # 同一份计划书被重复落库两次
        await ctx.repos.insert("trips", {
            "elder_id": elder_id, "purpose": card["title"],
            "plan": card, "status": "planned"})

    shown = await list_trips_for_display(ctx.repos, elder_id)
    assert len(shown) == 1, "展示时折叠成一条"
    rows = await ctx.repos.list("trips", where={"elder_id": elder_id})
    assert len(rows) == 2, "但库里一条都不许少"


async def test_plan_notification_is_idempotent_per_trip(ctx, elder, child):
    """同一份计划书重生成 3 次：trips 去重成 1 条，通知也只能是 1 条。"""
    card = {"title": "张桂芳 · 北京就医出行计划书", "pages": []}
    for _ in range(3):
        await dispatch_plan_created_notification(
            ctx.repos, elder, card, "trip-idem-1", "medical_plan")

    notifs = await ctx.repos.list(
        "notifications", where={"user_id": child["id"]})
    plan_notifs = [n for n in notifs if n.get("type") == "plan_created"
                   and (n.get("data") or {}).get("trip_id") == "trip-idem-1"]
    assert len(plan_notifs) == 1



