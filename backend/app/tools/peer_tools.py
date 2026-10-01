"""对等信箱通信工具集 (Peer Messaging Tools)。

让各智能体（HealthAgent、BdsNavAgent、WeatherAgent、GuardianAgent、MainAgent等）
具备主动对等磋商、广播和查收信箱的能力。
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.mailbox import (
    PeerMessage,
    PeerMessageType,
    get_session_mailbox_hub,
)
from app.core.tool import ToolRegistry
from app.tools.common import fail, make_tool, ok

logger = logging.getLogger(__name__)


async def send_teammate_message(turn: Any, args: dict) -> dict:
    """向指定队友智能体发送点对点信箱电文。"""
    to_agent = str(args.get("to_agent") or "").strip()
    if not to_agent:
        return fail("目标智能体 (to_agent) 不能为空，可选: health, bds_nav, weather, guardian, main 等")

    summary = str(args.get("summary") or "").strip()
    content = str(args.get("content") or "").strip()
    if not summary and not content:
        return fail("电文内容与摘要不能均为空")
    if not summary:
        summary = content[:20]

    msg_type = str(args.get("msg_type") or PeerMessageType.DIRECT.value).strip()
    data = args.get("data")
    if not isinstance(data, dict):
        data = {}

    from_agent = getattr(turn, "agent_id", "agent").split("#")[0]
    session_id = getattr(turn, "session_id", "default")

    msg = PeerMessage(
        from_agent=from_agent,
        to_agent=to_agent,
        msg_type=msg_type,
        summary=summary,
        content=content,
        data=data,
        reply_to=args.get("reply_to"),
        correlation_id=args.get("correlation_id"),
    )

    hub = get_session_mailbox_hub(session_id)
    await hub.send(msg, turn=turn)

    return ok(
        summary=f"已成功向 @{to_agent} 发送信箱电文: {summary}",
        data={"message_id": msg.id, "to_agent": to_agent, "summary": summary, "peer_message": msg.model_dump()},
    )


async def broadcast_teammate_message(turn: Any, args: dict) -> dict:
    """向团队内全体其他智能体广播信箱电文。"""
    summary = str(args.get("summary") or "").strip()
    content = str(args.get("content") or "").strip()
    if not summary and not content:
        return fail("广播内容与摘要不能均为空")
    if not summary:
        summary = content[:20]

    msg_type = str(args.get("msg_type") or PeerMessageType.BROADCAST.value).strip()
    data = args.get("data")
    if not isinstance(data, dict):
        data = {}

    from_agent = getattr(turn, "agent_id", "agent").split("#")[0]
    session_id = getattr(turn, "session_id", "default")

    msg = PeerMessage(
        from_agent=from_agent,
        to_agent="*",
        msg_type=msg_type,
        summary=summary,
        content=content,
        data=data,
    )

    hub = get_session_mailbox_hub(session_id)
    await hub.send(msg, turn=turn)

    return ok(
        summary=f"已向团队全体成员广播电文: {summary}",
        data={"message_id": msg.id, "summary": summary, "peer_message": msg.model_dump()},
    )


async def read_teammate_inbox(turn: Any, args: dict) -> dict:
    """查收当前智能体的信箱电文。"""
    clear_read = bool(args.get("clear_read", True))
    current_agent = getattr(turn, "agent_id", "agent").split("#")[0]
    session_id = getattr(turn, "session_id", "default")

    hub = get_session_mailbox_hub(session_id)
    messages = hub.drain(current_agent) if clear_read else hub.get_unread(current_agent)

    if not messages:
        return ok(summary="信箱暂无新电文", data={"messages": [], "count": 0})

    lines = [f"查收到 {len(messages)} 条队友新电文："]
    data_list = []
    for m in messages:
        lines.append(f"- @{m.from_agent} [{m.msg_type}]: {m.summary} ({m.content})")
        data_list.append(m.model_dump())

    return ok(
        summary="\n".join(lines),
        data={"messages": data_list, "count": len(messages)},
    )


def register_peer_tools(registry: ToolRegistry) -> None:
    """注册对等信箱工具集（全部注册为 common，各智能体均可调用）。"""
    registry.register(make_tool(
        "send_teammate_message",
        "向指定的协同智能体发送信箱电文（可注入体能红线、微地形坡度要求、微气候建议等）。",
        {
            "to_agent": {
                "type": "string",
                "enum": ["main", "health", "bds_nav", "weather", "guardian", "travel", "community"],
                "description": "接收方智能体名称",
            },
            "summary": {
                "type": "string",
                "description": "5-10字电文摘要（用于前端实时显像与气泡提示）",
            },
            "content": {
                "type": "string",
                "description": "电文详细内容（如'长辈右膝退行性关节炎，单次步行严控在500米内，避开台阶'）",
            },
            "msg_type": {
                "type": "string",
                "enum": ["direct", "proposal", "handoff", "ack", "task_assignment", "emergency"],
                "description": "电文类型，默认为 direct",
            },
            "data": {
                "type": "object",
                "description": "结构化参数字典（如 {'max_distance_m': 500, 'avoid_stairs': True, 'max_slope_percent': 3.0}）",
            },
        },
        send_teammate_message,
        agent="common",
    ))

    registry.register(make_tool(
        "broadcast_teammate_message",
        "向团队内所有协同智能体广播重要事件或安全预警电文。",
        {
            "summary": {
                "type": "string",
                "description": "5-10字广播摘要",
            },
            "content": {
                "type": "string",
                "description": "广播详细内容（如'检测到长辈心率过快，启动紧急防护模式'）",
            },
            "msg_type": {
                "type": "string",
                "enum": ["broadcast", "proposal", "emergency"],
                "description": "电文类型，默认为 broadcast",
            },
            "data": {
                "type": "object",
                "description": "结构化参数字典",
            },
        },
        broadcast_teammate_message,
        agent="common",
    ))

    registry.register(make_tool(
        "read_teammate_inbox",
        "查收当前智能体的信箱，获取队友发来的最新约束条件或协助请求。",
        {
            "clear_read": {
                "type": "boolean",
                "description": "是否标记为已读并清空未读队列，默认为 true",
            },
        },
        read_teammate_inbox,
        agent="common",
    ))
