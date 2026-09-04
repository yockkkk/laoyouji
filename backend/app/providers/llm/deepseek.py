"""DeepSeek chat provider：OpenAI 兼容接口，流式 + function calling，3 次退避重试。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.providers.llm.base import DeltaCallback, LLMProvider, LLMResponse, ToolCallReq

logger = logging.getLogger(__name__)

# 这些状态码重试多少次都是同一个结果：key 不对、余额没了、模型名写错、参数非法。
# 退避重试只会把"立刻能看懂的报错"拖成 5 秒后的同一个报错。
_FATAL_STATUS = {400, 401, 402, 403, 404, 422}


class LLMConfigError(RuntimeError):
    """凭据/配置层面的错误 —— 不重试，直接把 API 的原话报出来。"""


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-chat", timeout: float = 120.0):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   on_delta: DeltaCallback | None = None) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._base_url}/chat/completions"

        last_exc: Exception | None = None
        for attempt in range(3):  # ADR：流式不稳 → 3 次指数退避
            try:
                return await self._request_once(url, headers, payload, on_delta)
            except LLMConfigError:
                raise                       # 配置错，重试无意义
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = 0.8 * (2 ** attempt)
                logger.warning("DeepSeek 请求失败(第%d次): %s，%.1fs 后重试",
                               attempt + 1, exc, wait)
                await asyncio.sleep(wait)
        raise RuntimeError(f"DeepSeek 请求连续失败: {last_exc}")

    async def _request_once(self, url: str, headers: dict, payload: dict,
                            on_delta: DeltaCallback | None) -> LLMResponse:
        content_parts: list[str] = []
        # tool_calls 按 index 聚合：流式时 id/name/arguments 分片到达
        tc_acc: dict[int, dict] = {}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    # 流式响应的 body 是懒读的，不 aread 就只能拿到干巴巴的
                    # "Client error 401"，看不出是 key 错了还是余额没了。
                    detail = (await resp.aread()).decode("utf-8", "replace")[:500]
                    message = (f"DeepSeek 接口 {resp.status_code}"
                               f"（model={self._model}）：{detail}")
                    if resp.status_code in _FATAL_STATUS:
                        raise LLMConfigError(message)
                    raise RuntimeError(message)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise RuntimeError(f"DeepSeek 返回错误: {chunk['error']}")
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta") or {}
                        text = delta.get("content")
                        if text:
                            content_parts.append(text)
                            if on_delta:
                                await on_delta(text)
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            slot = tc_acc.setdefault(
                                idx, {"id": "", "name": "", "arguments": ""}
                            )
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]

        tool_calls: list[ToolCallReq] = []
        for idx in sorted(tc_acc):
            slot = tc_acc[idx]
            if not slot["name"]:
                continue
            try:
                args = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCallReq(id=slot["id"] or f"call_{idx}", name=slot["name"],
                            arguments=args)
            )
        return LLMResponse(content="".join(content_parts), tool_calls=tool_calls)
