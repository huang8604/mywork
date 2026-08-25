"""Persistent, resumable audio generation for every local dictionary entry.

The generated MP3s form a shared cache under ``TTS_AUDIO_DIR/dictionary``.  A
small sidecar SQLite database stores cache metadata and the singleton job state,
so pause/quota-wait/progress survive an application restart without adding a
large row set to the main vocabulary database.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models import Word
from app.services import tts as tts_service
from app.services.dictionary import dictionary_words
from app.services.domain import utc_text
from app.services.words import audio_dir

log = logging.getLogger(__name__)

ACTIVE_STATES = {"running", "waiting_retry", "waiting_quota", "completed"}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


class _DictionaryAudioStore:
    def path(self) -> Path:
        return audio_dir() / "dictionary-audio.sqlite3"

    def exists(self) -> bool:
        return self.path().is_file()

    def _connect(self, *, create: bool = True) -> sqlite3.Connection | None:
        path = self.path()
        if not create and not path.is_file():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=10000")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS dictionary_audio_entries (
                normalized_word TEXT PRIMARY KEY,
                en_word TEXT NOT NULL,
                audio_path TEXT NOT NULL,
                audio_format TEXT NOT NULL,
                audio_provider TEXT,
                audio_model TEXT,
                audio_voice TEXT NOT NULL,
                audio_bytes INTEGER NOT NULL,
                generated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dictionary_audio_job (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state TEXT NOT NULL,
                total INTEGER NOT NULL,
                generated INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                provider TEXT,
                model TEXT,
                voice TEXT,
                last_provider TEXT,
                last_model TEXT,
                last_voice TEXT,
                force_regenerate INTEGER NOT NULL DEFAULT 0,
                next_run_at TEXT,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {
            row[1] for row in con.execute("PRAGMA table_info(dictionary_audio_entries)")
        }
        for name, definition in (("audio_provider", "TEXT"), ("audio_model", "TEXT")):
            if name not in columns:
                con.execute(f"ALTER TABLE dictionary_audio_entries ADD COLUMN {name} {definition}")  # noqa: S608
        job_columns = {row[1] for row in con.execute("PRAGMA table_info(dictionary_audio_job)")}
        for name, definition in (
            ("model", "TEXT"),
            ("voice", "TEXT"),
            ("last_provider", "TEXT"),
            ("last_model", "TEXT"),
            ("last_voice", "TEXT"),
            ("force_regenerate", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in job_columns:
                con.execute(f"ALTER TABLE dictionary_audio_job ADD COLUMN {name} {definition}")  # noqa: S608
        con.execute(
            """INSERT OR IGNORE INTO dictionary_audio_job
               (id,state,total,generated,failed,provider,model,voice,last_provider,last_model,last_voice,
                force_regenerate,next_run_at,last_error,updated_at)
               VALUES (1,'idle',0,0,0,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL,?)""",
            (utc_text(),),
        )
        con.commit()
        return con

    def state(self, *, create: bool = True) -> dict[str, Any]:
        con = self._connect(create=create)
        if con is None:
            return {
                "state": "idle", "total": 0, "generated": 0, "failed": 0,
                "provider": None, "model": None, "voice": None,
                "last_provider": None, "last_model": None, "last_voice": None,
                "force_regenerate": 0, "next_run_at": None, "last_error": None,
                "updated_at": None,
            }
        try:
            row = con.execute("SELECT * FROM dictionary_audio_job WHERE id=1").fetchone()
            return dict(row) if row else {}
        finally:
            con.close()

    def update_state(self, **values: Any) -> dict[str, Any]:
        values["updated_at"] = utc_text()
        con = self._connect()
        assert con is not None
        try:
            columns = ",".join(f"{key}=?" for key in values)
            con.execute(
                f"UPDATE dictionary_audio_job SET {columns} WHERE id=1",  # noqa: S608
                tuple(values.values()),
            )
            con.commit()
        finally:
            con.close()
        return self.state()

    def entry(self, normalized_word: str) -> dict[str, Any] | None:
        con = self._connect(create=False)
        if con is None:
            return None
        try:
            row = con.execute(
                "SELECT * FROM dictionary_audio_entries WHERE normalized_word=?",
                (normalized_word,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            con.close()

    def cached_words(self) -> set[str]:
        con = self._connect(create=False)
        if con is None:
            return set()
        try:
            return {row[0] for row in con.execute("SELECT normalized_word FROM dictionary_audio_entries")}
        finally:
            con.close()

    def valid_cached_words(self, candidates: tuple[str, ...]) -> set[str]:
        wanted = set(candidates)
        con = self._connect(create=False)
        if con is None:
            return set()
        root = audio_dir().resolve()
        valid: set[str] = set()
        try:
            rows = con.execute(
                "SELECT normalized_word,audio_path FROM dictionary_audio_entries"
            )
            for normalized_word, audio_path in rows:
                if normalized_word not in wanted:
                    continue
                candidate = (root / audio_path).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError:
                    continue
                if candidate.is_file():
                    valid.add(normalized_word)
            return valid
        finally:
            con.close()

    def save_entry(self, entry: dict[str, Any]) -> None:
        con = self._connect()
        assert con is not None
        try:
            con.execute(
                """INSERT INTO dictionary_audio_entries
                   (normalized_word,en_word,audio_path,audio_format,audio_provider,audio_model,
                    audio_voice,audio_bytes,generated_at)
                   VALUES (:normalized_word,:en_word,:audio_path,:audio_format,:audio_provider,:audio_model,
                    :audio_voice,:audio_bytes,:generated_at)
                   ON CONFLICT(normalized_word) DO UPDATE SET
                     en_word=excluded.en_word,audio_path=excluded.audio_path,
                     audio_format=excluded.audio_format,audio_provider=excluded.audio_provider,
                     audio_model=excluded.audio_model,audio_voice=excluded.audio_voice,
                     audio_bytes=excluded.audio_bytes,generated_at=excluded.generated_at""",
                entry,
            )
            con.commit()
        finally:
            con.close()


_store = _DictionaryAudioStore()


def _entry_file(entry: dict[str, Any]) -> Path | None:
    root = audio_dir().resolve()
    candidate = (root / str(entry["audio_path"])).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def attach_cached_dictionary_audio(word: Word) -> bool:
    """Attach a shared cached clip to a newly-created/restored Word, if present."""
    entry = _store.entry(word.normalized_en_word)
    if entry is None or _entry_file(entry) is None:
        return False
    word.audio_path = entry["audio_path"]
    word.audio_format = entry["audio_format"]
    word.audio_provider = entry.get("audio_provider")
    word.audio_model = entry.get("audio_model")
    word.audio_voice = entry["audio_voice"]
    word.audio_generated_at = entry["generated_at"]
    word.audio_bytes = entry["audio_bytes"]
    return True


def _write_shared_audio(
    normalized_word: str, audio: bytes, *, provider: str, model: str, voice: str
) -> dict[str, Any]:
    root = audio_dir()
    target_dir = root / "dictionary"
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(normalized_word.encode("utf-8")).hexdigest()[:24]
    filename = f"dictionary-{digest}.mp3"
    final = target_dir / filename
    fd, tmp_name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=target_dir)
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
    return {
        "normalized_word": normalized_word,
        "en_word": normalized_word,
        "audio_path": str(Path("dictionary") / filename),
        "audio_format": "mp3",
        "audio_provider": provider,
        "audio_model": model,
        "audio_voice": voice,
        "audio_bytes": len(audio),
        "generated_at": utc_text(),
    }


def _attach_existing_words(normalized_word: str) -> None:
    db = SessionLocal()
    try:
        words = list(
            db.scalars(
                select(Word).where(
                    Word.normalized_en_word == normalized_word,
                    Word.deleted_at.is_(None),
                    Word.audio_path.is_(None),
                )
            )
        )
        for word in words:
            if attach_cached_dictionary_audio(word):
                word.version += 1
                word.updated_at = utc_text()
        db.commit()
    except Exception:
        db.rollback()
        log.warning("dictionary audio: failed to attach cache to existing word", exc_info=True)
    finally:
        db.close()


class _DictionaryAudioWorker:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stopped = False

    def ensure_thread(self) -> None:
        with self._condition:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._loop, name="dictionary-audio-worker", daemon=True
                )
                self._thread.start()
            self._condition.notify_all()

    def start(self, provider: str | None = None, *, force: bool = False) -> dict[str, Any]:
        from app.services.system_settings import audio_runtime_settings
        from app.services.tts import canonical_provider, provider_model_voice

        settings = audio_runtime_settings()
        chosen = canonical_provider(provider, settings)
        other = "mimo" if chosen == "volc" else "volc"
        if not settings.provider_enabled(chosen) and not settings.provider_enabled(other):
            raise AppError(409, "TTS_NOT_CONFIGURED", "所选 TTS 服务尚未配置")
        words = dictionary_words()
        if not words:
            raise AppError(409, "DICTIONARY_UNAVAILABLE", "本地词库不存在或没有可生成的单词")
        cached = _store.valid_cached_words(words)
        _store.update_state(
            state="running" if force or len(cached) < len(words) else "completed",
            total=len(words), generated=len(cached), failed=0, provider=chosen,
            model=provider_model_voice(settings, chosen)[0], voice=provider_model_voice(settings, chosen)[1],
            last_provider=None, last_model=None, last_voice=None,
            force_regenerate=int(force),
            next_run_at=None, last_error=None,
        )
        if len(cached) == len(words) and not force:
            _store.update_state(next_run_at=_after(settings.dictionary_audio_scan_seconds))
        self.ensure_thread()
        return dictionary_audio_progress()

    def pause(self) -> dict[str, Any]:
        state = _store.state()
        if state.get("state") != "idle":
            _store.update_state(state="paused", next_run_at=None)
        self.ensure_thread()
        return dictionary_audio_progress()

    def resume(self) -> dict[str, Any]:
        state = _store.state()
        from app.services.system_settings import audio_runtime_settings

        provider = state.get("provider") or audio_runtime_settings().tts_provider
        return self.start(provider, force=bool(state.get("force_regenerate")))

    def _loop(self) -> None:
        while not self._stopped:
            state = _store.state()
            current = state.get("state", "idle")
            next_run = _parse_time(state.get("next_run_at"))
            due = next_run is not None and next_run <= datetime.now(UTC)
            if current == "running":
                self._run_pass()
                continue
            if current in {"waiting_retry", "waiting_quota", "completed"} and due:
                _store.update_state(state="running", failed=0, next_run_at=None, last_error=None)
                continue
            timeout = 30.0
            if next_run is not None:
                timeout = max(0.5, min(timeout, (next_run - datetime.now(UTC)).total_seconds()))
            with self._condition:
                self._condition.wait(timeout=timeout)

    def stop(self) -> None:
        """Stop this worker instance (used by isolated tests)."""
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _run_pass(self) -> None:
        from app.services.system_settings import audio_runtime_settings

        settings = audio_runtime_settings()
        words = dictionary_words()
        cached = _store.valid_cached_words(words)
        _store.update_state(total=len(words), generated=len(cached), failed=0)
        failed = 0
        state = _store.state()
        provider = state.get("provider") or settings.tts_provider
        force_regenerate = bool(state.get("force_regenerate"))
        for normalized_word in words:
            if _store.state().get("state") != "running":
                return
            entry = _store.entry(normalized_word)
            if not force_regenerate and entry is not None and _entry_file(entry) is not None:
                continue
            try:
                result = tts_service.synthesize_word_mp3(
                    normalized_word, provider=provider, settings=settings
                )
                if isinstance(result, tts_service.SynthesisResult):
                    audio, voice = result.audio, result.voice
                    actual_provider, model = result.provider, result.model
                else:
                    audio, voice = result
                    actual_provider = provider
                    model = settings.volc_model if actual_provider == "volc" else settings.tts_model
                entry = _write_shared_audio(
                    normalized_word,
                    audio,
                    provider=actual_provider,
                    model=model,
                    voice=voice,
                )
                _store.save_entry(entry)
                _attach_existing_words(normalized_word)
                cached.add(normalized_word)
                _store.update_state(
                    generated=len(cached), failed=failed, last_error=None,
                    last_provider=actual_provider, last_model=model, last_voice=voice,
                )
            except AppError as exc:
                if exc.code == "TTS_QUOTA_EXHAUSTED":
                    _store.update_state(
                        state="waiting_quota", failed=failed,
                        next_run_at=_after(settings.dictionary_audio_quota_wait_seconds),
                        last_error="TTS 额度已用完，5 小时后自动继续",
                    )
                    return
                failed += 1
                _store.update_state(failed=failed, last_error=exc.message)
                log.warning("dictionary audio failed word=%s code=%s", normalized_word, exc.code)
            except Exception as exc:  # keep a long batch alive after storage/network surprises
                failed += 1
                _store.update_state(failed=failed, last_error=str(exc)[:500])
                log.warning("dictionary audio failed word=%s", normalized_word, exc_info=True)
        if len(cached) >= len(words):
            _store.update_state(
                state="completed", generated=len(cached), failed=0,
                force_regenerate=0, next_run_at=_after(settings.dictionary_audio_scan_seconds), last_error=None,
            )
        else:
            _store.update_state(
                state="waiting_retry", generated=len(cached), failed=failed,
                next_run_at=_after(settings.dictionary_audio_retry_seconds),
            )


_worker = _DictionaryAudioWorker()


def dictionary_audio_progress() -> dict[str, Any]:
    words = dictionary_words()
    state = _store.state(create=False)
    total = len(words)
    if state.get("total", 0) == 0 and total:
        state["total"] = total
        state["generated"] = len(_store.cached_words().intersection(words))
    generated = int(state.get("generated") or 0)
    return {
        **state,
        "total": total or int(state.get("total") or 0),
        "generated": generated,
        "remaining": max(0, (total or int(state.get("total") or 0)) - generated),
        "dictionary_available": bool(words),
    }


def start_dictionary_audio(provider: str | None = None, *, force: bool = False) -> dict[str, Any]:
    return _worker.start(provider, force=force)


def pause_dictionary_audio() -> dict[str, Any]:
    return _worker.pause()


def resume_dictionary_audio() -> dict[str, Any]:
    return _worker.resume()


def resume_persisted_dictionary_audio_worker() -> None:
    """Restart only a previously-enabled job; a pristine install remains idle."""
    if not _store.exists():
        return
    state = _store.state(create=False)
    if state.get("state") in ACTIVE_STATES:
        _worker.ensure_thread()
