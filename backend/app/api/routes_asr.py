"""语音识别上传：POST /api/asr/upload（方言 ASR 接缝入口）。"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import get_ctx

router = APIRouter(prefix="/api/asr", tags=["asr"])


@router.post("/upload")
async def asr_upload(
    file: UploadFile = File(...),
    dialect: str = Form("mandarin"),
):
    ctx = get_ctx()
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "音频为空")
    provider = ctx.resolve("asr")
    fmt = (file.filename or "audio.wav").rsplit(".", 1)[-1].lower()

    result = await provider.transcribe(audio, fmt=fmt, dialect=dialect)

    # MockASR：按文件名关键字返回预置演示文本（彩排用）
    if getattr(provider, "name", "") == "mock_asr" and file.filename:
        from app.providers.asr.mock import _PRESET

        for key, text in _PRESET.items():
            if key in file.filename:
                result = {"ok": True, "text": text, "dialect": dialect}
                break

    if not result.get("ok"):
        raise HTTPException(502, result.get("error", "识别失败"))
    return {
        "text": result.get("text", ""),
        "dialect": dialect,
        "provider": getattr(provider, "name", "asr"),
    }
