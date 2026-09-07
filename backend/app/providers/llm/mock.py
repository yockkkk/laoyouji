"""MockLLM —— 离线开发/演示兜底（无需 API Key）。

两种用法：
1. **script 模式**：构造时注入按顺序消费的应答队列（测试/冒烟用，完全确定性）
2. **heuristic 模式**：默认，按"这一支已经跑过哪些工具"决定下一步，
   保证拔掉网线也能把旗舰场景演完（离线剧本）。

第 2 种的状态判断改成了**看工具结果里的 ``"tool": "<名字>"``**，不再猜中文措辞。
理由：``_finalize`` 给每个结果都盖了 ``tool`` 字段，这是流水线的硬事实；
而"查到""已订餐"这类中文摘要一改文案，旧启发式就悄悄失灵。

另外每支子智能体只看到**自己作用域**的历史（内核负责隔离），所以这里的
transcript 天然就是"我这一支干过什么"，不会被兄弟智能体的动静干扰。
"""
from __future__ import annotations

from app.providers.llm.base import DeltaCallback, LLMProvider, LLMResponse, ToolCallReq

# 离线剧本里的固定角色（与 app/data 里的 Mock 数据对齐）
_HOSPITAL = "北京积水潭医院"
_TRAIN = "G102"


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
        # 好让下面按行取"上一波查到的酒店名"这类字段。
        transcript = "\n".join(
            str(m.get("content") or "")
            for m in messages if m.get("role") != "system").replace("\\n", "\n")
        user_text = self._last_user(messages)

        if "delegate" in tool_names:                 # 总智能体
            return self._main(user_text, transcript)
        if "search_train" in tool_names:             # 银发导航
            return self._travel(user_text, transcript)
        if "register_appointment" in tool_names:     # 安康助手
            return self._health(user_text, transcript)
        if "canteen_order" in tool_names:            # 邻里帮
            return self._community(transcript)
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
        """旗舰场景与多类别场景调度：多波并行派发 → 确定性交付物。"""
        waves = self._ran(transcript, "delegate")

        # 场景 D：复合跨领域协同（本地就医挂号 + 医院陪诊服务）
        if _wants_complex_escort(text):
            if waves == 0:
                return LLMResponse(
                    content="好嘞，心脏不舒服马虎不得。我帮您预约南京鼓楼医院心内科专家号，并安排下午的陪诊护士全程陪您。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "预约南京鼓楼医院心内科专家号", "status": "in_progress"},
                                {"content": "预约下午医院陪诊服务", "status": "in_progress"},
                                {"content": "安排就医与陪诊衔接", "status": "pending"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="delegate", arguments={
                            "tasks": [
                                {"agent": "health", "label": "心内科挂号",
                                 "instruction": "老人心脏不舒服，想去南京鼓楼医院看心血管内科。请查号源并预约专家号。"},
                                {"agent": "community", "label": "医院陪诊",
                                 "instruction": "老人一个人去鼓楼医院看病腿脚不便，需要预约今天下午的医院陪诊服务。"},
                            ]}),
                    ],
                )
            return LLMResponse(
                content="鼓楼医院心内科专家号与下午的医院陪诊服务都帮您预约好啦！"
                        "挂号和陪诊订单已提交给家人确认，陪诊人员去医院前会提前电话联系您，您安心等候即可。")

        # 场景 C：邻里社区与家政服务（厨房打扫保洁 + 社区食堂清淡晚餐）
        if _wants_community_mix(text):
            if waves == 0:
                return LLMResponse(
                    content="好的，厨房油烟机脏了帮您找家政师傅打扫，今晚社区食堂的清淡晚餐也一并帮您订好送到家。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "预约厨房抽油烟机保洁上门", "status": "in_progress"},
                                {"content": "预订社区食堂少油清淡晚餐", "status": "in_progress"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="delegate", arguments={
                            "tasks": [
                                {"agent": "community", "label": "保洁与配餐",
                                 "instruction": "老人厨房油烟机脏了想找人打扫保洁，顺便订一份今晚社区食堂的少油清淡晚餐送到家。"},
                            ]}),
                    ],
                )
            if not self._ran(transcript, "compose_deliverable"):
                return LLMResponse(
                    content="保洁和晚餐都安排上了，我给您整理一份社区服务预约单。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "预约厨房抽油烟机保洁上门", "status": "completed"},
                                {"content": "预订社区食堂少油清淡晚餐", "status": "completed"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="compose_deliverable",
                                    arguments={"kind": "community_card"}),
                    ],
                )
            return LLMResponse(
                content="保洁师傅和今晚的清淡晚餐都帮您安排好啦！家政师傅已派单，傍晚热乎的晚餐也会准时送到家。")

        # 场景 B：跨城文旅出行闭环（南京到杭州看西湖，高铁+西湖附近酒店+天气+文旅出行计划书）
        if _wants_tourism(text):
            if waves == 0:
                return LLMResponse(
                    content="好嘞，去杭州看西湖风景散心真不错。我这就帮您查高铁票并物色西湖附近的无障碍酒店。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "查去杭州的高铁票", "status": "in_progress"},
                                {"content": "订西湖附近的无障碍酒店", "status": "pending"},
                                {"content": "查杭州天气并出文旅计划书", "status": "pending"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="delegate", arguments={
                            "tasks": [
                                {"agent": "travel", "label": "高铁车票",
                                 "instruction": "老人想从南京去杭州看西湖。请查南京去杭州的高铁并订上午二等座车票。"},
                            ]}),
                    ],
                )
            if waves == 1:
                return LLMResponse(
                    content="去杭州的高铁票已选好。我再给您订西湖附近的无障碍酒店并查查杭州天气。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "查去杭州的高铁票", "status": "completed"},
                                {"content": "订西湖附近的无障碍酒店", "status": "in_progress"},
                                {"content": "查杭州天气并出文旅计划书", "status": "pending"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="delegate", arguments={
                            "tasks": [
                                {"agent": "travel", "label": "西湖酒店与天气",
                                 "instruction": "请查杭州西湖附近有无障碍设施的酒店并订2晚，同时查一下杭州这几天的天气。"},
                            ]}),
                    ],
                )
            if not self._ran(transcript, "compose_deliverable"):
                return LLMResponse(
                    content="杭州的车票、酒店和天气都备齐了。我把整个文旅行程给您做成一份文旅出行计划书，一共五页。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "查去杭州的高铁票", "status": "completed"},
                                {"content": "订西湖附近的无障碍酒店", "status": "completed"},
                                {"content": "查杭州天气并出文旅计划书", "status": "in_progress"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="compose_deliverable",
                                    arguments={"kind": "trip_plan", "city": "杭州"}),
                    ],
                )
            return LLMResponse(
                content="杭州文旅出行计划书给您做好啦，一共五页。去程车票、西湖边的无障碍酒店和天气都给您列好啦，"
                        "等家人在手机上确认后就能安心出发！")

        # 场景 A：异地就医全流程闭环（去北京积水潭看骨科，号源+高铁+酒店+天气+就医出行计划书）
        if _wants_medical_trip(text):
            if waves == 0:
                # 第一波：挂号和车票同时派（两支并发，这才是"调度"）
                return LLMResponse(
                    content="好嘞，您想去北京看腿疼的老毛病。我这就安排上。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "选医院、挂骨科专家号",
                                 "status": "in_progress"},
                                {"content": "查去北京的高铁票",
                                 "status": "in_progress"},
                                {"content": "订医院附近的酒店", "status": "pending"},
                                {"content": "出一份出行计划书", "status": "pending"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="delegate", arguments={
                            "tasks": [
                                {"agent": "health", "label": "挂号",
                                 "instruction": "老人腿疼（骨关节炎老毛病），想去北京看。"
                                                "请查北京骨科的号源并挂上，"
                                                "医院、科室、医生、日期、时段、挂号费"
                                                "都照抄查询结果。"},
                                {"agent": "travel", "label": "车票",
                                 "instruction": "老人明天从南京去北京看病。"
                                                "请查明天的高铁并订上午的二等座，"
                                                "车次、时刻、票价照抄查询结果。"},
                            ]}),
                    ],
                )
            if waves == 1:
                # 第二波：医院名从第一波的回报摘要里来（不是模型印象）
                hospital = _hospital_from(transcript)
                return LLMResponse(
                    content="医院和车票都安排上了。我再给您订个离医院近的酒店。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "选医院、挂骨科专家号",
                                 "status": "completed"},
                                {"content": "查去北京的高铁票", "status": "completed"},
                                {"content": "订医院附近的酒店",
                                 "status": "in_progress"},
                                {"content": "出一份出行计划书", "status": "pending"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="delegate", arguments={
                            "tasks": [
                                {"agent": "travel", "label": "酒店和天气",
                                 "instruction": f"老人要去{hospital}看病，"
                                                f"请先查{hospital}附近有无障碍设施的酒店，"
                                                f"用查到的酒店订两晚，"
                                                f"再查一下北京这几天的天气。"},
                            ]}),
                    ],
                )
            if not self._ran(transcript, "compose_deliverable"):
                return LLMResponse(
                    content="都齐了。我把整个行程给您做成一份计划书，照着做就行。",
                    tool_calls=[
                        ToolCallReq(id=self._cid(), name="todo_write", arguments={
                            "todos": [
                                {"content": "选医院、挂骨科专家号",
                                 "status": "completed"},
                                {"content": "查去北京的高铁票", "status": "completed"},
                                {"content": "订医院附近的酒店", "status": "completed"},
                                {"content": "出一份出行计划书",
                                 "status": "in_progress"},
                            ]}),
                        ToolCallReq(id=self._cid(), name="compose_deliverable",
                                    arguments={"kind": "trip_plan", "city": "北京"}),
                    ],
                )
            return LLMResponse(
                content="计划书您收好，一共五页。等家人点完同意，号和票就都锁定了，"
                        "有消息我第一时间告诉您。")

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
                    content="好的，让邻里帮的小管家来帮您。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="delegate",
                                            arguments={"tasks": [
                                                {"agent": "community",
                                                 "instruction": text}]})],
                )
            return LLMResponse(content="社区的事办好啦。")

        if _wants_health(text):
            if waves == 0:
                return LLMResponse(
                    content="好的，我让安康助手看看。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="delegate",
                                            arguments={"tasks": [
                                                {"agent": "health",
                                                 "instruction": text}]})],
                )
            return LLMResponse(content="健康的事我给您记下啦。")

        return LLMResponse(content="我在呢。您可以跟我说：想看病挂号、买票出门，"
                                   "或者订食堂的饭、找保洁，我都办得了。")

    # ---------------------------------------------------------------- 银发导航

    def _travel(self, instruction: str, transcript: str) -> LLMResponse:
        """银发导航：支持车票、酒店、天气。根据上下文自动识别城市与地标。"""
        full_text = f"{instruction}\n{transcript}"
        is_hangzhou = "杭州" in full_text or "西湖" in full_text
        city = "杭州" if is_hangzhou else "北京"
        station_to = "杭州东" if is_hangzhou else "北京南"
        train_no = "G7615" if is_hangzhou else _TRAIN
        train_price = 117.5 if is_hangzhou else 443.5
        depart_time = "08:30" if is_hangzhou else "08:00"
        arrive_time = "09:58" if is_hangzhou else "12:18"
        hotel_landmark = "西湖" if is_hangzhou else _HOSPITAL

        wants_hotel = any(k in instruction for k in ("酒店", "住", "天气"))
        wants_ticket = any(k in instruction for k in ("车票", "买票", "高铁", "火车", "车次"))

        if wants_hotel and not wants_ticket:
            if not self._ran(transcript, "search_hotel"):
                return LLMResponse(
                    content=f"我先看看{city}{hotel_landmark}附近有哪些方便老人住的无障碍酒店。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="search_hotel",
                                            arguments={"city": city,
                                                       "near_hospital": hotel_landmark})],
                )
            if not self._ran(transcript, "book_hotel"):
                hotel, price = _hotel_choice_from(transcript)
                args: dict = {"hotel": hotel, "checkin": "tomorrow", "nights": 2}
                if price is not None:
                    args["price"] = price
                return LLMResponse(
                    content=f"就订{hotel}，走过去几分钟，有无障碍设施。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="book_hotel",
                                            arguments=args)],
                )
            if not self._ran(transcript, "get_weather"):
                return LLMResponse(
                    content=f"我再看看{city}这几天的天气。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="get_weather",
                                            arguments={"city": city,
                                                       "date": "tomorrow"})],
                )
            return LLMResponse(content="酒店和天气都看好啦，我记在计划里了。")

        if not self._ran(transcript, "search_train"):
            return LLMResponse(
                content=f"我先查一下明天去{city}的车次。",
                tool_calls=[ToolCallReq(id=self._cid(), name="search_train",
                                        arguments={"from_city": "南京",
                                                   "to_city": city,
                                                   "date": "tomorrow"})],
            )
        if not self._ran(transcript, "book_ticket"):
            return LLMResponse(
                content=f"查到了。我帮您订早上{depart_time}的 {train_no}，二等座。",
                tool_calls=[ToolCallReq(id=self._cid(), name="book_ticket",
                                        arguments={
                                            "train_no": train_no, "date": "tomorrow",
                                            "from_station": "南京南",
                                            "to_station": station_to,
                                            "depart": depart_time, "arrive": arrive_time,
                                            "seat_type": "二等座",
                                            "price": train_price})],
            )
        if wants_hotel:
            if not self._ran(transcript, "search_hotel"):
                return LLMResponse(
                    content=f"我先看看{city}{hotel_landmark}附近有哪些方便老人住的无障碍酒店。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="search_hotel",
                                            arguments={"city": city,
                                                       "near_hospital": hotel_landmark})],
                )
            if not self._ran(transcript, "book_hotel"):
                hotel, price = _hotel_choice_from(transcript)
                args: dict = {"hotel": hotel, "checkin": "tomorrow", "nights": 2}
                if price is not None:
                    args["price"] = price
                return LLMResponse(
                    content=f"就订{hotel}，走过去几分钟，有无障碍设施。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="book_hotel",
                                            arguments=args)],
                )
            if not self._ran(transcript, "get_weather"):
                return LLMResponse(
                    content=f"我再看看{city}这几天的天气。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="get_weather",
                                            arguments={"city": city,
                                                       "date": "tomorrow"})],
                )

        if '"suspended": true' in transcript:
            return LLMResponse(content="票已经发给家人确认了。他点一下同意，马上就出票。")
        return LLMResponse(content="车票的事办好啦。")

    # ---------------------------------------------------------------- 安康助手

    def _health(self, instruction: str, transcript: str) -> LLMResponse:
        """两条支线：挂号（查医院 → 挂号）和反诈（念一遍 → 判定）。"""
        if _wants_scam_check(instruction):
            if not self._ran(transcript, "check_scam"):
                return LLMResponse(
                    content="您别急，我先看看这条是什么来路。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="check_scam",
                                            arguments={"content": instruction})],
                )
            return LLMResponse(content="这种事您别自己做决定。我已经记在您的档案里了，"
                                       "也跟家里说一声。")

        is_nanjing = any(k in instruction for k in ("南京", "鼓楼", "心", "心脏", "心内科", "心血管"))
        hospital = "南京鼓楼医院" if is_nanjing else _HOSPITAL
        city = "南京" if is_nanjing else "北京"
        symptom = "心脏" if is_nanjing else "腿疼"
        dept = "心内科" if is_nanjing else "骨科"
        doctor = "王振华" if is_nanjing else "田伟"
        fee = 70 if is_nanjing else 100
        slot_date = "+1" if is_nanjing else "+3"
        slot_time = "上午 08:30" if is_nanjing else "上午"

        if not self._ran(transcript, "search_hospital"):
            hint = "心脏不舒服要看心内科。我帮您找南京看心内科最好的医院。" if is_nanjing else "腿疼要看骨科。我帮您找北京看骨科最好的医院。"
            return LLMResponse(
                content=hint,
                tool_calls=[ToolCallReq(id=self._cid(), name="search_hospital",
                                        arguments={"city": city,
                                                   "symptom": symptom})],
            )
        if not self._ran(transcript, "register_appointment"):
            hint = f"给您挂{hospital}{dept}的专家号。"
            return LLMResponse(
                content=hint,
                tool_calls=[ToolCallReq(id=self._cid(),
                                        name="register_appointment",
                                        arguments={"hospital": hospital,
                                                   "department": dept,
                                                   "doctor": doctor,
                                                   "date": slot_date,
                                                   "time": slot_time,
                                                   "fee": fee})],
            )
        if '"suspended": true' in transcript:
            return LLMResponse(content="挂号的事已经发给家人确认了。他同意了号就锁上。")
        return LLMResponse(content="挂号的事我给您办好啦。")

    # ---------------------------------------------------------------- 邻里帮

    def _community(self, transcript: str) -> LLMResponse:
        wants_cleaning = any(k in transcript for k in ("保洁", "打扫", "油烟机", "家政"))
        wants_accompany = any(k in transcript for k in ("陪诊", "陪护"))
        wants_canteen = any(k in transcript for k in ("食堂", "饭", "餐", "吃", "晚餐", "午餐"))

        if wants_cleaning and not self._ran(transcript, "order_service"):
            return LLMResponse(
                content="好的，我帮您预约家政保洁上门服务。",
                tool_calls=[ToolCallReq(id=self._cid(), name="order_service",
                                        arguments={"service_type": "cleaning",
                                                   "date": "今天下午",
                                                   "hours": 2})],
            )

        if wants_accompany and not self._ran(transcript, "order_service"):
            return LLMResponse(
                content="好的，我帮您预约医院陪诊服务。",
                tool_calls=[ToolCallReq(id=self._cid(), name="order_service",
                                        arguments={"service_type": "accompany",
                                                   "date": "今天下午",
                                                   "hours": 4})],
            )

        if (wants_canteen or not (wants_cleaning or wants_accompany)) and not self._ran(transcript, "canteen_order"):
            return LLMResponse(
                content="好的，帮您订今天的软食清淡套餐。",
                tool_calls=[ToolCallReq(id=self._cid(), name="canteen_order",
                                        arguments={"menu_item": "软食套餐A",
                                                   "count": 1,
                                                   "deliver_time": "18:00"})],
            )

        return LLMResponse(content="社区的事办好啦，您放心。")


# ---------------------------------------------------------------------- 意图词

def _wants_complex_escort(text: str) -> bool:
    """复合跨领域协同：本地就医挂号 + 医院陪诊服务"""
    has_escort = any(k in text for k in ("陪诊", "陪护"))
    has_med = any(k in text for k in ("医院", "挂号", "看病", "心血管", "鼓楼", "心内科", "心脏", "门诊"))
    return has_escort and has_med


def _wants_community_mix(text: str) -> bool:
    """社区家政与餐饮：打扫保洁 + 社区食堂"""
    has_clean = any(k in text for k in ("保洁", "打扫", "家政", "抽油烟机", "油烟机", "打扫厨房"))
    has_food = any(k in text for k in ("食堂", "晚餐", "午餐", "清淡", "软食", "送餐", "吃饭", "订餐", "订饭"))
    return has_clean and has_food


def _wants_tourism(text: str) -> bool:
    """跨城文旅出行：高铁 + 酒店 + 天气 + 文旅计划书（无医院/看病/挂号）"""
    if any(k in text for k in ("看病", "就医", "挂号", "医院", "医生", "专家号", "骨科")):
        return False
    has_travel_target = any(k in text for k in ("杭州", "西湖", "旅游", "文旅", "游玩"))
    has_trip_intent = any(k in text for k in ("高铁", "火车", "车票", "酒店", "计划书", "出行"))
    return has_travel_target and has_trip_intent


def _wants_medical_trip(text: str) -> bool:
    """异地跨城就医出行：去外地医院看病"""
    if _wants_complex_escort(text) or _wants_community_mix(text) or _wants_tourism(text):
        return False
    return any(k in text for k in ("北京", "上海", "积水潭", "骨科", "看病", "就医", "腿", "膝盖", "挂号", "医院"))


def _wants_travel(text: str) -> bool:
    return any(k in text for k in ("买票", "车票", "高铁", "火车", "出门", "打车", "叫车"))


def _wants_community(text: str) -> bool:
    return any(k in text for k in ("食堂", "保洁", "打扫", "陪诊", "社区", "活动",
                                   "订餐", "订饭", "套餐", "吃饭", "送餐"))


def _wants_health(text: str) -> bool:
    return any(k in text for k in ("吃药", "用药", "报告", "体检", "骗", "短信",
                                   "饮食", "中奖", "转账", "汇款", "交钱",
                                   "验证码", "链接"))


def _wants_scam_check(text: str) -> bool:
    """派过来的这句话是"帮我看看这东西是不是骗子"，而不是"帮我挂个号"。

    比 ``_wants_health`` 窄：后者决定"这事归安康助手管"，这个决定"归它的哪条
    支线"。念出来的原文一般带这些词，而挂号那句不会。
    """
    return any(k in text for k in ("骗", "短信", "中奖", "转账", "汇款", "交钱",
                                   "验证码", "链接", "神药", "根治"))


def _hospital_from(transcript: str) -> str:
    """从第一波的回报摘要（``appointment: 医院 / 科室 / …``）里取医院名。

    离线剧本也走"标识符从上一波的结构化回报里来"这条路，
    而不是让模型凭印象写一个医院名 —— 真模型走的也是这条路。
    """
    return _digest_field(transcript, "appointment") or _HOSPITAL


def _hotel_choice_from(transcript: str) -> tuple[str, float | None]:
    """从 ``search_hotel`` 的摘要里取第一家酒店的**名字和房价**（同一行，同一家）。

    摘要每行形如 ``如家精选（新街口地铁站店）：329元/晚，离…步行8分钟（600米）…``

    房价必须和名字一起取回来：``book_hotel`` 的这份参数会被冻结成家人手机上那张
    确认卡，也是守卫算金额的唯一依据。卡上没有金额，家人就是在给一件不知道多少钱
    的事按"同意"。价格只认这一行自己的 —— 拼上别家的房价比空着更糟。
    """
    for line in transcript.splitlines():
        if "步行" in line and "元/晚" in line and "：" in line:
            name, _, rest = line.partition("：")
            name = name.strip()
            if not name:
                continue
            try:
                price = float(rest.split("元/晚")[0].strip())
            except ValueError:
                price = None
            return name, price
    return "汉庭酒店（积水潭店）", None


def _digest_field(transcript: str, key: str) -> str:
    for line in transcript.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}: "):
            first = stripped[len(key) + 2:].split(" / ")[0].strip()
            if first:
                return first
    return ""
