"""English and Chinese number-announcement audio for online dictation.

These are standalone MP3 assets — **not words**. They live under
``audio_dir()/numbers`` with no DB record, generated once via TTS
(豆包 seed-tts-2.0 preferred; mimo fallback — see ``services/tts.synthesize_word_mp3``)
and served cached. Online dictation plays "number {position}" before each word so
the learner can map the audio to the printed worksheet's question number.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.services import tts as tts_service
from app.services.words import audio_dir

log = logging.getLogger(__name__)

NUMBER_MIN = 1
NUMBER_MAX = 50


def _numbers_root(settings: Settings | None = None, language: str = "en") -> Path:
    root = audio_dir(settings).resolve() / "numbers"
    return root if language == "en" else root / "zh"


def number_audio_path(
    n: int, settings: Settings | None = None, *, language: str = "en"
) -> Path:
    """Absolute path for the "number {n}" clip (the file may not exist yet)."""
    return _numbers_root(settings, language) / f"number-{n}.mp3"


def number_audio_file(
    n: int, settings: Settings | None = None, *, language: str = "en"
) -> Path | None:
    """Resolved path if the clip exists and sits under the audio root, else None.

    Mirrors ``word_audio_file``'s path-traversal guard so a stray ``n`` can't escape
    the numbers directory.
    """
    if not (NUMBER_MIN <= n <= NUMBER_MAX):
        return None
    if language not in {"en", "zh"}:
        return None
    root = _numbers_root(settings, language)
    candidate = number_audio_path(n, settings, language=language).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def generate_number_audio(
    n: int,
    *,
    force: bool = False,
    provider: str | None = None,
    settings: Settings | None = None,
    language: str = "en",
) -> Path:
    """Synthesize + cache the "number {n}" clip. Idempotent unless ``force``.

    ``provider`` defaults to ``"volc"`` (豆包 preferred); ``synthesize_word_mp3``
    falls back to the other configured provider. Returns the absolute path. Raises
    ``AUDIO_STORAGE_ERROR`` (503) on write failure.
    """
    if not (NUMBER_MIN <= n <= NUMBER_MAX):
        raise AppError(400, "VALIDATION_ERROR", f"序号必须在 {NUMBER_MIN}..{NUMBER_MAX} 之间")
    if language not in {"en", "zh"}:
        raise AppError(422, "VALIDATION_ERROR", "不支持的语音语言")
    settings = settings or get_settings()
    existing = number_audio_file(n, settings, language=language)
    if existing and not force:
        return existing
    text = f"number {n}" if language == "en" else f"第{_chinese_number(n)}题"
    kwargs = {"provider": provider or "volc", "settings": settings}
    if language == "zh":
        kwargs["language"] = "zh"
    audio, _voice = tts_service.synthesize_word_mp3(text, **kwargs)
    root = _numbers_root(settings, language)
    filename = f"number-{n}.mp3"
    final = root / filename
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=root)
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


def missing_numbers(
    settings: Settings | None = None, *, limit: int = NUMBER_MAX, language: str = "en"
) -> list[int]:
    """Numbers in 1..min(NUMBER_MAX, limit) whose clip does not yet exist (ascending)."""
    upper = min(NUMBER_MAX, max(NUMBER_MIN, limit))
    return [
        n
        for n in range(NUMBER_MIN, upper + 1)
        if number_audio_file(n, settings, language=language) is None
    ]


def missing_number_pairs(
    settings: Settings | None = None, *, limit: int = NUMBER_MAX
) -> list[int]:
    """Numbers missing either their English or Chinese clip, in ascending order."""
    return [
        n
        for n in range(NUMBER_MIN, NUMBER_MAX + 1)
        if number_audio_file(n, settings, language="en") is None
        or number_audio_file(n, settings, language="zh") is None
    ][:limit]


def _chinese_number(n: int) -> str:
    digits = "零一二三四五六七八九"
    if n < 10:
        return digits[n]
    tens, ones = divmod(n, 10)
    prefix = "十" if tens == 1 else f"{digits[tens]}十"
    return prefix if ones == 0 else f"{prefix}{digits[ones]}"
