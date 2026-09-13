"""语音转写预览端点(ADR-004;端点单源=ws-contract §1 语音转写通道)。

POST /asr/transcribe:base64 webm/opus → SenseVoice 转写文本,前端回填文本框,
用户确认后按文本输入发送(对话输入单源文本,本端点不进 WS)。
- 200 + {text}:转写成功,含空串="没听到"(前端 toast 不动 draft)
- 413:超字节护栏;503:转写不可用(模型未加载/异常)
- 音频转写后即弃不落存储(红线 §7);日志只记长度+指纹,事件名与网关时代一致
"""

from __future__ import annotations

import asyncio
import base64

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="voice")

router = APIRouter(prefix="/asr", tags=["asr"])

_MAX_AUDIO_BYTES = 1 * 1024 * 1024
"""base64 解码后字节护栏:15s webm/opus 实际 ~45KB,护栏防滥用而非业务限制(ADR-004)。"""
_MAX_AUDIO_B64 = (_MAX_AUDIO_BYTES + 2) // 3 * 4
"""base64 串长护栏(解码前先查,D7):防大包先整体收进内存+解码完才被拒。"""


class TranscribeRequest(BaseModel):
    """§1 语音转写请求:audio 必填(base64 webm/opus,单段 ≤15s)。"""

    audio: str = Field(min_length=1, description="base64 编码的 webm/opus 音频")


class TranscribeResponse(BaseModel):
    """§1 语音转写响应:text 含空串(="没听到")。"""

    text: str


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(req: TranscribeRequest) -> TranscribeResponse:
    from app.voice import asr  # 函数内导入:模型懒加载,不拖慢启动(同 gateway 旧模式)

    if len(req.audio) > _MAX_AUDIO_B64:
        raise HTTPException(status_code=413, detail="语音超过单段长度上限")
    try:
        audio = base64.b64decode(req.audio, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="audio 不是合法 base64") from exc
    if len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="语音超过单段长度上限")

    try:
        text = await asyncio.to_thread(asr.transcribe, audio)
    except asr.ASRError as exc:
        logger.bind(event="degraded", reason="asr_failed", detail=str(exc)[:120]).log(
            "WARN", "degraded"
        )
        raise HTTPException(status_code=503, detail="语音转写暂时不可用") from exc

    if not text:
        logger.bind(event="asr_empty").log("INFO", "asr_empty")
    else:
        logger.bind(
            event="asr_transcribed",
            length=len(text),
            fingerprint=app_logger.text_fingerprint(text),
        ).log("INFO", "asr_transcribed")
    return TranscribeResponse(text=text)
