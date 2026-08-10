from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import SystemAudioSetting, SystemIssueNote
from app.models.entities import utc_now_text
from app.services.tts import audio_providers_info


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
    return audio_providers_info(default_provider=preferred)


def resolve_audio_provider(db: Session, requested: str | None = None) -> str:
    if requested:
        return requested
    return str(audio_provider_catalog(db)["current"])


def audio_settings_data(db: Session) -> dict[str, object]:
    setting = db.get(SystemAudioSetting, 1)
    catalog = audio_provider_catalog(db)
    return {
        **catalog,
        "default_provider": catalog["current"],
        "version": setting.version if setting is not None else 1,
        "updated_at": setting.updated_at if setting is not None else None,
        "updated_by": setting.updated_by if setting is not None else None,
    }


def update_audio_settings(
    db: Session, *, default_provider: str, expected_version: int, actor_id: str | None
) -> SystemAudioSetting:
    settings = get_settings()
    if not settings.provider_enabled(default_provider):
        raise AppError(409, "TTS_NOT_CONFIGURED", "所选 TTS 服务尚未配置")
    setting = db.get(SystemAudioSetting, 1)
    if setting is None:
        if expected_version != 1:
            raise AppError(409, "VERSION_CONFLICT", "音频设置已被修改，请刷新后重试")
        setting = SystemAudioSetting(
            id=1,
            default_provider=default_provider,
            version=2,
            updated_at=utc_now_text(),
            updated_by=actor_id,
        )
        db.add(setting)
    else:
        if setting.version != expected_version:
            raise AppError(409, "VERSION_CONFLICT", "音频设置已被修改，请刷新后重试")
        setting.default_provider = default_provider
        setting.version += 1
        setting.updated_at = utc_now_text()
        setting.updated_by = actor_id
    db.flush()
    return setting
