"""Audio routes — port of the /api/speak and /api/transcribe handlers in
server/routes.ts (search for `textToSpeech` / `speechToText` there).

Both routes are gated the same way as the original: `isAuthenticatedOrToken`
in TS -> `require_authenticated_or_token` here.

WebM -> WAV conversion: the original TS `/api/transcribe` handler always ran
uploaded audio through `convertWebmToWav` (ffmpeg via `child_process.spawn`)
before handing it to OpenAI's transcription API. That conversion turned out
to be unnecessary: OpenAI's `gpt-4o-mini-transcribe` (and Whisper) accept
webm directly, so this port sends the base64-decoded webm bytes straight to
the transcription API and skips the ffmpeg step — no ffmpeg dependency is
introduced by this module. See client.py's module docstring.
"""

import base64
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from pydantic import BaseModel

from app.dependencies import require_authenticated_or_token
from app.modules.audio.client import speech_to_text, text_to_speech

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audio"])


class SpeakRequest(BaseModel):
    text: str | None = None
    voice: str = "alloy"


class TranscribeRequest(BaseModel):
    audio: str | None = None


@router.post("/api/speak")
async def speak(
    body: SpeakRequest,
    request: Request,
    _=Depends(require_authenticated_or_token),
):
    if not body.text:
        raise HTTPException(status_code=400, detail="No text provided")

    # Limit text length to prevent abuse (matches TS: text.slice(0, 2000))
    truncated_text = body.text[:2000]

    try:
        audio_bytes = await text_to_speech(truncated_text, body.voice, "mp3")
    except Exception:
        logger.exception("Error generating speech")
        raise HTTPException(status_code=500, detail="Failed to generate speech")

    return {
        "audio": base64.b64encode(audio_bytes).decode("ascii"),
        "format": "mp3",
    }


@router.post("/api/transcribe")
async def transcribe(
    body: TranscribeRequest,
    request: Request,
    _=Depends(require_authenticated_or_token),
):
    if not body.audio:
        raise HTTPException(status_code=400, detail="No audio data provided")

    try:
        audio_bytes = base64.b64decode(body.audio)
    except Exception:
        raise HTTPException(status_code=400, detail="No audio data provided")

    try:
        transcript = await speech_to_text(audio_bytes, "webm")
    except Exception:
        logger.exception("Error transcribing audio")
        raise HTTPException(status_code=500, detail="Failed to transcribe audio")

    return {"transcript": transcript}
