# Project: LaoYouJi Multi-Agent & Navigation Map Elevation

## Architecture
- **Backend Architecture**:
  - FastAPI event-sourced micro-kernel with write-behind logging (`events.py`) and turn gate (`turn_gate.py`).
  - **Teammate Mailbox Hub (`app/core/mailbox.py`)**: Peer-to-peer mailbox messaging protocol inspired by Claude Code (`teammateMailbox.ts`) and Nanobot (`loop.py` `_pending_queues`). Supports direct messages, broadcasts, proposals, handoffs, and acknowledgments.
  - **Shared Task Board (`app/core/tasks.py`)**: Inspired by Claude Code (`tasks.ts`), provides monotonic IDs, atomic task claiming (`claim_task_with_busy_check`), dynamic dependency DAG (`blocks`/`blocked_by`), and state transitions (`pending` -> `in_progress` -> `completed`).
  - **Standalone GuardianAgent (`app/agents/guardian_agent.py`)**: Implements `BaseAgent` for safety geofencing, route compliance supervision, abnormal dwell alerts, and SOS green channel routing.
  - **Real-Time Thinking & Stream Pipeline (`app/core/session.py`, `app/api/routes_chat.py`)**: 5-stage stream state machine emitting `thinking_delta`, `agent_handoff`, `peer_message`, `task_board_sync` over SSE.
  - **Adaptive Hierarchical Memory (`app/core/memory.py`)**: 3-tier memory consolidation inspired by Nanobot (`memory.py`) and Claude Code (`teamMemoryOps.ts`) (Live context -> Token-budget consolidation into `episodic_history.jsonl` -> Dream consolidation into `ELDER_PROFILE.md`).
- **Frontend Architecture**:
  - Uni-app Vue 3 H5 / mobile container.
  - **Elderly Humanized Dialogue Stream (`chat.vue`)**: Real-time thinking bubbles (`ThinkingTraceBubble`) with warm elder phrasing, dynamic agent handoff cards (`AgentHandoffCard`) displaying theme colors and transitions (`@health ▶ @bds_nav`).
  - **Multi-Agent Deliberation Tree (`AgentExecutionTree.vue`)**: Visualizes all 5 agents (Main, Health, BdsNav, Weather, Guardian) with active peer mailbox message logs and shared task board status.
  - **60fps Smooth Map Navigation Engine (`route-map.vue`)**: Leaflet raster tile rendering with `touch-action: none` gesture isolation, integer tile zoom (`zoomSnap: 1`), smooth cubic-bezier `flyTo`/`panTo` easing curves, and GPU hardware-accelerated elder live pulse marker pane.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Peer Mailbox Protocol | `AgentMailbox` & `SessionMailboxHub` for P2P and broadcast messaging | M1 | R1, Claude Code |
| F2 | Shared Task Board | `SharedTaskBoard` with atomic claiming, monotonic IDs, dependency blocking | M1 | R1, Claude Code |
| F3 | GuardianAgent Standalone Class | Dedicated agent class inheriting `BaseAgent` with safety tools & theme | M1 | R1, LaoYouJi |
| F4 | Multi-Agent Peer Deliberation | Health->BdsNav constraint injection, BdsNav->Weather query in agent loops | M1 | R1, Nanobot |
| F5 | SSE Real-time Thinking & Handoff Stream | Backend stream pipeline emitting `thinking_delta`, `agent_handoff`, `peer_message` | M2 | R2, Claude Code & Nanobot |
| F6 | Frontend Elder Thinking Bubble & Handoff Card | Animated warm thinking bubbles and agent handoff transition cards in `chat.vue` | M2 | R2, Claude Code |
| F7 | 5-Agent Execution Tree & Swarm Board | Full visualization of 5 agents, peer messaging logs, and task board in `AgentExecutionTree.vue` | M2 | R2, LaoYouJi |
| F8 | Adaptive Hierarchical Memory Store | 3-tier store (`episodic_history.jsonl`, `ELDER_PROFILE.md`, consolidation engine) | M3 | R3, Nanobot & Claude Code |
| F9 | Proactive Context Care & Recall | Turn start auto-loading of physical limits, frequent landmarks, and proactive accompaniment | M3 | R3, Nanobot |
| F10 | Map Gesture Isolation | `touch-action: none` and `@touchmove.stop` on Leaflet container preventing scroll conflict | M4 | R4, Spec |
| F11 | Native Integer Tile Zoom | `zoomSnap: 1, zoomDelta: 1` preventing raster tile blurring and layout recalculation | M4 | R4, Spec |
| F12 | Smooth Easing Viewport Transitions | Cubic-bezier `flyTo` / `panTo` animation replacing abrupt `setView` snaps | M4 | R4, Spec |
| F13 | GPU Hardware-Accelerated Marker Layer | `will-change: transform`, `translateZ(0)` on elder live pulse marker for stable 60fps | M4 | R4, Spec |
| F14 | 100% E2E Pass & Regression Baseline | Full pass on all 721 existing backend tests + new test tiers + `npm run build:h5` | M5 | Acceptance Criteria |
| F15 | Adversarial Coverage Hardening | White-box adversarial testing (Tier 5): concurrency stress, edge conditions, fault recovery | M6 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Multi-Agent Swarm, Peer Mailbox & GuardianAgent | F1, F2, F3, F4 | none | PLANNED |
| M2 | Real-Time Thinking Stream & Frontend Handoff | F5, F6, F7 | M1 | PLANNED |
| M3 | Adaptive Hierarchical Memory & Proactive Care | F8, F9 | M1 | PLANNED |
| M4 | 60fps Smooth Map Navigation Engine | F10, F11, F12, F13 | none | PLANNED |
| M5 | Final Integration & E2E Acceptance (Tiers 1-4) | F14 | M1, M2, M3, M4 | PLANNED |
| M6 | Adversarial Coverage Hardening (Tier 5) | F15 | M5 | PLANNED |

## Interface Contracts

### 1. Peer Mailbox Envelope Contract (`app/core/mailbox.py`)
```python
class PeerMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    from_agent: str      # "main", "health", "bds_nav", "weather", "guardian"
    to_agent: str        # target agent name or "*" for broadcast
    msg_type: str        # "direct", "broadcast", "proposal", "handoff", "ack", "task_assignment"
    summary: str         # 5-10 word summary for UI display
    content: str         # full content
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str      # ISO8601 UTC
    read: bool = False
```

### 2. Shared Task Board Contract (`app/core/tasks.py`)
```python
class BoardTask(BaseModel):
    id: str              # monotonic string "1", "2", "3"
    subject: str         # short task title
    description: str     # detailed acceptance criteria
    active_form: str     # present participle (e.g. "正在规避陡坡与长阶梯")
    owner: str | None    # assigned agent name
    status: str          # "pending" | "in_progress" | "completed"
    blocks: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 3. SSE Stream Chunk Contract (`backend/app/api/routes_chat.py` ➔ `frontend/laoyouji-app/src/api/sse.js`)
- `event: thinking_delta`: `{"agent": "health", "delta": "检索长辈骨科病史...", "color": "#67C23A"}`
- `event: peer_message`: `{"from": "health", "to": "bds_nav", "summary": "注入膝关节受力红线", "preview": "单程≤600米"}`
- `event: agent_handoff`: `{"from_agent": "health", "to_agent": "bds_nav", "reason": "体能约束已明确，交由北斗导航计算微地形", "agent_meta": {...}}`
- `event: task_board_sync`: `{"tasks": [...]}`

### 4. Hierarchical Cognitive Memory Contract (`app/core/memory.py`)
- Directory: `data/memory/users/{user_id}/`
- `ELDER_PROFILE.md`: Chronic health constraints, fatigue thresholds, high-frequency landmarks, guardian preferences.
- `episodic_history.jsonl`: Monotonic chronological ledger (`cursor`, `timestamp`, `summary`, `facts`).
- Method: `get_elder_context(user_id) -> str` (injected automatically into every turn prompt).

### 5. Map 60fps Contract (`route-map.vue`)
- CSS: `#elder-amap-container, .amap-box { touch-action: none; -webkit-overflow-scrolling: auto; }`
- Leaflet Options: `zoomSnap: 1, zoomDelta: 1`
- Animation: `flyTo(latlng, zoom, { animate: true, duration: 0.8, easeLinearity: 0.25 })`
- Pulse Marker: GPU composite layer `transform: translateZ(0); will-change: transform;`

## Code Layout
- Backend Source: `backend/app/`
  - Core: `backend/app/core/` (`mailbox.py`, `tasks.py`, `memory.py`, `session.py`, `events.py`, `bus.py`, `subagents.py`)
  - Agents: `backend/app/agents/` (`base.py`, `main_agent.py`, `health_agent.py`, `bds_nav_agent.py`, `weather_agent.py`, `guardian_agent.py`)
  - API Routes: `backend/app/api/` (`routes_chat.py`, `routes_guardian.py`)
- Frontend Source: `frontend/laoyouji-app/src/`
  - Pages: `frontend/laoyouji-app/src/pages/elder/` (`chat.vue`, `route-map.vue`)
  - Components: `frontend/laoyouji-app/src/components/` (`AgentExecutionTree.vue`, `AgentHandoffCard.vue`, `ThinkingTraceBubble.vue`)
  - API Client: `frontend/laoyouji-app/src/api/` (`sse.js`, `chat.js`)
- Tests: `backend/tests/` (721 tests existing + new milestone tests)
