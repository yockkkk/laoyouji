"""腾讯云 ASR 连通性自检：真调一次一句话识别，凭据从 app.config / backend/.env 读取。

不含任何硬编码密钥（此前 xt 误把真 Key 写进本文件并提交，已脱敏）。
用法：cd backend && .venv/Scripts/python.exe scripts/test_tencent_asr.py
前提：backend/.env 里 ASR_PROVIDER=tencent 且 TENCENT_SECRET_ID / TENCENT_SECRET_KEY 已填。
"""
import asyncio
import io
import wave

from app.config import settings
from app.providers.asr.tencent import TencentASRProvider


async def test():
    if not (settings.tencent_secret_id and settings.tencent_secret_key):
        print("未配置 TENCENT_SECRET_ID / TENCENT_SECRET_KEY，跳过真调（demo 走 mock 不受影响）。")
        return
    provider = TencentASRProvider(
        secret_id=settings.tencent_secret_id,
        secret_key=settings.tencent_secret_key,
        region=settings.tencent_region or "ap-shanghai",
    )
    # 生成 1 秒空的标准 16k 16bit 单声道 wav 音频头（静音，能通即可，结果应无文字）
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000)
    audio_bytes = buf.getvalue()

    res = await provider.transcribe(audio_bytes, fmt="wav", dialect="mandarin")
    print("ASR 返回结果:", res)


if __name__ == "__main__":
    asyncio.run(test())
