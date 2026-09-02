"""风险规则 —— Guard 流水线的具体守卫（安全管控中间层）。

- PaymentRiskRule：高危工具集 + 金额阈值 → INTERCEPT（子女确认）
- ScamContentRule：参数中出现疑似诈骗内容（可疑链接/话术）→ DENY
- HealthDisclaimerGuard（后置过滤器）：健康域输出强制追加免责声明（红线 R4）
- 诊断口吻改写（``install_medical_safety``）：红线 R1/R2 的最后一道 ——
  挂在 ``agent/request`` 上，模型说出"您这是××病"的那一刻就被改写成引导就医。
  提示词是第一道防线，不是最后一道：模型偶尔会忘，而这条线不能靠自觉。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from app.core.bus import EventBus, REQUEST
from app.core.context import TurnContext
from app.core.guard import Guard, GuardResult, GuardVerdict
from app.core.tool import Tool

logger = logging.getLogger(__name__)

# 红线 R5：高危工具集一律拦截（支付/订票/订酒店/挂号付费/服务下单）
HIGH_RISK_TOOLS = {
    "book_ticket", "book_hotel", "register_appointment", "pay", "order_service",
}

HEALTH_TOOLS = {
    "interpret_report", "diet_advice", "register_appointment", "search_hospital",
    "check_scam",
}

# 口径按用户要求收紧：明说"辅助解读、不做诊断"，别让人误读成"AI 看过就算看过病"。
#
# 两版措辞，同一个口径。DISCLAIMER 是体检解读那一版 —— 它说的是"报告上的话"，
# 只有 interpret_report 面前真有一份报告。GENERIC_DISCLAIMER 给其余健康域工具：
# 反诈判定、挂号回执、医院列表、饮食建议后面挂一句"以上是把报告上的话换成大白话"，
# 老人听到的是一句对不上号的话，而对不上号的免责声明是会被当噪音跳过去的。
#
# 两版都含"辅助""不是诊断结论""遵医嘱"三要素 —— R4 的**实质**在哪个工具上都一样，
# 变的只是指代。去重判据（"遵医嘱"）对两版同时成立，所以换措辞不会换出两遍声明。
DISCLAIMER = ("（以上是把报告上的话换成大白话，属于辅助解读，"
              "不是诊断结论。身体的事请听医生的，遵医嘱。）")
GENERIC_DISCLAIMER = ("（以上是帮您参考的，属于辅助提醒，"
                      "不是诊断结论。身体的事请听医生的，遵医嘱。）")

# 谁用哪一版：一张明账，不是散在 apply 里的 if。默认走 GENERIC ——
# 新增健康域工具时忘了登记，拿到的是那句放之四海皆可的，不是一句错的。
_DISCLAIMER_BY_TOOL = {"interpret_report": DISCLAIMER}

# 疑似诈骗信号（配合 check_scam 工具的语料库）。
#
# 这份词表看的是**工具参数**，命中就硬拒绝执行 —— 所以它必须窄，宽了会把正常
# 下单也拒掉，而 DENY 没有"问一下家人"这个出口。老人念出来的原文由 check_scam
# 自己那份更宽的词表判断（`tools/health_tools.py:_SCAM_MARKERS`），那一支只出
# 判断、不动钱，宁可多提醒一句。改词表前先想清楚改的是哪一份。
_SCAM_PATTERNS = [
    r"转账", r"保证金", r"解冻费", r"安全账户", r"中奖.{0,6}领取",
    r"冒充.{0,4}(孙子|儿子|客服|公检法)", r"保健品.{0,8}(根治|神药|包治)",
]
_URL_RE = re.compile(r"https?://[^\s\"']+")

# 判断内容 ≠ 照着内容办事。
#
# 反诈工具的入参**就是**那条可疑短信，所以下面这条守卫每次都会在它身上命中：
# 老人说"帮我看看这条短信是不是骗子"，被自己的反诈规则 DENY 掉，拿不到语料库
# 那句具体建议（"挂了电话给孙子本人打一个"），健康档案里也不留痕 —— 反诈这个
# 加分项因此在最该生效的那一刻是空的。
#
# 豁免的前提写死在这里：这类工具不动钱、不下单、不锁号源，只产出一个判断。
# R5 管的是"不做无人监护的执行"，不是"不许看一眼"。
_JUDGES_CONTENT = {"check_scam"}


class PaymentRiskRule(Guard):
    """高危操作拦截：触发子女确认机制。"""

    name = "payment_risk"

    def __init__(self, amount_threshold: float = 50.0):
        self._threshold = amount_threshold

    async def check(self, turn: TurnContext, tool_name: str, args: dict) -> GuardResult:
        amount = _extract_amount(args)
        if tool_name in HIGH_RISK_TOOLS:
            return GuardResult(
                GuardVerdict.INTERCEPT,
                reason="涉及支付/重要事项，需要家人确认" if not amount
                else f"涉及金额 {amount:.2f} 元，需要家人确认",
                risk_level="high" if (amount or 0) >= self._threshold else "medium",
                amount=amount,
            )
        if amount and amount >= self._threshold:
            return GuardResult(
                GuardVerdict.INTERCEPT,
                reason=f"金额 {amount:.2f} 元超过阈值，需要家人确认",
                risk_level="medium", amount=amount,
            )
        return GuardResult(GuardVerdict.ALLOW)


class ScamContentRule(Guard):
    """疑似诈骗内容：直接拒绝并给老人可执行的建议。"""

    name = "scam_content"

    async def check(self, turn: TurnContext, tool_name: str, args: dict) -> GuardResult:
        if tool_name in _JUDGES_CONTENT:
            return GuardResult(GuardVerdict.ALLOW)  # 见 _JUDGES_CONTENT
        text = " ".join(str(v) for v in args.values())
        for pattern in _SCAM_PATTERNS:
            if re.search(pattern, text):
                return GuardResult(
                    GuardVerdict.DENY,
                    reason="这个内容像是骗子的话术，先别操作。",
                    payload={"advice": "千万别转账。先给儿子打个电话问一问。"},
                )
        # 非白名单链接同样拒绝执行
        for url in _URL_RE.findall(text):
            if not _trusted_url(url):
                return GuardResult(
                    GuardVerdict.DENY,
                    reason="这个链接不是正规网站的。",
                    payload={"advice": "来路不明的链接不要点。让家人帮您看看。"},
                )
        return GuardResult(GuardVerdict.ALLOW)


class HealthDisclaimerGuard:
    """后置过滤器（PostToolFilter）：健康域工具输出强制带免责声明，不依赖 LLM 自觉。"""

    async def apply(self, turn: TurnContext, tool: Tool, result: dict) -> dict:
        if tool.name in HEALTH_TOOLS and result.get("ok"):
            note = _DISCLAIMER_BY_TOOL.get(tool.name, GENERIC_DISCLAIMER)
            for key in ("summary", "announce"):
                text = result.get(key) or ""
                if text and "遵医嘱" not in text and "不能替代" not in text:
                    result[key] = f"{text}{note}"
        return result


def _extract_amount(args: dict) -> float:
    """从调用参数里读出"这一笔要花多少钱"。

    ``price`` 往往是**单价**（每晚房价、每份餐费），而家人手机上那张卡问的是
    这一笔的总额。所以取到 ``price`` 后，若同一份参数里带着晚数/份数就乘起来
    —— 乘数和被乘数都在这份参数里，是算术，不是推测。``amount`` / ``total``
    本身已是总额，不再乘。

    这个数字不只印在卡上，还决定 ``risk_level``。按单价判风险等于按一晚的钱
    批一整趟住店。
    """
    for key in ("amount", "total", "price", "fee"):
        value = _as_float(args.get(key))
        if value is None:
            continue
        return value * _quantity(args) if key == "price" else value
    return 0.0


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):          # True 不是 1 块钱
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _quantity(args: dict) -> int:
    """单价的乘数：晚数 / 份数。取不到或不合理就按 1，绝不放大。"""
    for key in ("nights", "count", "quantity"):
        value = _as_float(args.get(key))
        if value is not None and value >= 1:
            return int(value)
    return 1


_TRUSTED_DOMAINS = (
    "12306.cn", "gov.cn", "supabase.co", "amap.com",
)


def _trusted_url(url: str) -> bool:
    return any(domain in url for domain in _TRUSTED_DOMAINS)


# ---------------------------------------------------------------- R1/R2 最后一道
# 提示词里已经写了"绝不诊断"，但提示词是**请求**，不是**保证**。这一段是保证：
# 模型的每句话在离开 provider 后、进入事件日志和老人屏幕之前，都过一遍这把筛子。
#
# 做法是**整句替换**而不是抠词：抠词会留下"您这是…（已隐去）"这种更吓人的残句，
# 整句换掉之后剩下的话仍然通顺。宁可少说一句，不可错说一句。

_DIAGNOSIS_PATTERNS = (
    r"(您|你|老人|奶奶|爷爷)(这)?(是|得的?是|患的?是|应该是|可能是)"
    r"[^，。；！？]{0,12}(病|症|癌|炎|瘤|梗|栓|中风|高血压|糖尿病|骨质疏松)",
    r"确诊",
    r"诊断(为|是|结果是|下来)",
    r"可以(确定|断定)[^，。；！？]{0,8}(是|为)",
    r"(属于|就是)[^，。；！？]{0,6}(期|型)[^，。；！？]{0,4}(癌|瘤|糖尿病|高血压)",
)

# 处方类：刻意要求出现**剂量单位或"药"字**才算命中。
# 否则"建议吃点清淡的"这类饮食建议会被误杀 —— 饮食推荐是本项目的正常能力。
_PRESCRIPTION_PATTERNS = (
    r"(吃|服用|口服|注射|输)[^，。；！？]{0,10}(片|粒|毫克|mg|ml|毫升|克|支|袋|颗)",
    r"每(天|日|次|晚)[^，。；！？]{0,6}\d+\s*(片|粒|毫克|mg|克)",
    r"(加大|加倍|减半|停|换)[^，。；！？]{0,6}药",
    r"(建议|应该|需要|可以)[^，。；！？]{0,6}(吃|服)[^，。；！？]{0,8}药",
    r"剂量",
)

DIAGNOSIS_REPLACEMENT = "这我不能替医生下判断，得让大夫当面看看才算。"
PRESCRIPTION_REPLACEMENT = "吃什么药、吃多少，得听医生的，我不能给您定。"

_SENTENCE_RE = re.compile(r"[^。！？\n]*[。！？\n]|[^。！？\n]+")


def scrub_medical_text(text: str) -> tuple[str, list[str]]:
    """逐句体检。命中即整句替换，返回 ``(新文本, 命中标签)``。

    纯函数：好测、好在答辩现场当场演示"输进去一句诊断，出来是什么"。
    """
    if not text:
        return text, []
    hits: list[str] = []
    out: list[str] = []
    replaced_kinds: set[str] = set()

    for raw in _SENTENCE_RE.findall(text):
        sentence = raw
        kind = ""
        if any(re.search(p, sentence) for p in _DIAGNOSIS_PATTERNS):
            kind = "diagnosis"
        elif any(re.search(p, sentence) for p in _PRESCRIPTION_PATTERNS):
            kind = "prescription"
        if not kind:
            out.append(sentence)
            continue
        hits.append(kind)
        if kind in replaced_kinds:
            continue                     # 同类只留一句替代话，不复读
        replaced_kinds.add(kind)
        out.append(DIAGNOSIS_REPLACEMENT if kind == "diagnosis"
                   else PRESCRIPTION_REPLACEMENT)

    cleaned = "".join(out).strip()
    if hits and not cleaned:
        cleaned = DIAGNOSIS_REPLACEMENT
    return cleaned, hits


def make_diagnosis_scrubber():
    """``agent/request`` 环绕中间件：改写模型这一步说出口的诊断/处方内容。

    挂在 request 瀑布的**最外层**（order 取负），所以它看到的是所有重试、
    所有其它中间件之后的**最终**那条应答 —— 谁也绕不过它。

    一个诚实的边界：流式 ``delta`` 是在 provider 内部逐片推的，比这里更早到前端。
    那些片段是"打字预览"（``persist=False``，不进事件日志）；进日志、进历史、
    以及前端最终定稿的那条气泡都来自随后 ``agent_msg`` 里的正文，也就是被改写过
    的这一份。前端必须用 ``agent_msg`` 覆盖预览 —— 这条契约写在 docs/DESIGN.md 里。
    """

    async def diagnosis_scrubber(request: Any,
                                 next_: Callable[..., Awaitable[Any]]) -> Any:
        response = await next_()
        content = getattr(response, "content", None)
        if not isinstance(content, str) or not content:
            return response
        cleaned, hits = scrub_medical_text(content)
        if hits:
            agent = getattr(getattr(request, "agent", None), "name", "?")
            logger.warning("R1/R2 改写：%s 的输出命中 %s，已替换为引导就医的话",
                           agent, "、".join(sorted(set(hits))))
            response.content = cleaned
        return response

    return diagnosis_scrubber


def install_medical_safety(bus: EventBus) -> list[Callable[[], None]]:
    """装配点：返回 disposer 列表。"""
    return [bus.on(REQUEST, make_diagnosis_scrubber(), order=-100,
                   label="diagnosis-scrubber")]
