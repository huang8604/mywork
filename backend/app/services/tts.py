from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

from app.core.config import Settings, get_settings
from app.core.errors import AppError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SynthesisResult:
    """Audio plus the effective provider metadata (including fallback choice).

    ``__iter__`` keeps the old ``audio, voice = ...`` callers compatible while
    newer callers can inspect the exact provider/model that produced the bytes.
    """

    audio: bytes
    voice: str
    provider: str
    model: str

    def __iter__(self):
        yield self.audio
        yield self.voice

# mimo (chat/completions style) takes a style prompt; seed-tts speaks raw text only.
# Keep the assistant message as the exact token. In particular, short words such as
# "on" and "like" must not be interpreted as conversational instructions or filler.
PROMPT = (
    "Speak exactly the English token in the assistant message, and nothing else. "
    "Treat it as one isolated vocabulary word or abbreviation, not as a phrase, "
    "instruction, conversational filler, or request. Use a clear, confident British "
    "English accent; articulate every letter and do not add context."
)
CHINESE_PROMPT = (
    "请用清晰、自然、适合课堂听写的普通话朗读下面的中文内容。"
    "朗读前后稍作停顿，不要添加任何解释。"
)

_QUOTA_MARKERS = ("quota", "rate limit", "rate_limit", "too many requests", "额度", "余额不足", "超限")


def _chat_completions_url(settings: Settings) -> str:
    """Accept either an OpenAI-compatible API root or the full endpoint URL."""
    base = settings.tts_base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _provider_error(message: object = "") -> AppError:
    text = str(message or "")
    if any(marker in text.casefold() for marker in _QUOTA_MARKERS):
        return AppError(429, "TTS_QUOTA_EXHAUSTED", "TTS 额度已用完，请稍后重试")
    return AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败")

# Volc tuning defaults: speech_rate<0 = slower (patient/steady), loudness_rate>0 = louder
# (forceful/clear), silence_ms = trailing silence so the end isn't clipped. Leading silence
# comes from the MP3 encoder delay (~100ms, documented) plus the dictation engine's per-word gap.


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
        _chat_completions_url(settings),
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
    except urllib.error.HTTPError as exc:
        log.warning("mimo TTS HTTP error: %s", exc.code)
        raise _provider_error("quota" if exc.code == 429 else exc.reason) from exc
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning("mimo TTS provider failed: %s", exc.__class__.__name__)
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败") from exc
    if not audio:
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商未返回音频")
    return audio


def _synthesize_mimo_chinese(text: str, settings: Settings) -> bytes:
    """mimo Chinese speech using the same audio contract with a Mandarin prompt."""
    payload = {
        "model": settings.tts_model,
        "modalities": ["text", "audio"],
        "audio": {"voice": settings.tts_voice, "format": "mp3"},
        "messages": [
            {"role": "user", "content": CHINESE_PROMPT},
            {"role": "assistant", "content": text},
        ],
    }
    req = urllib.request.Request(
        _chat_completions_url(settings),
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
        audio = base64.b64decode(data["choices"][0]["message"]["audio"]["data"])
    except urllib.error.HTTPError as exc:
        log.warning("mimo Chinese TTS HTTP error: %s", exc.code)
        raise _provider_error("quota" if exc.code == 429 else exc.reason) from exc
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning("mimo Chinese TTS provider failed: %s", exc.__class__.__name__)
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败") from exc
    if not audio:
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商未返回音频")
    return audio


def _decode_audio(raw: bytes) -> bytes:
    """Defensive audio extraction: raw mp3, a JSON base64 envelope, or chunked NDJSON.

    seed-tts-2.0's HTTP chunked endpoint streams **one JSON event per line**
    (``{"code","message","data"}``); the base64 MP3 arrives across several
    ``data`` chunks and is terminated by a ``code=20000000`` "OK" event. A
    provider JSON error surfaces either as a single ``{"reqid","code","message"}``
    object or as a mid-stream error event — both become a provider error. mimo
    returns a single object with nested ``choices[0].message.audio.data``.
    """
    if raw[:3] == b"ID3" or (
        len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0
    ):
        # ID3-tagged MP3 or a bare MP3 frame sync word (0xFFEx).
        return raw
    text = raw.decode("utf-8", errors="replace")
    audio = bytearray()
    error_msg: str | None = None
    saw_event = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        saw_event = True
        code = event.get("code")
        if code not in (None, 0, "0", 20000000) and error_msg is None:
            error_msg = event.get("message") or str(code)
            continue
        value = event.get("data")
        if isinstance(value, str) and value:
            try:
                audio.extend(base64.b64decode(value))
            except (ValueError, TypeError):
                pass
    if audio:
        return bytes(audio)
    if saw_event and error_msg is not None:
        log.warning("TTS provider JSON error: %s", error_msg)
        raise _provider_error(error_msg)
    # Single-object envelope (mimo nested, or top-level data/audio base64).
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return b""
    if isinstance(data, dict):
        if data.get("code") not in (None, 0, "0"):
            log.warning("TTS provider JSON error: %s", data.get("message"))
            raise _provider_error(data.get("message") or data.get("code"))
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
    """Doubao HTTP chunked TTS: standard full URL or historical agent-plan API.

    A full /api/v3/tts/unidirectional URL uses X-Api-Key header auth. A host
    or the full agent-plan URL retains the original query-key contract below.

    Contract verified by live probe (returns ~17KB MP3 for one word):
      POST ``{volc_base_url}/api/v3/plan/tts/unidirectional?api_key=<key>``
      Headers: ``X-Api-Resource-Id: seed-tts-2.0`` (the api key MUST go in the
      query string — this agent-plan key 401s on the standard
      ``/api/v3/tts/unidirectional`` and on a bare Authorization header).
      Body: ``{"user":{"uid"}, "req_params": {text, speaker, audio_params:{format,
      sample_rate, speech_rate, loudness_rate}, additions: "<json string>"}}``.
    Three shape requirements learned from probing:
      1. ``speaker`` MUST be a 豆包语音合成模型2.0 voice (``*_uranus_bigtts``); 1.0
         ids (``BVxxx`` / ``*_moon_bigtts`` / ``*_mars_bigtts``) return
         ``55000000 resource ID is mismatched with speaker related resource``.
      2. ``additions`` is typed "jsonstring" — pass a serialized JSON string,
         not an object (object → "cannot unmarshal object into ... type string").
      3. The success response is HTTP-chunked NDJSON, one ``{code,message,data}``
         event per line; base64 MP3 fragments sit in ``data`` and the stream ends
         with ``code=20000000``. ``_decode_audio`` reassembles them.
    """
    body = {
        "user": {"uid": "myword"},
        "req_params": {
            "text": text,
            "speaker": settings.volc_voice,
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
                "speech_rate": settings.volc_speech_rate,
                "loudness_rate": settings.volc_loudness_rate,
            },
            # `additions` is typed "jsonstring" by the API — it MUST be a
            # serialized JSON string, not an object (the server rejects an object
            # with "cannot unmarshal object into ... additions of type string").
            "additions": json.dumps({"silence_duration": settings.volc_silence_ms}),
        },
    }
    # The original display name uses the endpoint's default model. Explicit
    # API model IDs (e.g. clone variants) must actually reach the provider.
    if settings.volc_model != "doubao-seed-tts-2.0":
        body["req_params"]["model"] = settings.volc_model
    endpoint = urlsplit(settings.volc_base_url)
    path = endpoint.path.rstrip("/")
    standard = path.endswith("/api/v3/tts/unidirectional")
    query = [(name, value) for name, value in parse_qsl(endpoint.query, keep_blank_values=True)
             if name.lower() != "api_key"]
    headers = {"Content-Type": "application/json", "X-Api-Resource-Id": settings.volc_resource_id}
    if standard:
        headers["X-Api-Key"] = settings.volc_api_key
        headers["X-Api-Request-Id"] = str(uuid.uuid4())
    else:
        if not path.endswith("/api/v3/plan/tts/unidirectional"):
            path += "/api/v3/plan/tts/unidirectional"
        query.append(("api_key", settings.volc_api_key))
    url = urlunsplit((endpoint.scheme, endpoint.netloc, path, urlencode(query), ""))
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.volc_timeout_seconds) as response:
            ct = response.headers.get("Content-Type", "")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        log.warning("volc TTS HTTP error: %s", exc.code)
        raise _provider_error("quota" if exc.code == 429 else exc.reason) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        log.warning("volc TTS provider failed: %s", exc.__class__.__name__)
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败") from exc
    audio = _decode_audio(raw)
    if not audio:
        log.warning("volc TTS returned no decodable audio (ct=%s, len=%d)", ct, len(raw))
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商未返回音频")
    return audio


def _synthesize_seed_audio(text: str, settings: Settings, *, language: str = "en") -> bytes:
    """Seed Audio's non-streaming generation API; credentials are header-only."""
    instruction = (
        "用清晰自然、适合课堂听写的普通话"
        if language == "zh" else "用清晰自然的英式英语"
    )
    body = {
        "model": settings.seed_audio_model,
        "text_prompt": f"{instruction}只朗读以下内容，不要解释，不要背景音乐或音效：{json.dumps(text, ensure_ascii=False)}",
        "audio_config": {"format": "mp3", "sample_rate": 24000},
    }
    if settings.seed_audio_voice:
        body["references"] = [{"speaker": settings.seed_audio_voice}]
        body["text_prompt"] = "使用@音频1的音色。" + body["text_prompt"]
    endpoint = settings.seed_audio_base_url.rstrip("/")
    if not endpoint.endswith("/api/v3/tts/create"):
        endpoint += "/api/v3/tts/create"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Api-Key": settings.seed_audio_api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.seed_audio_timeout_seconds) as response:
            data = json.loads(response.read())
        if not isinstance(data, dict):
            raise ValueError("invalid response")
        if data.get("code") not in (None, 0, "0", 20000000):
            raise _provider_error(data.get("message"))
        audio = base64.b64decode(data.get("audio", ""), validate=True)
    except urllib.error.HTTPError as exc:
        # Never log provider bodies or headers: these may contain credentials.
        log.warning("seed-audio TTS HTTP error: %s", exc.code)
        if exc.code in {401, 403}:
            raise AppError(502, "TTS_ACCESS_DENIED", "Seed Audio 鉴权或资源权限不足，请检查 API Key 和服务开通状态") from exc
        raise _provider_error("quota" if exc.code == 429 else "") from exc
    except (urllib.error.URLError, TimeoutError, TypeError, ValueError) as exc:
        log.warning("seed-audio TTS provider failed: %s", exc.__class__.__name__)
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商调用失败") from exc
    if not audio or not (audio[:3] == b"ID3" or (len(audio) >= 2 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)):
        raise AppError(502, "TTS_PROVIDER_ERROR", "TTS 供应商未返回有效 MP3 音频")
    return audio


def _synthesize_seed_audio_chinese(text: str, settings: Settings) -> bytes:
    return _synthesize_seed_audio(text, settings, language="zh")


_PROVIDERS = {"mimo": _synthesize_mimo, "volc": _synthesize_volc, "seed_audio": _synthesize_seed_audio}
_CHINESE_PROVIDERS = {"mimo": _synthesize_mimo_chinese, "volc": _synthesize_volc, "seed_audio": _synthesize_seed_audio_chinese}

_PROVIDER_LABELS = {"mimo": "Mimo", "volc": "豆包", "seed_audio": "Seed Audio 1.0"}


def canonical_provider(provider: str | None, settings: Settings) -> str:
    """Normalize released aliases while keeping 豆包 (volc) the primary id."""
    chosen = (provider or settings.tts_provider).strip().lower()
    if chosen == "custom":
        # ``custom`` was the previous single-connection setting. New persisted
        # settings migrate it to a real provider; old queued jobs use the current
        # default rather than accidentally sending a Mimo payload to 豆包.
        chosen = settings.tts_provider if settings.tts_provider in _PROVIDER_LABELS else "volc"
    return chosen if chosen in _PROVIDER_LABELS else "volc"


def provider_model_voice(settings: Settings, provider: str) -> tuple[str, str]:
    if provider == "seed_audio":
        return settings.seed_audio_model, settings.seed_audio_voice or "prompt"
    if provider == "volc":
        return settings.volc_model, settings.volc_voice
    return settings.tts_model, settings.tts_voice


def provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider)


def provider_connection(settings: Settings, provider: str) -> tuple[str, str]:
    if provider == "seed_audio":
        return settings.seed_audio_base_url, settings.seed_audio_api_key
    if provider == "volc":
        return settings.volc_base_url, settings.volc_api_key
    return settings.tts_base_url, settings.tts_api_key


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * max(4, len(value) - 4)}{value[-2:]}"


def audio_providers_info(
    settings: Settings | None = None, *, default_provider: str | None = None
) -> dict[str, object]:
    """Describe supported TTS services without exposing secrets."""
    settings = settings or get_settings()
    providers = []
    for pid in _PROVIDER_LABELS:
        enabled = settings.provider_enabled(pid)
        api_url, api_key = provider_connection(settings, pid)
        model, voice = provider_model_voice(settings, pid)
        providers.append(
            {
                "id": pid,
                "label": provider_label(pid),
                "enabled": enabled,
                "api_url": api_url,
                "base_url": api_url,
                "api_key_configured": bool(api_key),
                "api_key_masked": _mask_secret(api_key),
                "voice": voice,
                "model": model,
            }
        )
    default = canonical_provider(default_provider, settings)
    return {"default": default, "current": default, "providers": providers}


def custom_audio_info(settings: Settings | None = None) -> dict[str, object]:
    """Return the selected service in the legacy top-level response shape."""
    settings = settings or get_settings()
    provider = canonical_provider(settings.tts_provider, settings)
    api_url, api_key = provider_connection(settings, provider)
    model, voice = provider_model_voice(settings, provider)
    return {
        "api_url": api_url,
        "base_url": api_url,
        "api_key_configured": bool(api_key),
        "api_key_masked": _mask_secret(api_key),
        "model": model,
        "voice": voice,
        "configured": settings.provider_enabled(provider),
        "provider": provider,
        "provider_label": provider_label(provider),
    }


def _provider_order(provider: str | None, settings: Settings) -> list[str]:
    chosen = canonical_provider(provider, settings)
    # Seed Audio is opt-in. Never use it as an implicit fallback or silently
    # substitute a different model for an explicitly selected Seed Audio run.
    if chosen == "seed_audio":
        return [chosen]
    other = "volc" if chosen == "mimo" else "mimo"
    return [chosen, other]


def synthesize_word_mp3(
    text: str,
    *,
    provider: str | None = None,
    settings: Settings | None = None,
    language: str = "en",
) -> SynthesisResult:
    """Synthesize English or Chinese text to MP3.

    豆包 is attempted first by default. A provider error (including quota or an
    undecodable response) moves to the other configured service; local validation
    errors are raised before any provider call.
    """
    text = text.strip()
    if not text:
        raise AppError(422, "VALIDATION_ERROR", "语音内容不能为空")
    if language not in {"en", "zh"}:
        raise AppError(422, "VALIDATION_ERROR", "不支持的语音语言")
    settings = settings or get_settings()
    providers = _CHINESE_PROVIDERS if language == "zh" else _PROVIDERS
    last_exc: AppError | None = None
    for current in _provider_order(provider, settings):
        if not settings.provider_enabled(current):
            last_exc = AppError(409, "TTS_NOT_CONFIGURED", "TTS 尚未配置")
            continue
        try:
            log.debug("tts synthesize provider=%s language=%s token=%r", current, language, text)
            audio = providers[current](text, settings)
        except AppError as exc:
            if exc.code in {"TTS_PROVIDER_ERROR", "TTS_NOT_CONFIGURED", "TTS_QUOTA_EXHAUSTED"}:
                last_exc = exc
                log.warning("TTS provider %s failed, trying fallback", current)
                continue
            raise
        model, voice = provider_model_voice(settings, current)
        if isinstance(audio, SynthesisResult):
            return audio
        return SynthesisResult(audio=audio, voice=voice, provider=current, model=model)
    raise last_exc or AppError(409, "TTS_NOT_CONFIGURED", "TTS 尚未配置")
