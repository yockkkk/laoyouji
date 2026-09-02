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
            return self._travel(transcript)
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
        """旗舰场景：两波并行派发 → 确定性交付物。"""
        waves = self._ran(transcript, "delegate")

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

    def _travel(self, transcript: str) -> LLMResponse:
        """两条支线：车票（查→订）和酒店（查→订→天气）。按指令里的关键词分。"""
        if "酒店" in transcript:
            if not self._ran(transcript, "search_hotel"):
                return LLMResponse(
                    content="我先看看医院附近有哪些方便老人住的酒店。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="search_hotel",
                                            arguments={"city": "北京",
                                                       "near_hospital": _HOSPITAL})],
                )
            if not self._ran(transcript, "book_hotel"):
                hotel, price = _hotel_choice_from(transcript)
                # 房价照抄查询结果 —— 少了它，家人手机上那张卡的金额就是 0
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
                    content="我再看看北京这几天的天气。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="get_weather",
                                            arguments={"city": "北京",
                                                       "date": "tomorrow"})],
                )
            return LLMResponse(content="酒店和天气都看好啦，我记在计划里了。")

        if not self._ran(transcript, "search_train"):
            return LLMResponse(
                content="我先查一下明天去北京的车次。",
                tool_calls=[ToolCallReq(id=self._cid(), name="search_train",
                                        arguments={"from_city": "南京",
                                                   "to_city": "北京",
                                                   "date": "tomorrow"})],
            )
        if not self._ran(transcript, "book_ticket"):
            # 参数照抄查询结果：这份参数会被冻结给家人确认，也会印上计划书第二页
            return LLMResponse(
                content=f"查到了。我帮您订早上八点的 {_TRAIN}，二等座。",
                tool_calls=[ToolCallReq(id=self._cid(), name="book_ticket",
                                        arguments={
                                            "train_no": _TRAIN, "date": "tomorrow",
                                            "from_station": "南京南",
                                            "to_station": "北京南",
                                            "depart": "08:00", "arrive": "12:18",
                                            "seat_type": "二等座",
                                            "price": 553.5})],
            )
        if '"suspended": true' in transcript:
            return LLMResponse(content="票已经发给家人确认了。他点一下同意，马上就出票。")
        return LLMResponse(content="车票的事办好啦。")

    # ---------------------------------------------------------------- 安康助手

    def _health(self, instruction: str, transcript: str) -> LLMResponse:
        """两条支线：挂号（查医院 → 挂号）和反诈（念一遍 → 判定）。

        反诈这一支原来不存在，于是 ``check_scam`` 这个工具在离线剧本里**根本
        到不了** —— 而断网兜底和 ``scripts/demo_smoke.py`` 走的都是离线剧本。
        加分项不能只在联网时成立。

        分支看的是 ``instruction``（派过来的那句原话）而不是整段 transcript：
        判定结果本身含"骗"字，拿 transcript 分支会在第二步自己认错支线。
        """
        if _wants_scam_check(instruction):
            if not self._ran(transcript, "check_scam"):
                return LLMResponse(
                    content="您别急，我先看看这条是什么来路。",
                    tool_calls=[ToolCallReq(id=self._cid(), name="check_scam",
                                            arguments={"content": instruction})],
                )
            return LLMResponse(content="这种事您别自己做决定。我已经记在您的档案里了，"
                                       "也跟家里说一声。")

        if not self._ran(transcript, "search_hospital"):
            return LLMResponse(
                content="腿疼要看骨科。我帮您找北京看骨科最好的医院。",
                tool_calls=[ToolCallReq(id=self._cid(), name="search_hospital",
                                        arguments={"city": "北京",
                                                   "symptom": "腿疼"})],
            )
        if not self._ran(transcript, "register_appointment"):
            return LLMResponse(
                content="给您挂积水潭医院骨科的专家号。",
                tool_calls=[ToolCallReq(id=self._cid(),
                                        name="register_appointment",
                                        arguments={"hospital": _HOSPITAL,
                                                   "department": "骨科",
                                                   "doctor": "田伟",
                                                   "date": "+3",
                                                   "time": "上午",
                                                   "fee": 100})],
            )
        if '"suspended": true' in transcript:
            return LLMResponse(content="挂号的事已经发给家人确认了。他同意了号就锁上。")
        return LLMResponse(content="挂号的事我给您办好啦。")

    # ---------------------------------------------------------------- 邻里帮

    def _community(self, transcript: str) -> LLMResponse:
        if not self._ran(transcript, "canteen_order"):
            return LLMResponse(
                content="好的，帮您订今天的软食套餐。",
                tool_calls=[ToolCallReq(id=self._cid(), name="canteen_order",
                                        arguments={"menu_item": "软食套餐A",
                                                   "count": 1,
                                                   "deliver_time": "11:30"})],
            )
        return LLMResponse(content="饭订好啦。11点半送到家，您记得开门。")


# ---------------------------------------------------------------------- 意图词

def _wants_medical_trip(text: str) -> bool:
    return any(k in text for k in ("北京", "上海", "医院", "看病", "就医", "腿", "挂号"))


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
