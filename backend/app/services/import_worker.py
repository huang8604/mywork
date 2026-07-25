"""Background word-list import.

Single-user NAS context (same as ``audio_worker``): no task queue, one uvicorn
worker. One daemon thread pulls import jobs off a queue and processes them one
row at a time, **each row in its own short-lived session + its own commit**.
That is the fix for the old all-or-nothing behavior: the previous ``/import``
ran every row inside one ``BEGIN IMMEDIATE`` transaction and committed once at
the end, so a slow enrichment (dictionary + AI) blowing past the browser's 60s
timeout rolled the whole batch back — nothing was imported. Now a row that
errors or times out is rolled back alone and the batch continues; already
committed rows survive a process restart.

A progress snapshot ``{state,total,processed,created,updated,skipped,failed,
unresolved,unresolved_words,resolved,audio_generation}`` is exposed via
``import_progress()`` so the UI can render a progress bar by polling
``GET /api/v1/words/import/progress``. The final tally stays readable until
the next job resets the counters. ``Idempotency-Key`` (when supplied) is
finalized from the worker via ``complete_by_key`` so a replay returns the
final result instead of a perpetual "processing".
"""
from __future__ import annotations

import logging
import queue
import threading
from collections import namedtuple
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models import Word
from app.schemas import WordCreate, WordUpdate
from app.services.domain import normalize_word

log = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


# A queued import job. ``payloads`` are post-parse + post-default-tag-merge
# WordCreate rows; ``conflict_policy`` ∈ {skip, update} (reject is pre-scanned
# away by the route before enqueueing); ``unresolved_policy`` ∈ {skip, ai}
# (reject collapses to skip — unresolved rows are never written, only counted).
_ImportJob = namedtuple(
    "_ImportJob",
    [
        "payloads",
        "conflict_policy",
        "unresolved_policy",
        "actor_type",
        "actor_id",
        "request_id",
        "idempotency_key",
    ],
)


def run_import_row(
    db: Session,
    payload: WordCreate,
    *,
    conflict_policy: str,
    allow_ai: bool,
    dry_run: bool = False,
) -> dict:
    """Resolve ONE payload against ``db``. Returns ``{en_word, word_id, action,
    dictionary_found?}`` with action ∈ {created, updated, skipped, unresolved}.

    In ``dry_run`` no row is written and would-be-created rows report
    ``word_id=None``. Does not commit — the caller owns the session/transaction.

    Assumes in-file dedup is already handled by the caller (only the DB is
    checked here). ``conflict_policy`` ∈ {skip, update}; reject is pre-scanned
    away by the route before enqueueing, so it is treated as update here.
    """
    from app.services.dictionary import enrich_word
    from app.services.words import create_word, reimport_word, update_word

    _, normalized = normalize_word(payload.en_word)
    existing = db.scalar(select(Word).where(Word.normalized_en_word == normalized))
    if (
        existing is not None
        and existing.deleted_at is None
        and conflict_policy == "skip"
    ):
        return {"en_word": payload.en_word, "word_id": existing.id, "action": "skipped"}

    try:
        enriched, found = enrich_word(payload, allow_ai=allow_ai)
    except AppError as exc:
        if exc.code == "DICTIONARY_ENTRY_NOT_FOUND":
            return {"en_word": payload.en_word, "word_id": None, "action": "unresolved"}
        raise

    if existing is None:
        if dry_run:
            return {
                "en_word": enriched.en_word,
                "word_id": None,
                "action": "created",
                "dictionary_found": found,
            }
        word = create_word(db, enriched)
        return {
            "en_word": word.en_word,
            "word_id": word.id,
            "action": "created",
            "dictionary_found": found,
        }
    if existing.deleted_at is not None:
        # Re-importing a soft-deleted word restores it regardless of policy.
        if not dry_run:
            reimport_word(db, existing.id, enriched)
        return {
            "en_word": enriched.en_word,
            "word_id": existing.id,
            "action": "updated",
            "dictionary_found": found,
        }
    if not dry_run:
        update_word(
            db,
            existing.id,
            WordUpdate(**enriched.model_dump(), expected_version=existing.version),
        )
    return {
        "en_word": enriched.en_word,
        "word_id": existing.id,
        "action": "updated",
        "dictionary_found": found,
    }


class _ImportWorker:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory
        self._queue: queue.Queue[_ImportJob] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._reset_state()

    def _reset_state(self) -> None:
        self._state = "idle"
        self._total = 0
        self._processed = 0
        self._created = 0
        self._updated = 0
        self._skipped = 0
        self._failed = 0
        self._unresolved = 0
        self._unresolved_words: list[str] = []
        self._resolved: list[dict] = []
        self._audio_queued = 0
        self._finished = False

    def enqueue(self, job: _ImportJob) -> int:
        """Queue a new job and (re)start the worker thread. Returns total rows.

        A new job always resets the counters (only one import runs at a time on
        this single-user deployment; a previous run is already finished because
        the thread processes jobs sequentially).
        """
        with self._lock:
            self._reset_state()
            self._total = len(job.payloads)
            self._state = "running"
            self._queue.put(job)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="import-worker", daemon=True
                )
                self._thread.start()
        return self._total

    def progress(self) -> dict[str, object]:
        with self._lock:
            return {
                "state": self._state,
                "total": self._total,
                "processed": self._processed,
                "created": self._created,
                "updated": self._updated,
                "skipped": self._skipped,
                "failed": self._failed,
                "unresolved": self._unresolved,
                "unresolved_words": list(self._unresolved_words),
                "resolved": list(self._resolved),
                "dictionary_matches": sum(
                    1 for r in self._resolved if r.get("dictionary_found")
                ),
                "audio_generation": {"queued": self._audio_queued},
                "finished": self._finished,
            }

    def _bump(self, **counts: int) -> None:
        with self._lock:
            for key, value in counts.items():
                setattr(self, f"_{key}", getattr(self, f"_{key}") + value)

    def _append_resolved(self, entry: dict) -> None:
        with self._lock:
            self._resolved.append(entry)

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                self._process_job(job)
            except Exception:  # defensive: never let the worker thread die
                log.warning("import worker: job crashed", exc_info=True)
            finally:
                with self._lock:
                    self._state = "idle"
                    self._finished = True
                self._queue.task_done()

    def _process_job(self, job: _ImportJob) -> None:
        allow_ai = job.unresolved_policy == "ai"
        seen: set[str] = set()
        seen_ids: dict[str, int | None] = {}

        for payload in job.payloads:
            _, normalized = normalize_word(payload.en_word)
            # In-file dedup. Under skip: first occurrence wins, repeats skipped.
            # Under update: an in-file duplicate can't be reconciled without
            # aborting — count it as failed and continue (partial success).
            if normalized in seen:
                action = "skipped" if job.conflict_policy == "skip" else "failed"
                entry = {
                    "en_word": payload.en_word,
                    "word_id": seen_ids.get(normalized),
                    "action": action,
                }
                self._bump(processed=1, **{("skipped" if action == "skipped" else "failed"): 1})
                self._append_resolved(entry)
                continue
            seen.add(normalized)

            try:
                db = self._session_factory()
                try:
                    result = run_import_row(
                        db,
                        payload,
                        conflict_policy=job.conflict_policy,
                        allow_ai=allow_ai,
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
                finally:
                    db.close()
            except Exception:
                log.warning(
                    "import worker: row failed en_word=%s",
                    payload.en_word,
                    exc_info=True,
                )
                self._bump(processed=1, failed=1)
                self._append_resolved(
                    {"en_word": payload.en_word, "word_id": None, "action": "failed"}
                )
                continue

            seen_ids[normalized] = result.get("word_id")
            self._bump(processed=1)
            action = result["action"]
            if action == "created":
                self._bump(created=1)
            elif action == "updated":
                self._bump(updated=1)
            elif action == "skipped":
                self._bump(skipped=1)
            elif action == "unresolved":
                with self._lock:
                    self._unresolved += 1
                    self._unresolved_words.append(payload.en_word)
            self._append_resolved(result)

        self._enqueue_audio_for_created()
        self._finalize_idempotency(job)

    def _enqueue_audio_for_created(self) -> None:
        with self._lock:
            created_ids = [
                r["word_id"]
                for r in self._resolved
                if r.get("action") == "created" and r.get("word_id")
            ]
        if not created_ids:
            return
        settings = get_settings()
        if not (
            settings.tts_auto_generate_on_import
            and (settings.tts_enabled or settings.volc_enabled)
        ):
            return
        try:
            from app.services.audio_worker import enqueue_audio_generation

            queued = enqueue_audio_generation(created_ids, force=False)
        except Exception:
            log.warning("import worker: audio enqueue failed", exc_info=True)
            return
        with self._lock:
            self._audio_queued = queued

    def _finalize_idempotency(self, job: _ImportJob) -> None:
        if not job.idempotency_key:
            return
        try:
            from app.services.idempotency import complete_by_key

            db = self._session_factory()
            try:
                complete_by_key(
                    db,
                    actor_type=job.actor_type,
                    actor_id=job.actor_id,
                    method="POST",
                    route_template="/api/v1/words/import",
                    key=job.idempotency_key,
                    data=self.progress(),
                    status_code=200,
                    resource_type="word_import",
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        except Exception:
            log.warning("import worker: idempotency finalize failed", exc_info=True)

    def wait_drained(self, timeout: float | None = None) -> None:
        """Block until all queued jobs are processed. Test helper."""
        self._queue.join()
        if self._thread is not None:
            self._thread.join(timeout=timeout)


_worker = _ImportWorker()


def enqueue_import(
    payloads: list[WordCreate],
    *,
    conflict_policy: str,
    unresolved_policy: str,
    actor_type: str,
    actor_id: str | None,
    request_id: str,
    idempotency_key: str | None,
) -> int:
    """Enqueue an import for background processing. Returns the row total."""
    job = _ImportJob(
        payloads=payloads,
        conflict_policy=conflict_policy,
        unresolved_policy=unresolved_policy,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )
    return _worker.enqueue(job)


def import_progress() -> dict[str, object]:
    """Snapshot of the current/last import run for the progress UI."""
    return _worker.progress()
