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
from app.services.tts import audio_providers_info, custom_audio_info

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
    if requested:
        return requested
    setting = db.get(SystemAudioSetting, 1)
    if setting is not None and (setting.custom_base_url or setting.custom_api_key):
        return "custom"
    return str(audio_provider_catalog(db)["current"])


def audio_settings_data(db: Session) -> dict[str, object]:
    setting = db.get(SystemAudioSetting, 1)
    runtime = audio_runtime_settings(db)
    # Keep the legacy catalog/tuning keys in the wire response during the
    # rolling migration.  The current System UI intentionally ignores them and
    # only renders the custom URL/Key fields; old workers and API clients can
    # therefore upgrade without a flag day.
    legacy_catalog = audio_provider_catalog(db)
    return {
        **custom_audio_info(runtime),
        "auto_generate_on_import": runtime.tts_auto_generate_on_import,
        "default": legacy_catalog["default"],
        "current": legacy_catalog["current"],
        "default_provider": setting.default_provider if setting is not None else legacy_catalog["default"],
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
        custom_url = setting.custom_base_url or setting.mimo_base_url
        custom_key = setting.custom_api_key or setting.mimo_api_key
        values: dict[str, Any] = {
            "tts_provider": (
                "custom"
                if setting.custom_base_url or setting.custom_api_key
                else setting.default_provider or settings.tts_provider
            ),
            "tts_base_url": custom_url or settings.tts_base_url,
            "tts_api_key": custom_key or settings.tts_api_key,
            "tts_model": setting.mimo_model or settings.tts_model,
            "tts_voice": setting.mimo_voice or settings.tts_voice,
            "volc_base_url": setting.volc_base_url or settings.volc_base_url,
            "volc_api_key": setting.volc_api_key or settings.volc_api_key,
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
    persisted_default = "mimo" if default_provider in (None, "custom") else default_provider
    if setting is None:
        if expected_version != 1:
            raise AppError(409, "VERSION_CONFLICT", "音频设置已被修改，请刷新后重试")
        setting = SystemAudioSetting(
            id=1,
            # The released table constraint predates the custom UI.  Keep the
            # historical value internally; runtime resolution below treats a
            # populated custom_* pair as the active connection.
            default_provider=persisted_default or "mimo",
            version=2,
            updated_at=utc_now_text(),
            updated_by=actor_id,
        )
        db.add(setting)
    else:
        if setting.version != expected_version:
            raise AppError(409, "VERSION_CONFLICT", "音频设置已被修改，请刷新后重试")
        if default_provider is not None:
            setting.default_provider = persisted_default or "mimo"
        setting.version += 1
        setting.updated_at = utc_now_text()
        setting.updated_by = actor_id
    for provider in ("mimo", "volc"):
        values = _provider_override_values((provider_configs or {}).get(provider))
        for field, value in values.items():
            setattr(setting, f"{provider}_{field}", value)
    for field, value in _custom_override_values(custom_config).items():
        setattr(setting, f"custom_{field}", value)
    if auto_generate_on_import is not None:
        setting.auto_generate_on_import = auto_generate_on_import
    for field, value in _volc_tuning_values((provider_configs or {}).get("volc")).items():
        setattr(setting, f"volc_{field}", value)
    db.flush()
    if custom_config is None and default_provider is not None and not audio_runtime_settings(db).provider_enabled(default_provider):
        raise AppError(409, "TTS_NOT_CONFIGURED", "所选 TTS 服务尚未配置")
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
