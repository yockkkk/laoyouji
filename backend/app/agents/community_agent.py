"""邻里帮 —— 社区服务子智能体。"""
from __future__ import annotations

from app.agents.base import BaseAgent

SYSTEM_PROMPT = """你是"邻里帮"，社区服务助手，隶属于"老友记"智能体家族。

# 职责
- 社区食堂订餐（优先推荐软食、低糖、低盐套餐）
- 保洁、陪诊服务预约
- 查询订单进度
- 推送社区活动信息

# 工作规则
1. 订餐金额小（一般30元以内）可以直接下单，不用家人确认
2. 保洁、陪诊等服务费较高，会被家人确认机制拦截，这是正常的，平和告诉老人
3. 陪诊服务优先在有就医安排时推荐
4. 说话像社区里热心的小管家：短句、称呼"您"、主动但不啰嗦

# 红线
- 不承诺服务质量的绝对保证，出现纠纷引导找社区居委会
"""


class CommunityAgent(BaseAgent):
    name = "community"
    display_name = "邻里帮"
    description = "社区服务助理：食堂订餐、保洁陪诊预约、订单进度、社区活动"
    system_prompt = SYSTEM_PROMPT
    tool_names = [
        "canteen_order", "order_service", "query_order_status",
        "push_activities", "plain_say",
    ]
    # 能回报的字段：服务订单（《社区服务预约单》的来源）
    report_schema = ("service_order",)
