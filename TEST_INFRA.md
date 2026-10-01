# E2E Test Infra: LaoYouJi Multi-Agent & Navigation Map

## Test Philosophy
- Opaque-box, requirement-driven derived strictly from ORIGINAL_REQUEST.md.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial Testing + Real-World Workload Scenarios.
- Guarantees: All 721 existing baseline tests remain 100% passing; all new requirement tiers verify R1, R2, R3, R4 behavior end-to-end.

## Feature Inventory & Test Coverage Matrix
| # | Feature | Requirement | Tier 1 (>=5) | Tier 2 (>=5) | Tier 3 (Pairwise) | Tier 4 (Real-world) |
|---|---------|-------------|:------------:|:------------:|:-----------------:|:-------------------:|
| F1 | Peer Mailbox Protocol | R1 | 5 | 5 | ✓ | ✓ |
| F2 | Shared Task Board | R1 | 5 | 5 | ✓ | ✓ |
| F3 | GuardianAgent Standalone Class | R1 | 5 | 5 | ✓ | ✓ |
| F4 | Multi-Agent Peer Deliberation | R1 | 5 | 5 | ✓ | ✓ |
| F5 | SSE Real-time Thinking & Handoff Stream | R2 | 5 | 5 | ✓ | ✓ |
| F6 | Frontend Elder Thinking Bubble & Handoff Card | R2 | 5 | 5 | ✓ | ✓ |
| F7 | 5-Agent Execution Tree & Swarm Board | R2 | 5 | 5 | ✓ | ✓ |
| F8 | Adaptive Hierarchical Memory Store | R3 | 5 | 5 | ✓ | ✓ |
| F9 | Proactive Context Care & Recall | R3 | 5 | 5 | ✓ | ✓ |
| F10 | Map Gesture Isolation (`touch-action: none`) | R4 | 5 | 5 | ✓ | ✓ |
| F11 | Native Integer Tile Zoom (`zoomSnap: 1`) | R4 | 5 | 5 | ✓ | ✓ |
| F12 | Smooth Easing Viewport Transitions | R4 | 5 | 5 | ✓ | ✓ |
| F13 | GPU Hardware-Accelerated Marker Layer | R4 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- Backend Test Runner: `backend/.venv/Scripts/python.exe -m pytest tests/ -v`
- Frontend Build Runner: `npm run build:h5`
- Test Case Directory: `backend/tests/` (new files: `test_peer_mailbox.py`, `test_thinking_stream.py`, `test_hierarchical_memory.py`, `test_e2e_swarm_deliberation.py`)
- Frontend E2E Map Spec: `tests/test_amap_frontend.mjs`

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Expected Outcome |
|---|----------|--------------------|------------------|
| S1 | 烈士公园晨练伴随 (Morning Exercise at Martyr's Park) | F1, F4, F8, F9, F10-F13 | Health injects knee constraint; BdsNav plans shade route avoiding stairs; Elder profile remembers habit; Map pans smoothly. |
| S2 | 湘雅就医与突发体能不适 (Hospital Visit & Fatigue Alert) | F1, F2, F3, F4, F5 | Guardian monitors safety corridor; Health detects fatigue; Task board assigns rest bench finding. |
| S3 | 暴雨短临微气象与避雨绕行 (Sudden Downpour & Route Reroute) | F1, F4, F5, F6 | Weather notifies BdsNav; BdsNav reroutes to covered pavilion; Live handoff card shows transition. |
| S4 | 异地子女紧急守护与偏航联动 (Guardian SOS & Deviation Reroute) | F3, F4, F9, F12 | Deviation detected; Guardian triggers green corridor; Handoff stream notifies child and elder simultaneously. |
| S5 | 跨多轮对话体能记忆自动加载 (Multi-Turn Habit Persistence) | F8, F9 | System retains chronic arthritis constraint from prior day; No repetitive inquiry required. |
