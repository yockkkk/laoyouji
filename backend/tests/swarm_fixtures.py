"""Swarm Deliberation Test Fixtures and Reference Specification Oracle.

《银发导航智能体：基于多Agent协同的老年人安心出行伴侣》
端到端 (E2E) 群智研讨与高精导航 4-Tier 评测预言机 (Oracle) 与规约夹具。

涵盖：
1. F1: Teammate Mailbox 对等信箱通信协议
2. F2: Shared Task Board 共享任务看板与依赖调度
3. F3: GuardianAgent 独立安澜卫士规约
4. F4: Multi-Agent Peer Deliberation 群智多智能体闭环磋商
5. F5: SSE Real-Time Thinking & Handoff Stream 心智显像流
6. F6: 前端长辈关怀心智气泡与交接卡片契约
7. F7: 5-Agent 协同执行树与群智态势看板
8. F8: Adaptive Hierarchical Memory 分层认知记忆 (3-Tier Store)
9. F9: Proactive Context Care 主动情境关怀与免答记忆回溯
10. F10-F13: 适老 60fps 高精地图引擎契约 (手势隔离、整数瓦片、平滑缓动、GPU标记)
11. S1-S5: 长沙实景银发真实出行场景数据集与评测预言机
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field, ValidationError

# ==============================================================================
# F1: 对等信箱通信协议 (Peer Mailbox Protocol)
# ==============================================================================

VALID_AGENT_NAMES: Set[str] = {"main", "health", "bds_nav", "weather", "guardian"}
VALID_MSG_TYPES: Set[str] = {
    "direct",
    "broadcast",
    "proposal",
    "handoff",
    "ack",
    "task_assignment",
    "plan_approval_request",
    "plan_approval_response",
}


class PeerMessage(BaseModel):
    """多智能体对等信箱电文信封模型 (PROJECT.md § Interface Contracts 1)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    from_agent: str = Field(..., description="发送方 Agent 名称")
    to_agent: str = Field(..., description="接收方 Agent 名称或 '*' 全体广播")
    msg_type: str = Field(
        ...,
        description="电文类型: direct|broadcast|proposal|handoff|ack|task_assignment",
    )
    summary: str = Field(..., min_length=1, max_length=120, description="5-10字UI流式摘要")
    content: str = Field(..., description="电文完整正文")
    data: Dict[str, Any] = Field(default_factory=dict, description="结构化负载")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO8601 UTC时间戳",
    )
    read: bool = Field(default=False, description="是否已读")


class AgentMailbox:
    """智能体独立收件箱与发件箱。"""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self.inbox: List[PeerMessage] = []
        self.outbox: List[PeerMessage] = []

    def receive_message(self, message: PeerMessage) -> None:
        self.inbox.append(message)

    def send_message(
        self,
        to_agent: str,
        msg_type: str,
        summary: str,
        content: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> PeerMessage:
        msg = PeerMessage(
            from_agent=self.agent_name,
            to_agent=to_agent,
            msg_type=msg_type,
            summary=summary,
            content=content,
            data=data or {},
        )
        self.outbox.append(msg)
        return msg

    def get_unread_messages(self, mark_as_read: bool = True) -> List[PeerMessage]:
        unread = [m for m in self.inbox if not m.read]
        if mark_as_read:
            for m in unread:
                m.read = True
        return unread

    def peek_all(self) -> List[PeerMessage]:
        return list(self.inbox)

    def mark_read(self, message_id: str) -> bool:
        for m in self.inbox:
            if m.id == message_id:
                m.read = True
                return True
        return False

    def clear(self) -> None:
        self.inbox.clear()
        self.outbox.clear()


class SessionMailboxHub:
    """会话级多智能体信箱路由中枢。"""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.mailboxes: Dict[str, AgentMailbox] = {
            name: AgentMailbox(name) for name in VALID_AGENT_NAMES
        }
        self.audit_log: List[PeerMessage] = []

    def get_mailbox(self, agent_name: str) -> AgentMailbox:
        if agent_name not in self.mailboxes:
            self.mailboxes[agent_name] = AgentMailbox(agent_name)
        return self.mailboxes[agent_name]

    def route_message(self, message: PeerMessage) -> List[str]:
        """将电文投递至目的信箱。广播时投递给除自身外的所有智能体。返回送达的智能体列表。"""
        delivered_to: List[str] = []
        self.audit_log.append(message)

        if message.to_agent == "*":
            for name, box in self.mailboxes.items():
                if name != message.from_agent:
                    # 创建一份独立副本避免状态污染
                    clone = message.model_copy(update={"read": False})
                    box.receive_message(clone)
                    delivered_to.append(name)
        else:
            target_box = self.get_mailbox(message.to_agent)
            clone = message.model_copy(update={"read": False})
            target_box.receive_message(clone)
            delivered_to.append(message.to_agent)

        return delivered_to


# ==============================================================================
# F2: 共享任务看板与依赖图 (Shared Task Board & DAG)
# ==============================================================================

VALID_TASK_STATUSES: Set[str] = {"pending", "in_progress", "completed"}


class BoardTask(BaseModel):
    """共享任务看板项模型 (PROJECT.md § Interface Contracts 2)."""

    id: str = Field(..., description="高水位单调自增字符串ID, 如 '1', '2'")
    subject: str = Field(..., min_length=1, max_length=80, description="任务短标题")
    description: str = Field(..., description="详细验收标准与约束")
    active_form: str = Field(..., description="正在进行时短语，如 '正在规避陡坡与长阶梯'")
    owner: Optional[str] = Field(default=None, description="认领此任务的智能体名称")
    status: str = Field(default="pending", description="pending | in_progress | completed")
    blocks: List[str] = Field(default_factory=list, description="本任务阻断的后置任务ID")
    blocked_by: List[str] = Field(default_factory=list, description="本任务依赖的前置任务ID")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SharedTaskBoard:
    """支持原子认领防竞态、依赖阻断与级联解锁的共享任务看板。"""

    def __init__(self) -> None:
        self.tasks: Dict[str, BoardTask] = {}
        self._highwatermark: int = 0

    def add_task(
        self,
        subject: str,
        description: str,
        active_form: str,
        owner: Optional[str] = None,
        blocks: Optional[List[str]] = None,
        blocked_by: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BoardTask:
        self._highwatermark += 1
        task_id = str(self._highwatermark)
        task = BoardTask(
            id=task_id,
            subject=subject,
            description=description,
            active_form=active_form,
            owner=owner,
            status="pending",
            blocks=blocks or [],
            blocked_by=blocked_by or [],
            metadata=metadata or {},
        )
        self.tasks[task_id] = task

        # 双向同步 blocks / blocked_by 拓扑
        for dep_id in task.blocked_by:
            if dep_id in self.tasks and task_id not in self.tasks[dep_id].blocks:
                self.tasks[dep_id].blocks.append(task_id)

        for blocked_id in task.blocks:
            if blocked_id in self.tasks and task_id not in self.tasks[blocked_id].blocked_by:
                self.tasks[blocked_id].blocked_by.append(task_id)

        return task

    def claim_task_with_busy_check(self, task_id: str, agent_name: str) -> bool:
        """原子认领：若任务不存在、已被认领、有未完成前置依赖、或该智能体已有进行中任务，则拒绝。"""
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        if task.status != "pending" or task.owner is not None:
            return False

        # 检查前置依赖是否全部完成
        for dep_id in task.blocked_by:
            dep_task = self.tasks.get(dep_id)
            if dep_task is None or dep_task.status != "completed":
                return False

        # 检查该智能体是否已有进行中任务 (Busy Check)
        for t in self.tasks.values():
            if t.owner == agent_name and t.status == "in_progress":
                return False

        task.owner = agent_name
        task.status = "in_progress"
        return True

    def complete_task(self, task_id: str) -> bool:
        """完成任务并级联解除后续任务的 blocked_by 依赖。"""
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        task.status = "completed"

        # 级联解锁
        for other_id, other_task in self.tasks.items():
            if task_id in other_task.blocked_by:
                other_task.blocked_by.remove(task_id)

        return True

    def release_task(self, task_id: str) -> bool:
        """宕机或换人时回退任务至 pending 状态。"""
        if task_id not in self.tasks:
            return False
        task = self.tasks[task_id]
        task.owner = None
        task.status = "pending"
        return True

    def has_cycle(self) -> bool:
        """检测任务依赖是否存在环路 (DAG 检测)."""
        visited: Dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited

        def _dfs(node_id: str) -> bool:
            visited[node_id] = 1
            node = self.tasks.get(node_id)
            if node:
                for nxt in node.blocks:
                    if visited.get(nxt, 0) == 1:
                        return True
                    if visited.get(nxt, 0) == 0:
                        if _dfs(nxt):
                            return True
            visited[node_id] = 2
            return False

        for t_id in self.tasks:
            if visited.get(t_id, 0) == 0:
                if _dfs(t_id):
                    return True
        return False


# ==============================================================================
# F3: 独立安澜卫士 (GuardianAgent Specification)
# ==============================================================================

class GuardianAgentSpec:
    """安澜卫士 GuardianAgent 核心规约与能力模型。"""

    NAME: str = "guardian"
    DISPLAY_NAME: str = "安澜卫士"
    COLOR_PRIMARY: str = "#9B5DE5"
    COLOR_SECONDARY: str = "#AD1457"
    TOOL_NAMES: List[str] = [
        "monitor_safety_corridor",
        "detect_abnormal_dwell",
        "trigger_sos_reroute",
    ]

    @staticmethod
    def monitor_safety_corridor(
        current_lat: float,
        current_lng: float,
        corridor_polyline: List[Tuple[float, float]],
        corridor_tolerance_m: float = 30.0,
    ) -> Dict[str, Any]:
        """计算当前北斗点位距离计划安全走廊折线的最短垂直距离并判定是否偏航。"""
        if not corridor_polyline:
            return {"is_deviated": True, "distance_m": float("inf"), "status": "NO_CORRIDOR"}

        min_dist = float("inf")
        for i in range(len(corridor_polyline) - 1):
            p1 = corridor_polyline[i]
            p2 = corridor_polyline[i + 1]
            dist = point_to_segment_dist_m(current_lat, current_lng, p1[0], p1[1], p2[0], p2[1])
            if dist < min_dist:
                min_dist = dist

        is_deviated = min_dist > corridor_tolerance_m
        return {
            "is_deviated": is_deviated,
            "distance_m": round(min_dist, 2),
            "tolerance_m": corridor_tolerance_m,
            "status": "SAFE" if not is_deviated else "DEVIATED_ALERT",
        }

    @staticmethod
    def detect_abnormal_dwell(
        dwell_duration_min: float,
        is_at_rest_bench: bool = False,
        is_traffic_light: bool = False,
        threshold_min: float = 12.0,
    ) -> Dict[str, Any]:
        """异常长时间滞留检测 (有长椅或红绿灯时免除警报)。"""
        if is_at_rest_bench or is_traffic_light:
            return {
                "is_abnormal": False,
                "reason": "RESTING_BENCH_EXEMPTION" if is_at_rest_bench else "TRAFFIC_LIGHT_WAIT",
                "dwell_duration_min": dwell_duration_min,
            }

        is_abnormal = dwell_duration_min >= threshold_min
        return {
            "is_abnormal": is_abnormal,
            "reason": "PROLONGED_UNKNOWN_STATIONARY" if is_abnormal else "NORMAL_TEMPORARY_STOP",
            "dwell_duration_min": dwell_duration_min,
            "severity": "HIGH_ALERT" if dwell_duration_min >= threshold_min * 2 else ("WARN" if is_abnormal else "OK"),
        }

    @staticmethod
    def trigger_sos_reroute(
        elder_id: str,
        current_coords: Tuple[float, float],
        destination_hospital: str,
        guardian_phone: str,
    ) -> Dict[str, Any]:
        """触发一键 SOS 三甲医院避险绿通并生成双向告警。"""
        return {
            "sos_active": True,
            "elder_id": elder_id,
            "emergency_target": destination_hospital,
            "guardian_notified_phone": guardian_phone,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "priority": "P0_EMERGENCY_OVERRIDE",
            "green_corridor_id": f"SOS-GREEN-{uuid.uuid4().hex[:6].upper()}",
        }


def point_to_segment_dist_m(
    lat: float, lng: float,
    lat1: float, lng1: float,
    lat2: float, lng2: float,
) -> float:
    """平面近距离高保真点线距离近似 (长沙地区纬度 28.2°)."""
    # 局部米制投影: 1 deg lat ~ 111139 m, 1 deg lng ~ 111139 * cos(lat) m
    mean_lat_rad = math.radians((lat + lat1 + lat2) / 3.0)
    kx = 111139.0 * math.cos(mean_lat_rad)
    ky = 111139.0

    px, py = lng * kx, lat * ky
    x1, y1 = lng1 * kx, lat1 * ky
    x2, y2 = lng2 * kx, lat2 * ky

    dx = x2 - x1
    dy = y2 - y1
    segment_len_sq = dx * dx + dy * dy

    if segment_len_sq == 0.0:
        return math.hypot(px - x1, py - y1)

    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / segment_len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy

    return math.hypot(px - proj_x, py - proj_y)


# ==============================================================================
# F4: 多智能体群智研讨闭环 (Multi-Agent Peer Deliberation Engine)
# ==============================================================================

class PhysicalFatigueLimit(BaseModel):
    """体能约束红线 (Health -> BdsNav)."""

    knee_joint_osteoarthritis: bool = True
    max_slope_percent: float = Field(default=3.5, le=4.0)
    avoid_stairs: bool = True
    max_walking_distance_m: int = Field(default=600, le=1000)
    prefer_rest_benches: bool = True


class MicroWeatherReport(BaseModel):
    """微气象与林荫度报告 (Weather -> BdsNav)."""

    segment_id: str
    shade_coverage_percent: float = Field(..., ge=0.0, le=100.0)
    surface_temperature_c: float
    precipitation_mm_h: float
    wind_speed_m_s: float
    uv_index: float
    is_rainy_slippery: bool = False


class DeliberationCouncil:
    """多智能体群智闭环研讨中枢。"""

    def __init__(self, session_hub: SessionMailboxHub, task_board: SharedTaskBoard) -> None:
        self.hub = session_hub
        self.board = task_board
        self.deliberation_history: List[Dict[str, Any]] = []

    def conduct_deliberation(
        self,
        elder_fatigue: PhysicalFatigueLimit,
        candidate_segments: List[Dict[str, Any]],
        weather_reports: List[MicroWeatherReport],
    ) -> Dict[str, Any]:
        """运行一次典型的多智能体闭环磋商：
        1. Health 派发电文至 BdsNav 注入体能红线
        2. BdsNav 向 Weather 发起林荫与防滑评测查询
        3. Weather 回执气象报告
        4. BdsNav 综合评估输出最终适老路线
        """
        # Step 1: Health -> BdsNav
        msg1 = self.hub.get_mailbox("health").send_message(
            to_agent="bds_nav",
            msg_type="proposal",
            summary="注入膝关节受力红线与平缓坡度约束",
            content=f"长辈膝关节退行性病变：坡度限制<={elder_fatigue.max_slope_percent}%，全线避开台阶，单程<={elder_fatigue.max_walking_distance_m}米",
            data=elder_fatigue.model_dump(),
        )
        self.hub.route_message(msg1)

        # Step 2: BdsNav -> Weather
        msg2 = self.hub.get_mailbox("bds_nav").send_message(
            to_agent="weather",
            msg_type="direct",
            summary="查询候选步道微气象与林荫舒适度",
            content="请校验烈士公园西门与南门步道树荫覆盖度及短临降雨风险",
            data={"segments": [s["id"] for s in candidate_segments]},
        )
        self.hub.route_message(msg2)

        # Step 3: Weather -> BdsNav
        weather_map = {w.segment_id: w for w in weather_reports}
        msg3 = self.hub.get_mailbox("weather").send_message(
            to_agent="bds_nav",
            msg_type="ack",
            summary="反馈步道林荫与路面湿滑评测数据",
            content="西门环湖林荫道树荫覆盖率85%，南门阶梯无遮荫且微雨湿滑",
            data={"reports": [w.model_dump() for w in weather_reports]},
        )
        self.hub.route_message(msg3)

        # Step 4: BdsNav 过滤路线
        selected_route = None
        for seg in candidate_segments:
            seg_weather = weather_map.get(seg["id"])
            if elder_fatigue.avoid_stairs and seg.get("stairs_count", 0) > 0:
                continue
            if seg.get("slope_percent", 0.0) > elder_fatigue.max_slope_percent:
                continue
            if seg_weather and seg_weather.is_rainy_slippery and seg.get("stairs_count", 0) > 0:
                continue
            selected_route = seg
            break

        # Step 5: BdsNav 广播最终方案
        msg4 = self.hub.get_mailbox("bds_nav").send_message(
            to_agent="*",
            msg_type="handoff",
            summary="适老无障碍微地形最优路径生成完成",
            content=f"已选定无障碍平缓路线：{selected_route['name'] if selected_route else '未找到合适路线'}",
            data={"selected_route": selected_route},
        )
        self.hub.route_message(msg4)

        return {
            "status": "CONSENSUS_REACHED" if selected_route else "NO_VIABLE_ROUTE",
            "selected_route": selected_route,
            "messages_exchanged": len(self.hub.audit_log),
        }


# ==============================================================================
# F5: SSE 实时心智流协议 (Real-Time Thinking & Stream Pipeline)
# ==============================================================================

class ThinkingDeltaChunk(BaseModel):
    """心智流细粒度思考分块 (PROJECT.md § Interface Contracts 3)."""

    event: str = "thinking_delta"
    agent: str
    delta: str
    color: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentHandoffChunk(BaseModel):
    """智能体动态流光交接卡片分块."""

    event: str = "agent_handoff"
    from_agent: str
    to_agent: str
    reason: str
    agent_meta: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PeerMessageChunk(BaseModel):
    """信箱电文流式推送分块."""

    event: str = "peer_message"
    from_agent: str
    to_agent: str
    summary: str
    preview: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskBoardSyncChunk(BaseModel):
    """看板同步分块."""

    event: str = "task_board_sync"
    tasks: List[Dict[str, Any]]
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def format_sse_event(event_name: str, payload: Dict[str, Any]) -> str:
    """标准 SSE 事件序列化: event: <name>\ndata: <json>\n\n"""
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ==============================================================================
# F6 & F7: 前端长辈关怀心智气泡、交接卡片与5-Agent协同看板
# ==============================================================================

AGENT_THEME_COLORS: Dict[str, str] = {
    "main": "#E65100",      # 暖心橙
    "health": "#67C23A",    # 健康绿
    "bds_nav": "#409EFF",   # 北斗蓝
    "weather": "#E6A23C",   # 气象金
    "guardian": "#9B5DE5",  # 守护紫
}

AGENT_AVATAR_TITLES: Dict[str, str] = {
    "main": "康乐总管",
    "health": "安康助手",
    "bds_nav": "北斗导航",
    "weather": "气象感知",
    "guardian": "安澜卫士",
}


def create_elder_thinking_bubble(agent: str, raw_thought: str) -> Dict[str, Any]:
    """将智能体技术思考转换为长辈温情口吻的思考气泡文本。"""
    color = AGENT_THEME_COLORS.get(agent, "#909399")
    elder_phrasing = raw_thought
    if agent == "health":
        elder_phrasing = f"正在为您调取近期体检与膝盖关节受力情况…"
    elif agent == "bds_nav":
        elder_phrasing = f"北斗高精定位正在为您勘测沿途是否有陡坡和高台阶…"
    elif agent == "weather":
        elder_phrasing = f"正在感知沿途树荫覆盖与实时降雨湿度…"
    elif agent == "guardian":
        elder_phrasing = f"正在为您规划全程安心步道并建立家人守护通道…"

    return {
        "agent": agent,
        "title": AGENT_AVATAR_TITLES.get(agent, agent),
        "color": color,
        "raw_thought": raw_thought,
        "elder_text": elder_phrasing,
    }


def create_agent_handoff_card(from_agent: str, to_agent: str, reason: str) -> Dict[str, Any]:
    """生成流光交接卡片规范数据。"""
    return {
        "transition_title": f"@{from_agent} ▶ @{to_agent}",
        "from_agent": from_agent,
        "to_agent": to_agent,
        "from_color": AGENT_THEME_COLORS.get(from_agent, "#909399"),
        "to_color": AGENT_THEME_COLORS.get(to_agent, "#909399"),
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ==============================================================================
# F8 & F9: 自适应分层认知记忆与主动情境关怀 (Hierarchical Memory & Care)
# ==============================================================================

class EpisodicMemoryEntry(BaseModel):
    """情景记忆单条流转日志."""

    cursor: int
    timestamp: str
    summary: str
    facts: List[str] = Field(default_factory=list)


class HierarchicalMemoryStore:
    """3-Tier 自适应分层认知记忆存储引擎:
    Tier 1: 内存 Live Context
    Tier 2: Token预算滚动情景记忆 ledger (episodic_history.jsonl)
    Tier 3: 深度睡眠提炼长辈画像档案 (ELDER_PROFILE.md)
    """

    def __init__(self, base_dir: Path, user_id: str) -> None:
        self.user_dir = base_dir / "users" / user_id
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.episodic_file = self.user_dir / "episodic_history.jsonl"
        self.profile_file = self.user_dir / "ELDER_PROFILE.md"

    def record_episode(self, summary: str, facts: List[str]) -> EpisodicMemoryEntry:
        """追加一条情景事实日志."""
        entries = self.load_episodic_entries()
        cursor = len(entries) + 1
        entry = EpisodicMemoryEntry(
            cursor=cursor,
            timestamp=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            facts=facts,
        )
        with open(self.episodic_file, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")
        return entry

    def load_episodic_entries(self) -> List[EpisodicMemoryEntry]:
        if not self.episodic_file.exists():
            return []
        res = []
        with open(self.episodic_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        res.append(EpisodicMemoryEntry.model_validate_json(line))
                    except Exception:
                        continue
        return res

    def consolidate_profile(self, profile_markdown: str) -> None:
        """持久化提炼的长辈核心健康与偏好档案。"""
        with open(self.profile_file, "w", encoding="utf-8") as f:
            f.write(profile_markdown)

    def load_profile(self) -> str:
        if not self.profile_file.exists():
            return ""
        with open(self.profile_file, "r", encoding="utf-8") as f:
            return f.read()

    def get_elder_context(self) -> str:
        """自动注入每一轮 Prompt 的上下文认知切片 (F9 主动关怀核心)."""
        profile = self.load_profile()
        episodes = self.load_episodic_entries()
        recent_facts: List[str] = []
        for ep in episodes[-3:]:
            recent_facts.extend(ep.facts)

        facts_block = "\n".join(f"- {f}" for f in set(recent_facts)) if recent_facts else "- 暂无近期新增情景事实"

        return (
            f"# 银发长辈自适应认知记忆档案（严禁让长辈重复陈述已有事实）：\n"
            f"## 长期认知档案 (ELDER_PROFILE.md)\n"
            f"{profile or '暂无持久画像'}\n\n"
            f"## 近期情景记忆增量 (Recent Episodic Facts)\n"
            f"{facts_block}\n"
        )


# ==============================================================================
# F10-F13: 适老 60fps 导航地图性能契约 (Map 60fps Contract)
# ==============================================================================

class MapPerformanceContract:
    """适老高精地图手势隔离与 60fps 丝滑渲染规约验证器。"""

    REQUIRED_CONTAINER_CSS = {
        "touch-action": "none",
        "-webkit-overflow-scrolling": "auto",
    }

    REQUIRED_LEAFLET_OPTIONS = {
        "zoomSnap": 1,
        "zoomDelta": 1,
        "fadeAnimation": True,
        "markerZoomAnimation": True,
    }

    REQUIRED_GPU_MARKER_CSS = {
        "will-change": "transform",
        "transform": "translateZ(0)",
    }

    @staticmethod
    def verify_css_isolation(css_declarations: Dict[str, str]) -> Tuple[bool, List[str]]:
        errors = []
        for prop, expected in MapPerformanceContract.REQUIRED_CONTAINER_CSS.items():
            actual = css_declarations.get(prop)
            if actual != expected:
                errors.append(f"CSS property '{prop}' expected '{expected}', got '{actual}'")
        return len(errors) == 0, errors

    @staticmethod
    def verify_leaflet_zoom_options(options: Dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = []
        if options.get("zoomSnap") != 1:
            errors.append(f"zoomSnap must be exactly 1 to prevent raster tile blur, got {options.get('zoomSnap')}")
        if options.get("zoomDelta") != 1:
            errors.append(f"zoomDelta must be exactly 1, got {options.get('zoomDelta')}")
        return len(errors) == 0, errors

    @staticmethod
    def calculate_smooth_flyto_trajectory(
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        duration_sec: float = 0.8,
        ease_linearity: float = 0.25,
        fps: int = 60,
    ) -> List[Tuple[float, float, float]]:
        """计算平滑缓动飞行动画在 60fps 下的每一帧坐标与帧耗时 (验证单帧 <= 16.6ms)."""
        frames: List[Tuple[float, float, float]] = []
        total_frames = max(1, int(duration_sec * fps))
        frame_interval_ms = 1000.0 / fps

        for i in range(total_frames + 1):
            t = i / total_frames
            # 三次贝塞尔拟合 ease-out
            ease_t = 1.0 - math.pow(1.0 - t, 3)
            cur_lat = start_lat + (end_lat - start_lat) * ease_t
            cur_lng = start_lng + (end_lng - start_lng) * ease_t
            frames.append((round(cur_lat, 6), round(cur_lng, 6), frame_interval_ms))

        return frames


# ==============================================================================
# S1-S5: 长沙实景大赛业务全链路数据集 (Changsha Real-World Datasets)
# ==============================================================================

CHANGSHA_REALWORLD_FIXTURES: Dict[str, Any] = {
    "S1_MARTYRS_PARK": {
        "elder_id": "elder_cs_001",
        "elder_name": "刘爷爷",
        "chronic_conditions": ["双侧膝关节骨性关节炎", "轻度心肌劳损"],
        "origin_community": "华夏路社区",
        "origin_coords": (28.2241, 112.9842),
        "destination": "湖南烈士公园",
        "gates": {
            "south_gate": {
                "name": "烈士公园南门",
                "coords": (28.2045, 112.9928),
                "stairs_count": 68,
                "slope_percent": 8.5,
                "shade_percent": 30.0,
                "suitable_for_arthritis": False,
            },
            "west_gate": {
                "name": "烈士公园西门 (无障碍缓坡通道)",
                "coords": (28.2120, 112.9880),
                "stairs_count": 0,
                "slope_percent": 2.2,
                "shade_percent": 88.0,
                "suitable_for_arthritis": True,
            },
        },
    },
    "S2_XIANGYA_HOSPITAL": {
        "elder_id": "elder_cs_002",
        "elder_name": "张奶奶",
        "origin": (28.2215, 112.9830),
        "destination": "中南大学湘雅医院",
        "destination_coords": (28.2155, 112.9865),
        "corridor_width_m": 25.0,
        "rest_benches": [
            {"id": "bench_xy_1", "coords": (28.2190, 112.9845), "shade": True},
            {"id": "bench_xy_2", "coords": (28.2170, 112.9855), "shade": True},
        ],
    },
    "S3_DOWNPOUR_REROUTE": {
        "elder_id": "elder_cs_003",
        "elder_name": "王爷爷",
        "start_coords": (28.2180, 112.9850),
        "target_park": "烈士公园环湖步道",
        "sudden_rain_mm_h": 35.0,
        "shelters": [
            {"id": "pavilion_1", "name": "寄情亭雨廊", "coords": (28.2185, 112.9856), "distance_m": 65},
            {"id": "pavilion_2", "name": "东便门茶室", "coords": (28.2220, 112.9910), "distance_m": 650},
        ],
    },
    "S4_GUARDIAN_SOS": {
        "elder_id": "elder_cs_004",
        "elder_name": "周老伯",
        "child_phone": "13873199888",
        "corridor": [(28.2200, 112.9840), (28.2180, 112.9850), (28.2160, 112.9860)],
        "deviated_point": (28.2175, 112.9885),  # 偏离走廊 280米 (建筑工地危险区)
        "nearest_tertiary_hospital": "湖南省人民医院",
    },
    "S5_HABIT_PERSISTENCE": {
        "elder_id": "elder_cs_005",
        "elder_name": "陈奶奶",
        "day1_dialogue": "我这右腿膝盖一受凉下楼梯就钻心疼，千万别给我走有台阶的地方。",
        "day1_extracted_constraint": "右膝骨关节炎，绝对禁用台阶步道，最大平路步行距离400米",
        "day2_prompt": "闺女，我想去楼下小公园透透气，怎么走好？",
    },
}
