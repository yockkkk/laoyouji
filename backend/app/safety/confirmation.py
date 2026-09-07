"""ConfirmationService —— 高危操作确认状态机 + 延迟重放执行（ADR-1）。

状态机：
  pending ──approve──► executing ──成功──► executed
     │ │                                 └─失败──► failed
     │ └──reject──► rejected
     └──超时(30min, 惰性清扫)──► expired

约束：非 pending 再审批 ⇒ 409；过期审批 ⇒ 409 并标记 expired。
bypass 凭证：approve 后重放必须与冻结的 tool_args 完全一致（防篡改重放）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.context import AppContext, TurnContext
from app.core.events import durable_type
from app.core.guard import GuardResult
from app.core.sse import SSEEvent
from app.core.tool import Tool
from app.db.repositories import Repository

logger = logging.getLogger(__name__)


class ConfirmationError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


class ConfirmationService:
    def __init__(self, repo: Repository, timeout_min: int):
        self._repo = repo
        self._timeout = timedelta(minutes=timeout_min)

    # ------------------------------------------------------------- 挂起（拦截时）

    async def suspend(self, turn: TurnContext, tool: Tool, args: dict,
                      guard_result: GuardResult) -> dict:
        """由 ToolDispatcher 调用：冻结参数、建确认任务、通知双端。"""
        user_id = turn.user.get("id")
        user_role = turn.user.get("role", "elder")

        # 查找家庭关联：
        binding = await self._repo.find_one(
            "family_bindings", {"elder_id": user_id, "status": "active"}
        )
        if not binding:
            binding = await self._repo.find_one("family_bindings", {"elder_id": user_id})

        # 容错兜底：如果当前用户身份是 child（或在绑定中作为 child_id 存在）
        if not binding and user_role == "child":
            binding = await self._repo.find_one(
                "family_bindings", {"child_id": user_id, "status": "active"}
            )
            if not binding:
                binding = await self._repo.find_one("family_bindings", {"child_id": user_id})

        # 没有"全局兜底"：查不到属于此人的绑定就是查不到。child_id=None 不是
        # 要兜住的 bug，而是 R5 的正确结局 —— 宁可这张卡谁都领不走，也不许
        # 从库里随便挑一个陌生家庭的子女来审批别人家的老人。
        active_binding = (
            binding if (binding and binding.get("status") in (None, "active"))
            else None
        )
        child_id = active_binding["child_id"] if active_binding else None
        # 只有子女本人发起的挂起，才采用他名下绑定里的 elder_id；
        # binding 是按 child_id == user_id 查出来的，归属已经成立。
        elder_id = binding["elder_id"] if (binding and user_role == "child") else user_id
        relation = (binding or {}).get("relation") or ("儿子" if binding else "家人")

        elder_user = await self._repo.get("users", elder_id) if elder_id else turn.user
        child_user = await self._repo.get("users", child_id) if child_id else None
        elder_name = (elder_user or {}).get("name") or turn.user.get("name", "张桂芳")
        child_name = (child_user or {}).get("name") or ("李明" if binding else None)

        # 关系角色铁律防倒置：
        # 对老人（长辈端）：若有绑定称 "您儿子李明"（或配置的具体称谓），未绑定称 "家人"
        # 对子女（家人端）：称 "母亲张桂芳"
        if binding:
            relation_for_elder = f"您{relation}{child_name}" if child_name else f"您{relation}"
        else:
            relation_for_elder = "家人"
        elder_title_for_child = f"母亲{elder_name}"

        summary_text = (
            tool.child_summary(args) if tool.child_summary
            else f"{elder_title_for_child}想执行 {tool.name}：{args}"
        )
        card = {
            "title": f"{elder_title_for_child}想进行一项需要确认的操作",
            "summary": summary_text,
            "reason": guard_result.reason or "涉及资金/重要事项",
            "risk_level": guard_result.risk_level,
            "amount": guard_result.amount,
            "relation": relation,
        }

        now = datetime.now(timezone.utc)
        task = await self._repo.insert("confirmation_tasks", {
            "session_id": turn.session_id,
            "elder_id": elder_id,
            "child_id": child_id,
            "tool_name": tool.name,
            "tool_args": args,
            "arguments": args,
            "risk_level": guard_result.risk_level,
            "amount": guard_result.amount,
            "summary_for_child": card,
            "relation_for_elder": relation_for_elder,
            "elder_title_for_child": elder_title_for_child,
            "elder_name": elder_name,
            "child_name": child_name,
            "status": "pending",
            "expires_at": (now + self._timeout).isoformat(),
        })
        await self._repo.insert("audit_log", {
            "actor_id": turn.user.get("id"),
            "action": "confirmation_created",
            "target": task["id"],
            "detail": {"tool": tool.name, "args": args, "risk_level": guard_result.risk_level},
        })

        # 写入通知中心 (notifications 表)，确保子女端在看板与通知中心第一时间收到提醒！
        # 行形状以 schema.sql 的 notifications 定义为准（summary/is_read/data），
        # 与 plan_helpers.dispatch_plan_created_notification 保持一致 —— 单表
        # JSON 存储不报错，但前端靠 is_read 判未读，写两套字段就是永久"未读"。
        if child_id:
            try:
                await self._repo.insert("notifications", {
                    "user_id": child_id,
                    "elder_id": elder_id,
                    "type": "confirmation_request",
                    "title": f"【待您审批】{card['title']}",
                    "summary": card["summary"],
                    "is_read": False,
                    "data": {
                        "task_id": task["id"],
                        "tool": tool.name,
                        "amount": guard_result.amount,
                        "elder_name": elder_name,
                        "reason": guard_result.reason,
                    },
                    "created_at": now.isoformat(),
                })
            except Exception as e:
                logger.warning(f"Failed to insert notification for suspended task: {e}")

        await turn.emit("suspended", {
            "confirmation_id": task["id"],
            "tool": tool.name,
            "summary": summary_text,
            "amount": guard_result.amount,
            "expires_at": task["expires_at"],
            "relation": relation_for_elder,
            "message": f"这步要先过{relation_for_elder}的确认。已经发过去了，"
                       f"他点一下同意，我马上帮您办好。",
        })
        return {
            "ok": False,
            "suspended": True,
            "confirmation_id": task["id"],
            "summary": f"已发起{relation_for_elder}确认，等待通过后自动执行。",
        }

    # ------------------------------------------------------------- 放行凭证校验

    async def check_bypass(self, confirmation_id: str, tool_name: str,
                           args: dict) -> bool:
        task = await self._repo.get("confirmation_tasks", confirmation_id)
        if not task or task.get("status") != "approved":
            return False
        if task.get("tool_name") != tool_name:
            return False
        # 参数必须与冻结时完全一致（防篡改重放）
        return (task.get("tool_args") or {}) == args

    # ------------------------------------------------------------- 子女端操作

    async def approve_and_execute(self, task_id: str, ctx: AppContext,
                                  child_id: str | None = None) -> dict:
        """子女批准 → 校验状态机 → 带 bypass 凭证重放冻结的工具调用。"""
        # 预查 session_id 用于进入会话闸门（避免重放执行与老人同时对话产生交错因果错乱）
        raw_task = await self._repo.get("confirmation_tasks", task_id)
        session_id = (raw_task or {}).get("session_id") or ""

        async def _execute() -> dict:
            task = await self._get_valid_pending(task_id)
            await self._repo.update("confirmation_tasks", task_id, {
                "status": "approved", "resolved_at": _now_iso(),
            })
            await self._repo.insert("audit_log", {
                "actor_id": child_id or task.get("child_id"),
                "action": "confirmation_approved",
                "target": task_id,
                "detail": {"tool": task["tool_name"]},
            })

            elder = await self._repo.get("users", task["elder_id"])
            turn = TurnContext(
                ctx=ctx, session_id=session_id, user=elder or {},
            )
            result = await ctx.dispatcher.execute(
                turn, task["tool_name"], task.get("tool_args") or {},
                bypass_confirmation_id=task_id,
            )

            status = "executed" if result.get("ok") else "failed"
            await self._repo.update("confirmation_tasks", task_id, {
                "status": status, "result": _jsonable(result),
            })
            await self._announce(ctx, task, elder or {}, result, status=status)
            return {"ok": bool(result.get("ok")), "status": status, "result": _jsonable(result)}

        if session_id and getattr(ctx, "turn_gate", None) is not None:
            # 审批是 HTTP 请求：闸门等 105 秒默认对一个点击太长。老人在等审批期间
            # 又说了一句话时闸门被占，此时等一小段时间就该认输 —— TurnBusy 由
            # 路由层翻译成 409，而不是逃成 500。
            async with ctx.turn_gate.hold(session_id, max_wait_s=15.0):
                return await _execute()
        return await _execute()

    async def reject(self, task_id: str, ctx: AppContext,
                     child_id: str | None = None,
                     reason: str = "") -> dict:
        task = await self._get_valid_pending(task_id)
        update_data = {
            "status": "rejected", "resolved_at": _now_iso(),
        }
        if reason:
            update_data["reject_reason"] = reason
        await self._repo.update("confirmation_tasks", task_id, update_data)
        detail = {"tool": task["tool_name"]}
        if reason:
            detail["reason"] = reason
        await self._repo.insert("audit_log", {
            "actor_id": child_id or task.get("child_id"),
            "action": "confirmation_rejected",
            "target": task_id,
            "detail": detail,
        })
        # 老人是这条播报的归属人：拿真人记账，别拿 {}。否则"家人没同意"这条
        # 事件在日志里没有 user_id，和"家人同意了"那条对不上，按人查审计会漏。
        elder = await self._repo.get("users", task["elder_id"])
        announce_text = (
            f"家人觉得这次先不办（理由：{reason}）。您要是有疑问，给他打个电话商量商量。"
            if reason
            else "家人觉得这次先不办。您要是有疑问，给他打个电话商量商量。"
        )
        await self._announce(ctx, task, elder or {}, {
            "ok": False,
            "announce": announce_text,
            "reason": reason,
        }, status="rejected")
        return {"ok": True, "status": "rejected"}

    async def list_for_child(self, child_id: str, status: str | None = None) -> list[dict]:
        await self._expire_stale(child_id=child_id)
        # 只认 active 绑定：revoked 的子女连列表都看不到（approve 那路有
        # _ensure_task_in_family 挡着，列表这路也不能漏 —— 摘要里有医院和金额）。
        bindings = await self._repo.list(
            "family_bindings", where={"child_id": child_id, "status": "active"})
        elder_ids = [b["elder_id"] for b in bindings if b.get("elder_id")]

        # 不拉全表再内存过滤：历史任务一多，pending 就被挤出 100 行窗口，
        # 老人那一轮永远挂着没人能批。按条件分查（status 下推给库），按 id 合并。
        matched: dict[str, dict] = {}
        status_where = {"status": status} if status else {}

        own = await self._repo.list(
            "confirmation_tasks", where={"child_id": child_id, **status_where},
            order="-created_at", limit=50)
        for t in own:
            # child_id 直接匹配也要落在 active 绑定内，否则 revoked 后仍泄露
            if t.get("elder_id") in elder_ids:
                matched[t["id"]] = t
        for eid in elder_ids:
            rows = await self._repo.list(
                "confirmation_tasks", where={"elder_id": eid, **status_where},
                order="-created_at", limit=50)
            for t in rows:
                matched[t["id"]] = t

        return sorted(matched.values(),
                      key=lambda t: t.get("created_at") or "", reverse=True)[:50]

    # ------------------------------------------------------------- 内部

    async def _get_valid_pending(self, task_id: str) -> dict:
        task = await self._repo.get("confirmation_tasks", task_id)
        if not task:
            raise ConfirmationError("确认任务不存在", 404)
        if task.get("status") != "pending":
            raise ConfirmationError(f"该任务已处理（当前状态: {task['status']}）", 409)
        expires_at = _parse_iso(task.get("expires_at"))
        if expires_at and datetime.now(timezone.utc) > expires_at:
            await self._repo.update("confirmation_tasks", task_id, {
                "status": "expired", "resolved_at": _now_iso(),
            })
            raise ConfirmationError("确认已超时过期（30 分钟）", 409)
        return task

    async def _expire_stale(self, *, child_id: str | None = None) -> int:
        """惰性清扫：任何读取路径触发，把超时的 pending 标记 expired。"""
        where = {"status": "pending"}
        if child_id:
            where["child_id"] = child_id
        rows = await self._repo.list("confirmation_tasks", where=where, limit=200)
        now = datetime.now(timezone.utc)
        count = 0
        for task in rows:
            expires_at = _parse_iso(task.get("expires_at"))
            if expires_at and now > expires_at:
                await self._repo.update("confirmation_tasks", task["id"], {
                    "status": "expired", "resolved_at": _now_iso(),
                })
                count += 1
        return count

    async def _announce(self, ctx: AppContext, task: dict, elder: dict,
                        result: dict, *, status: str) -> None:
        """执行结果回播老人端（+落会话日志，断线可轮询恢复）。

        ``status`` 用 ``confirmation_tasks.status`` 那套词（``executed`` /
        ``failed`` / ``rejected``），不新造第四套。它必须单独发出去，因为
        ``ok=False`` 是**两件不同的事**：家人不同意，和家人同意了但没办成。
        少了这个字段，老人端只能在两者之间猜一个 —— 猜错哪一头都是在替家人
        表态。
        """
        session_id = task.get("session_id") or ""
        if not session_id:
            return
        # 重放走的是子女端 HTTP 请求，进程里可能还没这个会话的内存日志；
        # 不先 hydrate 就 append，seq 会从 1 重新发号，把已有行撞掉。
        await ctx.event_log.hydrate(session_id)
        if status == "executed":
            raw_ann = result.get("announce") or result.get("summary") or ""
            if raw_ann:
                announce = raw_ann if raw_ann.startswith("事情办好啦") else f"事情办好啦，{raw_ann}"
            else:
                announce = "事情办好啦，车票/医院已成功订好。"
        else:
            announce = result.get("announce") or result.get("summary") or "事情办好啦。"
        for event, payload in (
            ("confirmation_resolved", {
                "confirmation_id": task["id"],
                "tool": task["tool_name"],
                "ok": bool(result.get("ok")),
                "status": status,
            }),
            ("agent_msg", {"text": announce, "agent": "main"}),
            ("final", {"text": announce}),
        ):
            ctx.event_log.append(session_id, elder.get("id"),
                                 durable_type(event), payload)
            ctx.broadcast.push_sync(session_id, SSEEvent(event, payload))
        if result.get("card"):
            ctx.event_log.append(session_id, elder.get("id"),
                                 durable_type("card"), result["card"])
            ctx.broadcast.push_sync(session_id, SSEEvent("card", result["card"]))
        # 重放发生在 HTTP 请求里（不在 agent 轮次里），所以这里自己落一次库
        await ctx.event_log.flush(session_id)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _jsonable(result: dict) -> dict:
    import json

    return json.loads(json.dumps(result, ensure_ascii=False, default=str))
