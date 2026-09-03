"""腾讯云语音识别 Provider —— 一句话识别（官方 SDK，非讯飞）。

凭据模型与讯飞完全不同：腾讯云是 CAM 的 SecretId/SecretKey 两件套（新建密钥时
SecretKey 只完整显示一次，之后列表一律打码），TC3 签名由官方
``tencentcloud-sdk-python`` 在内部完成，不需要自己拼鉴权头。

为什么选「一句话识别」而不是流式/录音文件：
  - 一句话识别 = 同步 HTTP、整段音频一次性上传（≤60s、≤3MB），
    与本项目「录完整段 → /api/asr/upload → transcribe(audio)」的接缝形状完全吻合；
  - 录音文件识别要求音频放公网 URL（它主动去拉），后端还得托管文件，多一层；
  - 实时流式识别是 WebSocket 长连，前端已是「录完再发」，用不上。

方言：腾讯一句话识别没有「逐方言引擎 id」，多方言共用一个 ``16k_zh_dialect``
引擎（内置沪/川/汉/贵/昆…共 23 种，西南官话走四川/贵阳/昆明话），粤语单独
``16k_yue``。真实方言效果需要拿真 Key 对着腾讯文档核一遍（docs/TODO.md A2）。

格式：前端 App/小程序 ``getRecorderManager`` 录 mp3（腾讯支持）；H5 不走
MediaRecorder 的 webm/opus（不在腾讯/讯飞容器白名单里），而是 AudioContext 采
PCM 封装成 16k wav 再上传（见前端 asr.js）—— 与白名单吻合。若仍有人直接拿
webm 上传，这里对不认识的容器报错，不假装能认。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import uuid

from app.providers.asr.base import ASRProvider

logger = logging.getLogger(__name__)

# dialect → 腾讯 EngSerViceType（引擎 + 采样率一体，一句话识别取值）
DIALECT_ENGINES = {
    "mandarin": "16k_zh",
    "southwestern": "16k_zh_dialect",  # 多方言引擎：川/贵/昆…23 种，含西南官话分支
    "cantonese": "16k_yue",
    "shanghainese": "16k_zh_dialect",
}

# 腾讯一句话识别支持的音频容器（VoiceFormat）
_SUPPORTED_FORMATS = {"wav", "mp3", "aac", "flac", "amr", "m4a", "ogg", "mp4"}


class TencentASRProvider(ASRProvider):
    name = "tencent_asr"

    def __init__(self, secret_id: str, secret_key: str, region: str = "ap-guangzhou"):
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._region = region

    def _client(self):
        # 延迟导入：ASR_PROVIDER 不选 tencent 时不需要装/加载这个重量级 SDK
        from tencentcloud.asr.v20190614 import asr_client
        from tencentcloud.common import credential

        cred = credential.Credential(self._secret_id, self._secret_key)
        return asr_client.AsrClient(cred, self._region)

    async def transcribe(self, audio: bytes, fmt: str = "wav",
                         dialect: str = "mandarin") -> dict:
        if not audio:
            return {"ok": False, "error": "音频为空",
                    "dialect": dialect, "provider": self.name}

        engine = DIALECT_ENGINES.get(dialect, DIALECT_ENGINES["mandarin"])
        voice_format = fmt if fmt in _SUPPORTED_FORMATS else ""
        if not voice_format:
            return {
                "ok": False,
                "error": (
                    f"腾讯一句话识别不支持 {fmt or '未知'} 容器"
                    f"（支持：{', '.join(sorted(_SUPPORTED_FORMATS))}）"
                ),
                "dialect": dialect,
                "provider": self.name,
            }

        audio_b64 = base64.b64encode(audio).decode("utf-8")

        def _call() -> str:
            # 放到线程里：SDK 是同步 HTTP，别堵事件循环（同 SupabaseRepo 的 to_thread 习惯）
            from tencentcloud.asr.v20190614 import models

            req = models.SentenceRecognitionRequest()
            req.ProjectId = 0
            req.SubServiceType = 2        # 2 = 一句话识别
            req.EngSerViceType = engine
            req.SourceType = 1            # 1 = 本地音频上传（走 Data 字段）
            req.VoiceFormat = voice_format
            req.UsrAudioKey = uuid.uuid4().hex  # 用户标识，唯一即可
            req.Data = audio_b64
            req.DataLen = len(audio)      # 原始字节数，不是 base64 长度
            resp = self._client().SentenceRecognition(req)
            return (resp.Result or "").strip()

        try:
            text = await asyncio.to_thread(_call)
        except Exception as exc:  # TencentCloudSDKException 与网络错误统一转为失败返回
            logger.warning("腾讯一句话识别失败: %s", exc)
            return {"ok": False, "error": f"腾讯云识别失败: {exc}",
                    "dialect": dialect, "provider": self.name}

        return {"ok": True, "text": text,
                "dialect": dialect, "provider": self.name}
