"""应用装配根（composition root）：按 .env 选择 Provider 实现，组装 AppContext。

"一切皆插件"的落点：换真实 12306 / DeepSeek / 腾讯·讯飞 ASR / Supabase
= 只改这里（或 .env）的一行注册，agents / tools / safety 零改动。

这里也是**唯一**装配内核的地方：事件总线上挂哪些监听者、工具派发器长什么样、
子智能体接缝由谁提供，全在 ``build_context`` 里一次决定。没有第二处偷偷 new
—— 旧版 ``ctx.dispatcher`` 是个 ``@property``，每次访问都新建一个，中间件和
计数器刚挂上就随对象一起没了（缺陷 #9）。
"""
from __future__ import annotations

import logging

from app.agents.bds_nav_agent import BdsNavAgent, register_bds_tools
from app.agents.community_agent import CommunityAgent
from app.agents.health_agent import HealthAgent
from app.agents.main_agent import MainAgent, register_main_agent_tools
from app.agents.travel_agent import TravelAgent
from app.agents.weather_agent import WeatherAgent, register_weather_escort_tools
from app.config import Settings, settings
from app.core.broadcast import SessionBroadcast
from app.core.bus import EventBus, SESSION_FLUSH
from app.core.compaction import install_compaction
from app.core.context import AppContext
from app.core.events import SessionEventLog
from app.core.guard import Guard  # noqa: F401（类型引用）
from app.core.guards import install_loop_guards
from app.core.registry import ServiceDefinition, ServiceProvider, ServiceRegistry
from app.core.subagents import SubagentRegistry
from app.core.tool import ToolDispatcher, ToolRegistry
from app.core.turn_gate import SessionTurnGate
from app.db.client import build_repo
from app.providers.external.community import MockCommunityProvider
from app.providers.external.services import (
    AmapMapProvider,
    MockMapProvider,
    MockPaymentProvider,
    MockRideProvider,
    MockWeatherProvider,
)
from app.providers.external.hospital import MockHospitalProvider
from app.providers.external.mailer import Mailer, build_mailer
from app.providers.llm.base import LLMProvider
from app.providers.asr.base import ASRProvider
from app.providers.llm.deepseek import DeepSeekProvider
from app.providers.llm.mock import MockLLMProvider
from app.safety.confirmation import ConfirmationService
from app.safety.privacy import PrivacyService
from app.safety.risk_rules import (
    HealthDisclaimerGuard,
    PaymentRiskRule,
    ScamContentRule,
    install_medical_safety,
)
from app.shared.plain_language import PlainLanguageEngine
from app.tools.community_tools import register_community_tools
from app.tools.common_tools import register_common_tools
from app.tools.health_tools import register_health_tools
from app.tools.travel_tools import register_travel_tools

logger = logging.getLogger(__name__)


def build_context(cfg: Settings | None = None) -> AppContext:
    cfg = cfg or settings
    repo = build_repo(cfg)
    registry = ServiceRegistry()
    bus = EventBus()

    tools = ToolRegistry()
    register_common_tools(tools)
    register_travel_tools(tools)
    register_health_tools(tools)
    register_community_tools(tools)
    register_bds_tools(tools)
    register_weather_escort_tools(tools)
    register_main_agent_tools(tools)

    # ---- Provider 声明（能力契约）----
    for name, proto in [
        ("llm", LLMProvider), ("asr", ASRProvider),
        ("hospital", object),
        ("weather", object), ("map", object), ("ride", object),
        ("community", object), ("payment", object), ("plain_language", object),
        ("mail", Mailer),
    ]:
        registry.define(ServiceDefinition(name, proto))

    ctx = AppContext(
        settings=cfg,
        registry=registry,
        repos=repo,
        event_log=SessionEventLog(repo),
        tools=tools,
        bus=bus,
        broadcast=SessionBroadcast(),
        turn_gate=SessionTurnGate(
            # 比预算墙钟略宽：前一轮最迟也会在墙钟到点时收尾，
            # 等到那时候还等不到，说明真出了别的问题，不该继续等
            max_wait_s=float(getattr(cfg, "budget_wall_clock_s", 90.0)) + 15.0),
    )
    registry.ctx = ctx

    # ---- Provider 装配（按 .env 选择实现）----

    # 大模型
    if cfg.llm_provider == "deepseek" and cfg.deepseek_api_key:
        registry.register(ServiceProvider(
            "llm", lambda _ctx: DeepSeekProvider(
                cfg.deepseek_api_key, cfg.deepseek_base_url, cfg.deepseek_model)))
        llm: LLMProvider = registry.resolve("llm")
    else:
        registry.register(ServiceProvider("llm", lambda _ctx: MockLLMProvider()))
        llm = registry.resolve("llm")

    # 方言 ASR（腾讯一句话识别优先；讯飞次之；key 缺一即退化 mock，与 LLM 同哲学）
    if cfg.asr_provider == "tencent" and cfg.tencent_secret_id and cfg.tencent_secret_key:
        from app.providers.asr.tencent import TencentASRProvider

        registry.register(ServiceProvider("asr", lambda _ctx: TencentASRProvider(
            cfg.tencent_secret_id, cfg.tencent_secret_key, cfg.tencent_region)))
    elif cfg.asr_provider == "iflytek" and cfg.iflytek_app_id:
        from app.providers.asr.iflytek import IflytekASRProvider

        registry.register(ServiceProvider("asr", lambda _ctx: IflytekASRProvider(
            cfg.iflytek_app_id, cfg.iflytek_api_key, cfg.iflytek_api_secret)))
    else:
        from app.providers.asr.mock import MockASRProvider

        registry.register(ServiceProvider("asr", lambda _ctx: MockASRProvider()))

    # 外部业务服务：竞赛原型全部 Mock（正式落地换 Real*Provider 注册行）
    registry.register(ServiceProvider("hospital", lambda _ctx: MockHospitalProvider()))
    registry.register(ServiceProvider("weather", lambda _ctx: MockWeatherProvider()))
    registry.register(ServiceProvider("map", lambda _ctx: AmapMapProvider()))
    registry.register(ServiceProvider("ride", lambda _ctx: MockRideProvider()))
    registry.register(ServiceProvider("community", lambda _ctx: MockCommunityProvider()))
    registry.register(ServiceProvider("payment", lambda _ctx: MockPaymentProvider()))

    # 邮件送达：子女知会的跨设备兜底。**唯一**与 app 开关无关、又不要企业资质的
    # 通道（App 是 WebView 壳，关掉就没有推送；厂商离线推送要资质）。缺 SMTP 配置
    # 时 build_mailer 自动退回 mock，不抛异常 —— 评委的笔记本要能原样跑起来。
    registry.register(ServiceProvider("mail", lambda _ctx: build_mailer(cfg)))

    # 大白话引擎（公共组件：词典 + LLM 润色）
    registry.register(ServiceProvider(
        "plain_language", lambda _ctx: PlainLanguageEngine(llm)))

    # ---- 安全管控中间层 ----
    ctx.guards = [ScamContentRule(), PaymentRiskRule(cfg.risk_amount_threshold)]
    ctx.post_filters = [HealthDisclaimerGuard()]
    ctx.confirmation = ConfirmationService(repo, cfg.confirm_timeout_min)
    # 隐私分级：存了不用的开关比没有开关更糟，所以这里把它接进出库路径
    ctx.privacy = PrivacyService(repo)

    # ---- 内核装配（顺序有意义）----

    # 1. 工具派发器：**只建一次**，中间件和重复调用计数器才有地方附着
    ctx.dispatcher = ToolDispatcher(
        tools, ctx.guards, ctx.confirmation, ctx.post_filters,
        bus=bus, concurrency=cfg.tool_concurrency,
    )

    # 2. 子智能体接缝：``delegate`` 的扇出落点
    ctx.subagents = SubagentRegistry(ctx)

    # 3. 循环卫生（单工具超时 + 重复调用提醒）与上下文压缩，都是可卸载的监听者。
    #    disposer 挂在 ctx 上：测试可以整体摘掉，答辩可以现场演示"插件可逆"。
    ctx.disposers = [
        *install_loop_guards(bus, tool_timeout_s=cfg.tool_timeout_s),
        install_compaction(bus),
        # 红线 R1/R2：诊断口吻的输出在**离开模型的那一刻**就被改写，
        # 不指望提示词自觉（提示词只是第一道，不是最后一道）
        *install_medical_safety(bus),
    ]

    # 4. 持久化检查点：write-behind 的排水口。热路径只往内存 append，
    #    轮次结束在这里 await 落库 —— 这是"append 同步、I/O 不阻塞对话"的另一半。
    async def flush_session(payload: dict) -> None:
        session_id = (payload or {}).get("session_id") or None
        written = await ctx.event_log.flush(session_id)
        if written:
            logger.debug("session/flush 落库 %d 条事件（session=%s）",
                         written, session_id or "*")

    ctx.disposers.append(
        bus.on(SESSION_FLUSH, flush_session, label="event-log-flush"))

    # ---- 智能体家族 ----
    ctx.agents = {
        "main": MainAgent(),
        "travel": TravelAgent(),
        "health": HealthAgent(),
        "community": CommunityAgent(),
        "bds_nav": BdsNavAgent(),
        "weather": WeatherAgent(),
    }
    return ctx
