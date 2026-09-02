"""讯飞语音听写 Provider（WebSocket 流式识别，支持方言引擎）。

签名协议：HMAC-SHA256 鉴权 URL（讯飞开放平台 v2 接口）。
方言支持：讯飞语音听写（方言版）提供 23 种方言引擎，engine id 在讯飞控制台
文档中按语种列出（如西南官话/粤语/吴语等）；这里通过 DIALECT_ENGINES 映射，
正式接入时按控制台开通情况调整映射即可。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse
from wsgiref.handlers import format_date_time

from app.providers.asr.base import ASRProvider

logger = logging.getLogger(__name__)

_WS_URL = "wss://iat-api.xfyun.cn/v2/iat"

# 方言 → 讯飞引擎/参数映射（正式接入时按控制台开通语种校正）
DIALECT_ENGINES = {
    "mandarin": {"engine_type": "sms16k", "language": "zh_cn"},
    "southwestern": {"engine_type": "sms16k", "language": "zh_cn", "accent": "southwestern"},
    "cantonese": {"engine_type": "sms16k", "language": "zh_cn", "accent": "cantonese"},
    "shanghainese": {"engine_type": "sms16k", "language": "zh_cn", "accent": "shanghainese"},
}

FRAME_SIZE = 1280  # 每帧 40ms 的 16k 16bit 音频字节数


class IflytekASRProvider(ASRProvider):
    name = "iflytek"

    def __init__(self, app_id: str, api_key: str, api_secret: str):
        self._app_id = app_id
        self._api_key = api_key
        self._api_secret = api_secret

    def _auth_url(self) -> str:
        now = datetime.now(timezone.utc)
        date = format_date_time(now.timestamp())
        signature_origin = (
            f"host: {urlparse(_WS_URL).netloc}\n"
            f"date: {date}\nGET {urlparse(_WS_URL).path} HTTP/1.1"
        )
        signature_sha = hmac.new(
            self._api_secret.encode(), signature_origin.encode(), hashlib.sha256
        ).digest()
        signature = base64.b64encode(signature_sha).decode()
        params = {
            "authorization": (
                f'api_key="{self._api_key}", '
                f'algorithm="hmac-sha256", headers="host date request-line", '
                f'signature="{signature}"'
            ),
            "date": date,
            "host": urlparse(_WS_URL).netloc,
        }
        return f"{_WS_URL}?{urlencode(params)}"

    async def transcribe(self, audio: bytes, fmt: str = "wav",
                         dialect: str = "mandarin") -> dict:
        import asyncio

        import websockets

        engine = DIALECT_ENGINES.get(dialect, DIALECT_ENGINES["mandarin"])
        business = {
            "engine_type": engine["engine_type"],
            "language": engine.get("language", "zh_cn"),
        }
        if engine.get("accent"):
            business["accent"] = engine["accent"]

        text_parts: list[str] = []
        url = self._auth_url()
        audio_b64 = base64.b64encode(audio).decode()

        async with websockets.connect(url, max_size=2**22) as ws:
            # 首帧
            await ws.send(json.dumps({
                "common": {"app_id": self._app_id},
                "business": business,
                "data": {"status": 0, "format": fmt if fmt != "wav" else "pcm",
                         "encoding": "raw", "audio": ""},
            }))
            # 音频 base64 分片发送
            chunk_size = 2048
            chunks = [audio_b64[i:i + chunk_size]
                      for i in range(0, len(audio_b64), chunk_size)] or [""]
            for idx, chunk in enumerate(chunks):
                status = 2 if idx == len(chunks) - 1 else 1
                await ws.send(json.dumps({
                    "data": {"status": status, "format": "pcm",
                             "encoding": "raw", "audio": chunk},
                }))
                await asyncio.sleep(0.04)  # 模拟实时音频节奏
            # 接收结果
            async for message in ws:
                resp = json.loads(message)
                if resp.get("code") != 0:
                    return {"ok": False, "error": f"讯飞返回错误: {resp.get('message')}"}
                data = resp.get("data", {})
                if data.get("result"):
                    ws_result = data["result"].get("ws", [])
                    for w in ws_result:
                        for c in w.get("cw", []):
                            text_parts.append(c.get("w", ""))
                if data.get("status") == 2:
                    break

        return {
            "ok": True,
            "text": "".join(text_parts),
            "dialect": dialect,
            "provider": self.name,
        }
