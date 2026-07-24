from __future__ import annotations

from collections.abc import Callable

from app.core.config import get_settings
from app.core.errors import AppError
from conftest import create_word, seed_credential

MP3 = b"\xff\xf3\x84\xc4" + b"audio" * 20


def _enable_tts(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TTS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("TTS_API_KEY", "test-key")
    monkeypatch.setenv("TTS_MODEL", "mimo-v2.5-tts")
    monkeypatch.setenv("TTS_VOICE", "Chloe")
    monkeypatch.setenv("TTS_AUDIO_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()


def _enable_volc(monkeypatch) -> None:
    monkeypatch.setenv("VOLC_TTS_BASE_URL", "https://openspeech.example.invalid")
    monkeypatch.setenv("VOLC_TTS_API_KEY", "volc-key")
    monkeypatch.setenv("VOLC_TTS_MODEL", "doubao-seed-tts-2.0")
    monkeypatch.setenv("VOLC_TTS_RESOURCE_ID", "seed-tts-2.0")
    monkeypatch.setenv("VOLC_TTS_VOICE", "BV700_V2_streaming")
    get_settings.cache_clear()


def _mock_tts(monkeypatch, impl: Callable[..., bytes] | None = None) -> list[str]:
    import app.services.tts as tts

    calls: list[str] = []

    def fake(text: str, *, provider=None, settings=None) -> tuple[bytes, str]:
        calls.append(text)
        if impl is not None:
            return impl(text, settings=settings), "Chloe"
        return MP3, "Chloe"

    monkeypatch.setattr(tts, "synthesize_word_mp3", fake)
    return calls


def _mock_providers(monkeypatch, mimo_fn, volc_fn):
    import app.services.tts as tts

    monkeypatch.setattr(tts, "_PROVIDERS", {"mimo": mimo_fn, "volc": volc_fn})


def test_audio_generation_requires_tts_config(client):
    word = create_word(client, {"en_word": "camera", "cn_meaning": "相机", "tags": []})
    response = client.post(
        f"/api/v1/words/{word['id']}/audio",
        headers={"Idempotency-Key": "audio-missing-config"},
        json={},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "TTS_NOT_CONFIGURED"


def test_generate_and_get_word_audio(client, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    calls = _mock_tts(monkeypatch)
    word = create_word(client, {"en_word": "camera", "cn_meaning": "相机", "tags": []})

    response = client.post(
        f"/api/v1/words/{word['id']}/audio",
        headers={"Idempotency-Key": "audio-generate-camera"},
        json={},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["audio_path"].endswith(".mp3")
    assert data["audio_format"] == "mp3"
    assert data["audio_voice"] == "Chloe"
    assert data["audio_generated_at"] is not None
    assert data["audio_bytes"] == len(MP3)
    assert data["version"] == word["version"] + 1
    assert calls == ["camera"]

    audio = client.get(f"/api/v1/words/{word['id']}/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/mpeg")
    assert audio.headers["content-disposition"] == "inline"
    assert audio.content == MP3


def test_generate_word_audio_is_idempotent_without_force(client, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    calls = _mock_tts(monkeypatch)
    word = create_word(client, {"en_word": "focus", "cn_meaning": "焦点", "tags": []})

    first = client.post(
        f"/api/v1/words/{word['id']}/audio",
        headers={"Idempotency-Key": "audio-focus-1"},
        json={},
    )
    second = client.post(
        f"/api/v1/words/{word['id']}/audio",
        headers={"Idempotency-Key": "audio-focus-2"},
        json={"force": False},
    )
    assert first.status_code == second.status_code == 200
    assert calls == ["focus"]
    assert second.json()["data"]["version"] == first.json()["data"]["version"]


def test_force_regenerates_word_audio(client, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    calls = _mock_tts(monkeypatch)
    word = create_word(client, {"en_word": "again", "cn_meaning": "再次", "tags": []})

    first = client.post(
        f"/api/v1/words/{word['id']}/audio",
        headers={"Idempotency-Key": "audio-again-1"},
        json={},
    ).json()["data"]
    second = client.post(
        f"/api/v1/words/{word['id']}/audio",
        headers={"Idempotency-Key": "audio-again-2"},
        json={"force": True},
    ).json()["data"]
    assert calls == ["again", "again"]
    assert second["version"] == first["version"] + 1
    assert second["audio_bytes"] == len(MP3)


def test_batch_generates_missing_audio_in_id_order_with_failures(client, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)

    def impl(text: str, *, settings=None) -> bytes:
        if text == "beta":
            raise RuntimeError("provider down")
        return MP3 + text.encode()

    calls = _mock_tts(monkeypatch, impl)
    a = create_word(client, {"en_word": "alpha", "cn_meaning": "阿尔法", "tags": []})
    b = create_word(client, {"en_word": "beta", "cn_meaning": "贝塔", "tags": []})
    c = create_word(client, {"en_word": "gamma", "cn_meaning": "伽马", "tags": []})

    response = client.post(
        "/api/v1/words/audio/generate-missing",
        headers={"Idempotency-Key": "audio-batch-1"},
        json={"limit": 2},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["requested"] == 2
    assert data["generated"] == 1
    assert data["failed"] == 1
    assert data["has_more"] is True
    assert data["failures"] == [{"word_id": b["id"], "en_word": "beta", "message": "TTS 供应商调用失败"}]
    assert calls == ["alpha", "beta"]
    assert client.get(f"/api/v1/words/{a['id']}/audio").status_code == 200
    assert client.get(f"/api/v1/words/{b['id']}/audio").status_code == 404
    assert client.get(f"/api/v1/words/{c['id']}/audio").status_code == 404


def test_student_cannot_use_word_audio_routes_but_can_read_session_item_audio(
    client, db_session, login_mode, monkeypatch, tmp_path
):
    _enable_tts(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)
    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "stu", "stupass1", role="student")

    client.post("/api/v1/auth/login", json={"username": "admin", "password": "supersecret"})
    word = create_word(client, {"en_word": "sound", "cn_meaning": "声音", "tags": []})
    generated = client.post(
        f"/api/v1/words/{word['id']}/audio",
        headers={"Idempotency-Key": "audio-sound-admin"},
        json={},
    )
    assert generated.status_code == 200, generated.text
    session = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "audio-session"},
        json={
            "new_words_limit": 1,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "seed": 1,
        },
    ).json()["data"]
    item = session["items"][0]

    client.post("/api/v1/auth/login", json={"username": "stu", "password": "stupass1"})
    assert client.get(f"/api/v1/words/{word['id']}/audio").status_code == 403
    assert client.post(
        f"/api/v1/words/{word['id']}/audio",
        headers={"Idempotency-Key": "audio-sound-student"},
        json={},
    ).status_code == 403

    practice_audio = client.get(
        f"/api/v1/practice-sessions/{session['session_id']}/items/{item['item_id']}/audio"
    )
    assert practice_audio.status_code == 200
    assert practice_audio.headers["content-type"].startswith("audio/mpeg")
    assert practice_audio.content == MP3


def test_practice_item_audio_missing_falls_back_with_404(client):
    create_word(client, {"en_word": "silent", "cn_meaning": "安静", "tags": []})
    session = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "audio-missing-session"},
        json={
            "new_words_limit": 1,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "seed": 1,
        },
    ).json()["data"]
    item = session["items"][0]
    response = client.get(
        f"/api/v1/practice-sessions/{session['session_id']}/items/{item['item_id']}/audio"
    )
    assert response.status_code == 404
    assert response.json()["code"] == "AUDIO_NOT_FOUND"


def test_synthesize_dispatches_to_selected_provider(monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    _enable_volc(monkeypatch)
    import app.services.tts as tts

    mimo_calls: list[str] = []
    volc_calls: list[str] = []

    def fake_mimo(text, settings):
        mimo_calls.append(text)
        return MP3

    def fake_volc(text, settings):
        volc_calls.append(text)
        return MP3

    _mock_providers(monkeypatch, fake_mimo, fake_volc)
    audio, voice = tts.synthesize_word_mp3("camera", provider="volc")
    assert audio == MP3
    assert voice == "BV700_V2_streaming"
    assert volc_calls == ["camera"]
    assert mimo_calls == []


def test_synthesize_falls_back_to_other_provider_on_failure(monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    _enable_volc(monkeypatch)
    import app.services.tts as tts

    def fake_mimo(text, settings):
        raise AppError(502, "TTS_PROVIDER_ERROR", "mimo down")

    def fake_volc(text, settings):
        return MP3 + b"volc"

    _mock_providers(monkeypatch, fake_mimo, fake_volc)
    audio, voice = tts.synthesize_word_mp3("camera", provider="mimo")
    assert audio == MP3 + b"volc"
    assert voice == "BV700_V2_streaming"


def test_synthesize_skips_unconfigured_provider(monkeypatch, tmp_path):
    # mimo configured, volc not; ask for volc → falls back to mimo.
    _enable_tts(monkeypatch, tmp_path)
    import app.services.tts as tts

    def fake_mimo(text, settings):
        return MP3

    def fake_volc(text, settings):
        raise AssertionError("volc should not be called when unconfigured")

    _mock_providers(monkeypatch, fake_mimo, fake_volc)
    audio, voice = tts.synthesize_word_mp3("camera", provider="volc")
    assert audio == MP3
    assert voice == "Chloe"


def test_synthesize_raises_when_neither_configured(monkeypatch):
    monkeypatch.delenv("TTS_BASE_URL", raising=False)
    monkeypatch.delenv("TTS_API_KEY", raising=False)
    monkeypatch.delenv("VOLC_TTS_API_KEY", raising=False)
    get_settings.cache_clear()
    import app.services.tts as tts

    _mock_providers(monkeypatch, lambda t, s: MP3, lambda t, s: MP3)
    try:
        tts.synthesize_word_mp3("camera")
    except AppError as exc:
        assert exc.code == "TTS_NOT_CONFIGURED"
    else:
        raise AssertionError("expected TTS_NOT_CONFIGURED")


def test_audio_providers_endpoint(client, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)  # mimo on, volc off
    response = client.get("/api/v1/words/audio/providers")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current"] == "mimo"
    by_id = {p["id"]: p for p in data["providers"]}
    assert by_id["mimo"]["enabled"] is True
    assert by_id["volc"]["enabled"] is False
    assert by_id["mimo"]["model"] == "mimo-v2.5-tts"
    assert by_id["volc"]["model"] == "doubao-seed-tts-2.0"


def test_regenerate_all_enqueues_all_non_deleted_force(client, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)
    a = create_word(client, {"en_word": "alpha", "cn_meaning": "阿尔法", "tags": []})
    b = create_word(client, {"en_word": "beta", "cn_meaning": "贝塔", "tags": []})

    recorded: dict = {}

    def fake_enqueue(word_ids, *, force, provider=None):
        recorded["ids"] = list(word_ids)
        recorded["force"] = force
        recorded["provider"] = provider
        return len(word_ids)

    import app.api.words as words_api

    monkeypatch.setattr(words_api, "enqueue_audio_generation", fake_enqueue)

    response = client.post(
        "/api/v1/words/audio/regenerate-all",
        headers={"Idempotency-Key": "regen-all-1"},
        json={"provider": "volc"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["queued"] == 2
    assert data["total"] == 2
    assert sorted(recorded["ids"]) == sorted([a["id"], b["id"]])
    assert recorded["force"] is True
    assert recorded["provider"] == "volc"


def test_audio_worker_run_job_generates_and_skips_deleted(db_session, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)
    from app.services import audio_worker
    from app.models import Word

    word = Word(
        en_word="ghost",
        normalized_en_word="ghost",
        cn_meaning="幽灵",
        is_custom=0,
        version=1,
    )
    db_session.add(word)
    db_session.flush()
    deleted = Word(
        en_word="gone",
        normalized_en_word="gone",
        cn_meaning="消失",
        is_custom=0,
        version=1,
        deleted_at="2026-01-01T00:00:00Z",
    )
    db_session.add(deleted)
    db_session.flush()

    assert audio_worker.run_audio_job(db_session, word.id, force=False) is True
    assert db_session.get(Word, word.id).audio_path is not None
    assert audio_worker.run_audio_job(db_session, deleted.id, force=False) is False


def test_audio_worker_enqueue_dedups_and_drains(monkeypatch):
    from app.services import audio_worker
    from unittest.mock import MagicMock

    processed: list[int] = []

    def fake_run(db, word_id, *, force, provider):
        processed.append(word_id)

    monkeypatch.setattr(audio_worker, "run_audio_job", fake_run)
    worker = audio_worker._AudioWorker(session_factory=lambda: MagicMock())
    added1 = worker.enqueue([1, 2, 3], force=True)
    assert added1 == 3
    added2 = worker.enqueue([2, 4], force=True)  # 2 already pending
    assert added2 == 1
    worker.wait_drained(timeout=5)
    assert sorted(processed) == [1, 2, 3, 4]


def test_import_enqueues_background_audio_generation(client, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)
    import json

    import app.api.words as words_api

    recorded: dict = {}

    def fake_enqueue(word_ids, *, force, provider=None):
        recorded["ids"] = list(word_ids)
        recorded["force"] = force
        return len(word_ids)

    monkeypatch.setattr(words_api, "enqueue_audio_generation", fake_enqueue)

    rows = [{"en_word": "ember", "cn_meaning": "余烬"}, {"en_word": "flame", "cn_meaning": "火焰"}]
    response = client.post(
        "/api/v1/words/import",
        headers={"Idempotency-Key": "import-audio-1"},
        files={"file": ("words.json", json.dumps(rows).encode(), "application/json")},
        data={"conflict_policy": "skip", "unresolved_policy": "skip", "dry_run": "false"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["created"] == 2
    assert data["audio_generation"]["queued"] == 2
    assert recorded["force"] is False
    assert len(recorded["ids"]) == 2


def test_import_skips_audio_generation_when_disabled(client, monkeypatch, tmp_path):
    _enable_tts(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)
    monkeypatch.setenv("TTS_AUTO_GENERATE_ON_IMPORT", "false")
    get_settings.cache_clear()
    import app.api.words as words_api

    def fake_enqueue(word_ids, *, force, provider):
        raise AssertionError("should not enqueue when auto-generate disabled")

    monkeypatch.setattr(words_api, "enqueue_audio_generation", fake_enqueue)

    response = client.post(
        "/api/v1/words/import",
        headers={"Idempotency-Key": "import-audio-off"},
        files={"file": ("words.txt", b"smoke\n", "text/plain")},
        data={"conflict_policy": "skip", "unresolved_policy": "skip", "dry_run": "false"},
    )
    assert response.status_code == 200, response.text
    assert "audio_generation" not in response.json()["data"]
