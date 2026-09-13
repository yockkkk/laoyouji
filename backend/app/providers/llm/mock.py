"""MockLLM —— 离线开发/演示兜底（无需 API Key）。

两种用法：
1. **script 模式**：构造时注入按顺序消费的应答队列（测试/冒烟用，完全确定性）
2. **heuristic 模式**：默认，按"这一支已经跑过哪些工具"决定下一步，
   保证拔掉网线也能把旗舰场景演完（离线剧本）。

第 2 种的状态判断改成了**看工具结果里的 ``"tool": "<名字>"``**，不再猜中文措辞。
理由：``_finalize`` 给每个结果都盖了 ``tool`` 字段，这是流水线的硬事实；
而"查到""已挂号"这类中文摘要一改文案，旧启发式就悄悄失灵。

另外每支子智能体只看到**自己作用域**的历史（内核负责隔离），所以这里的
transcript 天然就是"我这一支干过什么"，不会被兄弟智能体的动静干扰。

康乐收敛后，离线剧本只剩一条主线：**本地就近就医**（挂号 ‖ 天气 → 路线 → 计划书）。
城际车票/异地酒店/付费社区服务/反诈问答整条砍掉，对应的旧剧本也一并删除。
"""
from __future__ import annotations

import re

from app.providers.external.base import load_fixture
from app.providers.llm.base import DeltaCallback, LLMProvider, LLMResponse, ToolCallReq

# 离线剧本里的固定角色（与 app/data 里的 Mock 数据对齐）：常住地南京，就近就医
_HOSPITAL = "南京鼓楼医院"
_CITY = "南京"

# 子助理一个字没说时，main_agent 拿这两个词凑出回报行（见 main_agent.py 的 digest）。
# 它们是**占位**不是内容：转述给老人就成了"已完成。"这样一句谁也不懂的话。
_EMPTY_REPORT_LINES = frozenset({"已完成", "未完成"})


class MockLLMProvider(LLMProvider):
    name = "mock"

    def __init__(self, script: list[LLMResponse] | None = None):
        self._script = list(script or [])
        self._cursor = 0
        self._call_seq = 0

    def feed(self, response: LLMResponse) -> None:
        """向 script 追加一条应答。"""
        self._script.append(response)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   on_delta: DeltaCallback | None = None) -> LLMResponse:
        if self._cursor < len(self._script):
            resp = self._script[self._cursor]
            self._cursor += 1
        else:
            resp = self._heuristic(messages, tools or [])
        if on_delta and resp.content:
            # 模拟流式：按 6 字一片下发
            text = resp.content
            for i in range(0, len(text), 6):
                await on_delta(text[i:i + 6])
        return resp

    # ---------------------------------------------------------------- heuristics

    def _heuristic(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        tool_names = {t["function"]["name"] for t in tools}
        # 只看对话消息的正文（system prompt 里也提工具名和关键词，会干扰判断）。
        # 工具结果是 JSON 串，里面的换行是转义过的 \n —— 先还原，
        # 好让下面按行取"上一波挂到的医院名"这类字段。
        transcript = "\n".join(
            str(m.get("content") or "")
            for m in messages if m.get("role") != "system").replace("\\n", "\n")
        user_text = self._last_user(messages)

        if "delegate" in tool_names:                 # 总智能体
            return self._main(user_text, transcript)
        if "plan_route" in tool_names:               # 银发导航（本地出行）
            return self._travel(user_text, transcript)
        if "register_appointment" in tool_names:     # 安康助手（挂号）
            return self._health(user_text, transcript)
        if "push_activities" in tool_names:          # 邻里帮（社交活动）
            return self._community(user_text, transcript)
        return LLMResponse(content="好的，我在呢。您慢慢说。")

    def _last_user(self, messages: list[dict]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content", "")
        return ""

    def _cid(self) -> str:
        """调用 id 全局唯一：同一个 id 在两步里出现会把 function-calling 配对搞乱。"""
        self._call_seq += 1
        return f"mock_{self._call_seq}"

    @staticmethod
    def _ran(transcript: str, tool: str) -> int:
        """这一支已经跑完过几次某工具（数结果里的 tool 字段，不猜措辞）。"""
        return transcript.count(f'"tool": "{tool}"')

    # ---------------------------------------------------------------- 总智能体

    def _main(self, text: str, transcript: str) -> LLMResponse:
        """本地就医旗舰调度：挂号 ‖ 天气 并行 → 路线（依赖挂到的医院）→ 计划书。"""
        waves = self._ran(transcript, "delegate")

        # 场景 A：本地就近就医闭环（号源 + 本地路线 + 天气 + 四页就医出行计划书）
        if _wants_medical_trip(text):
            city = _city_from_text(text)
            if waves == 0:
                # 第一波：挂号和查天气同时派（两支并发；天气不依赖挂号，先跑起来）
                return LLMResponse(
                    content="好嘞，看病要紧。我这就帮您挂号，再看看天。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "挂号：查本地医院、挂专家号",
                                 "status": "in_progress"},
                                {"content": f"查{city}这两天的天气",
                                 "status": "in_progress"},
                                {"content": "规划从家怎么去医院", "status": "pending"},
                                {"content": "出一份就医出行计划书", "status": "pending"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="delegate", arguments={
                            "tasks": [
                                {"agent": "health", "label": "挂号",
                                 "instruction": f"老人在{city}，{text}。请就近查本地大医院的"
                                                "号源并挂上专家号，医院、科室、医生、日期、"
                                                "时段、挂号费都照抄查询结果。"},
                                {"agent": "travel", "label": "天气",
                                 "instruction": f"老人明天要在{city}本地出门看病，"
                                                f"请查一下{city}这两天的天气，提醒穿衣。"},
                            ]}),
                    ],
                )
            if waves == 1:
                # 第二波：路线的目的地从第一波挂到的医院来（不是模型印象）
                hospital = _hospital_from(transcript)
                return LLMResponse(
                    content="号挂上了，天也看了。我再帮您想想从家怎么过去。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "挂号：查本地医院、挂专家号",
                                 "status": "completed"},
                                {"content": f"查{city}这两天的天气",
                                 "status": "completed"},
                                {"content": "规划从家怎么去医院",
                                 "status": "in_progress"},
                                {"content": "出一份就医出行计划书", "status": "pending"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="delegate", arguments={
                            "tasks": [
                                {"agent": "travel", "label": "怎么去医院",
                                 "instruction": f"老人要从家去{hospital}看病，腿脚不便。"
                                                f"请规划从家到{hospital}的本地出行路线"
                                                "（公交或地铁，腿脚不便优先直达公交，"
                                                "少换乘、好走），"
                                                "把怎么走一步步说清楚。"},
                            ]}),
                    ],
                )
            if not self._ran(transcript, "compose_deliverable"):
                return LLMResponse(
                    content="都齐了。我把挂号、怎么走、要带的东西和天气做成一份计划书。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "挂号：查本地医院、挂专家号",
                                 "status": "completed"},
                                {"content": f"查{city}这两天的天气",
                                 "status": "completed"},
                                {"content": "规划从家怎么去医院",
                                 "status": "completed"},
                                {"content": "出一份就医出行计划书",
                                 "status": "in_progress"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="compose_deliverable",
                                    arguments={"kind": "trip_plan", "city": city}),
                    ],
                )
            return LLMResponse(
                content="计划书您收好，一共四页：挂号、怎么去、要带啥、天气。"
                        "号已经挂好了，您的情况我也一并跟家里说了 —— "
                        "看病这事您自己拿主意就行，不用等谁点头。")

        # —— 散步/遛弯：**先于出行线判**。
        # "陪我散散步"这句话里同时有"散步"和（"我想出门散散步"里的）"出门"，
        # 出行线那条 if 在前，整个就会被它接走。可这句话里**没有目的地** ——
        # 出行线的 plan_route 要一个终点，它只能给出一条不知通向哪里的路线，
        # 老人最后听到的是那句"出行的事都办好啦，您放心"，而右翼那条环线卡
        # （多远、走多久、在哪儿歇、走回出发点，不必有终点）一次都没出过。
        # 所以：**只是想动动**的走右翼；**问怎么去哪儿**的（说了路线/怎么走/打车）
        # 还是出行线的事 —— 后者才需要终点，也才用得上 plan_route。
        if _wants_walk(text) and not any(k in text for k in _ROUTE_WORDS):
            if waves == 0:
                return LLMResponse(
                    content="好，让邻里帮给您找条走得动的道儿。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="delegate",
                                            arguments={"tasks": [
                                                {"agent": "community",
                                                 "instruction": text}]})],
                )
            return LLMResponse(content=_specialist_line(transcript, "邻里帮")
                               or "给您找了条道儿，您看看上面。")

        if _wants_travel(text):
            if waves == 0:
                return LLMResponse(
                    content="明白，这就让出行助理帮您安排。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="delegate",
                                            arguments={"tasks": [
                                                {"agent": "travel",
                                                 "instruction": text}]})],
                )
            return LLMResponse(content="出行的事都办好啦，您放心。")

        if _wants_community(text):
            if waves == 0:
                return LLMResponse(
                    content="好的，让邻里帮的小管家给您找找热闹。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="delegate",
                                            arguments={"tasks": [
                                                {"agent": "community",
                                                 "instruction": text}]})],
                )
            # 主智能体这句是老人**最后**听到的一句，不能一律说"活动都给您找出来啦" ——
            # 出过拨号卡、给过菜谱的那些轮次，这一句会把子助理刚放到老人手边的卡
            # 一句话盖过去：他明明要的是菜，最后听见的是社区汇演。
            #
            # 原先这里是四个 ``self._ran(transcript, "suggest_call")`` 之类的判断，
            # 想按"流水里出现过哪个工具"自己拼一句。它**一个都不成立**：``delegate``
            # 交给主智能体的只有一段摘要，子助理调的工具根本不在主智能体这一层的流水里
            # —— 于是不管老人要菜还是要人，四个分支全落进最后那句"都给您张罗好啦"。
            # 现在照抄子助理自己的收尾：它是唯一知道这轮真出了哪几张卡的一方。
            return LLMResponse(content=_specialist_line(transcript, "邻里帮")
                               or "都给您张罗好啦，您看看上面。")

        if _wants_health(text):
            if waves == 0:
                return LLMResponse(
                    content="好的，我让安康助手看看。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="delegate",
                                            arguments={"tasks": [
                                                {"agent": "health",
                                                 "instruction": text}]})],
                )
            # 收口要**照子助理分出来的档位**说话：老人听到的最后一句就是它。
            # 档位是从 delegate 回报里读出来的结构化字段，不是这里自己判的。
            level = _level_from(transcript)
            if level == "紧急":
                return LLMResponse(content="这个数比较急，您先给家里打个电话，"
                                           "或者拨 120，别自己一个人扛着。")
            if level == "建议就医":
                # 措辞对"报了个数"和"说了哪儿难受"两种情况都要成立。
                # 而且要**看子助理的回报**判断号到底挂上没有 —— 老人听到的最后一句
                # 不能还停在"我帮您约"上，那是一句没有下文的承诺。
                # 这里同样不能用 ``self._ran(transcript, "register_appointment")``：
                # 挂号是安康助手调的，主智能体这一层的流水里没有它，判断恒为假 ——
                # 结果就是号明明挂好了，老人最后听见的还是"我帮您约个号"。
                line = _specialist_line(transcript, "安康助手")
                if line:
                    return LLMResponse(content=line)
                # 安康助手没留下话（办砸了 / 没走到收尾）：**不能说"号已经挂好了"**，
                # 也不能退回那句"我帮您约"—— 两种都是把没发生的事说成发生了。
                return LLMResponse(content="这个情况得让医生看看。号还没挂上，"
                                           "我再给您想办法，您先别急。")
            if level == "观察":
                # 同"建议就医"：主智能体这一层不知道老人报的是数还是症状，
                # 措辞不能假设"有个数偏高"。
                return LLMResponse(content="先别急，这个先观察着。按时吃药、今天少盐少油、"
                                           "多歇歇，明后天再量一次；还不见好我再帮您约医生。")
            if level == "保健":
                return LLMResponse(content="记好了，这个数挺稳的。接着按时吃药、"
                                           "清淡饮食，不用特意跑医院。")
            return LLMResponse(content="健康的事我给您记下啦。")

        return LLMResponse(content="我在呢。您可以跟我说：想看病挂号、出门怎么走，"
                                   "或者想找人一起下棋遛弯，我都能帮您张罗。")

    # ---------------------------------------------------------------- 银发导航

    def _travel(self, instruction: str, transcript: str) -> LLMResponse:
        """银发导航（本地）：查天气 / 规划本地路线。城际车票、酒店已砍。"""
        city = _city_from_text(f"{instruction}\n{transcript}")
        wants_weather = any(k in instruction for k in ("天气", "穿衣", "冷", "热", "下雨", "带伞"))
        wants_route = any(k in instruction for k in ("路线", "怎么走", "怎么去", "带路",
                                                     "导航", "去医院", "到医院", "去看病"))

        # 只查天气那一支（第一波常和挂号并发）
        if wants_weather and not wants_route:
            if not self._ran(transcript, "get_weather"):
                return LLMResponse(
                    content=f"我先看看{city}这两天的天气。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="get_weather",
                                            arguments={"city": city,
                                                       "date": "tomorrow"})],
                )
            return LLMResponse(content="天气看好啦，我记在计划里了。")

        # 规划本地路线那一支（默认）：目的地是主智能体从上一波挂到的医院写进指令的
        if not self._ran(transcript, "plan_route"):
            destination = _hospital_in(instruction) or _HOSPITAL
            args: dict = {"origin": "家", "destination": destination}
            # 老人自己说了想怎么走，就照他说的查；没说不带 mode，由工具按默认
            # （公交，腿脚不便优先直达）出方案。**打车不在这里** —— 那是 hail_ride
            # 那条线，plan_route 的三种方式（公交/地铁/步行）里没有它。
            spoken = next((m for m in ("地铁", "步行", "走路", "公交")
                           if m in instruction), "")
            if spoken:
                args["mode"] = "步行" if spoken == "走路" else spoken
            return LLMResponse(
                content=f"我帮您想想从家怎么去{destination}。",
                tool_calls=[ToolCallReq(id=self._cid(), name="plan_route",
                                        arguments=args)],
            )
        if wants_weather and not self._ran(transcript, "get_weather"):
            return LLMResponse(
                content=f"我再看看{city}这两天的天气。",
                tool_calls=[ToolCallReq(id=self._cid(), name="get_weather",
                                        arguments={"city": city, "date": "tomorrow"})],
            )
        return LLMResponse(content="路线我给您规划好啦，怎么走都写下了。")

    # ---------------------------------------------------------------- 安康助手

    def _health(self, instruction: str, transcript: str) -> LLMResponse:
        """安康助手：报指标 → 记下来并分诊；说要挂号 → 查医院 → 挂号；
        只说哪儿难受 → **先分诊**再决定去不去。

        分岔的顺序是**明确要办的事优先**：老人（或总智能体转来的指令）已经说了
        "约个骨科号"，那就是下单，直接查号源；只有没说要挂号、光说哪儿不舒服时，
        才轮到分诊去决定要不要去。反过来先分诊的话，"帮我约个骨科号"会被
        当成一次症状主诉，旗舰那条线就断了。
        """
        vital = _vital_in(instruction)
        if vital:
            # ``_vital`` 返回 None = 报的数分诊到了"建议就医"，**接着往下走挂号那条线**
            # （与下面 ``_triage`` 同一个约定）。原先这里直接 return，等于老人报了个
            # 178/105、听见"我帮您就近约个号"就没了下文 —— 号没挂、子女也没收到知会，
            # 左翼那条链断在一句承诺上。
            measured = self._vital(vital, transcript)
            if measured is not None:
                return measured

        if not _wants_medical_trip(instruction):
            symptom = _symptom_in(instruction)
            if symptom:
                triage = self._triage(symptom, transcript)
                if triage is not None:
                    return triage
                # 落到这儿 = 档位到了"建议就医"，接着往下走挂号那条线

        dept, doctor, fee, slot_date, slot_time, city, symptom_phrase, hospital = \
            _health_pick(instruction)

        if not self._ran(transcript, "search_hospital"):
            return LLMResponse(
                content=f"{symptom_phrase}要看{dept}。我帮您找{city}看{dept}好的医院。",
                tool_calls=[ToolCallReq(id=self._cid(), name="search_hospital",
                                        arguments={"city": city,
                                                   "symptom": symptom_phrase})],
            )
        if not self._ran(transcript, "register_appointment"):
            return LLMResponse(
                content=f"给您挂{hospital}{dept}的专家号。",
                tool_calls=[ToolCallReq(id=self._cid(),
                                        name="register_appointment",
                                        arguments={"hospital": hospital,
                                                   "department": dept,
                                                   "doctor": doctor,
                                                   "date": slot_date,
                                                   "time": slot_time,
                                                   "fee": fee,
                                                   # 知会子女时"为什么去"全靠这一条。
                                                   # 不带它，家人收到的就只是"挂了骨科号"，
                                                   # 看不出这事该不该上心。
                                                   "reason": symptom_phrase})],
            )
        # 挂号已经没有"挂起等确认"那一档了（就医不需要子女审批）：走到这儿就是
        # **已经办好**，并且同一步里已经把完整情况知会了子女。原先那条
        # '"suspended": true' 分支永远走不到，留着会让人以为挂号还要等谁点头。
        return LLMResponse(content="号已经挂好啦，也把您的情况跟家里说了一声。")

    def _triage(self, symptom: str, transcript: str) -> LLMResponse | None:
        """说不舒服：**先分诊**，再由档位决定去不去医院。

        这一段就是"日常保健优先于就医"在离线剧本里的落点，也是原先漏掉的一环：
        旧剧本对任何症状都直接 search_hospital → register_appointment，等于老人说一句
        "有点头晕"就跳过全部分诊被送去挂号 —— 正是本项目定义的最严重错误；
        而"胸口闷"这种可能急症的情况，反而被当成普通门诊约了个号。

        返回 ``None`` 表示"分诊到了建议就医，该走挂号那条线了"，由调用方接着办。
        """
        if not self._ran(transcript, "assess_health"):
            return LLMResponse(
                content="我先看看您这个情况要不要紧。",
                tool_calls=[ToolCallReq(id=self._cid(), name="assess_health",
                                        arguments={"symptom": symptom})],
            )
        level = _level_from(transcript)
        if level == "紧急":
            return LLMResponse(content="这个情况比较急，您先给家里打个电话，"
                                       "或者拨 120，先别自己一个人扛着。")
        if level == "建议就医":
            return None
        # 保健 / 观察 / 读不出档位：都不张罗医院
        return LLMResponse(content="先别急，这个不用特意跑医院。按时吃药、"
                                   "多歇歇，哪儿不对劲您随时喊我。")

    def _vital(self, args: dict, transcript: str) -> LLMResponse | None:
        """记指标 → 分诊 → 照档位说话。档位取自**工具结果里的结构化字段**，不猜文案。

        返回 ``None`` 表示"分诊到了建议就医，该走挂号那条线了"，由 ``_health`` 接着办 ——
        与 ``_triage`` 同一个约定。这一条是补上的：老人**直接报数**走的是这条路，
        原先它在"建议就医"只回一句终局承诺就结束了，而"说哪儿难受"那条路（``_triage``）
        早就改成回落了。同一个档位，两条路必须落到同一件事上。
        """
        if not self._ran(transcript, "log_vital"):
            return LLMResponse(
                content="我给您记上。",
                tool_calls=[ToolCallReq(id=self._cid(), name="log_vital", arguments=args)],
            )
        if not self._ran(transcript, "assess_health"):
            return LLMResponse(
                content="我看看您这几天的情况。",
                tool_calls=[ToolCallReq(id=self._cid(), name="assess_health",
                                        arguments={})],
            )
        level = _level_from(transcript)
        if level == "紧急":
            return LLMResponse(content="这个数比较急，您先给家里打个电话，或者拨 120，"
                                       "别自己一个人扛着。")
        if level == "建议就医":
            # 不再在这儿说"我帮您约"然后停下 —— 见方法 docstring。
            return None
        if level == "观察":
            return LLMResponse(content="有点偏高，先别急。按时吃药、今天少盐少油，"
                                       "明后天再量一次，还高我再帮您约医生。")
        if level == "保健":
            return LLMResponse(content="记好了，这个数挺稳的。接着按时吃药、清淡饮食，"
                                       "每天散散步就行，不用特意跑医院。")
        # 认不出档位时**绝不给宽心话**：宁可说一句中性的，也不能把 178/105 说成
        # "挺稳的"。这里"往好里猜"是错误方向 —— 分诊读不出来就先不下结论。
        return LLMResponse(content="记下了。这个数要不要紧，得让医生看了才算数。")

    # ---------------------------------------------------------------- 邻里帮

    def _community(self, user_text: str, transcript: str) -> LLMResponse:
        """邻里帮（心理·社交线）：心里闷 → 一键拨号；想吃什么 → 菜谱；
        想热闹 → 线下活动；想动动 → 散步环线。

        **分支顺序就是优先级，最要紧的那张卡先落到老人手边**：老人说"心里闷得慌，
        一个人没意思"时，该先出现的是那个能打通子女电话的按钮，而不是一份社区活动
        清单 —— 孤独当下缺的是人，不是节目。两样都给，但电话排在活动前面。

        走到哪一步由 ``_ran``（数结果里的 tool 字段）决定，不猜措辞。
        """
        if _wants_call(user_text) and not self._ran(transcript, "suggest_call"):
            return LLMResponse(
                content="心里闷就说出来，我这就把电话按钮放您手边。",
                tool_calls=[ToolCallReq(id=self._cid(), name="suggest_call",
                                        arguments={"reason": user_text})],
            )
        if _wants_recipe(user_text) and not self._ran(transcript, "get_recipe"):
            return LLMResponse(
                content="我给您挑个软烂好嚼的家常菜。",
                tool_calls=[ToolCallReq(id=self._cid(), name="get_recipe",
                                        arguments={})],
            )
        # 兜底推活动 —— 但**老人这轮明确点了别的（菜谱/散步），就别把活动清单盖上去**。
        # 原先这条是无条件兜底：老人问"教我做菜"，菜谱办完紧接着又被推了一串活动，
        # 最后听到的一句成了"活动都给您找出来啦"，他问的那道菜反倒没了下文。
        # 问菜的人脑子里是今晚那顿饭，不是社区汇演。
        if not (_wants_recipe(user_text) or _wants_walk(user_text)) \
                and not self._ran(transcript, "push_activities"):
            return LLMResponse(
                content="我看看最近社区有啥活动，挑个热闹的您去。",
                tool_calls=[ToolCallReq(id=self._cid(), name="push_activities",
                                        arguments={})],
            )
        if _wants_walk(user_text) and not self._ran(transcript, "suggest_walk"):
            return LLMResponse(
                content="再给您找条能走动的道儿，慢慢溜达一圈。",
                tool_calls=[ToolCallReq(id=self._cid(), name="suggest_walk",
                                        arguments={})],
            )
        # 收尾**照这轮真的办成了什么**来说，不写死。老人最后听到的一句必须对得上
        # 他手边真有的卡：出了拨号卡就提电话、给了菜谱就提菜。原先一律说"活动都给您
        # 找出来啦"，于是问菜的人听到活动、孤独的人听到活动清单却没听见那张电话卡 ——
        # 而电话卡才是这一刻最该提的东西。只提真的出过的卡：指着不存在的东西让老人
        # 去点，他会真的去找，然后找不到。
        said: list[str] = []
        if self._ran(transcript, "suggest_call"):
            said.append("想孩子了，上面那张电话卡点一下就能打")
        if self._ran(transcript, "get_recipe"):
            said.append("菜谱给您放上面了，照着做就行")
        if self._ran(transcript, "suggest_walk"):
            said.append("散步那条道儿也在上面，慢慢溜达一圈")
        if self._ran(transcript, "push_activities"):
            said.append("社区活动都给您找出来啦，约上老伙计一块儿去")
        return LLMResponse(content="；".join(said) + "。" if said else "都给您张罗好啦。")


# ---------------------------------------------------------------------- 意图词

def _wants_medical_trip(text: str) -> bool:
    """就医出行：**明确要看病、要挂号**（本地就近，不再区分本地/跨城）。

    这里刻意不认症状本身：老人说"我有点头晕"是在**求助**，不是在下单挂号 ——
    先分诊，档位到了"建议就医"才轮到挂号这条线。把症状算成"要挂号"，
    等于跳过整个左翼的分诊，见个"膝盖疼"就撵老人上医院。

    但要认三种**把事说全了**的说法，它们都不是单纯的主诉：
    - 明说要办：看病、挂号、去医院、门诊……
    - 点名科室："帮我约个明天的骨科号"；
    - 看/瞧 直接接一个症状名："看腿疼的老毛病"（旗舰队就是这么说的）——
      这是"要医生看这个毛病"，和"腿疼"两个字的主诉不是一回事。
    """
    if any(k in text for k in ("看病", "就医", "挂号", "医院", "专家号", "门诊",
                               "看医生", "瞧病", "复诊")):
        return True
    if any(k in text for k in _DEPT_NAMES):
        return True
    return any(f"看{k}" in text or f"瞧{k}" in text for k in _SYMPTOM_KEYS)


_DEPT_NAMES: tuple[str, ...] = tuple(
    {dep["name"] for h in load_fixture("hospitals")["hospitals"]
     for dep in h["departments"]})

# 症状名（hospitals.json 那份映射的键）。比 _SYMPTOM_WORDS 精确：这里要的是
# "能被老人当作一个毛病说出来"的词，用来认"看腿疼"这种说法。
_SYMPTOM_KEYS: tuple[str, ...] = tuple(
    load_fixture("hospitals")["symptom_to_department"])


# 出行线要的是"去哪儿、怎么去"：这些词一出现，老人问的就是一条**有终点**的路线，
# 环线卡答不了。``_main`` 拿它把"想动动"和"问怎么走"分开，见 ``_wants_walk``。
_ROUTE_WORDS: tuple[str, ...] = ("路线", "怎么走", "怎么去", "导航", "带路",
                                 "打车", "叫车", "坐几路", "多远")


def _wants_travel(text: str) -> bool:
    """本地出行：出门、打车、路线、怎么走 —— 以及**问怎么去散步**的那种散步。

    光说"散步/遛弯"不算它：那句话没有目的地，归右翼的环线卡（见 ``_main``）。
    这里留着这两个词，是为了"去公园散步怎么走"这种**带了路线词**的说法仍归出行线
    —— ``plan_route`` 里"散步→步行"那条映射也就还有人走到。
    """
    return any(k in text for k in ("出门", "打车", "叫车", "路线", "怎么走",
                                   "怎么去", "散步", "遛弯"))


def _wants_community(text: str) -> bool:
    """心理·社交：找人一起、社区活动、排解孤独、张罗一顿饭。

    "闷"不单独收：老人说"胸口闷"是身体症状（归心内科那条线），只有"心里闷"
    才是没人说话的闷。一个字的宽松匹配会把胸闷送进活动推荐里 —— 那是把
    急症当孤独处理。

    收"吃什么/菜谱"这类**点菜式**的说法，是因为右翼的菜谱卡（get_recipe）挂在
    邻里帮这条线上；而"饮食上要注意什么"那种**问忌口**的说法留给健康线的
    diet_advice（在 ``_wants_health`` 的"饮食"里）。两个工具都在册，问的不是同一件事：
    一个要的是一道菜的做法，一个要的是一份忌口清单。
    """
    return any(k in text for k in ("社区", "活动", "下棋", "棋牌", "无聊",
                                   "心里闷", "解闷", "烦闷", "孤独",
                                   "老伙计", "散心", "一个人",
                                   "菜谱", "做菜", "做饭", "教我做",
                                   "吃啥", "吃什么", "吃点什么"))


def _wants_call(text: str) -> bool:
    """想找人说话、想孩子了 —— 该把**拨号卡**放到他手边，而不是先给他推活动。

    只给 ``_community`` 内部用，不进 ``_wants_community``：它决定的是"这一支里
    先办哪件事"，不是"这句话归哪一支"。
    """
    return any(k in text for k in ("想孩子", "想儿子", "想闺女", "想女儿",
                                   "给孩子", "打电话", "没人说话",
                                   "心里闷", "孤独", "一个人", "没意思"))


def _wants_recipe(text: str) -> bool:
    """点菜式地问吃什么 —— 要的是一道菜的做法，不是一份忌口清单。"""
    return any(k in text for k in ("菜谱", "做菜", "做饭", "教我做",
                                   "吃啥", "吃什么", "吃点什么", "怎么做"))


def _wants_walk(text: str) -> bool:
    """想出去走走 —— 给一条环线（多远、走多久、哪儿能歇）。

    **只给 ``_community`` 内部和 ``_main`` 最前面那道门用，绝不能加进
    ``_wants_community``**：``_main`` 里 walk 分支的判据是"有走动的意思、又没提
    路线"，一旦并进 ``_wants_community``，这个区分就没了 —— 老人问"去公园怎么走"
    会被推一串社区活动。

    它拦在 ``_wants_travel`` 前面，是因为这两句话长得像而问的不是一件事：
    "陪我散散步"要的是"想动动"，没有目的地；"怎么去公园"要的是路线，必须有终点。
    见 ``_ROUTE_WORDS``。
    """
    return any(k in text for k in ("散步", "遛弯", "走走", "环线", "公园走走"))


def _wants_health(text: str) -> bool:
    """健康日常：用药、报告、饮食、指标，以及**说不舒服**（先分诊再决定）。"""
    if _symptom_in(text) or _vital_in(text):
        return True
    return any(k in text for k in ("吃药", "用药", "报告", "体检", "饮食",
                                   "血压", "血糖", "复查"))


def _city_from_text(text: str) -> str:
    """从原话里认城市；认不出就退回常住地南京（就近就医的默认）。"""
    for c in ("北京", "上海", "南京"):
        if c in (text or ""):
            return c
    return _CITY


def _hospital_in(text: str) -> str:
    """从指令里认出提到的医院名（主智能体第二波把上一波挂到的医院写进了指令）。

    路线子智能体只看得到自己作用域的历史，看不到挂号那一波的结构化回报，
    所以医院名只能从主智能体交给它的指令原文里取 —— 主智能体填的正是
    ``_hospital_from`` 从挂号回报里读出来的那个名字，链路是闭合的。
    """
    for name in ("南京鼓楼医院", "北京积水潭医院", "北京协和医院",
                 "上海市第六人民医院", "复旦大学附属华山医院"):
        if name in (text or ""):
            return name
    return ""


def _health_pick(instruction: str):
    """按症状选定就诊科室/医院/医生/号源，**全部从 hospitals.json 取**。

    返回 (科室, 医生, 挂号费, 日期, 时段, 城市, 症状, 医院)。选法就是产品写死的
    "排在最前面的专科权威医院的首位专家的最早可用号源"：按文件顺序找该城市里
    有这个科室的第一家医院，取第一位医生的第一个号。

    以前这里是写死的两张小表（只认心内科和骨科），症状一旦落在别的科室，
    "消化内科"会配上骨科的医生和挂号费 —— 参数会一路冻结给家人确认、印到老人的
    计划书上。现在科室来自症状映射，医生/号源来自同一份数据，对不上账是不可能的。
    """
    city = _city_from_text(instruction)
    phrase, dept = _symptom_key(instruction)
    hospital, doctor, fee, slot_date, slot_time = _slot_for(city, dept)
    return dept, doctor, fee, slot_date, slot_time, city, phrase, hospital


def _slot_for(city: str, dept: str) -> tuple[str, str, float, str, str]:
    """该城市该科室的第一个号源：(医院, 医生, 挂号费, 日期, 时段)。"""
    data = load_fixture("hospitals")
    for h in data["hospitals"]:
        if h["city"] != city:
            continue
        for dep in h["departments"]:
            if dep["name"] != dept:
                continue
            doc = dep["doctors"][0]
            slot = doc["slots"][0]
            return (h["name"], doc["name"], doc["fee"],
                    slot["date"], slot["time"])
    # 该城市没有这个科室：退回默认的三甲，别让挂号停在这儿
    return (_HOSPITAL, "邱勇", 70, "+1", "上午 08:30")


def _hospital_from(transcript: str) -> str:
    """从第一波的回报摘要（``appointment: 医院 / 科室 / …``）里取医院名。

    离线剧本也走"标识符从上一波的结构化回报里来"这条路，
    而不是让模型凭印象写一个医院名 —— 真模型走的也是这条路。
    """
    return _digest_field(transcript, "appointment") or _HOSPITAL


# 指标 → (正则, 合理区间)。区间不是医学判断，是**防误读**：`12/09` 这种日期、
# 门牌号、电话号码都不该被当成一个读数。落不进区间的，就当老人没报数。
_VITAL_PATTERNS: tuple[tuple[str, str, tuple[float, float] | None], ...] = (
    ("bp", r"(\d{2,3})\s*/\s*(\d{2,3})", None),
    ("glucose", r"血糖\D{0,6}(\d+(?:\.\d+)?)", (1.0, 35.0)),
    ("heart_rate", r"心率\D{0,6}(\d{2,3})", (25.0, 250.0)),
    ("spo2", r"血氧\D{0,6}(\d{2,3})", (50.0, 100.0)),
    ("temperature", r"体温\D{0,6}(\d{2}(?:\.\d+)?)", (30.0, 45.0)),
)

# 血糖的"什么时候测的"。老人日常说法不止"餐后"一个词，都得认 ——
# 同一个数，空腹和餐后不是一个意思，丢了 context 分诊就会判错档。
_GLUCOSE_CONTEXTS: tuple[tuple[str, str], ...] = (
    ("空腹", "空腹"), ("餐前", "餐前"), ("饭前", "餐前"),
    ("餐后", "餐后"), ("饭后", "餐后"), ("吃完饭", "餐后"), ("吃过饭", "餐后"),
)


# "哪儿不舒服"的说法。老人说症状常常不带病名、也不提医院 —— "我有点头晕"
# 就是一次完整的求助，必须先分诊再决定要不要去医院。
#
# 这份名单**故意比科室映射宽**：识别症状和给症状配科室是两件事。
# "乏力""失眠"这种说不清哪儿的问题照样要过一遍分诊（很可能落"保健/观察"，
# 那正是我们想要的），但它们配不出一个说得过去的科室 —— 不该硬塞一个。
_SYMPTOM_WORDS: tuple[str, ...] = (
    "头晕", "眩晕", "晕", "头疼", "头痛", "疼", "痛", "麻", "肿", "酸",
    "胸口", "胸闷", "心慌", "心悸", "发慌", "慌", "心口", "喘", "气短", "咳嗽", "痰",
    "胃", "肚子", "腹痛", "反酸", "恶心", "呕吐", "拉肚子", "腹泻", "便秘",
    "眼睛", "看不清", "眼花", "视物", "视力",
    "关节", "风湿", "腿", "膝盖", "腰", "肩", "颈", "骨头", "脚", "手",
    "发烧", "发热", "乏力", "没劲", "失眠", "睡不着",
    "不舒服", "难受",
)


def _symptom_in(text: str) -> str:
    """老人这句话里有没有"哪儿不舒服"。返回要说给分诊听的原话，没有就空串。

    返回**原话**而不是解析出的病名：产品要求症状照老人原话转述，绝不替他
    改写成某个病名（那是诊断，红线 R1）。
    """
    text = text or ""
    return text if any(w in text for w in _SYMPTOM_WORDS) else ""


def _dept_for(text: str) -> str:
    """症状 → 科室。**以 hospitals.json 的 ``symptom_to_department`` 为准**。

    不在那份映射里的（乏力、失眠、说不清哪儿难受）落回骨科，和
    ``search_hospital`` 在没有科室时的默认一致 —— 不另立一份表，否则同一句话
    在真模型那条路上查的是心内科、在离线剧本里查的是骨科，演示和答辩对不上账。

    **已知边界**：配不出科室的症状（"我这两天有点乏力"）现在会挂到骨科去。
    要更准得往 hospitals.json 的映射里补条目（那是产品数据的事），或者在
    分诊驱动里按最重的那个指标定科室（血压→心内科）。这里不悄悄替它编一个。
    """
    return _symptom_key(text)[1]


def _symptom_key(text: str) -> tuple[str, str]:
    """老人原话里命中的那个症状词 → (症状词, 科室)。没命中就空串 + 默认骨科。

    返回**命中的那个词**而不是整句：这个词要作为 symptom 传给 search_hospital，
    而 search_hospital 会拿它去查同一份映射。传整句的话，指令里夹带的其它词
    （城市、"挂号"之类）也会参与匹配，科室就可能和这里算出来的不是同一个。
    """
    text = text or ""
    for key, dept in load_fixture("hospitals")["symptom_to_department"].items():
        if key in text:
            return key, dept
    return "", "骨科"


def _vital_in(text: str) -> dict:
    """老人这句话里报的是哪一项指标？解析成 log_vital 的参数；没报数就返回 {}。

    血压认 ``178/105`` 这种写法（老人和血压计都这么说）。每项都过一遍合理区间，
    落不进去就当没报 —— 否则主智能体指令里一个日期 ``12/09`` 就会被读成"血压 12/9"，
    然后一本正经地告诉老人"血压偏低"。
    """
    text = text or ""
    for metric, pattern, bounds in _VITAL_PATTERNS:
        m = re.search(pattern, text)
        if not m:
            continue
        if metric == "bp":
            systolic, diastolic = float(m.group(1)), float(m.group(2))
            if not (60 <= systolic <= 300 and 30 <= diastolic <= 200):
                continue                      # 像是日期/编号，不是血压
            return {"metric_type": "bp",
                    "systolic": systolic, "diastolic": diastolic}
        value = float(m.group(1))
        if bounds and not (bounds[0] <= value <= bounds[1]):
            continue
        args: dict = {"metric_type": metric, "value": value}
        if metric == "glucose":
            for word, ctx in _GLUCOSE_CONTEXTS:
                if word in text:
                    args["context"] = ctx
                    break
        return args
    return {}


def _specialist_line(transcript: str, who: str = "") -> str:
    """从 delegate 回报里取回**子助理自己**的收尾语。

    delegate 交给主智能体的只有摘要，形如::

        已协调子助理处理完毕：
        ✔ 邻里帮：<子助理最后说的那句>
           分诊: 建议就医；…

    子助理是唯一知道"这轮到底哪几张卡落到了老人手边"的一方：出了拨号卡它才提电话，
    给了菜谱它才提菜。主智能体原先不看这一句、自己另说一句，于是子助理说"电话卡在
    上面"、主智能体说"活动都给您找出来啦" —— 老人最后听见的是后一句，两句话对不上，
    那张卡也就白出了。这里把话语权还给知道实情的那一方。

    ``who`` 给角色名（"邻里帮"）时只认那一条回报：一轮里派了两个子助理时，
    最后那条 ✔ 未必是你要的那个。留空则取最后一条。

    **只认 ``✔``**：``✘``/``⏳`` 那两条线下面是错误信息或"等家人确认"，都不是子助理
    办成之后说的话，照搬会把失败当成功念给老人听。

    取不到返回空串，由调用方给一句中性的兜底（**不要**在这里编一句 —— 主智能体不知道
    实情，它编出来的每句"都办好了"都是在替子助理吹牛）。
    """
    idx = transcript.rfind(f"✔ {who}：") if who else transcript.rfind("✔")
    if idx < 0:
        return ""
    tail = transcript[idx + 1:]          # 跳过 ✔，留下 "<角色>：<原话>…"
    # 摘要后面还缀着 JSON 的其余字段（", "tool": "delegate"}）与分诊摘要行，
    # 在第一个引号或换行处截断。真换行与 JSON 里转义的 \n 两种都要认。
    cut = len(tail)
    for stop in ('"', "\n", "\\n"):
        pos = tail.find(stop)
        if pos >= 0:
            cut = min(cut, pos)
    tail = tail[:cut]
    # 去掉"邻里帮："这样的角色前缀，只留子助理的原话
    colon = tail.find("：")
    if colon >= 0:
        tail = tail[colon + 1:]
    line = tail.strip()
    # 子助理没留下话时，main_agent 用这两个占位词凑一行。那是**空**不是内容，
    # 照搬过去等于让老人听见一句"已完成"。
    return "" if line in _EMPTY_REPORT_LINES else line


def _level_from(transcript: str) -> str:
    """从工具结果里读分诊档位。两处来源都认，因为两支看到的东西不一样：

    - 子助理自己那一支：工具结果的 ``"level": "建议就医"``；
    - 主智能体那一支：回报摘要里的 ``分诊: 建议就医``（delegate 只把摘要给它）。

    按**最重**的先找 —— 几步结果都在时往急的方向读。宁可说重了让老人白跑一趟，
    不可说轻了把该看医生的数说成"挺稳的"。
    """
    for level in ("紧急", "建议就医", "观察", "保健"):
        if (f'"level": "{level}"' in transcript
                or f"分诊: {level}" in transcript):
            return level
    return ""

def _digest_field(transcript: str, key: str) -> str:
    for line in transcript.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}: "):
            first = stripped[len(key) + 2:].split(" / ")[0].strip()
            if first:
                return first
    return ""
