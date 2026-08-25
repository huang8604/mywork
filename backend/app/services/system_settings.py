from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import SystemAudioSetting, SystemIssueNote
from app.models.entities import utc_now_text
from app.services.tts import audio_providers_info, canonical_provider, custom_audio_info

log = logging.getLogger(__name__)


def issue_note_data(note: SystemIssueNote) -> dict[str, object]:
    return {
        "content": note.content,
        "version": note.version,
        "updated_at": note.updated_at,
        "updated_by": note.updated_by,
    }


def get_issue_note_data(db: Session) -> dict[str, object]:
    note = db.get(SystemIssueNote, 1)
    if note is None:
        return {
            "content": "",
            "version": 1,
            "updated_at": utc_now_text(),
            "updated_by": None,
        }
    return issue_note_data(note)


def update_issue_note(
    db: Session, *, content: str, expected_version: int, actor_id: str | None
) -> SystemIssueNote:
    note = db.get(SystemIssueNote, 1)
    if note is None:
        if expected_version != 1:
            raise AppError(409, "VERSION_CONFLICT", "问题记录已被修改，请刷新后重试")
        note = SystemIssueNote(
            id=1,
            content=content,
            version=2,
            updated_at=utc_now_text(),
            updated_by=actor_id,
        )
        db.add(note)
    else:
        if note.version != expected_version:
            raise AppError(409, "VERSION_CONFLICT", "问题记录已被修改，请刷新后重试")
        note.content = content
        note.version += 1
        note.updated_at = utc_now_text()
        note.updated_by = actor_id
    db.flush()
    return note


def audio_provider_catalog(db: Session) -> dict[str, object]:
    setting = db.get(SystemAudioSetting, 1)
    preferred = setting.default_provider if setting is not None else None
    return audio_providers_info(audio_runtime_settings(db), default_provider=preferred)


def resolve_audio_provider(db: Session, requested: str | None = None) -> str:
    runtime = audio_runtime_settings(db)
    if requested:
        return canonical_provider(requested, runtime)
    setting = db.get(SystemAudioSetting, 1)
    preferred = setting.default_provider if setting is not None else runtime.tts_provider
    return canonical_provider(preferred, runtime)


def audio_settings_data(db: Session) -> dict[str, object]:
    setting = db.get(SystemAudioSetting, 1)
    runtime = audio_runtime_settings(db)
    # Keep the old top-level fields during the rolling migration, while the
    # current UI consumes the provider list and stores each service separately.
    legacy_catalog = audio_provider_catalog(db)
    return {
        **custom_audio_info(runtime),
        "auto_generate_on_import": runtime.tts_auto_generate_on_import,
        "default": legacy_catalog["default"],
        "current": legacy_catalog["current"],
        "default_provider": canonical_provider(
            setting.default_provider if setting is not None else legacy_catalog["default"], runtime
        ),
        "providers": legacy_catalog["providers"],
        "volc_tuning": {
            "resource_id": runtime.volc_resource_id,
            "speech_rate": runtime.volc_speech_rate,
            "loudness_rate": runtime.volc_loudness_rate,
            "silence_ms": runtime.volc_silence_ms,
        },
        "version": setting.version if setting is not None else 1,
        "updated_at": setting.updated_at if setting is not None else None,
        "updated_by": setting.updated_by if setting is not None else None,
    }


def audio_runtime_settings(db: Session | None = None):
    """Return environment settings with the persisted provider overrides applied.

    Background workers call this without a request session, so the short-lived
    database session is deliberately opened lazily here. Secrets never leave this
    function except through the internal TTS call; the API uses
    ``audio_providers_info`` which only returns masked metadata.
    """
    settings = get_settings()
    owned_session = False
    if db is None:
        from app.core.database import SessionLocal

        db = SessionLocal()
        owned_session = True
    try:
        try:
            setting = db.get(SystemAudioSetting, 1)
        except OperationalError as exc:
            # Direct/background helpers can run before the application database
            # has been migrated (notably isolated unit tests and migration-time
            # startup checks).  Only the missing-settings-table case is safe to
            # treat as "no persisted overrides"; every other database failure
            # must still surface.
            if not owned_session or "no such table: system_audio_settings" not in str(exc):
                raise
            log.info("system_audio_settings table unavailable; using environment settings")
            return settings
        if setting is None:
            return settings
        mimo_url = setting.mimo_base_url
        mimo_key = setting.mimo_api_key
        volc_url = setting.volc_base_url
        volc_key = setting.volc_api_key
        # 0010 stored the then-current single custom connection. Carry it into
        # the correct provider slot even when an installation has not reached
        # the next migration yet.
        legacy_url = setting.custom_base_url
        legacy_key = setting.custom_api_key
        if legacy_url or legacy_key:
            is_volc = _looks_like_volc_url(legacy_url)
            if is_volc:
                volc_url = volc_url or legacy_url
                volc_key = volc_key or legacy_key
            else:
                mimo_url = mimo_url or legacy_url
                mimo_key = mimo_key or legacy_key
        mimo_url = mimo_url or settings.tts_base_url
        mimo_key = mimo_key or settings.tts_api_key
        volc_url = volc_url or settings.volc_base_url
        volc_key = volc_key or settings.volc_api_key
        default_provider = setting.default_provider if setting.default_provider in {"mimo", "volc"} else settings.tts_provider
        values: dict[str, Any] = {
            "tts_provider": default_provider,
            "tts_base_url": mimo_url,
            "tts_api_key": mimo_key,
            "tts_model": setting.mimo_model or settings.tts_model,
            "tts_voice": setting.mimo_voice or settings.tts_voice,
            "volc_base_url": volc_url,
            "volc_api_key": volc_key,
            "volc_model": setting.volc_model or settings.volc_model,
            "volc_voice": setting.volc_voice or settings.volc_voice,
            "volc_resource_id": setting.volc_resource_id or settings.volc_resource_id,
            "volc_speech_rate": (
                setting.volc_speech_rate
                if setting.volc_speech_rate is not None
                else settings.volc_speech_rate
            ),
            "volc_loudness_rate": (
                setting.volc_loudness_rate
                if setting.volc_loudness_rate is not None
                else settings.volc_loudness_rate
            ),
            "volc_silence_ms": (
                setting.volc_silence_ms
                if setting.volc_silence_ms is not None
                else settings.volc_silence_ms
            ),
            "tts_auto_generate_on_import": (
                setting.auto_generate_on_import
                if setting.auto_generate_on_import is not None
                else settings.tts_auto_generate_on_import
            ),
        }
        return replace(settings, **values)
    finally:
        if owned_session:
            db.close()


def _provider_override_values(
    payload: dict[str, object] | None,
) -> dict[str, str | None]:
    if not payload:
        return {}
    result: dict[str, str | None] = {}
    for key in ("base_url", "api_key", "model", "voice"):
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            continue
        cleaned = str(value).strip()
        if key == "base_url":
            cleaned = cleaned.rstrip("/")
        # An empty key means "keep the existing secret". This lets the UI
        # submit normal non-secret fields without accidentally clearing a key.
        if key == "api_key" and not cleaned:
            continue
        result[key] = cleaned or None
    return result


def _volc_tuning_values(payload: dict[str, object] | None) -> dict[str, object]:
    """Cleanse the volc-only tuning knobs; explicit None clears the override."""
    if not payload:
        return {}
    result: dict[str, object] = {}
    for key in ("resource_id", "speech_rate", "loudness_rate", "silence_ms"):
        if key not in payload:
            continue
        value = payload[key]
        if key == "resource_id":
            cleaned = str(value).strip() if value is not None else ""
            result[key] = cleaned or None
        else:
            result[key] = value
    return result


def update_audio_settings(
    db: Session,
    *,
    default_provider: str | None = None,
    expected_version: int,
    actor_id: str | None,
    provider_configs: dict[str, dict[str, object] | None] | None = None,
    auto_generate_on_import: bool | None = None,
    custom_config: dict[str, object] | None = None,
) -> SystemAudioSetting:
    setting = db.get(SystemAudioSetting, 1)
    base_settings = get_settings()
    persisted_default = canonical_provider(default_provider, base_settings) if default_provider else None
    if setting is None:
        if expected_version != 1:
            raise AppError(409, "VERSION_CONFLICT", "音频设置已被修改，请刷新后重试")
        setting = SystemAudioSetting(
            id=1,
            default_provider=persisted_default or canonical_provider(None, base_settings),
            version=2,
            updated_at=utc_now_text(),
            updated_by=actor_id,
        )
        db.add(setting)
    else:
        if setting.version != expected_version:
            raise AppError(409, "VERSION_CONFLICT", "音频设置已被修改，请刷新后重试")
        if default_provider is not None:
            setting.default_provider = persisted_default or canonical_provider(None, base_settings)
        setting.version += 1
        setting.updated_at = utc_now_text()
        setting.updated_by = actor_id
    for provider in ("mimo", "volc"):
        values = _provider_override_values((provider_configs or {}).get(provider))
        for field, value in values.items():
            setattr(setting, f"{provider}_{field}", value)
    legacy_values = _custom_override_values(custom_config)
    legacy_target = "volc" if _looks_like_volc_url(legacy_values.get("base_url")) else "mimo"
    for field, value in legacy_values.items():
        # Keep accepting the released single-connection payload. Route it to a
        # provider slot based on the endpoint protocol; this prevents a Doubao
        # full URL from ever being treated as an OpenAI-compatible URL.
        setattr(setting, f"{legacy_target}_{field}", value)
    if auto_generate_on_import is not None:
        setting.auto_generate_on_import = auto_generate_on_import
    for field, value in _volc_tuning_values((provider_configs or {}).get("volc")).items():
        setattr(setting, f"volc_{field}", value)
    db.flush()
    return setting


def _custom_override_values(payload: dict[str, object] | None) -> dict[str, str | None]:
    """Normalize the public custom API fields into the persisted column names."""
    if not payload:
        return {}
    result: dict[str, str | None] = {}
    for public_name, column_name in (("api_url", "base_url"), ("api_key", "api_key")):
        if public_name not in payload:
            continue
        value = payload[public_name]
        if value is None:
            continue
        cleaned = str(value).strip()
        if column_name == "base_url":
            cleaned = cleaned.rstrip("/")
        # Empty API key means "keep the current key"; the UI can submit the
        # non-secret URL without clearing a stored secret.
        if column_name == "api_key" and not cleaned:
            continue
        result[column_name] = cleaned or None
    return result


def _looks_like_volc_url(value: object) -> bool:
    text = str(value or "").casefold()
    return "openspeech.bytedance.com" in text or "/api/v3/plan/tts/" in text
