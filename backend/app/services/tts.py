from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request

from app.core.config import Settings, get_settings
from app.core.errors import AppError

log = logging.getLogger(__name__)

# mimo (chat/completions style) takes a style prompt; seed-tts speaks raw text only.
# Prompt asks for British English, clear + forceful, with a tiny pause before/after —
# the "pause" is best-effort (models honor it loosely).
PROMPT = (
    "Pronounce this English word in a clear, confident British English accent. "
    "Pause briefly before speaking, articulate the word with force and clarity, "
    "then pause briefly at the end."
)

# Seed-TTS 2.0 speaks at a slightly slower rate for clarity/force.
VOLC_SPEED = 0.9


def _synthesize_mimo(text: str, settings: Settings) -> bytes:
    """mimo via OpenAI-style chat/completions with audio modality (base64 mp3)."""
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
        log.warning("mimo TTS provider failed: %s", exc.__class__.__name__)
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败") from exc
    if not audio:
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商未返回音频")
    return audio


def _decode_audio(raw: bytes) -> bytes:
    """Defensive audio extraction: binary mp3, or JSON base64 envelope.

    seed-tts-2.0's exact success field is unverified until the model is activated
    on the account, so accept the common shapes: raw mp3 bytes, a top-level base64
    `data`/`audio`, or a mimo-style nested message.audio.data. Volc JSON error
    envelopes (``{"reqid","code","message"}``) surface as a provider error.
    """
    if raw[:3] in (b"\xff\xf3", b"\xff\xfb") or raw[:3] == b"ID3":
        return raw
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return b""
    if isinstance(data, dict):
        if data.get("code") not in (None, 0, "0"):
            log.warning("TTS provider JSON error: %s", data.get("message"))
            raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败")
        for key in ("data", "audio"):
            value = data.get(key)
            if isinstance(value, str) and value:
                try:
                    return base64.b64decode(value)
                except (ValueError, TypeError):
                    pass
        try:
            return base64.b64decode(data["choices"][0]["message"]["audio"]["data"])
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    return b""


def _synthesize_volc(text: str, settings: Settings) -> bytes:
    """doubao-seed-tts-2.0 via the openspeech agent-plan HTTP endpoint.

    Contract verified by live probe up to the resource-acquire step:
      POST ``{volc_base_url}/api/v3/plan/tts/unidirectional?api_key=<key>``
      Headers: ``X-Api-Resource-Id: seed-tts-2.0`` (the api key MUST go in the query
      string — a bare Authorization header is rejected as "app key not found").
      Body: ``{"req_params": {text, model, voice_type, encoding, speed}}``.
    The success audio field is confirmed once the model is activated in the Ark
    console (配置模型 + 开启超额后付费); ``_decode_audio`` tolerates the likely shapes.
    """
    body = {
        "req_params": {
            "text": text,
            "model": settings.volc_model,
            "voice_type": settings.volc_voice,
            "encoding": "mp3",
            "speed": VOLC_SPEED,
        }
    }
    url = (
        f"{settings.volc_base_url}/api/v3/plan/tts/unidirectional"
        f"?api_key={settings.volc_api_key}"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Api-Resource-Id": settings.volc_resource_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.volc_timeout_seconds) as response:
            ct = response.headers.get("Content-Type", "")
            raw = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        log.warning("volc TTS provider failed: %s", exc.__class__.__name__)
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败") from exc
    audio = _decode_audio(raw)
    if not audio:
        log.warning("volc TTS returned no decodable audio (ct=%s, len=%d)", ct, len(raw))
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商未返回音频")
    return audio


_PROVIDERS = {"mimo": _synthesize_mimo, "volc": _synthesize_volc}

_PROVIDER_LABELS = {"mimo": "mimo", "volc": "豆包 seed-tts-2.0"}


def audio_providers_info(settings: Settings | None = None) -> dict[str, object]:
    """Describe the configured TTS providers for the word-library picker."""
    settings = settings or get_settings()
    providers = []
    for pid in ("mimo", "volc"):
        enabled = settings.provider_enabled(pid)
        providers.append(
            {
                "id": pid,
                "label": _PROVIDER_LABELS[pid],
                "enabled": enabled,
                "voice": settings.tts_voice if pid == "mimo" else settings.volc_voice,
                "model": settings.tts_model if pid == "mimo" else settings.volc_model,
            }
        )
    default = settings.tts_provider
    if not settings.provider_enabled(default):
        default = next((p["id"] for p in providers if p["enabled"]), default)
    return {"default": default, "current": default, "providers": providers}


def _provider_order(provider: str | None, settings: Settings) -> list[str]:
    chosen = (provider or settings.tts_provider).strip().lower()
    if chosen not in _PROVIDERS:
        chosen = "mimo"
    other = "volc" if chosen == "mimo" else "mimo"
    return [chosen, other]


def synthesize_word_mp3(
    text: str, *, provider: str | None = None, settings: Settings | None = None
) -> tuple[bytes, str]:
    """Synthesize one English word to MP3, returning ``(audio_bytes, effective_voice)``.

    Tries the selected (or default) provider first; if it is not configured or the
    remote call fails, falls back to the other configured provider. Raises
    ``TTS_NOT_CONFIGURED`` (409) if neither is configured, else the last provider error.
    """
    settings = settings or get_settings()
    last_exc: AppError | None = None
    for current in _provider_order(provider, settings):
        if not settings.provider_enabled(current):
            last_exc = AppError(409, "TTS_NOT_CONFIGURED", "TTS 尚未配置")
            continue
        try:
            audio = _PROVIDERS[current](text, settings)
        except AppError as exc:
            if exc.code in {"TTS_PROVIDER_ERROR", "TTS_NOT_CONFIGURED"}:
                last_exc = exc
                log.warning("TTS provider %s failed, trying fallback", current)
                continue
            raise
        voice = settings.tts_voice if current == "mimo" else settings.volc_voice
        return audio, voice
    raise last_exc or AppError(409, "TTS_NOT_CONFIGURED", "TTS 尚未配置")
