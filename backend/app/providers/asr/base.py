"""ASR Provider 协议 —— 方言语音识别接缝（iflytek | mock；前端另有 Web Speech 降级）。"""
from __future__ import annotations


class ASRProvider:
    name = "asr"

    async def transcribe(self, audio: bytes, fmt: str = "wav",
                         dialect: str = "mandarin") -> dict:
        """音频 → {text, dialect, provider}。"""
        raise NotImplementedError
