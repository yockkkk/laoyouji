"""大白话翻译引擎 —— 公共组件（安全管控中间层），所有子 Agent 共用。

两级处理：
1. 术语词典：确定性规则替换（医学术语 → 老人听得懂的比喻）
2. LLM 改写：可选（有真实 LLM 时），60 岁以上可懂、短句、每句 ≤ 20 字
词典优先且必有 —— 拔掉 LLM 也能用（离线兜底）。
"""
from __future__ import annotations

import re
from typing import Any

# 医学/专业术语 → 大白话（示例语料，覆盖演示场景）
GLOSSARY: dict[str, str] = {
    "骨关节炎": "关节里的“垫子”磨薄了，走路会疼",
    "退行性病变": "年纪大了，零件用久了的老化",
    "CT增强扫描": "给血管里打一针药水，拍一张更清楚的片子",
    "核磁共振": "躺进一个圆筒机器里拍片子，不疼",
    "血沉": "查血里炎症的指标",
    "类风湿因子": "查关节炎是哪一种的验血项目",
    "骨密度": "查骨头结不结实",
    "骨质疏松": "骨头变脆了，容易裂",
    "氨基葡萄糖": "给关节“垫子”补营养的药",
    "餐后血糖": "吃完饭两小时后测的血里糖分",
    "糖化血红蛋白": "查最近三个月血糖平均水平的指标",
    "低盐低脂饮食": "菜里少放盐、少吃肥肉",
    "专家号": "经验最丰富的老医生看的号",
    "无障碍设施": "有电梯、坡道，轮椅能进的",
}

_GLOSSARY_RE = re.compile("|".join(map(re.escape, GLOSSARY)))

PLAIN_RULES = [
    (r"建议就诊", "建议去看医生"),
    (r"随访", "过段时间再来复查"),
    (r"复查", "再来检查一次"),
    (r"禁忌症", "不能用的情形"),
    (r"不良反应", "吃了可能不舒服的地方"),
]


def plain_substitute(text: str) -> str:
    """第一级：术语词典确定性替换。"""
    text = _GLOSSARY_RE.sub(lambda m: GLOSSARY[m.group(0)], text)
    for pattern, repl in PLAIN_RULES:
        text = re.sub(pattern, repl, text)
    return text


class PlainLanguageEngine:
    """注册为服务 plain_language，子 Agent 工具直接消费。"""

    name = "plain_language"

    def __init__(self, llm: Any | None = None):
        self._llm = llm

    async def to_plain(self, text: str) -> str:
        """专业文本 → 老人听得懂的话。词典先行，LLM 可选润色。"""
        result = plain_substitute(text)
        if self._llm is None or not text:
            return result
        try:
            resp = await self._llm.chat(build_glossary_prompt(text))
        except Exception:  # noqa: BLE001 — LLM 不可用时退回词典结果
            return result
        return resp.content.strip() or result

    async def chat_with_rules(self, system_prompt: str, user_text: str) -> str:
        if self._llm is None:
            return plain_substitute(user_text)
        try:
            resp = await self._llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ])
            return resp.content.strip()
        except Exception:  # noqa: BLE001
            return plain_substitute(user_text)


def build_glossary_prompt(text: str) -> list[dict]:
    return [
        {"role": "system", "content": (
            "你把下面的话改写成语速慢、60岁以上老人一次能听懂的大白话。"
            "规则：每句不超过20个字；不用专业词；像家人说话一样亲切；"
            "不要添加原文没有的信息；直接输出改写结果。")},
        {"role": "user", "content": text},
    ]
