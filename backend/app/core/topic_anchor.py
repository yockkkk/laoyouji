"""TopicAnchor —— 意图与活动主题锚点与防漂移状态机。

彻底解决“老人要去公园散步，聊着聊着突然跑到医院挂号看病”的上下文串味与注意力漂移：
1. 显式跟踪当前活跃活动意图（ActivityType）：闲聊(IDLE)、休闲散步(LEISURE_WALK)、
   就医陪护(MEDICAL_ESCORT)、日常陪伴(DAILY_COMPANION)。
2. 锁定与防漂移机制（Anti-Drift Guard）：
   当处于休闲散步状态（LEISURE_WALK 且 lock_turns_remaining > 0）时，通用行动与位移动词
   （“现在就走”、“导航路线怎么不给我”、“我要跟着导航走”、“走”、“怎么去”）绝对严禁串味漂移至就医挂号；
   只有老人明确表达突发身体急症（“胸口闷”、“疼得厉害”、“去医院”、“挂号”、“急诊”等）时，
   才允许切换至 MEDICAL_ESCORT。
3. 结构化动态提示词指令（render_prompt_directive）：
   向大模型注入强负向约束守卫（Negative Constraints），严禁在散步场景下主动推荐挂号或开具就医计划书。
"""
from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ActivityType(str, Enum):
    IDLE = "idle"
    LEISURE_WALK = "leisure_walk"
    MEDICAL_ESCORT = "medical_escort"
    DAILY_COMPANION = "daily_companion"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            val_lower = value.strip().lower()
            for member in cls:
                if member.value == val_lower or member.name.lower() == val_lower:
                    return member
        return super()._missing_(value)


# 明确的突发急症与就医看病关键词（唯有包含这些显式词汇才允许从散步状态切换到就医）
EXPLICIT_MEDICAL_KEYWORDS: tuple[str, ...] = (
    "看病",
    "急诊",
    "挂号",
    "医生",
    "去医院",
    "胸口闷",
    "疼得厉害",
    "心绞痛",
    "摔倒",
    "骨折",
    "救护车",
    "120",
    "配药",
    "开药",
    "复诊",
    "就医",
    "医院",
    "门诊",
    "难受得很",
    "心脏难受",
    "头晕得厉害",
    "胸闷",
    "高血压发作",
    "送医",
    "叫救护车",
)

# 通用行动与位移动词（在散步场景下严禁漂移至就医挂号）
GENERIC_MOVEMENT_WORDS: tuple[str, ...] = (
    "现在就走",
    "导航路线怎么不给我",
    "我要跟着导航走",
    "走",
    "怎么去",
    "导航",
    "路线",
    "怎么走",
    "出发",
    "带路",
    "过去",
    "出发吧",
    "带我去",
    "路怎么走",
    "给个路线",
    "把路线给我",
    "路线图",
    "去哪走",
    "走吧",
    "跟着走",
    "开始导航",
)

# 休闲散步与公园出行关键词
LEISURE_WALK_KEYWORDS: tuple[str, ...] = (
    "散步",
    "走走",
    "逛逛",
    "溜达",
    "溜弯",
    "遛弯",
    "溜个弯",
    "遛个弯",
    "出去溜溜",
    "下楼遛遛",
    "下楼遛弯",
    "溜弯去",
    "出去溜",
    "下楼遛",
    "出门溜",
    "下楼透透气",
    "透透气",
    "透气",
    "公园",
    "漫步",
    "绿道",
    "年嘉湖",
    "烈士公园",
    "橘子洲",
    "岳麓山",
    "天心阁",
    "梅溪湖",
    "洋湖",
    "植物园",
    "南郊公园",
    "月湖",
    "松雅湖",
    "晓园",
    "出门走走",
    "湖边散步",
    "去散步",
    "想散步",
    "散步路线",
    "慢走",
    "健步走",
    "西湖公园",
    "后湖",
    "巴溪洲",
    "活动筋骨",
)

# 日常陪伴关键词
DAILY_COMPANION_KEYWORDS: tuple[str, ...] = (
    "无聊",
    "聊聊天",
    "说说话",
    "唠嗑",
    "陪我聊",
    "讲故事",
    "讲个笑话",
    "谈心",
    "日常陪伴",
    "解闷",
    "唱首歌",
    "问你个事",
)

# 已知高频目的地与景点词典（按匹配优先级降序，优先长词）
KNOWN_DESTINATIONS: tuple[str, ...] = (
    "湖南烈士公园年嘉湖",
    "烈士公园年嘉湖",
    "湖南烈士公园跃进湖",
    "烈士公园跃进湖",
    "岳麓山爱晚亭",
    "岳麓山风景名胜区",
    "岳麓山顶",
    "岳麓山东门",
    "橘子洲头",
    "橘子洲风景区",
    "洋湖湿地公园",
    "洋湖国家湿地公园",
    "松雅湖湿地公园",
    "松雅湖国家湿地公园",
    "天心阁公园",
    "梅溪湖国际文化艺术中心",
    "梅溪湖公园",
    "西湖文化园",
    "西湖公园",
    "巴溪洲生态旅游景区",
    "后湖艺术园",
    "后湖国际艺术区",
    "湖南省植物园",
    "省植物园",
    "长沙生态动物园",
    "生态动物园",
    "湖南省人民医院天心阁院区",
    "湖南省人民医院（天心阁院区）",
    "湖南省人民医院",
    "中南大学湘雅医院",
    "湘雅医院",
    "湘雅二医院",
    "湘雅三医院",
    "长沙市第一医院",
    "长沙市中心医院",
    "湖南烈士公园",
    "烈士公园",
    "橘子洲",
    "岳麓山",
    "天心阁",
    "梅溪湖",
    "洋湖湿地",
    "松雅湖",
    "月湖公园",
    "月湖",
    "晓园公园",
    "晓园",
    "南郊公园",
    "巴溪洲",
    "圭塘河风光带",
    "湘江风光带",
    "年嘉湖",
    "跃进湖",
    "爱晚亭",
)


class TopicAnchor(BaseModel):
    """会话活动主题锚点。"""

    activity_type: ActivityType = ActivityType.IDLE
    target_destination: Optional[str] = None
    origin: str = "家"
    target_spot: Optional[str] = None
    health_constraints: list[str] = Field(default_factory=list)
    confirmed_steps: list[str] = Field(default_factory=list)
    lock_turns_remaining: int = 0

    def is_locked(self) -> bool:
        return self.lock_turns_remaining > 0

    def can_transition_to(self, new_type: Union[ActivityType, str], query: str = "") -> bool:
        """防漂移核心拦截规则：
        若当前已处于 LEISURE_WALK 且处于锁定轮次内，只有老人明确表达急症或看病关键词时才允许切换至就医。
        通用行动/位移动词严禁改变 activity_type。
        """
        if isinstance(new_type, str):
            try:
                new_type = ActivityType(new_type)
            except ValueError:
                return True

        if self.activity_type == ActivityType.LEISURE_WALK and self.lock_turns_remaining > 0:
            if new_type == ActivityType.MEDICAL_ESCORT:
                return any(k in query for k in EXPLICIT_MEDICAL_KEYWORDS)
            if new_type != ActivityType.LEISURE_WALK:
                return False
        return True

    def render_prompt_directive(self) -> str:
        """生成注入到 SystemPrompt 中的强抗漂移指令。"""
        if self.activity_type == ActivityType.LEISURE_WALK:
            dest_desc = self.target_destination or "公园/绿道"
            spot_desc = f"（具体地标/景区核心：{self.target_spot}）" if self.target_spot else ""
            constraints_desc = ""
            if self.health_constraints:
                constraints_desc = (
                    f"- 适老与体能约束：{', '.join(str(c) for c in self.health_constraints)}\n"
                )

            return (
                f"\n# 【当前活跃主题锚点 · 防漂移指令 (TOPIC ANCHOR)】\n"
                f"- 当前核心活动：休闲散步 / 公园漫步出行 (LEISURE_WALK)\n"
                f"- 出发地：{self.origin}\n"
                f"- 目标目的地：{dest_desc}{spot_desc}\n"
                f"{constraints_desc}"
                f"- 意图锁定剩余轮次：{self.lock_turns_remaining}\n"
                f"【强负向约束守卫（绝对红线）】：\n"
                f"1. 当前老人处于公园散步与休闲出行场景，老人所说的“走”、“现在就走”、“导航”、“路线怎么不给我”、“我要跟着导航走”、“怎么去”等词汇，100% 指向当前散步目的地（{dest_desc}）的步行路线规划！\n"
                f"2. 严禁漂移到医院看病、挂号或门诊！在老人未明确表达突发身体急症（如胸口闷、剧烈心绞痛、摔倒骨折）之前，绝对严禁主动推荐医院、挂专家号、查门诊科室，绝对严禁出具就医挂号计划书！\n"
                f"3. 散步规划必须调用北斗适老路线工具（bds_escort_route / plan_bds_elder_route / plan_route），提供零台阶、平缓坡度、有林荫长椅的绿道方案。\n"
            )
        elif self.activity_type == ActivityType.MEDICAL_ESCORT:
            dest_desc = self.target_destination or "医院"
            return (
                f"\n# 【当前活跃主题锚点 · 就医护航指令 (TOPIC ANCHOR)】\n"
                f"- 当前核心活动：就近就医 / 看病就诊陪护 (MEDICAL_ESCORT)\n"
                f"- 出发地：{self.origin}\n"
                f"- 目标目的地：{dest_desc}\n"
                f"- 核心要求：为老人快速匹配对症医院、挂号绿通、无障碍就医出行路线与防护提示。\n"
            )
        elif self.activity_type == ActivityType.DAILY_COMPANION:
            return (
                f"\n# 【当前活跃主题锚点 · 日常关怀指令 (TOPIC ANCHOR)】\n"
                f"- 当前核心活动：日常陪伴 / 闲聊解闷 (DAILY_COMPANION)\n"
                f"- 核心要求：倾听老人心声，温暖亲切唠嗑，避免机械推荐外出或强加任务清单。\n"
            )
        return ""

    def dict(self, *args, **kwargs) -> dict[str, Any]:
        return self.model_dump(*args, **kwargs)


def detect_activity_from_text(text: str) -> Optional[ActivityType]:
    """从输入文本中识别活动意图。

    注意：若文本仅包含通用位移动词（如“现在就走”、“导航路线怎么不给我”），返回 None，
    避免无上下文时将移动指令误判为就医。
    若包含明确身体急症与就医关键词，优先识别为 MEDICAL_ESCORT。
    """
    if not text:
        return None

    # 1. 显式就医急症关键词判定（最高安全级）
    if any(k in text for k in EXPLICIT_MEDICAL_KEYWORDS):
        return ActivityType.MEDICAL_ESCORT

    # 2. 休闲散步与公园出行意图判定
    if any(k in text for k in LEISURE_WALK_KEYWORDS):
        return ActivityType.LEISURE_WALK

    # 3. 日常陪伴与闲聊意图判定
    if any(k in text for k in DAILY_COMPANION_KEYWORDS):
        return ActivityType.DAILY_COMPANION

    return None


def extract_destination(text: str) -> Optional[str]:
    """从文本中提取目标目的地（如“烈士公园年嘉湖”、“烈士公园”、“橘子洲”等），支持否定前缀过滤。"""
    if not text:
        return None

    # 1. 查找文本中所有否定词块的范围（如“不去烈士公园”、“别去XX”）
    neg_spans = []
    for neg_m in re.finditer(r"(?:不去|不要去|别去|不打算去|不想到|不到|取消去)\s*([A-Za-z0-9\u4e00-\u9fa5]{2,20})", text):
        neg_spans.append((neg_m.start(), neg_m.end(), neg_m.group(1)))

    def is_negated(start_idx: int, dest_name: str) -> bool:
        for ns, ne, neg_word in neg_spans:
            if start_idx >= ns and start_idx <= ne:
                return True
            if dest_name in neg_word:
                return True
        return False

    # 2. 匹配已知高频地标库（长词优先，正向优先）
    matched_positive = []
    for dest in KNOWN_DESTINATIONS:
        idx = text.find(dest)
        if idx != -1:
            if not is_negated(idx, dest):
                matched_positive.append((idx, len(dest), dest))

    if matched_positive:
        # 按长词优先、出现位置优先排序
        matched_positive.sort(key=lambda x: (-x[1], x[0]))
        return matched_positive[0][2]

    # 3. 模式匹配：以“去/到/往/前往/逛/游览”引导的目的地名称
    pattern = re.compile(
        r"(?:(?<!不)(?<!别)(?:去|到|往|前往|在|逛|游览|去往|去一趟))\s*"
        r"([A-Za-z0-9\u4e00-\u9fa5]{2,20}?(?:公园|湿地|景区|艺术园|风光带|绿道|广场|湖|山|阁|洲|医院|门诊|中心))"
    )
    match = pattern.search(text)
    if match:
        extracted = match.group(1).strip()
        if not any(w in extracted for w in ("怎么", "怎么去", "现在就", "导航")):
            return extracted

    # 4. 泛化名称模式：提取后缀为公园/湿地/绿道/风光带/景区的词组
    fallback_pattern = re.compile(
        r"([A-Za-z0-9\u4e00-\u9fa5]{2,12}(?:公园|湿地|绿道|风光带|景区))"
    )
    for fb_match in fallback_pattern.finditer(text):
        extracted = fb_match.group(1).strip()
        if not is_negated(fb_match.start(), extracted):
            return extracted

    return None


def _extract_spot(text: str) -> Optional[str]:
    """提取目的地内部具体景点/地标。"""
    spots = ("年嘉湖", "跃进湖", "爱晚亭", "橘子洲头", "问天台", "飞来石")
    for s in spots:
        if s in text:
            return s
    return None


def update_topic_anchor(current: Optional[TopicAnchor], user_text: str) -> TopicAnchor:
    """根据最新用户输入更新主题锚点，执行防漂移状态机流转。"""
    if current is None:
        anchor = TopicAnchor()
    else:
        anchor = current.model_copy(deep=True)

    text = (user_text or "").strip()
    if not text:
        return anchor

    has_explicit_medical = any(k in text for k in EXPLICIT_MEDICAL_KEYWORDS)
    detected_type = detect_activity_from_text(text)
    is_generic_movement = any(w in text for w in GENERIC_MOVEMENT_WORDS)

    # -------------------------------------------------------------
    # 状态机与防漂移仲裁
    # -------------------------------------------------------------
    if anchor.activity_type == ActivityType.LEISURE_WALK and anchor.lock_turns_remaining > 0:
        if has_explicit_medical:
            # 唯有老人明确提出突发急症/看病，才允许从散步状态切换到就医
            anchor.activity_type = ActivityType.MEDICAL_ESCORT
            anchor.lock_turns_remaining = 3
            step_msg = "突发身体急症：切换至就医护航通道"
            if step_msg not in anchor.confirmed_steps:
                anchor.confirmed_steps.append(step_msg)
        else:
            # 防漂移守卫：通用行动/位移动词严禁漂移到就医
            anchor.activity_type = ActivityType.LEISURE_WALK
            if is_generic_movement or "安静" in text:
                # 散步流程进行中，延续锁定
                anchor.lock_turns_remaining = max(anchor.lock_turns_remaining, 3)
            else:
                anchor.lock_turns_remaining = max(anchor.lock_turns_remaining - 1, 0)

    elif anchor.activity_type == ActivityType.LEISURE_WALK and anchor.lock_turns_remaining <= 0:
        if has_explicit_medical:
            anchor.activity_type = ActivityType.MEDICAL_ESCORT
            anchor.lock_turns_remaining = 3
        elif detected_type == ActivityType.DAILY_COMPANION:
            anchor.activity_type = ActivityType.DAILY_COMPANION
        else:
            # 未提急症且出现散步或通用行动词，保持 LEISURE_WALK 并重新加锁
            anchor.activity_type = ActivityType.LEISURE_WALK
            if is_generic_movement:
                anchor.lock_turns_remaining = 3

    else:
        # 当前为 IDLE、DAILY_COMPANION 或 MEDICAL_ESCORT
        if has_explicit_medical or detected_type == ActivityType.MEDICAL_ESCORT:
            anchor.activity_type = ActivityType.MEDICAL_ESCORT
            anchor.lock_turns_remaining = 3
        elif detected_type == ActivityType.LEISURE_WALK:
            anchor.activity_type = ActivityType.LEISURE_WALK
            anchor.lock_turns_remaining = 5  # 散步意图建立，锁定至少 5 轮
            step_msg = "意图确认：休闲散步"
            if step_msg not in anchor.confirmed_steps:
                anchor.confirmed_steps.append(step_msg)
        elif detected_type == ActivityType.DAILY_COMPANION:
            anchor.activity_type = ActivityType.DAILY_COMPANION

    # -------------------------------------------------------------
    # 目的地与景点地标更新（防止更具体的目的地被子景点退化降级）
    # -------------------------------------------------------------
    extracted_dest = extract_destination(text)
    if extracted_dest:
        if (
            anchor.target_destination
            and extracted_dest in anchor.target_destination
            and len(extracted_dest) < len(anchor.target_destination)
        ):
            # 保留更具体、包含大景区上下文的现有目的地（例如保留“烈士公园年嘉湖”，不降级为“年嘉湖”）
            pass
        else:
            anchor.target_destination = extracted_dest
            dest_step = f"锁定目的地：{extracted_dest}"
            if dest_step not in anchor.confirmed_steps:
                anchor.confirmed_steps.append(dest_step)

    extracted_spot = _extract_spot(text)
    if extracted_spot:
        anchor.target_spot = extracted_spot
        # 若此前尚未识别出大目的地，根据景点反向回填
        if not anchor.target_destination:
            if extracted_spot in ("年嘉湖", "跃进湖"):
                anchor.target_destination = f"烈士公园{extracted_spot}"
            elif extracted_spot in ("爱晚亭",):
                anchor.target_destination = f"岳麓山{extracted_spot}"
            elif extracted_spot in ("橘子洲头",):
                anchor.target_destination = "橘子洲头"

    # -------------------------------------------------------------
    # 适老偏好与健康体能约束提取（涵盖方言与口语变体）
    # -------------------------------------------------------------
    if "安静" in text or "清静" in text:
        c = "偏好清幽安静绿道"
        if isinstance(anchor.health_constraints, list) and c not in anchor.health_constraints:
            anchor.health_constraints.append(c)
    if any(k in text for k in ("避台阶", "不要走楼梯", "无台阶", "不要台阶", "不能走楼梯", "千万不要有台阶", "不想爬坡", "不能爬楼", "怕摔", "走平路", "路要平")):
        c = "避开台阶（零台阶步道）"
        if isinstance(anchor.health_constraints, list) and c not in anchor.health_constraints:
            anchor.health_constraints.append(c)
    if any(k in text for k in ("膝盖", "关节", "腿疼", "骨关节炎")):
        c = "膝关节退行性病变（坡度<3%）"
        if c not in anchor.health_constraints:
            anchor.health_constraints.append(c)
    if any(k in text for k in ("树荫", "遮阳", "防晒", "阴凉")):
        c = "优先林荫遮阳步道"
        if c not in anchor.health_constraints:
            anchor.health_constraints.append(c)
    if any(k in text for k in ("长椅", "休息", "歇歇", "坐坐")):
        c = "沿途长椅密集补给"
        if c not in anchor.health_constraints:
            anchor.health_constraints.append(c)
    if any(k in text for k in ("平缓", "平坦", "没有坡")):
        c = "平缓微地形"
        if c not in anchor.health_constraints:
            anchor.health_constraints.append(c)

    # -------------------------------------------------------------
    # 确认步骤节点推进
    # -------------------------------------------------------------
    if "现在就走" in text or "出发" in text:
        s = "确认出发动作：现在就走"
        if s not in anchor.confirmed_steps:
            anchor.confirmed_steps.append(s)
    if "导航路线" in text or "路线怎么不给我" in text or "路线" in text:
        s = "索要导航路线：呼叫北斗路线规划"
        if s not in anchor.confirmed_steps:
            anchor.confirmed_steps.append(s)
    if "我要跟着导航走" in text or "跟着导航走" in text:
        s = "确认实景导航：呼叫大地图实景导航"
        if s not in anchor.confirmed_steps:
            anchor.confirmed_steps.append(s)

    return anchor


__all__ = [
    "ActivityType",
    "TopicAnchor",
    "detect_activity_from_text",
    "extract_destination",
    "update_topic_anchor",
    "EXPLICIT_MEDICAL_KEYWORDS",
    "GENERIC_MOVEMENT_WORDS",
    "LEISURE_WALK_KEYWORDS",
    "DAILY_COMPANION_KEYWORDS",
    "KNOWN_DESTINATIONS",
]
