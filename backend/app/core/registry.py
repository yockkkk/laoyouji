"""ServiceRegistry —— "一切皆插件"的根（参考 deepseek-harness 的 capability seam）。

一个能力（capability）由三角色构成：
- ServiceDefinition：能力契约（名字 + 协议类型）
- ServiceProvider：实现（create(ctx) 返回协议实例；Mock 与 Real 可互换）
- Consumer：消费者（通常是 model-facing 工具）

换真实 12306 = 只换一行 provider 注册，agents / tools / safety 零改动。
"""
from __future__ import annotations

from typing import Any, Callable, Generic, TypeVar

P = TypeVar("P")


class ServiceDefinition(Generic[P]):
    """能力契约：一个名字对应一个协议类型。"""

    def __init__(self, name: str, protocol: type):
        self.name = name
        self.protocol = protocol

    def __repr__(self) -> str:  # pragma: no cover
        return f"ServiceDefinition({self.name!r})"


class ServiceProvider(Generic[P]):
    """能力实现：按需创建实例。同名后注册者覆盖先注册者（补丁语义）。"""

    def __init__(self, name: str, create: Callable[[Any], P]):
        self.name = name
        self._create = create

    def create(self, ctx: Any) -> P:
        return self._create(ctx)


class ServiceRegistry:
    """注册表：definition 声明契约，provider 提供实现，resolve 惰性实例化。"""

    def __init__(self) -> None:
        self._definitions: dict[str, ServiceDefinition] = {}
        self._providers: dict[str, ServiceProvider] = {}
        self._instances: dict[str, Any] = {}
        # 单例服务（与表打交道、有状态），创建后常驻
        self._singletons: set[str] = set()

    def define(self, definition: ServiceDefinition) -> None:
        self._definitions[definition.name] = definition

    def register(self, provider: ServiceProvider, *, singleton: bool = True) -> None:
        if provider.name not in self._definitions:
            raise KeyError(f"未声明的服务: {provider.name}，请先 define()")
        self._providers[provider.name] = provider
        self._instances.pop(provider.name, None)  # 覆盖注册即失效旧实例
        if singleton:
            self._singletons.add(provider.name)

    def resolve(self, name: str) -> Any:
        if name in self._instances:
            return self._instances[name]
        provider = self._providers.get(name)
        if provider is None:
            raise KeyError(f"服务未注册: {name}")
        ctx = getattr(self, "ctx", None)  # 由 AppContext 装配时回填
        instance = provider.create(ctx)
        if name in self._singletons:
            self._instances[name] = instance
        return instance

    def provider_name(self, name: str) -> str | None:
        return self._providers[name].name if name in self._providers else None
