"""演示种子数据：默认家庭（张桂芳 + 李明）+ 账号密码 + 用药计划 + 隐私默认授权。

幂等：reset 后重新灌入。POST /api/seed 与 scripts/seed_demo.py 共用。

另有 ``seed_kangle_persona``：在默认家庭之上，给张桂芳补一份**看起来像真的**的
30 天指标档案（高血压 + 2 型糖尿病），供康乐左翼的分诊演示用。它和 ``seed_demo``
分开是刻意的 —— 每个测试的 ``ctx`` 都建在 ``seed_demo`` 上，往里塞 30 天假数据会
让所有既有断言跟着晃。要演示分诊就显式再调一次它。

档案有四个剧本（``SCENARIOS``），四个分诊档位各一个，靠 ``scenario`` 切换；
指标是**合成的**，但日期相对"今天"生成、时刻不重样、数值逐个对着 health_rules 的
阈值反推过 —— 演示现场被追问"这数是真的吗"时，答案是"合成数据，但每个数都经得起看"。
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from typing import Any

from app.auth.security import hash_password
from app.db.repositories import Repository
from app.safety import health_rules as hr

# 演示环境统一密码（仅供开发测试与演示使用）
DEMO_PASSWORD_ELDER = "elder123456"
DEMO_PASSWORD_CHILD = "child123456"


async def seed_demo(repo: Repository) -> dict[str, Any]:
    await repo.reset()

    elder = await repo.insert("users", {
        "username": "zhangguifang",
        "password_hash": hash_password(DEMO_PASSWORD_ELDER),
        "status": "active",
        "role": "elder", "name": "张桂芳", "phone": "13800000001",
        "dialect": "southwestern", "city": "南京",
        "relation_to_child": "母亲",
    })
    child = await repo.insert("users", {
        "username": "liming",
        "password_hash": hash_password(DEMO_PASSWORD_CHILD),
        "status": "active",
        "role": "child", "name": "李明", "phone": "13900000002",
        # 知会的**跨设备**送达地址。刻意用 example.com：那是 RFC 2606 保留域，
        # **永远不会**是某位真人的邮箱。演示数据要"像真的"，但收件地址不能真 —
        # 一旦把 mail_provider 拨到 smtp，一个看着像真的地址就是往陌生人信箱里
        # 发真邮件。看得像样这件事，交给正文，不交给收件人。
        "email": "liming@example.com",
        "dialect": "mandarin", "city": "北京",
        "relation_to_elder": "儿子",
    })
    await repo.insert("family_bindings", {
        "elder_id": elder["id"], "child_id": child["id"], "relation": "儿子",
        "status": "active",
    })
    await repo.insert("privacy_permissions", {
        "elder_id": elder["id"], "child_id": child["id"],
        "location_level": "realtime", "health_level": "summary",
    })
    await repo.insert("medication_plans", {
        "elder_id": elder["id"], "drug_name": "硫酸氨基葡萄糖胶囊",
        "dose": "每次1粒", "times": ["08:00", "20:00"],
        "notes": "饭后温水送服，医生已开", "active": True,
    })
    await repo.insert("medication_plans", {
        "elder_id": elder["id"], "drug_name": "钙片",
        "dose": "每次1片", "times": ["09:00"],
        "notes": "和牛奶隔开一小时", "active": True,
    })
    return {"elder": elder, "child": child}


# ---------------------------------------------------------------- 康乐人物档案

# 剧本化的人物设定：72 岁、南京、高血压 5 年 + 2 型糖尿病 3 年（轻度）。
# 药只列"医生已开"的两种 —— 与 prompt 红线一致：系统不推荐药，只登记医嘱。
#
# sex/city/living/children 这四个键是给人物卡与命令行抬头用的：答辩现场被问
# "这位老人是谁"，一句话就得答得上来（女、独居、南京、儿子在北京）。判断逻辑
# 一个字都不认它们 —— 人设只解释"这份档案为什么长这样"，不参与分诊。
KANGLE_PERSONA = {
    "age": 72,
    "sex": "女",
    "city": "南京",
    "living": "独居",
    "children": "儿子李明在北京",
    "conditions": [
        {"name": "原发性高血压", "diagnosed_at": "2021-03-18", "severity": "中度",
         "notes": "每天服药，平时 140 上下", "active": True},
        {"name": "2 型糖尿病", "diagnosed_at": "2023-05-09", "severity": "轻度",
         "notes": "饮食控制，空腹 7 以内", "active": True},
    ],
    "medications": [
        {"drug_name": "苯磺酸氨氯地平片", "dose": "每次1片", "times": ["07:00"],
         "notes": "早饭前吃，降压药不能自己停", "active": True},
        {"drug_name": "二甲双胍缓释片", "dose": "每次1片", "times": ["08:00", "18:00"],
         "notes": "随餐吃，胃不舒服就跟医生说", "active": True},
    ],
}

# ---------------------------------------------------------------- 剧本与测量时刻
#
# 演示场合最常被追问的一句话是"这数是真的吗"。答案必须是：指标是**合成**的，
# 但每一个数都经得起追问 —— 时刻不是一个整点、七天不是一个值、今天不是几个月前。
# 下面这些常量就是这件事的施工图。

# 测量时刻刻意**不是清一色 08:00**：老人是早起吃完药顺手量一下，钟点在 06:40~07:35
# 之间飘。同一个钟点反复出现是"一眼假"的头号特征，翻一遍时间线就露。
_AM_CLOCKS = ("06:41", "06:53", "07:05", "07:12", "07:24", "07:33")   # 07:12 是 REFOCUS §6.4 点名的晨测时刻
_PM_CLOCKS = ("19:22", "19:36", "19:48", "20:05", "20:19")
# 这个池子原来是 ("06:47", "07:00", "07:16", "07:29")，那个 07:00 是全部钟点池里
# **唯一一个正点**，而它占本池 1/4 —— 30 天档案里会有 7 条血糖恰好落在整点。
# 其余指标都飘在 06:41~07:41 之间，唯独血糖每四条冒出一个 07:00，反而比清一色
# 08:00 更扎眼：翻时间线的人会指着它问"怎么就这个是整的"。
# 改成 07:04 后全库没有任何一条读数落在整点或半点上。用药时间（上面 times 里的
# 07:00）不动 —— 医嘱本来就开在整点，那是真的。
_GLU_FASTING_CLOCKS = ("06:47", "07:04", "07:16", "07:29")
_GLU_POST_CLOCKS = ("19:55", "20:12", "20:26")
# 每个指标的钟点池**互不重叠**：同一个 07:05 出现在四个池子里的话，单一时钟的占比
# 会被叠加到 15%（时间线上一眼看过去还是"整点打卡"），而实际上那是四件不同的事
# 碰巧同秒做完。各用各的池子，占比自然摊开。
_HR_CLOCKS = ("06:45", "06:52", "07:02", "07:15")
_SPO2_CLOCKS = ("07:11", "07:18", "07:41")
_TEMP_CLOCKS = ("06:58", "07:08", "07:26")
_WEIGHT_CLOCKS = ("06:49", "07:35")

# 整天漏测：老人不是机器 —— 出门了、血压计没电了、就是忘了。平均十来天漏一天，
# 只排在够长的档案里（短档案保持一条不缺，免得演示"最近一周"时缺出一块空白）。
# 漏在哪几天是**固定步长**推导出来的，不是随机抽的：同一份档案两次跑必须一模一样。
_MISSED_STEP = 10
_MISSED_MIN_DAYS = 14
_MISSED_OFFSETS = tuple(range(11, 30, _MISSED_STEP))    # 默认 30 天档案的漏测日 = (11, 21)


def _missed_offsets(days: int) -> set[int]:
    """该长度的档案里哪些偏移量整天没有读数（days 太短就一个不漏）。"""
    if days <= _MISSED_MIN_DAYS:
        return set()
    return set(range(11, days, _MISSED_STEP))

# 四个可切换剧本，一个档位一个。key 是给命令行敲的（ASCII，Windows 控制台不会乱码），
# level 是给答辩现场念的。切换只需重跑一次 seed 脚本，见 scripts/seed_demo.py --list。
#
# 数值全部反推自 health_rules 的阈值（**不是先编数再贴标签**）：
#   bp 抖动 ±2 是稳定档的护栏 —— stable 恒 <140/90（不越到观察），observation 的
#   141~145 恒 ≥140（不落回保健）；spike/emergency 的基线放宽到 ±4，因为它们本来就
#   该在更高的带里，飘一点不影响档位。
#   bp_tail 是**写死**的：演示要的那个数（178/105、186/112）每跑一次都必须一样，
#   尾日一律不加噪声。
SCENARIOS: dict[str, dict] = {
    "stable": {
        "level": "保健",
        "story": "血压平稳（138/86），全档案都在保健带里 —— 演示「日常保健优先于就医」",
        "bp_base": (134, 84), "bp_jitter": 2,
        "bp_tail": {4: (135, 84), 3: (135, 84), 2: (137, 85), 1: (136, 85), 0: (138, 86)},
        "glucose_fasting": (5.4, 0.4), "glucose_gap": (2.2, 0.5),
        "heart_rate": (74, 4), "spo2": (97, 1), "temperature": (36.3, 0.3),
        "weight": 62.4,
    },
    "observation": {
        "level": "观察",
        "story": "基线 143/91 常年略高于正常（145/92 收尾）—— 复测、按时吃药，别急着跑医院",
        "bp_base": (143, 91), "bp_jitter": 2,
        "bp_tail": {4: (142, 90), 3: (142, 91), 2: (143, 90), 1: (144, 91), 0: (145, 92)},
        "glucose_fasting": (6.2, 0.4), "glucose_gap": (2.2, 0.5),
        "heart_rate": (78, 4), "spo2": (97, 1), "temperature": (36.3, 0.3),
        "weight": 63.1,
    },
    "hypertension_spike": {
        "level": "建议就医",
        "story": "最近 5 天一路走高，今晨 178/105 —— 分诊「建议就医」，帮您就近挂号并知会子女",
        "bp_base": (140, 88), "bp_jitter": 4,
        "bp_tail": {4: (150, 92), 3: (155, 94), 2: (160, 95), 1: (168, 98), 0: (178, 105)},
        "glucose_fasting": (6.4, 0.5), "glucose_gap": (2.6, 0.6),
        # 血压顶上去的那几天血糖跟着抬一点：两个慢病不会各走各的，这处联动让它像一个人
        "glucose_lift": 0.4,
        "heart_rate": (80, 4), "spo2": (97, 1), "temperature": (36.3, 0.3),
        "weight": 62.8,
    },
    "emergency": {
        "level": "紧急",
        "story": "今晨 186/112 且血氧掉到 88% —— 分诊「紧急」，立刻联系家人或 120",
        "bp_base": (152, 93), "bp_jitter": 4,
        "bp_tail": {5: (158, 96), 4: (164, 99), 3: (170, 100), 2: (176, 106),
                    1: (182, 110), 0: (186, 112)},
        # 两条独立的触顶路径：血压到高血压急症区间，血氧又跌破 90。只给一条，
        # 评委容易问"血压高就一定要叫 120 吗"；两条同时出现，答案就没得争
        "heart_rate_tail": {3: 88, 2: 92, 1: 98, 0: 104},
        "spo2_tail": {3: 95, 2: 94, 1: 93, 0: 88},
        "temperature_tail": {1: 37.4, 0: 37.8},
        "glucose_fasting": (7.1, 0.6), "glucose_gap": (4.1, 0.8),
        "heart_rate": (84, 4), "spo2": (97, 1), "temperature": (36.4, 0.4),
        "weight": 63.0,
    },
}
SCENARIO_BY_LEVEL = {sc["level"]: name for name, sc in SCENARIOS.items()}

# 旧引用的兼容别名：值与原实现一致，别的地方若还 import 了它们，不至于断
_SCENARIOS = tuple(SCENARIOS)
_SPIKE_TAIL = [(o, *SCENARIOS["hypertension_spike"]["bp_tail"][o]) for o in (4, 3, 2, 1, 0)]


def resolve_scenario(name: str) -> str:
    """剧本 key（``emergency``）和中文档位（``紧急``）都认，认不出就抛。

    Windows 控制台上敲中文参数容易乱码，但演示者脑子里记的是档位名，所以两个都收。
    认不出时**必须抛**：静默退回默认剧本比报错坏得多 —— 演示者以为切到了"紧急"，
    屏幕上却是平稳档案，而他会照着自己以为的那份讲下去。
    """
    key = str(name or "").strip()
    if key in SCENARIOS:
        return key
    if key in SCENARIO_BY_LEVEL:
        return SCENARIO_BY_LEVEL[key]
    raise ValueError(
        f"没有这个剧本: {name}（可选剧本 {list(SCENARIOS)}，"
        f"或档位 {list(SCENARIO_BY_LEVEL)}）")


def _bp_pair(sc: dict, who: str, day: date, offset: int) -> tuple[int, int]:
    """当天**晨起**血压。tail 日取写死的精确值（一点噪声不加），其余在基线上抖。

    抖动上界是按档位反推的：stable 抖动 ±2 保证全档恒 <140/90，observation 的基线
    141~145 保证恒 ≥140。调大这里会让 stable 偶尔越进"观察"，演示叙事当场自相矛盾。
    """
    tail = sc.get("bp_tail") or {}
    if offset in tail:
        return tail[offset]
    base_s, base_d = sc["bp_base"]
    jitter = sc.get("bp_jitter", 2)
    return (base_s + _rng(who, "bp_s", day).randint(-jitter, jitter),
            base_d + _rng(who, "bp_d", day).randint(-jitter, jitter))


def _row(metric_type: str, measured_at: str, *, value=None, systolic=None,
         diastolic=None, context=None, source="") -> dict:
    """一条读数行（不含 elder_id）。**档位由存进去的那个数算出来**，不是另给的。

    先四舍五入到落库精度、再判档：不然会出现"库里存 7.0、却按 6.96 判成保健"这种
    数与档位对不上的行，回头查账无法复现。测试也拿库里的数重算一遍档位，同一个道理。
    """
    if metric_type == "bp":
        systolic, diastolic = float(systolic), float(diastolic)
    else:
        value = round(float(value), 1)
    level, _ = hr.classify_reading(metric_type, value=value, systolic=systolic,
                                   diastolic=diastolic, context=context)
    row: dict = {"metric_type": metric_type, "unit": hr.metric_unit(metric_type),
                 "measured_at": measured_at, "source": source, "level": level}
    if metric_type == "bp":
        row["systolic"], row["diastolic"] = systolic, diastolic
    else:
        row["value"] = value
    if context:
        row["context"] = context
    return row


def _scalar(sc: dict, key: str, who: str, day: date, *,
            whole: bool = False) -> float:
    """基线 + 日间抖动的连续指标。whole=True 的（心率/血氧）取整数，仪器本来就是整数。"""
    base, spread = sc[key]
    rng = _rng(who, key, day)
    if whole:
        return rng.randint(base - spread, base + spread)
    return base + rng.uniform(-spread, spread)


def _glucose_pair(sc: dict, who: str, day: date, offset: int) -> tuple[float, float]:
    """当天血糖 ``(空腹, 餐后)``。餐后跟着**当天**的空腹值走，不是各飘各的。

    两点都靠它：一是常识（餐后比空腹高，差值就是那一顿吃进去的量）；二是趋势窗里
    空腹与餐后混在同一条序列里（``_trends_by_type`` 只按 metric_type 分组，不看
    context），两列各飘各的把噪声翻倍 —— 让餐后跟着当天的空腹走，至少去掉这一层。

    但**别指望这样就能让血糖的"最近上升/下降"变成可信结论**：七点窗里首段两条与
    末段两条都是"一个空腹 + 一个餐后"，而 health_rules 的死区只有 5%（约 0.3 mmol/L），
    日间抖动本来就在这个量级上 —— 实测平稳只占约一半，另一半是噪声读出来的。
    要讲趋势就讲血压（那条是稳的：300 个样本里 295 次读作"平稳"，其余读成"上升"
    也确实是这七个数在涨），血糖按空腹/餐后分开看。

    血压顶上去的那几天（``glucose_lift``）空腹和餐后一起抬：两个慢病不会各走各的。
    """
    f_base, f_spread = sc["glucose_fasting"]
    lift = sc.get("glucose_lift", 0.0) if offset in (sc.get("bp_tail") or {}) else 0.0
    fasting = round(f_base + _rng(who, "glu_f", day).uniform(-f_spread, f_spread) + lift, 1)
    gap_base, gap_spread = sc["glucose_gap"]
    gap = gap_base + _rng(who, "glu_p", day).uniform(-gap_spread, gap_spread)
    return fasting, round(fasting + gap, 1)


def _tailed(sc: dict, key: str, who: str, day: date, offset: int, *,
            whole: bool = False) -> float:
    """同上，但 ``{key}_tail`` 里的那几天取写死的精确值（血氧 88%、心率 104 那种）。"""
    tail = sc.get(f"{key}_tail") or {}
    if offset in tail:
        return tail[offset]
    return _scalar(sc, key, who, day, whole=whole)


def _readings_for_day(sc: dict, who: str, day: date, offset: int) -> list[dict]:
    """生成**某一天**的全部读数（不含 elder_id、不落库）。

    剥成纯函数是为了让它可测：这批数据的唯一验收标准是"经 health_rules 跑出来是哪一档"，
    而验收要能在不建库的情况下逐条跑。``who`` 是稳定身份（用户名），``day`` 是随机种子的
    第三段 —— 同一个人同一天永远是同一批数，复位重灌不会换一副面孔。

    ``offset == 0``（今天）只出晨起那几条：演示是上午跑的，晚上那次还没测。留着会盖掉
    "最新一条"（睡前值天然比晨起低），分诊当场就不是主角那个数了。整天漏测由调用方
    （``seed_kangle_persona``）按 ``_MISSED_OFFSETS`` 跳过 —— 这里只负责"人正常量了"的那天。
    """
    stamp = day.isoformat()
    rows: list[dict] = []

    # —— 血压：晨起必测，睡前一半的日子测。
    # 睡前那次不是凑数：一天只有晨起一个点的话，7 条趋势窗要跨 7 天，曲线被拉平成直线；
    # 加上睡前值，7 条约跨 5 天，"晨起偏高、午后回落"才是看得见的形状。
    systolic, diastolic = _bp_pair(sc, who, day, offset)
    rows.append(_row("bp", f"{stamp}T{_rng(who, 'clk_am', day).choice(_AM_CLOCKS)}",
                     systolic=systolic, diastolic=diastolic,
                     context="晨起", source="血压计"))
    if offset != 0 and _rng(who, "pm_on", day).random() < 0.5:
        rows.append(_row("bp", f"{stamp}T{_rng(who, 'clk_pm', day).choice(_PM_CLOCKS)}",
                         # 午后回落：收缩压落 3~7、舒张压只落 1~3（老人血管弹性差，
                         # 舒张压落得少）。收缩压与舒张压的落差恒为正，不会出现
                         # "收缩压低于舒张压"这种生理上不可能的行
                         systolic=systolic - _rng(who, "bp_pm_s", day).randint(3, 7),
                         diastolic=diastolic - _rng(who, "bp_pm_d", day).randint(1, 3),
                         context="睡前", source="血压计"))

    # —— 血糖：空腹 + 餐后各一条，context 必须落库：同一个数，空腹和餐后不是一个档
    fasting, post = _glucose_pair(sc, who, day, offset)
    rows.append(_row("glucose",
                     f"{stamp}T{_rng(who, 'clk_gf', day).choice(_GLU_FASTING_CLOCKS)}",
                     value=fasting, context="空腹", source="血糖仪"))
    if offset != 0:
        rows.append(_row("glucose",
                         f"{stamp}T{_rng(who, 'clk_gp', day).choice(_GLU_POST_CLOCKS)}",
                         value=post, context="餐后", source="血糖仪"))

    # —— 心率/血氧/体温/体重。心率和血氧标"静息"：晨起坐定后量的，不是爬完楼那种
    rows.append(_row("heart_rate", f"{stamp}T{_rng(who, 'clk_hr', day).choice(_HR_CLOCKS)}",
                     value=_tailed(sc, "heart_rate", who, day, offset, whole=True),
                     context="静息", source="手环"))
    rows.append(_row("spo2", f"{stamp}T{_rng(who, 'clk_spo2', day).choice(_SPO2_CLOCKS)}",
                     value=_tailed(sc, "spo2", who, day, offset, whole=True),
                     context="静息", source="手环"))
    rows.append(_row("temperature", f"{stamp}T{_rng(who, 'clk_temp', day).choice(_TEMP_CLOCKS)}",
                     value=_tailed(sc, "temperature", who, day, offset),
                     context="晨起", source="体温计"))
    if offset % 3 == 0:      # 称体重不必天天来，三五天一次才像真的
        rows.append(_row("weight", f"{stamp}T{_rng(who, 'clk_wt', day).choice(_WEIGHT_CLOCKS)}",
                         value=sc["weight"] + _rng(who, "wt", day).uniform(-0.3, 0.3),
                         source="体重秤"))
    return rows


def _rng(*parts: Any) -> random.Random:
    """由内容派生的确定性随机源：同一个人同一天同一个指标，永远同一个数。

    用 md5 而不是 ``hash()``：``hash()`` 受 PYTHONHASHSEED 影响，今天跑出来 142、
    明天跑出来 137，演示就"每次都不一样"了。分诊演示最怕这个。

    ``parts`` 的第一段应当是**稳定身份**（用户名/姓名），不是 ``elder_id`` —— 后者是
    ``seed_demo`` 每次新建的 uuid4，拿它做种子的话，一 reset 数据就换一副面孔：曲线
    形状一样，数却对不上。演示要的是"复位之后还是那一份档案"。
    """
    seed = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return random.Random(int(seed[:12], 16))


async def seed_kangle_persona(repo: Repository, elder: dict, *,
                              scenario: str = "hypertension_spike",
                              days: int = 30,
                              today: date | None = None) -> dict[str, Any]:
    """给老人补一份 30 天指标档案 + 慢病 + 用药（**在 ``seed_demo`` 之后调用**）。

    四个剧本，靠 ``scenario`` 选（key 或中文档位都认，见 ``resolve_scenario``），
    用来在答辩现场演示"同一套阈值，四种结论"—— 现场一句话切档：

    - ``stable``（保健）：30 天都在正常带里。同样的工具跑出来是"不用特意往医院跑"。
      这一档才是康乐想证明的东西：**日常保健优先于就医**，不是见数就撵人去医院。
    - ``observation``（观察）：常年 143/91 上下，略高于正常。落"观察"：复测、按时吃药。
    - ``hypertension_spike``（建议就医，默认）：前 25 天平稳、最近 5 天一路走高，今晨
      178/105。跑 ``assess_health`` 落"建议就医"，advice 里就是"帮您就近挂号"。
    - ``emergency``（紧急）：今晨 186/112 且血氧 88%，两条独立的触顶路径同时成立。

    日期一律相对 ``today``（默认"今天"）生成，绝不写死：演示那天数据必须是当天的，
    否则时间线一翻全是几个月前，一眼露馅。

    幂等：只往 health_metrics / health_conditions / medication_plans 追加，
    重复调用会灌重。演示复位走 ``seed_demo``（它 reset 全表）。
    """
    key = resolve_scenario(scenario)
    sc = SCENARIOS[key]
    elder_id = elder["id"]
    # 噪声种子用稳定身份（用户名），不用 uuid —— 复位后还是同一份档案。见 ``_rng``。
    who = elder.get("username") or elder.get("name") or elder_id
    day0 = today or date.today()

    for cond in KANGLE_PERSONA["conditions"]:
        await repo.insert("health_conditions", {"elder_id": elder_id, **cond})
    for med in KANGLE_PERSONA["medications"]:
        await repo.insert("medication_plans", {"elder_id": elder_id, **med})

    readings: list[dict] = []
    missed: list[str] = []
    missed_offsets = _missed_offsets(days)
    for offset in range(days - 1, -1, -1):   # offset = 距今天数：0 是今天，days-1 是最早那天
        day = day0 - timedelta(days=offset)
        if offset in missed_offsets:
            missed.append(day.isoformat())   # 整天没量 —— 老人不是机器
            continue
        readings.extend({"elder_id": elder_id, **row}
                        for row in _readings_for_day(sc, who, day, offset))

    await repo.insert_many("health_metrics", readings)

    # 档位是**用生成的数算出来的**，不是把剧本名抄回来：抄回来的话，哪天数值改飘了，
    # 脚本照样念"紧急"，而库里的数其实落在别的档 —— 演示最怕这种自说自话。
    latest: dict[str, dict] = {}
    for row in readings:                     # 正序生成，后面的覆盖前面的 = 每类最新一条
        latest[row["metric_type"]] = row
    verdict = hr.triage(latest, conditions=KANGLE_PERSONA["conditions"])

    return {
        "elder_id": elder_id, "scenario": key,
        "conditions": len(KANGLE_PERSONA["conditions"]),
        "medications": len(KANGLE_PERSONA["medications"]),
        "readings": len(readings),
        # 四个剧本都给出今天的展示数（旧实现只有 spike 才非 None）。spike 仍是 (178, 105)
        "latest_bp": sc["bp_tail"][0],
        "level": verdict["level"], "declared_level": sc["level"],
        "days": days, "today": day0.isoformat(), "missed_days": missed,
    }
