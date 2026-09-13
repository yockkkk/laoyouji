"""分诊参考区间与规则引擎 —— 康乐左翼·身体健康的"分诊大脑"。

**这不是诊断，是分流。** 红线 R1/R2 说得很死：不下诊断、不开处方。所以这里做的
只有一件事 —— 把一条指标（或一句症状）放进一个**行动档位**：

    保健 < 观察 < 建议就医 < 紧急

档位决定的是"下一步做什么"，不是"得了什么病"：保健=在家照顾好、别往医院跑；
建议就医=帮你就近挂号、规划路线；紧急=立刻联系家人/120。用户的原话是
**"日常保健优先于就医"** —— 所以这套阈值刻意**偏保守地往低档收**：血压 138/86 这种
老人常态不该惊动医院，只有到了中重度区间才抬到"建议就医"，到了急症区间才报"紧急"。

两个设计前提，缺一不可：
- **保健优先**：默认落在"保健"。一条指标不明确越界，就不往上抬档 —— 宁可让系统
  显得"不够紧张"，也不能一有风吹草动就撵着老人上医院（那正是本项目要反的东西）。
- **急症有下限**：但"保健优先"绝不能盖住真正危险的值。血压 ≥180/110、血氧 <90、
  高热 ≥39、重度低血糖 —— 这些直接顶到"紧急"，不受保健优先影响。这是安全底线。

全部是**纯函数**：同输入同输出，不碰库、不碰模型。分诊结论要能在答辩现场当场演示
"输 178/105 进去，出来是哪一档、为什么" —— 可复现、可逐条指认，这是它敢挂"分诊"
两个字的前提。数值全是合成演示数据，临床区间取通行的老年人常用口径，仅供演示。
"""
from __future__ import annotations

from typing import Any

# 四个行动档位，从轻到重。名字直接给老人看，序号用来取"最重的那一档"。
LEVELS = ("保健", "观察", "建议就医", "紧急")


def level_rank(level: str) -> int:
    """档位的严重度序号（越大越重）。不认识的字样按最轻处理，不误抬档。"""
    return LEVELS.index(level) if level in LEVELS else 0


def max_level(*levels: str) -> str:
    """取最重的一档。没有任何输入时落回"保健"（保健优先的兜底）。"""
    ranked = [lv for lv in levels if lv in LEVELS]
    return max(ranked, key=level_rank) if ranked else "保健"


# ---------------------------------------------------------------- 指标元信息
# label 给老人看，unit 印在卡上，normal 是"正常范围"的大白话（趋势图底纹也用它）。
METRICS: dict[str, dict[str, Any]] = {
    "bp": {"label": "血压", "unit": "mmHg", "normal": "收缩压 90–140 / 舒张压 60–90",
           "compound": True},
    "glucose": {"label": "血糖", "unit": "mmol/L", "normal": "空腹 3.9–7.0，餐后 <10"},
    "heart_rate": {"label": "心率", "unit": "次/分", "normal": "60–100"},
    "spo2": {"label": "血氧", "unit": "%", "normal": "≥95"},
    "temperature": {"label": "体温", "unit": "℃", "normal": "36–37.2"},
    "weight": {"label": "体重", "unit": "kg", "normal": "因人而异，看趋势"},
}

# context 允许的取值（血糖分餐前/餐后，别的指标用不上）。
FASTING_CONTEXTS = ("空腹", "餐前", "fasting", "")


def metric_label(metric_type: str) -> str:
    meta = METRICS.get(metric_type)
    return meta["label"] if meta else metric_type


def metric_unit(metric_type: str) -> str:
    meta = METRICS.get(metric_type)
    return meta["unit"] if meta else ""


def coerce_reading(args: dict) -> dict:
    """模型填的参数 → 一条标准读数行（纯整形，不落库）。

    血压允许两种填法：分开的 systolic/diastolic，或合在一个字符串里的 "178/105" ——
    模型两种都见过，甚至会把整串塞进 systolic 或 value 里。这不能当没看见：那是老人
    真报出来的数，丢了就得让他再报一遍。其余指标读 value。context 原样带过（血糖分
    餐前/餐后要用）。数值一律过 ``_num``：填不进数字的（空、乱填）落成 None，由上层
    判成"没测到"。
    """
    mtype = str(args.get("metric_type") or "").strip()
    row: dict = {"metric_type": mtype}
    if mtype == "bp":
        s, d = args.get("systolic"), args.get("diastolic")
        if d is None:
            for candidate in (args.get("value"), s):
                if isinstance(candidate, str) and "/" in candidate:
                    s, _, d = candidate.partition("/")
                    break
        row["systolic"] = _num(s)
        row["diastolic"] = _num(d)
    else:
        row["value"] = _num(args.get("value"))
    ctx = str(args.get("context") or "").strip()
    if ctx:
        row["context"] = ctx
    return row


# ---------------------------------------------------------------- 单条读数分档

def classify_reading(metric_type: str, *, value: Any = None,
                     systolic: Any = None, diastolic: Any = None,
                     context: str | None = None) -> tuple[str, str]:
    """一条读数 → (档位, 一句大白话原因)。取不到有效数值就返回 ("保健", "")。

    这是分诊的原子操作：只看**这一条**读数，不看历史、不看慢病。历史与慢病由
    ``triage`` 在更上层合并。刻意如此 —— 单条判定要能被单元测试逐个钉死。
    """
    if metric_type == "bp":
        s, d = _num(systolic), _num(diastolic)
        if s is None or d is None:
            return "保健", ""
        return _classify_bp(s, d)

    v = _num(value)
    if v is None:
        return "保健", ""
    if metric_type == "glucose":
        return _classify_glucose(v, context)
    if metric_type == "heart_rate":
        return _classify_heart_rate(v)
    if metric_type == "spo2":
        return _classify_spo2(v)
    if metric_type == "temperature":
        return _classify_temperature(v)
    # 体重等无分诊意义的指标：只记录、看趋势，不参与抬档
    return "保健", ""


def _classify_bp(s: float, d: float) -> tuple[str, str]:
    si, di = int(round(s)), int(round(d))
    # 急症下限：高血压急症 / 明显低血压 —— 不受保健优先影响
    if s >= 180 or d >= 110:
        return "紧急", f"血压 {si}/{di}，已到高血压急症区间"
    if s < 90 or d < 60:
        return "建议就医", f"血压 {si}/{di}，偏低"
    # 中重度偏高：撑起主线 A 的"178/105 → 建议就医"
    if s >= 160 or d >= 100:
        return "建议就医", f"血压 {si}/{di}，中重度偏高"
    # 轻度偏高：观察、按时服药、复测，别急着跑医院
    if s >= 140 or d >= 90:
        return "观察", f"血压 {si}/{di}，略高于正常"
    # 主线 C 的"138/86 → 保健"落在这里
    return "保健", f"血压 {si}/{di}，在平稳范围"


def _classify_glucose(v: float, context: str | None) -> tuple[str, str]:
    fasting = (context or "") in FASTING_CONTEXTS
    when = "空腹" if fasting else "餐后"
    # 低血糖比高血糖更急：先判低
    if v < 3.0:
        return "紧急", f"血糖 {v}，重度偏低（低血糖）"
    if v < 3.9:
        return "建议就医", f"血糖 {v}，偏低"
    if fasting:
        if v >= 13.9:
            return "建议就医", f"{when}血糖 {v}，明显偏高"
        if v >= 7.0:
            return "观察", f"{when}血糖 {v}，略偏高"
        return "保健", f"{when}血糖 {v}，控制得不错"
    if v >= 16.7:
        return "建议就医", f"{when}血糖 {v}，明显偏高"
    if v >= 11.1:
        return "观察", f"{when}血糖 {v}，偏高"
    return "保健", f"{when}血糖 {v}，控制得不错"


def _classify_heart_rate(v: float) -> tuple[str, str]:
    hr = int(round(v))
    if v >= 130 or v <= 40:
        return "建议就医", f"心率 {hr} 次/分，明显异常"
    if v >= 100 or v < 50:
        return "观察", f"心率 {hr} 次/分，略偏{'快' if v >= 100 else '慢'}"
    return "保健", f"心率 {hr} 次/分，正常"


def _classify_spo2(v: float) -> tuple[str, str]:
    pct = int(round(v))
    if v < 90:
        return "紧急", f"血氧 {pct}%，过低"
    if v < 94:
        return "建议就医", f"血氧 {pct}%，偏低"
    if v < 95:
        return "观察", f"血氧 {pct}%，略低"
    return "保健", f"血氧 {pct}%，正常"


def _classify_temperature(v: float) -> tuple[str, str]:
    if v >= 39.0:
        return "建议就医", f"体温 {v}℃，高热"
    if v < 35.0:
        return "建议就医", f"体温 {v}℃，过低"
    if v >= 37.3:
        return "观察", f"体温 {v}℃，低热"
    return "保健", f"体温 {v}℃，正常"


# ---------------------------------------------------------------- 症状红旗
# 只认**明确的危险信号**，宁可漏、不可扩。一句普通的"有点累"不该惊动分诊 ——
# 保健优先。命中"紧急"词直接顶到紧急；命中"就医"词抬到建议就医；都没命中但确实报了
# 症状，落"观察"（比保健重一档，advice 里带一句"持续/加重就去看"）。
_EMERGENCY_SYMPTOMS = (
    "胸痛", "胸口疼", "胸口压", "胸闷得厉害", "呼吸困难", "喘不上气", "喘不过气",
    "意识不清", "晕厥", "昏迷", "抽搐", "半身", "偏瘫", "嘴歪", "说不出话",
    "剧烈头痛", "咯血", "呕血", "大出血",
)
_SEE_DOCTOR_SYMPTOMS = (
    "持续", "反复", "越来越", "加重", "高烧", "高热", "便血", "黑便",
    "视物模糊", "看不清", "站不稳", "剧烈", "撑不住",
    # "拖了好几天"是老人说"持续"的方式。只认书面语的"持续"，等于把最常见的那种
    # 主诉留在"观察"里 —— 而拖了几天的症状恰恰是该去看的那一类。
    "好几天", "几天了", "好久了", "好几个月", "一直没好", "不见好", "老不好",
)


def assess_symptom(text: str | None) -> tuple[str, str] | None:
    """一句症状描述 → (档位, 原因)。没报症状返回 None（不参与分诊）。"""
    if not text or not str(text).strip():
        return None
    t = str(text)
    for kw in _EMERGENCY_SYMPTOMS:
        if kw in t:
            return "紧急", f"提到“{kw}”，属于危险信号"
    for kw in _SEE_DOCTOR_SYMPTOMS:
        if kw in t:
            return "建议就医", f"提到“{kw}”，建议让医生看看"
    # 兜底这句原来是死板的"有不舒服，先观察…"，把老人**自己的话**丢掉了。这句会
    # 一路进到子女收到的知会里（``_visit_reason`` 取的就是 drivers 的 reason），
    # 家人只看到"有不舒服"，看不出老人这趟是去看什么 —— 而"完整知会"要的正是这一句：
    # 子女是照着它判断要不要回一趟家的。
    # 照抄原话，但**截断**：知会里该是"腿疼"这样的短主诉，不是老人整段转述。
    said = " ".join(str(t).split())
    if len(said) > 12:
        said = said[:12] + "…"
    return "观察", f"提到“{said}”，先观察，持续或加重就去看医生"


# ---------------------------------------------------------------- 趋势

def trend(series: list[float]) -> str:
    """一串按时间正序的数值 → "上升" / "下降" / "平稳"。

    比的是"后段均值"和"前段均值"：把序列三等分，用末段减首段，超过首段的 5%
    （且至少一个绝对下限）才算真的动了，否则一律"平稳" —— 避免把测量噪声读成趋势。
    主线 A 的"最近 5 天走高"就是靠这个亮出来的。
    """
    vals = [x for x in (_num(v) for v in series) if x is not None]
    if len(vals) < 4:
        return "平稳"
    third = max(1, len(vals) // 3)
    head = sum(vals[:third]) / third
    tail = sum(vals[-third:]) / third
    delta = tail - head
    deadband = max(abs(head) * 0.05, 1e-9)
    if delta > deadband:
        return "上升"
    if delta < -deadband:
        return "下降"
    return "平稳"


# ---------------------------------------------------------------- 合并分诊

def triage(latest_by_type: dict[str, dict], *, conditions: list[dict] | None = None,
           symptom: str | None = None,
           trends: dict[str, str] | None = None) -> dict:
    """把"每类指标的最新一条 + 慢病 + 症状"合并成一个分诊结论。

    ``latest_by_type``：``{metric_type: reading_row}``，每类只取最新一条 —— 分诊看的是
    "现在什么状态"，历史趋势由 ``trends`` 带进来只用于措辞（不改档位，趋势不是急症）。

    返回：``{level, advice, drivers, headline}``，全部结构化，交给 ``assess_health``
    落 report_key=assessment。**保健优先**：没有任何一条越界，就是"保健"。
    """
    conditions = conditions or {}
    trends = trends or {}
    drivers: list[dict] = []

    for mtype, row in (latest_by_type or {}).items():
        level, reason = classify_reading(
            mtype,
            value=row.get("value"),
            systolic=row.get("systolic"), diastolic=row.get("diastolic"),
            context=row.get("context"),
        )
        if level_rank(level) > 0 and reason:
            # 趋势只进措辞，不抬档：连续走高的血压更值得说一句，但档位仍由数值定
            if trends.get(mtype) == "上升":
                reason += "，且最近持续走高"
            drivers.append({"metric": mtype, "level": level, "reason": reason})

    sym = assess_symptom(symptom)
    if sym is not None:
        drivers.append({"metric": "symptom", "level": sym[0], "reason": sym[1]})

    overall = max_level(*(d["level"] for d in drivers)) if drivers else "保健"
    # 最重的驱动因素排在前面，advice 好据此说话
    drivers.sort(key=lambda d: level_rank(d["level"]), reverse=True)

    return {
        "level": overall,
        "advice": _advice_for(overall, conditions),
        "drivers": drivers,
        "headline": _headline(overall, drivers),
    }


_ADVICE = {
    "保健": "指标都在平稳范围，继续按时吃药、清淡饮食、每天散散步就好，不用特意往医院跑。",
    "观察": "略有偏高，先观察：按时服药、今天少盐少油，明后天再测一次；持续偏高我再帮您约医生。",
    "建议就医": "建议这两天去医院看看。我可以帮您就近挂个号、规划好怎么去，并把情况一并告诉家里人。",
    "紧急": "这个情况比较急，请立刻联系家人或拨打 120，先别自己扛，也别独自出门。",
}


def _advice_for(level: str, conditions: Any) -> str:
    base = _ADVICE.get(level, _ADVICE["保健"])
    return base


def _headline(level: str, drivers: list[dict]) -> str:
    if not drivers:
        return "各项指标平稳，注意日常保健即可。"
    top = "；".join(d["reason"] for d in drivers[:2])
    return f"{top}。分诊结论：{level}。"


# ---------------------------------------------------------------- 展示辅助

def metric_scalar(row: dict) -> float | None:
    """一条读数的"头条数值"：血压取收缩压，其余取 value。趋势/概览按它排。"""
    if row.get("metric_type") == "bp":
        return _num(row.get("systolic"))
    return _num(row.get("value"))


def format_reading(row: dict) -> str:
    """一条读数 → 印在卡上/念给老人听的一句：``178/105 mmHg`` / ``8.5 mmol/L（餐后）``。"""
    mtype = row.get("metric_type", "")
    unit = metric_unit(mtype)
    if mtype == "bp":
        s, d = _num(row.get("systolic")), _num(row.get("diastolic"))
        core = f"{int(round(s))}/{int(round(d))}" if s is not None and d is not None else "—"
    else:
        v = _num(row.get("value"))
        core = f"{v:g}" if v is not None else "—"
    text = f"{core} {unit}".strip()
    ctx = row.get("context")
    if mtype == "glucose" and ctx:
        text += f"（{ctx}）"
    return text


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None
