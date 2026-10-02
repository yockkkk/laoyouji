# E2E Test Infra: LaoYouJi Anti-Drift & Real-Time Navigation Elevation

## 1. Test Philosophy & Methodological Framework

### 1.1 Objective & Scope
The LaoYouJi Silver-Age Navigation Agent is designed to provide proactive, barrier-free, and compassionate mobility assistance for elderly users. The primary architectural objective is to eradicate semantic drift—specifically, the critical failure mode where an elderly user's request for a leisure park walk ("想去散步") is mistakenly conflated into hospital appointment triage ("去医院挂号看病").

This test infrastructure document establishes a requirement-driven, 4-tier verification suite grounded strictly in:
1. `ORIGINAL_REQUEST.md` (Specifically the authoritative elevation prompt `## 2026-10-02T11:28:39Z`)
2. `PROJECT.md` (Architecture, Milestones M1-M5, and Interface Contracts 1-4)
3. Explorer and Spec Miner Survey findings (`findings.md`)

### 1.2 4-Tier Testing Methodology
Testing is organized hierarchically into four distinct, non-overlapping tiers:

```
+-------------------------------------------------------------------------+
| Tier 4: Real-World Scenarios (S1-S4)                                    |
| Exact 5-Turn Park Walk Conversation, Acute Distress Escalations         |
+-------------------------------------------------------------------------+
                                    ▲
+-------------------------------------------------------------------------+
| Tier 3: Cross-Feature Interactions (C1-C4)                             |
| HealthAgent Knee Constraint ➔ BdsNavAgent Route ➔ PlanBuilder Synergy   |
+-------------------------------------------------------------------------+
                                    ▲
+-------------------------------------------------------------------------+
| Tier 2: Boundary & Corner Cases (B1-B5)                                 |
| Empty Fallbacks, Rapid Intent Switches, Non-standard Parks, Colloquial  |
+-------------------------------------------------------------------------+
                                    ▲
+-------------------------------------------------------------------------+
| Tier 1: Feature Coverage (>=5 tests per core feature)                   |
| F1 Topic Anchor | F2 Anti-Drift Guard | F3 Modular Prompt               |
| F4 Decoupled Walk Plan | F5 Route Action Pipeline                       |
+-------------------------------------------------------------------------+
```

- **Tier 1 (Feature Coverage)**: Validates nominal interface contracts and state transitions for each isolated component (>=5 tests per feature).
- **Tier 2 (Boundary & Corner Cases)**: Exercises boundary values, edge inputs, empty strings, rapid intent oscillations, and adversarial dialect inputs without hospital fallback.
- **Tier 3 (Cross-Feature Interactions)**: Tests multi-agent constraint transmission across teammate mailboxes, state synchronization between TopicAnchor and ModularPrompt, and synergy with PlanBuilder.
- **Tier 4 (Real-World Scenarios)**: Validates full multi-turn conversational lifecycles, specifically the exact 5-turn park walk sequence from the user incident screenshot, verifying zero medical drift across all turns.

---

## 2. Feature Inventory & Test Coverage Matrix

| Feature ID | Feature Name | Requirement Ref | Tier 1 (>=5) | Tier 2 (>=5) | Tier 3 (Pairwise) | Tier 4 (Real-World) |
|---|---|---|:---:|:---:|:---:|:---:|
| **F1** | Explicit Topic Anchor Model & State Machine | R1 (`PROJECT.md § Contract 1`) | 6 | 5 | ✓ | ✓ |
| **F2** | Context Conflict Interceptor & Anti-Drift Guard | R1 (`ORIGINAL_REQUEST.md R1`) | 6 | 5 | ✓ | ✓ |
| **F3** | Modular Dynamic SystemPrompt Architecture | R2 (`PROJECT.md § Contract 2`) | 5 | 5 | ✓ | ✓ |
| **F4** | Decoupled PlanBuilder (`bds_walk_escort_plan`) | R4 (`PROJECT.md § Contract 3`) | 6 | 5 | ✓ | ✓ |
| **F5** | Route Action & Navigation Launch Pipeline | R3 (`PROJECT.md § Contract 4`) | 5 | 5 | ✓ | ✓ |

### Matrix Summary
- **Tier 1**: 28 unit and contract tests across F1-F5.
- **Tier 2**: 25 boundary, dialect, and robustness tests.
- **Tier 3**: 8 pairwise and multi-agent cross-feature interaction tests.
- **Tier 4**: 6 end-to-end multi-turn conversation scenario tests.
- **Total Test Cases**: 67 new dedicated test cases + 918 existing regression tests = 985 total automated tests.

---

## 3. Tier 1: Feature Coverage Specifications

### F1: Topic Anchor Model & State Machine
Validates `app.core.topic_anchor.TopicAnchor` and `ActivityType`.
- **T1.1.1** `test_topic_anchor_initial_defaults`: Verifies default `ActivityType.IDLE`, origin "家", `lock_turns_remaining=0`, empty constraints and steps.
- **T1.1.2** `test_topic_anchor_leisure_walk_state`: Verifies initialization with `ActivityType.LEISURE_WALK`, `target_destination="烈士公园年嘉湖"`, `lock_turns_remaining=5`.
- **T1.1.3** `test_topic_anchor_decrement_turns`: Verifies calling `decrement_lock()` or updating per turn decrements `lock_turns_remaining` monotonically until 0.
- **T1.1.4** `test_topic_anchor_serialization_roundtrip`: Verifies `to_dict()` and `from_dict()` (or Pydantic model dump/load) preserves all fields without corruption.
- **T1.1.5** `test_topic_anchor_health_constraints_mutation`: Verifies dynamic mutation of `health_constraints` (e.g. `avoid_stairs: True`, `max_slope_percent: 2.5`).
- **T1.1.6** `test_topic_anchor_prompt_directive_rendering`: Verifies `render_prompt_directive()` produces explicit negative guidance prohibiting unsolicited hospital bookings.

### F2: Context Conflict Interceptor & Anti-Drift Guard
Validates semantic isolation between `LEISURE_WALK` and `MEDICAL_ESCORT`.
- **T1.2.1** `test_anti_drift_intercept_general_movement_terms`: Verifies that with an active `LEISURE_WALK` anchor, user phrases containing generic movement tokens ("走", "现在就走", "怎么去") are NOT reclassified as `MEDICAL_ESCORT`.
- **T1.2.2** `test_anti_drift_intercept_navigation_query`: Verifies that "导航路线怎么不给我" and "我要跟着导航走" remain firmly anchored to `LEISURE_WALK`.
- **T1.2.3** `test_anti_drift_allow_explicit_acute_medical_switch`: Verifies that explicit acute symptoms ("胸口闷", "心绞痛", "摔倒了要去医院") allow transition from `LEISURE_WALK` to `MEDICAL_ESCORT`.
- **T1.2.4** `test_anti_drift_reject_ambiguous_medical_without_symptoms`: Verifies that conversational ambiguities (e.g., "路过医院门口的公园") do not trigger intent mutation to `MEDICAL_ESCORT`.
- **T1.2.5** `test_anti_drift_destination_preservation`: Verifies that once `target_destination` is set (e.g., "烈士公园年嘉湖"), successive turns preserve the destination rather than defaulting to a hospital.
- **T1.2.6** `test_anti_drift_lock_expiration_behavior`: Verifies that when `lock_turns_remaining` reaches 0, neutral intent re-evaluation is permitted without spontaneous drift.

### F3: Modular Dynamic SystemPrompt Architecture
Validates modular section assembly from `app.core.system_prompt_sections`.
- **T1.3.1** `test_modular_prompt_base_role_section`: Verifies BaseRole establishes KangLe identity as elderly mobility and health companion.
- **T1.3.2** `test_modular_prompt_park_walk_sop_equality`: Verifies ParkWalkSOP is present with equal prominence to MedicalSOP, detailing leisure walk closed-loop procedures.
- **T1.3.3** `test_modular_prompt_negative_constraints_guard`: Verifies red-line rules forbidding unsolicited hospital registration, department assignment, or medical triage during walk planning.
- **T1.3.4** `test_modular_prompt_dynamic_situational_injection`: Verifies dynamic injection of active destination and mobility profile after the cache boundary.
- **T1.3.5** `test_modular_prompt_cache_boundary_stability`: Verifies static prompt prefix remains identical across queries to maximize LLM KV-cache reuse.

### F4: Decoupled PlanBuilder (`bds_walk_escort_plan`)
Validates `app.agents.plan_builder.build_bds_walk_escort_plan`.
- **T1.4.1** `test_walk_plan_page1_pure_park_destination`: Verifies Page 1 title is "适老目的地与步道体征适配", destination reflects park name, and contains barrier-free index.
- **T1.4.2** `test_walk_plan_zero_hospital_fields`: Verifies zero occurrences of medical terms ("医院", "对症专科", "就诊专家", "挂号与报备状态", "医保卡") in Page 1.
- **T1.4.3** `test_walk_plan_page2_accessible_route`: Verifies Page 2 provides accessible walking route metrics (distance, gentle slope %, zero stairs, BDS satellite count).
- **T1.4.4** `test_walk_plan_page3_micro_terrain_and_benches`: Verifies Page 3 details rest benches count, bench intervals, shade canopy coverage, and anti-slip pavement.
- **T1.4.5** `test_walk_plan_page4_outdoor_weather_guidance`: Verifies Page 4 weather advice guides sun protection and hydration, completely devoid of "医院里外温差大".
- **T1.4.6** `test_walk_plan_page5_guardian_and_benches`: Verifies Page 5 provides safety corridor radius and SOS guidance without hospital emergency fallback.

### F5: Route Action & Navigation Launch Pipeline
Validates tool dispatch, `PlanCard.vue` contract, and route map launch parameters.
- **T1.5.1** `test_route_action_trigger_on_direct_request`: Verifies that user utterances "导航路线怎么不给我" and "我要跟着导航走" trigger route tool dispatch (`bds_escort_route` or `plan_route`).
- **T1.5.2** `test_plan_card_has_route_action_for_walk_plan`: Verifies `hasRouteAction` contract returns `true` for `plan_type == 'bds_walk_escort_plan'`.
- **T1.5.3** `test_plan_card_has_route_action_keyword_matching`: Verifies `hasRouteAction` recognizes walk keywords ("散步", "漫步", "公园", "绿道") when compact is false.
- **T1.5.4** `test_plan_card_button_label_rendering`: Verifies button label is "🗺️ 开启北斗安心导航 / 查看路线" instead of third-party map text.
- **T1.5.5** `test_route_map_launch_query_params`: Verifies launch URL structure `/pages/elder/route-map?origin=家&destination=烈士公园年嘉湖&city=长沙`.

---

## 4. Tier 2: Boundary & Corner Cases

### B1: Empty Destination Fallback Without Hospital
- **Test**: `test_boundary_empty_destination_fallback`
- **Input**: User requests walk ("我想去散步"), but specifies no destination and declines prompt suggestions.
- **Expected Outcome**: Destination defaults to "长沙城市公园与适老绿道" or "就近社区绿道", **never** "湖南省人民医院".

### B2: Rapid Intent Switching
- **Test**: `test_boundary_rapid_intent_switching`
- **Input**: Sequence: Turn 1: "想去散步" ➔ Turn 2: "今天天气怎么样" ➔ Turn 3: "还是先散步吧" ➔ Turn 4: "走".
- **Expected Outcome**: System fluidly handles weather inquiry without clearing the leisure walk anchor; Turn 4 triggers walk route planning, not hospital registration.

### B3: Non-Standard Park & Scenic Destinations
- **Test**: `test_boundary_non_standard_park_destinations`
- **Input**: User specifies uncommon or informal destination names: "橘子洲头问天台", "后湖国际艺术区湖畔绿道", "松雅湖湿地公园金沙滩", "洋湖湿地白鹭塔".
- **Expected Outcome**: Destination is correctly extracted and preserved verbatim across all multi-turn cards and routes.

### B4: Colloquial Dialect & Informal Movement Phrases
- **Test**: `test_boundary_colloquial_elderly_movement`
- **Input**: User inputs: "出去遛个弯", "下楼透透气", "老头子想去转转", "走两步散散心".
- **Expected Outcome**: All recognized as `ActivityType.LEISURE_WALK`; no medical triage invoked.

### B5: Adversarial Prompt Injection via Negative Medical Bait
- **Test**: `test_boundary_adversarial_medical_bait`
- **Input**: "散步经过省人民医院门口，帮我规划散步路线".
- **Expected Outcome**: System plans walking route passing near landmark without registering a hospital appointment or creating a medical trip plan.

---

## 5. Tier 3: Cross-Feature Interactions

### C1: HealthAgent Mobility Constraint ➔ BdsNavAgent Route Synthesis
- **Test**: `test_interaction_health_constraint_to_bds_route`
- **Flow**: HealthAgent detects elder's knee osteoarthritis ➔ Transmits constraint (`avoid_stairs: True`, `max_slope_percent <= 3.0%`, `prefer_benches: True`) via Teammate Mailbox ➔ BdsNavAgent computes Martyr's Park Lake walk ➔ Route guarantees 0 stairs, max slope 2.1%, and benches every 140m.

### C2: TopicAnchor + Modular Prompt + Decoupled PlanBuilder Pipeline
- **Test**: `test_interaction_anchor_prompt_plan_synergy`
- **Flow**: TopicAnchor locks `LEISURE_WALK` ("烈士公园年嘉湖") ➔ Modular Prompt injects `ParkWalkSOP` and suppresses hospital prompts ➔ PlanBuilder executes `build_bds_walk_escort_plan` ➔ Resulting deliverable contains zero medical artifacts.

### C3: TopicAnchor Lock vs. Acute Symptom Preemption
- **Test**: `test_interaction_anchor_lock_acute_symptom_override`
- **Flow**: Turn 1-2 establishes locked `LEISURE_WALK` (`lock_turns_remaining=3`) ➔ Turn 3 user exclaims: "哎呀我突然胸口闷得慌，喘不上气，快去医院" ➔ Anti-Drift Guard intercepts acute trigger ➔ Preempts walk anchor, switches `ActivityType.MEDICAL_ESCORT`, alerts Guardian, and activates emergency green channel.

### C4: WeatherAgent Micro-Climate & BdsNavAgent Shading Alignment
- **Test**: `test_interaction_weather_bds_shading_alignment`
- **Flow**: WeatherAgent reports UV index 4 and temperature 29°C ➔ BdsNavAgent selects lakeside canopy route with 88% shade coverage ➔ Walk plan Page 4 recommends morning departure and wide-brim hat.

---

## 6. Tier 4: Real-World Scenarios

### S1: Exact 5-Turn Park Walk Conversation (User Incident Reproduction)
Reproduces the verbatim conversation from the user's issue report:
- **Turn 1**: User: `"想去散步"`
  - *Expected*: Assistant warmly inquires about preferences (quiet vs. lively, distance); TopicAnchor set to `LEISURE_WALK`, `lock_turns_remaining >= 3`. No hospital suggestions.
- **Turn 2**: User: `"安静一点"`
  - *Expected*: Assistant suggests "烈士公园年嘉湖畔平缓林荫步道"; TopicAnchor locks destination `"烈士公园年嘉湖"`. No medical terms.
- **Turn 3**: User: `"现在就走"`
  - *Expected*: Action triggered; subagents coordinate walk route and weather; `bds_walk_escort_plan` generated. ABSOLUTELY ZERO hospital/department/doctor/registration terms.
- **Turn 4**: User: `"导航路线怎么不给我"`
  - *Expected*: Assistant recognizes route request; immediately triggers `bds_escort_route` tool; returns step-by-step barrier-free walking route. Zero hospital terms.
- **Turn 5**: User: `"我要跟着导航走"`
  - *Expected*: System emits navigation action payload / launches `/pages/elder/route-map?origin=家&destination=烈士公园年嘉湖`; zero hospital terms.

### S2: Sudden Mid-Walk Acute Distress Escalation
- **Turn 1-3**: User plans and starts leisure walk in park.
- **Turn 4**: User states: `"突然头晕心慌，站不住了，快帮我叫救护车"`.
- **Expected**: Immediate shift to `MEDICAL_ESCORT`; GuardianAgent triggers SOS emergency broadcast.

### S3: Dual Scenic Option Comparison
- **Turn 1**: User: `"我想去散步，烈士公园和橘子洲哪个台阶少？"`
- **Turn 2**: User: `"那就去年嘉湖吧"`.
- **Expected**: System compares barrier-free indices, locks "烈士公园年嘉湖", and generates walk escort plan.

---

## 7. Test Execution & Verification Protocol

### 7.1 Backend Test Runner Commands
```powershell
# 1. Run all Topic Anchor unit tests
cd c:\Users\lenovo\Desktop\develop\laoyouji\backend
.\.venv\Scripts\python.exe -m pytest tests/test_topic_anchor.py -v

# 2. Run Decoupled Walk PlanBuilder tests
.\.venv\Scripts\python.exe -m pytest tests/test_plan_builder_walk.py -v

# 3. Run Anti-Drift E2E 5-Turn Conversation & Isolation suite
.\.venv\Scripts\python.exe -m pytest tests/test_anti_drift_e2e.py -v

# 4. Run all anti-drift and topic governance suites together
.\.venv\Scripts\python.exe -m pytest tests/test_topic_anchor.py tests/test_plan_builder_walk.py tests/test_anti_drift_e2e.py -v

# 5. Full regression check (all 918 existing + new test cases)
.\.venv\Scripts\python.exe -m pytest -q
```

### 7.2 Frontend Build & Contract Check
```powershell
cd c:\Users\lenovo\Desktop\develop\laoyouji\frontend\laoyouji-app
npm run build:h5
```

---

## 8. Expected Outputs & Authoritative Assertions

### Authoritative Negative Keyword Rule
In all leisure walk test cases (S1 Turns 1-5, F4, B1-B4), the following terms must **NEVER** appear in user-facing texts, prompt injections, or generated plan rows:
```python
PROHIBITED_MEDICAL_TERMS = [
    "医院",
    "挂号",
    "门诊",
    "科室",
    "医生",
    "对症专科",
    "就诊专家",
    "挂号与报备状态",
    "医保卡",
    "就医出行计划书",
    "湖南省人民医院",
    "中南大学湘雅医院",
]
```

Every test case in `test_anti_drift_e2e.py` and `test_plan_builder_walk.py` asserts:
```python
for term in PROHIBITED_MEDICAL_TERMS:
    assert term not in text, f"Violation: Forbidden medical term '{term}' found in leisure walk output: {text}"
```
