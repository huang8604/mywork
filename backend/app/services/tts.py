from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request

from app.core.config import Settings, get_settings
from app.core.errors import AppError

log = logging.getLogger(__name__)

PROMPT = "Pronounce this English word clearly and naturally for vocabulary dictation."


def synthesize_word_mp3(text: str, *, settings: Settings | None = None) -> bytes:
    """Generate an MP3 pronunciation for one English word via the configured TTS provider."""
    settings = settings or get_settings()
    if not settings.tts_enabled:
        raise AppError(409, "TTS_NOT_CONFIGURED", "TTS 尚未配置")
    payload = {
        "model": settings.tts_model,
        "modalities": ["text", "audio"],
        "audio": {"voice": settings.tts_voice, "format": "mp3"},
        "messages": [
            {"role": "user", "content": PROMPT},
            {"role": "assistant", "content": text},
        ],
    }
    req = urllib.request.Request(
        f"{settings.tts_base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.tts_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.tts_timeout_seconds) as response:
            raw = response.read()
        data = json.loads(raw)
        encoded = data["choices"][0]["message"]["audio"]["data"]
        audio = base64.b64decode(encoded)
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning("TTS provider failed: %s", exc.__class__.__name__)
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败") from exc
    if not audio:
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商未返回音频")
    return audio
