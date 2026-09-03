"""测试腾讯云 ASR API 连通性与密钥有效性。"""
import asyncio
import io
import wave
from app.providers.asr.tencent import TencentASRProvider

async def test():
    provider = TencentASRProvider(
        secret_id="AKID7JPr8KyQq69xgGhw781t8QYeaIuHPIvJ",
        secret_key="BIG7uW5UiiT1LRIvJWXLxNYVDCyXs92Y",
        region="ap-shanghai"
    )
    # 生成 1 秒空的标准 16k 16bit 单声道 wav 音频头
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b'\x00\x00' * 16000)
    audio_bytes = buf.getvalue()

    res = await provider.transcribe(audio_bytes, fmt="wav", dialect="mandarin")
    print("ASR 返回结果:", res)

if __name__ == "__main__":
    asyncio.run(test())
