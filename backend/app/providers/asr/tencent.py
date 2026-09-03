"""腾讯云 ASR Provider 适配器（一句话识别 SentenceRecognition，支持多方言）。"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.asr.v20190614 import asr_client, models

from app.providers.asr.base import ASRProvider

logger = logging.getLogger(__name__)

# 腾讯云 EngSerViceType 方言/语言引擎映射
# 16k_zh: 中文普通话通用
# 16k_zh_dialect: 西南官话/四川话等方言
# 16k_ca: 粤语
# 16k_wuu: 吴语/上海话
DIALECT_ENGINE_MAP = {
    "mandarin": "16k_zh",
    "southwestern": "16k_zh_dialect",
    "cantonese": "16k_ca",
    "wu": "16k_wuu",
}


class TencentASRProvider(ASRProvider):
    name = "tencent_asr"

    def __init__(self, secret_id: str, secret_key: str, region: str = "ap-shanghai"):
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._region = region
        self._cred = credential.Credential(secret_id, secret_key)
        http_profile = HttpProfile()
        http_profile.endpoint = "asr.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        self._client = asr_client.AsrClient(self._cred, region, client_profile)

    async def transcribe(self, audio: bytes, fmt: str = "wav",
                         dialect: str = "mandarin") -> dict:
        """调用腾讯云 SentenceRecognition 接口识别语音。"""
        def _call_api() -> dict:
            try:
                engine = DIALECT_ENGINE_MAP.get(dialect, "16k_zh")
                voice_format = fmt.lower()
                if voice_format == "mp3":
                    voice_format = "mp3"
                elif voice_format in ("pcm", "raw"):
                    voice_format = "pcm"
                else:
                    voice_format = "wav"

                req = models.SentenceRecognitionRequest()
                params = {
                    "ProjectId": 0,
                    "SubServiceType": 2,
                    "EngSerViceType": engine,
                    "SourceType": 1,
                    "VoiceFormat": voice_format,
                    "Data": base64.b64encode(audio).decode("utf-8"),
                    "DataLen": len(audio),
                }
                req.from_json_string(json.dumps(params))
                resp = self._client.SentenceRecognition(req)
                return {"ok": True, "text": resp.Result or "", "dialect": dialect}
            except Exception as exc:  # noqa: BLE001
                logger.error("腾讯云 ASR 识别异常: %s", exc)
                return {"ok": False, "error": str(exc), "text": "", "dialect": dialect}

        return await asyncio.to_thread(_call_api)
