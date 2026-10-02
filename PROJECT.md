# Project: LaoYouJi Silver-Age Navigation Agent Anti-Drift & Real-Time Navigation Elevation

## Architecture
- **Backend Architecture**:
  - FastAPI event-sourced micro-kernel with write-behind logging (`events.py`), session driver (`session.py`), and turn gate (`turn_gate.py`).
  - **Explicit Topic Anchor & Context Governance (`app/core/topic_anchor.py`, `app/core/context.py`)**: Inspired by Claude Code (`context.ts`, `compact.ts`). Maintains active intent (`activity_type`: `LEISURE_WALK` vs `MEDICAL_ESCORT`), `target_destination`, `origin`, and physical constraints across multi-turn interactions. Enforces intent isolation and prevents semantic drift.
  - **Modular Layered SystemPrompt Architecture (`app/core/system_prompt_sections.py`, `app/agents/main_agent.py`)**: Inspired by Claude Code (`systemPromptSections.ts`, `prompts.ts`). Assembles system prompts from distinct modular sections (`BaseRoleSection`, `ParkWalkSOPSection`, `MedicalSOPSection`, `NegativeConstraintsSection`, `DynamicSituationalSection`) with scenario equality between park walk and medical escort.
  - **PlanBuilder Decoupling (`app/agents/plan_builder.py`)**: Decouples `build_bds_escort_plan` into `bds_walk_escort_plan` (park name, gentle gradient, bench count, zero hospital/doctor fields) and `bds_medical_escort_plan`.
  - **Peer Mailbox & Constraint Propagation (`app/core/mailbox.py`, `app/agents/health_agent.py`, `app/agents/bds_nav_agent.py`)**: HealthAgent injects mobility constraints (`avoid_stairs: true`, `max_slope_percent <= 3.0%`, `prefer_rest_benches: true`) directly into BdsNavAgent via teammate mailbox.
  - **Intent-Driven Tool Dispatch (`app/tools/bds_nav.py`, `app/agents/main_agent.py`, `app/mock.py`)**: Immediate invocation of `bds_escort_route` / `plan_route` when user requests route or expresses navigation intent.
- **Frontend Architecture**:
  - Uni-app Vue 3 H5 / mobile container.
  - **PlanCard High Visibility & Route Action (`frontend/laoyouji-app/src/components/PlanCard.vue`)**: Fixed `hasRouteAction` computed property supporting park walk cards (`compact: false`, walk keyword matching). Prominent button rendering: "🗺️ 开启北斗安心导航 / 查看路线".
  - **Chat Action Dispatcher (`frontend/laoyouji-app/src/pages/elder/chat.vue`)**: Speech and text interceptor for navigation requests ("我要跟着导航走"), triggering direct one-click launch of route map.
  - **Real-Time 60fps Route Map (`frontend/laoyouji-app/src/pages/elder/route-map.vue`)**: Leaflet rendering with 25-meter safety corridor visualization, zero-stair gentle path display, and smooth animated easing.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Explicit Topic Anchor Model & State Machine | `TopicAnchor` tracking `activity_type`, `target_destination`, `origin`, `constraints` | M1 | R1, Claude Code context.ts |
| F2 | Context Conflict Interceptor & Anti-Drift Guard | Enforces intent isolation (blocks drift from LEISURE_WALK to MEDICAL_ESCORT) | M1 | R1, Claude Code compact.ts |
| F3 | History Dialogue Pruning & Intent Preservation | Prunes dialogue noise while preserving task quotes and active anchor | M1 | R1, Claude Code messages.ts |
| F4 | Modular SystemPrompt Architecture | Split monolithic prompt into structured, cache-friendly sections (`system_prompt_sections.py`) | M2 | R2, Claude Code systemPromptSections.ts |
| F5 | Park Walk SOP & Scenario Equality | First-class park walking closed loop (park destination -> health constraints -> bds nav -> weather -> card) | M2 | R2, LaoYouJi Spec |
| F6 | Strong Negative Constraints Guard | Red-line rules prohibiting unsolicited medical registration recommendations during walks | M2 | R2, Claude Code prompts.ts |
| F7 | Teammate Mailbox Mobility Constraint Injection | HealthAgent -> BdsNavAgent constraint transmission (`avoid_stairs`, slope < 3%, benches) | M2 | R3, Claude Code teammateMailbox.ts |
| F8 | PlanBuilder Walk/Medical Decoupling | Separate `bds_walk_escort_plan` (pure park/walk) from `bds_medical_escort_plan` | M3 | R4, Spec |
| F9 | Dynamic Destination Extraction | Dynamically extract user-specified destination (e.g. 烈士公园年嘉湖) without hospital fallback | M3 | R4, Spec |
| F10 | PlanCard `hasRouteAction` & Button Visibility | Fix computed property in `PlanCard.vue` and display "🗺️ 开启北斗安心导航 / 查看路线" | M4 | R3, Spec |
| F11 | 1-Click Launch to Real-Time Route Map | Chat action & button launch to `/pages/elder/route-map` with origin/destination query params | M4 | R3, Spec |
| F12 | Leaflet 25m Safety Corridor Visual Layer | Visual corridor polygon/buffer layer on `route-map.vue` | M4 | R3, Spec |
| F13 | Full Regression & Anti-Drift E2E Suite (Tiers 1-4) | 100% pass of existing 918 tests + 5-turn park walk anti-drift + intent isolation | M5 | Acceptance Criteria |
| F14 | White-Box Adversarial Hardening (Tier 5) | Adversarial stress testing for rapid intent shifts, malformed destinations, boundary cases | M5 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Context Governance & Topic Anchor Anti-Drift Engine | F1, F2, F3 | none | IN_PROGRESS |
| M2 | Modular SystemPrompt & Swarm Constraint Injection | F4, F5, F6, F7 | M1 | PLANNED |
| M3 | PlanBuilder Decoupling & Dynamic Destination Extraction | F8, F9 | M1 | PLANNED |
| M4 | Navigation Action Pipeline & Frontend Synergy | F10, F11, F12 | M2, M3 | PLANNED |
| M5 | Final E2E Acceptance & Adversarial Hardening | F13, F14 | M1, M2, M3, M4 | PLANNED |

## Interface Contracts

### 1. Topic Anchor Contract (`app/core/topic_anchor.py`)
```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class ActivityType(str, Enum):
    IDLE = "idle"
    LEISURE_WALK = "leisure_walk"
    MEDICAL_ESCORT = "medical_escort"
    DAILY_COMPANION = "daily_companion"

class TopicAnchor(BaseModel):
    activity_type: ActivityType = ActivityType.IDLE
    target_destination: Optional[str] = None
    origin: Optional[str] = "家"
    target_spot: Optional[str] = None
    health_constraints: Dict[str, Any] = Field(default_factory=dict)
    confirmed_steps: List[str] = Field(default_factory=list)
    lock_turns_remaining: int = 0  # turns to lock against accidental drift
```

### 2. Modular SystemPrompt Sections Contract (`app/core/system_prompt_sections.py`)
```python
class SystemPromptSection(BaseModel):
    name: str
    content: str
    is_cacheable: bool = True

def build_modular_system_prompt(
    agent_name: str,
    topic_anchor: Optional[TopicAnchor] = None,
    elder_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Combines BaseRole + ScenarioSOP + NegativeConstraints + DynamicContext."""
    ...
```

### 3. Decoupled PlanBuilder Contract (`app/agents/plan_builder.py`)
```python
def build_bds_walk_escort_plan(data: dict) -> Deliverable:
    """Builds a 5-page walk escort plan strictly for parks, lakes, and walking trails.
    Page 1: 适老目的地与步道体征适配 (Park name, barrier-free grade, gentle slope, benches).
    Page 2: 适老微地形路段指引.
    Page 3: 北斗长辈体能与慢病守护.
    Page 4: 实时微气象与户外出行建议.
    Page 5: 子女关爱与应急长椅补给.
    ABSOLUTELY NO hospital, department, doctor, or appointment registration rows.
    """
    ...

def build_bds_medical_escort_plan(data: dict) -> Deliverable:
    """Builds a medical escort plan specifically for hospital appointments."""
    ...
```

### 4. Frontend Route Action Contract (`PlanCard.vue` ➔ `chat.vue` ➔ `route-map.vue`)
- `PlanCard.vue`:
  - `hasRouteAction`: Returns `true` if `plan_type` in `['bds_walk_escort_plan', 'bds_escort_plan', 'trip_plan', 'medical_plan']` OR text includes `['散步', '漫步', '公园', '绿道', '就医', '出行', '路线', '医院']`.
  - Button Action: Emits `route-action` event with payload `{ origin, destination, trip_id, plan_type }`.
  - Label: `🗺️ 开启北斗安心导航 / 查看路线`.
- `chat.vue`:
  - Intercepts `"我要跟着导航走"` or handles `route-action` event.
  - Directly launches `/pages/elder/route-map?origin=...&destination=...&title=...`.

## Code Layout
- Backend:
  - `backend/app/core/topic_anchor.py` (New: Topic Anchor & State Machine)
  - `backend/app/core/system_prompt_sections.py` (New: Modular prompt builder)
  - `backend/app/core/session.py` (Integrate TopicAnchor into AgentDriver)
  - `backend/app/core/context.py` (Context conflict interception & pruning)
  - `backend/app/agents/main_agent.py` (Reconstructed with modular prompt & walk SOP)
  - `backend/app/agents/health_agent.py` (Registered `send_teammate_message`)
  - `backend/app/agents/bds_nav_agent.py` (Handle mailbox mobility constraints)
  - `backend/app/agents/plan_builder.py` (Decoupled `bds_walk_escort_plan`)
  - `backend/app/mock.py` (Anti-drift heuristics in MockLLMProvider)
- Frontend:
  - `frontend/laoyouji-app/src/components/PlanCard.vue` (`hasRouteAction` & button styling)
  - `frontend/laoyouji-app/src/pages/elder/chat.vue` (Compact logic & action dispatcher)
  - `frontend/laoyouji-app/src/pages/elder/route-map.vue` (Corridor visual rendering)
- Tests:
  - `backend/tests/` (Existing 918 tests)
  - `backend/tests/test_topic_anchor.py` (Topic Anchor unit tests)
  - `backend/tests/test_system_prompt_sections.py` (Modular prompt unit tests)
  - `backend/tests/test_plan_builder_walk.py` (Decoupled walk plan tests)
  - `backend/tests/test_anti_drift_e2e.py` (5-turn park walk conversation E2E test)
