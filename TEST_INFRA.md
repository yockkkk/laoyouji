# TEST_INFRA — 《银发导航智能体》竞赛级全景端到端测试架构体系

> **归属赛事**：第八届湖南省大学生智能导航科技创新大赛（科技创意类赛道）  
> **作品名称**：《银发导航智能体：基于多Agent协同的老年人安心出行伴侣》  
> **编制角色**：E2E Test Writer (`teamwork_preview_test_writer_m0`)  
> **发布日期**：2026-09-29  
> **执行环境**：Windows / Python 3.12 / pytest 9.1.1  

---

## 1. 测试架构全景 (Test Architecture Overview)

针对第八届湖南省大学生智能导航科技创新大赛的答辩与评审验收要求，本测试基础设施确立了**“规约驱动、全域对抗、分层穿透”**的 4-Tier 闭环测试方法论，彻底摒弃表面假跑的桩代码，全面覆盖国家北斗高精度时空服务与多Agent协同调度核心链路。

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              4-Tier E2E 测试验证金字塔                                 │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Tier 4: 长沙实景大闭环用例 (Real-World Changsha Scenarios)                     [4 Tests]│
│  - 华夏路社区至省人民医院、湘雅医院、烈士公园无障碍避障散步、老人-子女监护闭环         │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Tier 3: 跨特性两两正交组合用例 (Cross-Feature Combinations)                    [5 Tests]│
│  - 慢病关节炎+暴雨湿滑、偏航+涉诈高危、异常滞留+突发SOS、恶劣天气+跨城拒答、围栏+R6隐私│
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Tier 2: 极限边界与对抗用例 (Boundary & Corner Cases)                           [8 Tests]│
│  - 极限陡坡(20%)、120级无电梯台阶、隧道丢星(0,0)与重捕、100m临界容差、超长滞留、方言降噪│
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Tier 1: 核心功能特性全覆盖 (Feature Coverage, >=5用例/特性)                   [35 Tests]│
│  - F1: 北斗导航规划与RTK遥测 (5)   - F2: 慢病体能与步速物理约束 (5)                     │
│  - F3: 恶劣气象滑倒惩罚与防护 (5)   - F4: 北斗动态安全走廊与围栏 (5)                     │
│  - F5: 异常滞留预警与长椅豁免 (5)   - F6: 突发求助与三甲急救绿通 (5)                     │
│  - F7: 偏远高危涉诈目的地拦截 (5)                                                       │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 快速运行指南 (Runner Command)

进入项目 `backend` 根目录，使用项目专用虚拟环境执行：

### 2.1 一键标准测试命令 (Standard Runner)
```powershell
cd c:\Users\lenovo\Desktop\develop\laoyouji\backend
.venv\Scripts\python -m pytest tests/test_e2e_bds_competition.py -q
```
*预期输出*：`52 passed in 0.34s`

### 2.2 详细逐项核验命令 (Verbose Mode)
```powershell
.venv\Scripts\python -m pytest tests/test_e2e_bds_competition.py -v
```

### 2.3 按 Tier 分层聚焦测试
```powershell
# Tier 1 核心功能覆盖测试
.venv\Scripts\python -m pytest tests/test_e2e_bds_competition.py -k "TestTier1" -v

# Tier 2 边界对抗测试
.venv\Scripts\python -m pytest tests/test_e2e_bds_competition.py -k "TestTier2" -v

# Tier 3 跨特性组合测试
.venv\Scripts\python -m pytest tests/test_e2e_bds_competition.py -k "TestTier3" -v

# Tier 4 长沙实景场景测试
.venv\Scripts\python -m pytest tests/test_e2e_bds_competition.py -k "TestTier4" -v
```

---

## 3. 测试分层与用例清单 (Tier Distribution)

| 分层 | 测试类 | 用例数 | 覆盖重点与核心验证指标 |
|---|---|:---:|---|
| **Tier 1** | `TestTier1BdsRoutingAndTelemetry` | 5 | 北斗亚米级 RTK 固定解遥测模型、NMEA-0183 `$BDGGA` 语句格式及 XOR 校验和、适老微地形代价函数 $Cost(E)$、长椅奖励 $B_{amenity}=0.3$、无障碍指数 $\ge 0.95$ |
| **Tier 1** | `TestTier1ElderPhysicalConstraints` | 5 | 退行性膝骨关节炎台阶阻断惩罚、地面坡度硬顶 $\le 4.0\%$、适老步行速度 $0.7\text{m/s}$（2.5km/h）用时测算、单次连续步行 $600\text{m}$ 上限、高血压避暴晒 |
| **Tier 1** | `TestTier1WeatherPenaltyAndEscort` | 5 | 雨雪湿滑地面惩罚 $C_{weather}=2.0$、风雨连廊平缓通道优先、湿滑坡道复合风险惩罚、防滑胶底鞋与带伞大白话播报、高温遮阳树荫引导 |
| **Tier 1** | `TestTier1BdsGeofencingAndCorridor` | 5 | 80m 走廊内正常判定、偏离走廊 $>100\text{m}$ 触发偏航预警、500m 社区生活圈静默安全、终点 50m 到达收尾、与 backend 既有走廊算法一致性 |
| **Tier 1** | `TestTier1AbnormalDwellAlert` | 5 | 非休整区静止 $>15\text{min}$ 触发 ABNORMAL_DWELL 告警、行走速度恢复清零滞留计时、适老长椅 25m 内休整豁免报警、14分50秒宽限期不误报、医院候诊大厅豁免 |
| **Tier 1** | `TestTier1SosGreenChannelAndEmergency` | 5 | 突发不适点击 SOS 毫秒级重划最近三甲医院（湘雅/省人医）、绿色急救通道折线生成、算法解算耗时 $<500\text{ms}$、安抚语音播报、120 直拨大卡片 |
| **Tier 1** | `TestTier1ScamDestinationInterception` | 5 | 免费领鸡蛋/保健品讲座硬阻断 DENY、偏远厂房/高额分红拦截、祖传神药包治百病会场拦截、正规三甲医院与公园白名单放行、安全网关单调规则对齐 |
| **Tier 2** | `TestTier2BoundaryAndCornerCases` | 8 | 极限陡坡(20%)代价激增避让、120 级超长过街天桥阻断、隧道/地下过街丢星 $(0,0)$ 校准不误报、出隧道 18 星毫秒级重捕恢复、100m 走廊临界浮点判定、60分钟超长滞留升级、非法经纬度 Pydantic Schema 强校验、长沙方言口音输入降噪 |
| **Tier 3** | `TestTier3CrossFeatureCombinations` | 5 | 慢病关节炎 + 降雨湿滑双重约束下规避台阶与露天坡道、偏离走廊 + 移动方向指向涉诈会场复合高危告警、异常滞留 18 分钟突发心绞痛呼救一键转入急救绿通、暴雨台风天气坚守市内边界拒答跨城并就近避雨、动态走廊跃迁与 R6 隐私分级（city 档隐藏经纬度但忠实传递出入围栏） |
| **Tier 4** | `TestTier4RealWorldChangshaScenarios` | 4 | **场景 1**：开福区华夏路社区至湖南省人民医院（天心阁院区）适老就医专线；<br>**场景 2**：华夏路社区至中南大学湘雅医院极近无障碍就医；<br>**场景 3**：华夏路社区至湖南烈士公园（西门无障碍坡道避开南门 28 级纪念塔台阶）；<br>**场景 4**：长沙实景老人-子女多Agent协同守护完整闭环（启程、长椅休整、一键报平安、安全到达） |
| **总计** | **全部 4-Tier 覆盖** | **52** | **全用例 100% 通过（52 Passed, 0 Failed, 0 Skipped）** |

---

## 4. 功能特性资产映射表 (Feature Inventory Mapping)

严格对照 `PROJECT.md` 与 `spec_report.md` 中的特性清单建立双向指认：

| 特性编号 | 功能特性名称 | 对应的规约方法 / 算法组件 | E2E 测试用例定位 |
|---|---|---|---|
| **F01** | BDS Multi-Agent Escort Engine | 5-Agent 协同拓扑模型与结构化方案卡 | `TestTier4RealWorldChangshaScenarios::test_changsha_scenario4_full_elder_guardian_closed_loop` |
| **F02** | Micro-Terrain Elder Cost Routing | 代价函数 $Cost(E)$、坡度惩罚、台阶避障 | `TestTier1BdsRoutingAndTelemetry::test_bds_micro_terrain_cost_function_flat_vs_slope`<br>`TestTier1ElderPhysicalConstraints::test_elder_arthritis_avoid_stairs_block_penalty` |
| **F03** | BDS High-Precision Positioning & Telemetry | CGCS2000基准、RTK 0.35m精度、`$BDGGA` | `TestTier1BdsRoutingAndTelemetry::test_bds_telemetry_rtk_submeter_accuracy_contract`<br>`TestTier1BdsRoutingAndTelemetry::test_bds_nmea_bdgga_parsing_and_checksum_verification` |
| **F04** | 5-Page 《北斗适老出行护航方案书》 | `ElderEscortRouteResponse` 确定性交付结构 | `TestTier4RealWorldChangshaScenarios::test_changsha_scenario1_community_to_provincial_people_hospital` |
| **F05** | Elder Voice-First Interaction | 方言容错语义识别与出行意图提炼 | `TestTier2BoundaryAndCornerCases::test_boundary_dialect_noise_robustness` |
| **F07** | Landmark-Based Guidance Cards | 关键路口地标式实景卡片引导与播报话术 | `TestTier4RealWorldChangshaScenarios::test_changsha_scenario1_community_to_provincial_people_hospital` |
| **F08** | Voice Deviation Reassurance | 偏航时温和语音纠偏安抚（无技术黑话） | `TestTier1BdsGeofencingAndCorridor::test_geofence_off_route_detection_exceeding_100m` |
| **F10** | Multi-Tiered BDS Geofencing | 500m生活圈、100m动态走廊、50m终点围栏 | `TestTier1BdsGeofencingAndCorridor::test_geofence_in_corridor_evaluation_normal`<br>`TestTier1BdsGeofencingAndCorridor::test_geofence_home_living_circle_500m_safe_boundary` |
| **F12** | Abnormal Dwell & Fall Alert | 连续静止 $>15\text{min}$ 检测与长椅豁免 | `TestTier1AbnormalDwellAlert::test_dwell_stagnation_over_15_minutes_triggers_alert`<br>`TestTier1AbnormalDwellAlert::test_dwell_at_registered_rest_bench_exemption` |
| **F13** | Dual-Direction Family Reassurance Loop | 一键报平安与双向守护通知推送 | `TestTier4RealWorldChangshaScenarios::test_changsha_scenario4_full_elder_guardian_closed_loop` |
| **F14** | R6 Privacy Degradation Protection | 数据出库实时/城市/关闭三档动态变形 | `TestTier3CrossFeatureCombinations::test_pairwise_geofence_transition_plus_r6_privacy_masking` |
| **F15** | Scam Destination Interception | 涉诈/传销目的地语义匹配与单调阻断 | `TestTier1ScamDestinationInterception::test_scam_fake_health_lecture_interception`<br>`TestTier1ScamDestinationInterception::test_scam_legitimate_hospital_and_park_whitelisted` |
| **F16** | Emergency SOS & Hospital Green Channel | 毫秒级重划就近三甲医院急救避障绿通 | `TestTier1SosGreenChannelAndEmergency::test_sos_green_channel_reroute_to_nearest_tertiary_hospital`<br>`TestTier1SosGreenChannelAndEmergency::test_sos_green_channel_sub_500ms_computation_latency` |
| **F17** | Changsha Demonstration Data Fixtures | 华夏路社区、湘雅医院、省人民医院、烈士公园 | `TestTier4RealWorldChangshaScenarios::*` 全体实景用例 |

---

## 5. 核心算法与权威预言机数学模型 (Authoritative Oracles)

### 5.1 适老微地形代价函数 $Cost(E)$
$$Cost(E) = \sum_{e \in E} L(e) \cdot \Big( 1 + C_{\text{slope}}(e) + C_{\text{stairs}}(e) + C_{\text{weather}}(e) - B_{\text{amenity}}(e) \Big)$$
- **坡度惩罚**：$\theta(e) > 4.0\%$ 时，$C_{\text{slope}}(e) = 5.0 \cdot \left(1 + \left(\frac{\theta(e) - 4.0}{4.0}\right)^2\right)$，极端陡坡代价呈二次激增。
- **台阶阻断**：患有关节退行性病变老人设置 `avoid_stairs=True`，无电梯台阶施加 $C_{\text{stairs}}(e) = 100.0 \times N_{\text{steps}}$，达到数学意义上的绝对阻断。
- **气象湿滑**：雨雪天气露天地面附加 $C_{\text{weather}}(e) = 2.0$；露天湿滑坡道复合附加 $+3.0$。
- **友好奖励**：沿途具备长椅设施奖励 $B_{\text{amenity}}(e) = 0.3$，林荫遮阳奖励 $+0.15$。

### 5.2 动态走廊电子围栏投影距离算子
点 $P$ 到航迹折线段 $AB$ 的空间垂距解算：
$$t = \max\left(0, \min\left(1, \frac{\vec{AP} \cdot \vec{AB}}{|\vec{AB}|^2}\right)\right), \quad P_{\text{closest}} = A + t \cdot \vec{AB}$$
结合 Haversine 球面距离公式：
$$\text{dist}(P, P_{\text{closest}}) = 2R \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta\phi}{2}\right) + \cos\phi_1\cos\phi_2\sin^2\left(\frac{\Delta\lambda}{2}\right)}\right)$$
当 $\text{dist} > 100.0\text{m}$ 触发走廊偏离预警；当 $\text{dist} \le 100.0\text{m}$ 维持安全通行状态。

---

## 6. 代码边界与文件所有权隔离 (Write Boundaries)

测试套件严格遵守微内核工程规范，与后续业务实现智能体（M1/M2/M3/M4）保持绝对代码隔离：

- **E2E 测试专属所有权**：
  - `backend/tests/test_e2e_bds_competition.py`（全量 4-Tier 竞赛测试用例）
  - `backend/tests/bds_fixtures.py`（BDS 规约模型、NMEA生成器、预言机与长沙拓扑）
  - `TEST_INFRA.md`（本工程测试架构标准文档）
  - `TEST_READY.md`（测试就绪与验收验证交付报告）
- **严禁越界修改范围**：
  - 严禁修改 `backend/app/` 下任何业务源码（由 M1/M3 智能体按规约实现）。
  - 严禁修改 `frontend/` 下任何前端组件（由 M2/M3 智能体实现）。
