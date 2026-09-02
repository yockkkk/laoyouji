"""MockASR —— 无讯飞 Key 时的兜底（按文件名/预置语料返回演示文本）。"""
from __future__ import annotations

# 演示彩排预置语料：文件名包含关键字时返回对应文本
_PRESET = {
    "beijing": "我想去北京看腿疼的老毛病",
    "ticket": "帮我买明天去北京的高铁票",
    "canteen": "帮我订一份中午的软食套餐",
    "scam": "有人给我发短信说医保卡停了让我点链接",
    "chat": "今天天气怎么样",
}


class MockASRProvider:
    name = "mock_asr"

    async def transcribe(self, audio: bytes, fmt: str = "wav",
                         dialect: str = "mandarin") -> dict:
        hint = ""
        for key, text in _PRESET.items():
            if key in str(getattr(audio, "filename", "")):
                hint = text
                break
        return {
            "ok": True,
            "text": hint or "（模拟识别）我想去北京看腿疼的老毛病",
            "dialect": dialect,
            "provider": self.name,
        }
