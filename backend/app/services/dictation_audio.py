"""Cached Chinese dictation clips keyed by the immutable worksheet snapshot text."""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.services import tts as tts_service
from app.services.words import audio_dir

_lock = threading.Lock()


def _root(settings: Settings | None = None) -> Path:
    return audio_dir(settings).resolve() / "dictation" / "zh"


def chinese_audio_path(text: str, settings: Settings | None = None) -> Path:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    return _root(settings) / f"{digest}.mp3"


def chinese_audio_file(text: str, settings: Settings | None = None) -> Path | None:
    if not text.strip():
        return None
    root = _root(settings)
    candidate = chinese_audio_path(text, settings).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def generate_chinese_audio(
    text: str, *, provider: str | None = None, settings: Settings | None = None
) -> Path:
    cleaned = text.strip()
    if not cleaned:
        raise AppError(422, "VALIDATION_ERROR", "中文默写内容不能为空")
    settings = settings or get_settings()
    with _lock:
        existing = chinese_audio_file(cleaned, settings)
        if existing:
            return existing
        audio, _voice = tts_service.synthesize_word_mp3(
            cleaned, provider=provider, settings=settings, language="zh"
        )
        root = _root(settings)
        final = chinese_audio_path(cleaned, settings)
        try:
            root.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=f".{final.name}.", suffix=".tmp", dir=root)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(audio)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, final)
            except OSError:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise AppError(503, "AUDIO_STORAGE_ERROR", "音频文件写入失败") from exc
        return final
