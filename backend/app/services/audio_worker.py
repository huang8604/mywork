"""Background audio generation for imported / batch-regenerated words + number clips.

Single-user NAS context: no task queue, single uvicorn worker. One daemon thread
pulls jobs off a queue and generates MP3s one at a time, each in its own short-lived
session (word jobs) or directly against the filesystem (number jobs — no DB record).
Process restart interrupts unfinished work — the operator re-triggers via the
"一键生成" / "全部重新生成" / "生成序号音频" buttons. Per-job failures are logged
and do not stop the batch.

A run-level counter tuple (state/total/completed/failed/pending) is exposed via
``audio_progress()`` so the UI can render a progress bar by polling
``GET /api/v1/words/audio/progress``. A new "run" resets the counters when the
worker transitions idle→running; counters persist after the run ends (state=idle)
so the final tally is readable until the next batch begins.
"""
from __future__ import annotations

import logging
import queue
import threading
from collections import namedtuple
from collections.abc import Iterable
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Word
from app.services.words import generate_word_audio

log = logging.getLogger(__name__)


def run_audio_job(
    db: Session, word_id: int, *, force: bool = False, provider: str | None = None
) -> bool:
    """Generate audio for one word using ``db``. Returns False if the word no longer
    exists or is soft-deleted (a queued job for a since-deleted word is a no-op).

    Does not commit/close — the caller owns the session lifecycle so this stays
    unit-testable with an injected session.
    """
    word = db.scalar(select(Word).where(Word.id == word_id))
    if word is None or word.deleted_at is not None:
        return False
    generate_word_audio(db, word_id, force=force, provider=provider)
    return True


def run_number_job(n: int, *, force: bool = False, provider: str | None = None) -> None:
    """Generate the "number {n}" announcement clip (no DB record — file only).

    Imported lazily so unit tests that monkeypatch ``run_audio_job`` don't need the
    number-audio module loaded, and so a missing TTS config only errors at run time.
    """
    from app.services.number_audio import generate_number_audio

    generate_number_audio(n, force=force, provider=provider)


# A queued unit of audio work. ``kind`` ∈ {"word","number"}; ``key`` is the word_id
# (word) or the 1-based number n (number). ``provider`` default is resolved later —
# words defer to settings, numbers default to volc (豆包 preferred).
_AudioJob = namedtuple("_AudioJob", ["kind", "key", "force", "provider"])

SessionFactory = Callable[[], Session]


class _AudioWorker:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory
        self._queue: queue.Queue[_AudioJob] = queue.Queue()
        self._pending: set[tuple[str, int, bool]] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = "idle"
        self._total = 0
        self._completed = 0
        self._failed = 0

    def enqueue(
        self, word_ids: Iterable[int], *, force: bool = False, provider: str | None = None
    ) -> int:
        return self._enqueue_jobs(
            (("word", wid) for wid in word_ids), force=force, provider=provider
        )

    def enqueue_numbers(
        self, numbers: Iterable[int], *, force: bool = False, provider: str | None = None
    ) -> int:
        return self._enqueue_jobs(
            (("number", n) for n in numbers), force=force, provider=provider
        )

    def _enqueue_jobs(
        self, items: Iterable[tuple[str, int]], *, force: bool, provider: str | None
    ) -> int:
        added = 0
        with self._lock:
            for kind, key in items:
                dedup = (kind, key, force)
                if dedup in self._pending:
                    continue
                self._pending.add(dedup)
                self._queue.put(_AudioJob(kind, key, force, provider))
                added += 1
            if added:
                if self._state == "idle":
                    self._state = "running"
                    self._total = 0
                    self._completed = 0
                    self._failed = 0
                self._total += added
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="audio-worker", daemon=True
                )
                self._thread.start()
        return added

    def progress(self) -> dict[str, object]:
        with self._lock:
            return {
                "state": self._state,
                "total": self._total,
                "completed": self._completed,
                "failed": self._failed,
                "pending": len(self._pending),
            }

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                self._process(job)
                with self._lock:
                    self._completed += 1
            except Exception:  # defensive: never let the worker thread die
                log.warning(
                    "audio worker: generate failed kind=%s key=%s", job.kind, job.key, exc_info=True
                )
                with self._lock:
                    self._failed += 1
            finally:
                with self._lock:
                    self._pending.discard((job.kind, job.key, job.force))
                    if not self._pending:
                        self._state = "idle"
                self._queue.task_done()

    def _process(self, job: _AudioJob) -> None:
        if job.kind == "number":
            run_number_job(job.key, force=job.force, provider=job.provider)
            return
        db = self._session_factory()
        try:
            run_audio_job(db, job.key, force=job.force, provider=job.provider)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def wait_drained(self, timeout: float | None = None) -> None:
        """Block until all queued jobs are processed. Test helper."""
        self._queue.join()
        if self._thread is not None:
            self._thread.join(timeout=timeout)


_worker = _AudioWorker()


def enqueue_audio_generation(
    word_ids: Iterable[int], *, force: bool = False, provider: str | None = None
) -> int:
    """Enqueue words for background MP3 generation. Returns how many were newly added."""
    return _worker.enqueue(word_ids, force=force, provider=provider)


def enqueue_number_generation(
    numbers: Iterable[int], *, force: bool = False, provider: str | None = None
) -> int:
    """Enqueue "number {n}" clips for background generation. Returns newly-added count."""
    return _worker.enqueue_numbers(numbers, force=force, provider=provider)


def audio_progress() -> dict[str, object]:
    """Snapshot of the current/last batch run for the progress UI."""
    return _worker.progress()
