"""Audio (speech-to-text / text-to-speech) client.

Port of server/replit_integrations/audio/client.ts — only the pieces actually
used by the app's routes are ported (speechToText, textToSpeech). OpenAI
access is routed through Replit's AI Integrations proxy, matching the TS
client's `new OpenAI({ apiKey: AI_INTEGRATIONS_OPENAI_API_KEY, baseURL:
AI_INTEGRATIONS_OPENAI_BASE_URL })`.

Note on WebM -> WAV conversion: the TS route (`POST /api/transcribe`) always
ran the uploaded WebM audio through `convertWebmToWav` (a shelled-out ffmpeg
process) before calling `speechToText`. That conversion is NOT required by
OpenAI's transcription API — `gpt-4o-mini-transcribe` (and Whisper) accept
webm directly as an input format. This port skips the ffmpeg step entirely
and sends the browser-recorded webm bytes straight to the transcription API,
avoiding an ffmpeg dependency. See router.py's docstring for more detail.
"""

from io import BytesIO

from openai import AsyncOpenAI

from app.config import get_settings

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            api_key=settings.AI_INTEGRATIONS_OPENAI_API_KEY,
            base_url=settings.AI_INTEGRATIONS_OPENAI_BASE_URL,
        )
    return _client


async def speech_to_text(audio_bytes: bytes, fmt: str = "webm") -> str:
    """Transcribes audio using the dedicated transcription model.

    Port of `speechToText` in client.ts. Uses gpt-4o-mini-transcribe.
    """
    client = get_openai_client()
    file_obj = BytesIO(audio_bytes)
    file_obj.name = f"audio.{fmt}"
    response = await client.audio.transcriptions.create(
        file=file_obj,
        model="gpt-4o-mini-transcribe",
    )
    return response.text


async def text_to_speech(
    text: str,
    voice: str = "alloy",
    fmt: str = "mp3",
) -> bytes:
    """Converts text to speech verbatim.

    Port of `textToSpeech` in client.ts. Uses gpt-audio-mini via chat
    completions with audio modality (matches the TS implementation exactly —
    this is not the dedicated `/v1/audio/speech` endpoint).
    """
    client = get_openai_client()
    response = await client.chat.completions.create(
        model="gpt-audio-mini",
        modalities=["text", "audio"],
        audio={"voice": voice, "format": fmt},
        messages=[
            {
                "role": "system",
                "content": "You are an assistant that performs text-to-speech.",
            },
            {
                "role": "user",
                "content": f"Repeat the following text verbatim: {text}",
            },
        ],
    )
    message = response.choices[0].message
    audio_data = getattr(message, "audio", None)
    audio_b64 = getattr(audio_data, "data", "") if audio_data else ""
    return b64_to_bytes(audio_b64)


def b64_to_bytes(data: str) -> bytes:
    import base64

    if not data:
        return b""
    return base64.b64decode(data)
