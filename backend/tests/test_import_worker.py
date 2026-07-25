from __future__ import annotations

from app.core.config import get_settings
from app.schemas import WordCreate
from app.services import dictionary as dict_mod


def _patch_index(monkeypatch, mapping: dict) -> None:
    monkeypatch.setattr(dict_mod, "_load_index", lambda path: mapping)


def _payload(en_word: str) -> WordCreate:
    return WordCreate(en_word=en_word)


def _worker(db_factory):
    from app.services.import_worker import _ImportWorker

    return _ImportWorker(session_factory=db_factory)


def test_worker_creates_skips_and_progress(db_factory, monkeypatch):
    _patch_index(
        monkeypatch,
        {"camera": {"t": [{"pos": "n.", "cn": "照相机"}]}, "focus": {"t": [{"pos": "n.", "cn": "焦点"}]}},
    )
    # Pre-create "camera" so the worker's skip path fires.
    with db_factory() as db:
        from app.services.words import create_word

        camera = create_word(db, WordCreate(en_word="camera", cn_meaning="相机"))
        camera_id = camera.id
        db.commit()

    worker = _worker(db_factory)
    total = worker.enqueue(
        _make_job([_payload("camera"), _payload("focus")], conflict_policy="skip")
    )
    assert total == 2
    worker.wait_drained(timeout=10)

    prog = worker.progress()
    assert prog["state"] == "idle"
    assert prog["total"] == 2
    assert prog["processed"] == 2
    assert prog["skipped"] == 1
    assert prog["created"] == 1
    assert prog["failed"] == 0
    by_word = {r["en_word"]: r for r in prog["resolved"]}
    assert by_word["camera"]["action"] == "skipped"
    assert by_word["camera"]["word_id"] == camera_id
    assert by_word["focus"]["action"] == "created"
    focus_id = by_word["focus"]["word_id"]
    assert isinstance(focus_id, int) and focus_id != camera_id

    # The created row really is committed (worker uses one session per row).
    with db_factory() as db:
        from app.models import Word

        focus = db.get(Word, focus_id)
        assert focus is not None and focus.deleted_at is None


def test_worker_in_file_dedup_skip(db_factory, monkeypatch):
    _patch_index(monkeypatch, {"focus": {"t": [{"pos": "n.", "cn": "焦点"}]}})
    worker = _worker(db_factory)
    worker.enqueue(
        _make_job([_payload("focus"), _payload("FOCUS")], conflict_policy="skip")
    )
    worker.wait_drained(timeout=10)

    prog = worker.progress()
    by_word = {r["en_word"]: r for r in prog["resolved"]}
    assert by_word["focus"]["action"] == "created"
    first_id = by_word["focus"]["word_id"]
    assert isinstance(first_id, int)
    assert by_word["FOCUS"]["action"] == "skipped"
    assert by_word["FOCUS"]["word_id"] == first_id
    assert prog["created"] == 1
    assert prog["skipped"] == 1


def test_worker_marks_unresolved(db_factory, monkeypatch, tmp_path):
    monkeypatch.setenv("DICTIONARY_INDEX_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("AI_BASE_URL", "")
    monkeypatch.setenv("AI_API_KEY", "")
    get_settings.cache_clear()
    try:
        worker = _worker(db_factory)
        worker.enqueue(_make_job([_payload("syzygy")], conflict_policy="skip"))
        worker.wait_drained(timeout=10)

        prog = worker.progress()
        assert prog["unresolved"] == 1
        assert prog["unresolved_words"] == ["syzygy"]
        assert prog["resolved"][0]["action"] == "unresolved"
        # Nothing was written for the unresolved word.
        with db_factory() as db:
            from sqlalchemy import select

            from app.models import Word

            assert db.scalar(select(Word).where(Word.normalized_en_word == "syzygy")) is None
    finally:
        get_settings.cache_clear()
        dict_mod.clear_dictionary_cache()


def test_worker_skips_failing_row_and_continues(db_factory, monkeypatch):
    _patch_index(monkeypatch, {"focus": {"t": [{"pos": "n.", "cn": "焦点"}]}})
    import app.services.import_worker as iw

    real = iw.run_import_row
    calls = {"n": 0}

    def flaky(db, payload, *, conflict_policy, allow_ai, dry_run=False):
        calls["n"] += 1
        if payload.en_word == "boom":
            raise RuntimeError("simulated per-row failure")
        return real(db, payload, conflict_policy=conflict_policy, allow_ai=allow_ai, dry_run=dry_run)

    monkeypatch.setattr(iw, "run_import_row", flaky)
    worker = _worker(db_factory)
    worker.enqueue(
        _make_job([_payload("focus"), _payload("boom")], conflict_policy="update")
    )
    worker.wait_drained(timeout=10)

    prog = worker.progress()
    # focus committed, boom failed — batch did not abort.
    assert prog["created"] == 1
    assert prog["failed"] == 1
    actions = {r["en_word"]: r["action"] for r in prog["resolved"]}
    assert actions["focus"] == "created"
    assert actions["boom"] == "failed"


def test_worker_updates_existing_under_update_policy(db_factory, monkeypatch):
    _patch_index(monkeypatch, {"focus": {"t": [{"pos": "n.", "cn": "焦点；聚焦"}]}})
    with db_factory() as db:
        from app.services.words import create_word

        word = create_word(db, WordCreate(en_word="focus", cn_meaning="旧释义"))
        version_before = word.version
        db.commit()

    worker = _worker(db_factory)
    worker.enqueue(_make_job([_payload("focus")], conflict_policy="update"))
    worker.wait_drained(timeout=10)

    prog = worker.progress()
    assert prog["updated"] == 1
    with db_factory() as db:
        from app.models import Word

        refreshed = db.get(Word, 1)
        # cn_meaning refreshed from the dictionary, version bumped.
        assert refreshed.cn_meaning != "旧释义"
        assert refreshed.version == version_before + 1


def test_worker_enqueues_audio_for_created_when_enabled(db_factory, monkeypatch):
    _patch_index(
        monkeypatch,
        {"ember": {"t": [{"pos": "n.", "cn": "余烬"}]}, "flame": {"t": [{"pos": "n.", "cn": "火焰"}]}},
    )
    monkeypatch.setenv("VOLC_TTS_BASE_URL", "https://openspeech.example.invalid")
    monkeypatch.setenv("VOLC_TTS_API_KEY", "volc-key")
    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.services.audio_worker as aw

    recorded: dict[str, object] = {}

    def fake_enqueue(ids, *, force=False, provider=None):
        recorded["ids"] = list(ids)
        recorded["force"] = force
        return len(ids)

    monkeypatch.setattr(aw, "enqueue_audio_generation", fake_enqueue)
    try:
        worker = _worker(db_factory)
        worker.enqueue(_make_job([_payload("ember"), _payload("flame")], conflict_policy="update"))
        worker.wait_drained(timeout=10)
        prog = worker.progress()
        assert prog["created"] == 2
        assert prog["audio_generation"]["queued"] == 2
        assert recorded["force"] is False
        assert len(recorded["ids"]) == 2
    finally:
        get_settings.cache_clear()


def test_worker_skips_audio_when_auto_generate_disabled(db_factory, monkeypatch):
    _patch_index(monkeypatch, {"ember": {"t": [{"pos": "n.", "cn": "余烬"}]}})
    monkeypatch.setenv("VOLC_TTS_BASE_URL", "https://openspeech.example.invalid")
    monkeypatch.setenv("VOLC_TTS_API_KEY", "volc-key")
    monkeypatch.setenv("TTS_AUTO_GENERATE_ON_IMPORT", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.services.audio_worker as aw

    def fake_enqueue(*args, **kwargs):
        raise AssertionError("should not enqueue when auto-generate disabled")

    monkeypatch.setattr(aw, "enqueue_audio_generation", fake_enqueue)
    try:
        worker = _worker(db_factory)
        worker.enqueue(_make_job([_payload("ember")], conflict_policy="update"))
        worker.wait_drained(timeout=10)
        prog = worker.progress()
        assert prog["created"] == 1
        assert prog["audio_generation"]["queued"] == 0
    finally:
        get_settings.cache_clear()


def _make_job(payloads, *, conflict_policy):
    from app.services.import_worker import _ImportJob

    return _ImportJob(
        payloads=payloads,
        conflict_policy=conflict_policy,
        unresolved_policy="skip",
        actor_type="web_user",
        actor_id="local-admin",
        request_id="test",
        idempotency_key=None,
    )
