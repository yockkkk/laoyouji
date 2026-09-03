"""语音识别上传：POST /api/asr/upload（方言 ASR 接缝入口）。"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import get_ctx

router = APIRouter(prefix="/api/asr", tags=["asr"])


def _sniff_fmt(data: bytes) -> str | None:
    """魔数嗅探音频容器。uni H5 上传的是 blob URL，filename 常无扩展名，
    后端不能只信文件后缀 —— 嗅探到就优先用（也顺带兜 App 上传时后缀被剥的情况）。"""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"fLaC":
        return "flac"
    if data[4:8] == b"ftyp":  # ISO-BMFF：mp4/m4a
        return "mp4"
    if data[:3] == b"ID3":  # mp3 带 ID3 头
        return "mp3"
    if data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):  # 裸 mp3 帧头
        return "mp3"
    if data[:4] == b"\x1a\x45\xdf\xa3":  # EBML → webm/mkv
        return "webm"
    if data[:3] == b"#!A":  # AMR
        return "amr"
    return None


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

    # 容器判定：嗅探优先，后缀次之（blob URL / 命名异常时靠魔数兜底）
    fmt = _sniff_fmt(audio)
    if not fmt and file.filename:
        name = file.filename
        if "." in name:
            fmt = name.rsplit(".", 1)[-1].lower()

    result = await provider.transcribe(audio, fmt=fmt or "", dialect=dialect)

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
