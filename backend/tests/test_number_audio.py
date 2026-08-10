from __future__ import annotations

from collections.abc import Callable

from app.core.config import get_settings
from app.core.errors import AppError
from conftest import seed_credential

MP3 = b"\xff\xf3\x84\xc4" + b"number" * 20


def _audio_dir(monkeypatch, tmp_path) -> None:
    """Point TTS_AUDIO_DIR at a per-test dir and enable volc so provider='volc' is accepted."""
    monkeypatch.setenv("TTS_AUDIO_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("VOLC_TTS_BASE_URL", "https://openspeech.example.invalid")
    monkeypatch.setenv("VOLC_TTS_API_KEY", "volc-key")
    monkeypatch.setenv("VOLC_TTS_RESOURCE_ID", "seed-tts-2.0")
    monkeypatch.setenv("VOLC_TTS_VOICE", "zh_female_yingyujiaoxue_uranus_bigtts")
    get_settings.cache_clear()


def _mock_tts(monkeypatch, impl: Callable[..., bytes] | None = None) -> list[str]:
    import app.services.tts as tts

    calls: list[str] = []

    def fake(text: str, *, provider=None, settings=None) -> tuple[bytes, str]:
        calls.append(f"{text}|{provider}")
        if impl is not None:
            return impl(text), "zh_female_yingyujiaoxue_uranus_bigtts"
        return MP3, "zh_female_yingyujiaoxue_uranus_bigtts"

    monkeypatch.setattr(tts, "synthesize_word_mp3", fake)
    return calls


def test_generate_number_audio_writes_file_and_is_idempotent(monkeypatch, tmp_path):
    _audio_dir(monkeypatch, tmp_path)
    calls = _mock_tts(monkeypatch)
    from app.services.number_audio import generate_number_audio, number_audio_file

    path = generate_number_audio(1)
    assert path.is_file()
    assert path.read_bytes() == MP3
    assert calls == ["number 1|volc"]  # provider defaults to volc (豆包 preferred)

    # idempotent: second call without force does NOT re-synthesize.
    calls.clear()
    again = generate_number_audio(1)
    assert again == path
    assert calls == []

    # force regenerates.
    calls.clear()
    generate_number_audio(1, force=True)
    assert calls == ["number 1|volc"]
    assert number_audio_file(1) is not None


def test_missing_numbers_and_bounds(monkeypatch, tmp_path):
    _audio_dir(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)
    from app.services.number_audio import (
        NUMBER_MAX,
        generate_number_audio,
        missing_numbers,
        number_audio_file,
    )

    assert missing_numbers(limit=5) == [1, 2, 3, 4, 5]
    generate_number_audio(2)
    generate_number_audio(4)
    assert missing_numbers(limit=5) == [1, 3, 5]
    assert missing_numbers(limit=NUMBER_MAX)[:5] == [1, 3, 5, 6, 7]

    # out-of-range resolves to no file.
    assert number_audio_file(0) is None
    assert number_audio_file(NUMBER_MAX + 1) is None

    # generate rejects out-of-range.
    try:
        generate_number_audio(NUMBER_MAX + 1)
    except AppError as exc:
        assert exc.code == "VALIDATION_ERROR"
    else:
        raise AssertionError("expected AppError for out-of-range number")


def test_get_number_audio_404_then_200(client, monkeypatch, tmp_path):
    _audio_dir(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)
    from app.services.number_audio import generate_number_audio

    # Not generated yet → 404 (player silently skips the number).
    r0 = client.get("/api/v1/dictation/numbers/3/audio")
    assert r0.status_code == 404
    assert r0.json()["code"] == "AUDIO_NOT_FOUND"

    generate_number_audio(3)
    r1 = client.get("/api/v1/dictation/numbers/3/audio")
    assert r1.status_code == 200
    assert r1.headers["content-type"].startswith("audio/mpeg")
    assert r1.headers["content-disposition"] == "inline"
    assert r1.content == MP3


def test_get_number_audio_out_of_range_404(client, monkeypatch, tmp_path):
    _audio_dir(monkeypatch, tmp_path)
    r = client.get("/api/v1/dictation/numbers/999/audio")
    assert r.status_code == 404


def test_generate_numbers_route_defaults_volc_and_enqueues(client, monkeypatch, tmp_path):
    _audio_dir(monkeypatch, tmp_path)  # empty audio dir → all of 1..limit are missing
    import app.api.words as words_api

    recorded: dict[str, object] = {}

    def fake_enqueue(numbers, *, force, provider):
        recorded["numbers"] = list(numbers)
        recorded["force"] = force
        recorded["provider"] = provider
        return len(numbers)

    monkeypatch.setattr(words_api, "enqueue_number_generation", fake_enqueue)

    response = client.post(
        "/api/v1/words/audio/generate-numbers",
        headers={"Idempotency-Key": "numbers-gen-1"},
        json={"limit": 5},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["queued"] == 5
    assert data["total"] == 5
    # provider defaults to volc (豆包 preferred) when not specified.
    assert data["provider"] == "volc"
    assert recorded["provider"] == "volc"
    assert recorded["force"] is False
    assert recorded["numbers"] == [1, 2, 3, 4, 5]


def test_generate_numbers_route_force_all_50(client, monkeypatch, tmp_path):
    _audio_dir(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)  # generate some so "missing" alone wouldn't be 50
    from app.services.number_audio import generate_number_audio

    generate_number_audio(1)
    generate_number_audio(2)
    import app.api.words as words_api

    recorded: dict[str, object] = {}

    def fake_enqueue(numbers, *, force, provider):
        recorded["numbers"] = list(numbers)
        recorded["force"] = force
        return len(numbers)

    monkeypatch.setattr(words_api, "enqueue_number_generation", fake_enqueue)

    response = client.post(
        "/api/v1/words/audio/generate-numbers",
        headers={"Idempotency-Key": "numbers-force-1"},
        json={"force": True},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    # force → all 1..50 enqueued even though 1 and 2 already exist.
    assert data["total"] == 50
    assert recorded["numbers"] == list(range(1, 51))
    assert recorded["force"] is True


def test_worker_generates_number_clips(monkeypatch, tmp_path):
    _audio_dir(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)
    from app.services import audio_worker
    from app.services.number_audio import number_audio_file

    worker = audio_worker._AudioWorker(session_factory=lambda: None)
    added = worker.enqueue_numbers([1, 2, 3], force=False, provider="volc")
    assert added == 3
    worker.wait_drained(timeout=10)
    prog = worker.progress()
    assert prog["state"] == "idle"
    assert prog["total"] == 3
    assert prog["completed"] == 3
    assert prog["failed"] == 0
    for n in (1, 2, 3):
        assert number_audio_file(n) is not None


def test_student_can_read_number_audio_but_not_generate(
    client, db_session, login_mode, monkeypatch, tmp_path
):
    _audio_dir(monkeypatch, tmp_path)
    _mock_tts(monkeypatch)
    from app.services.number_audio import generate_number_audio

    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "stu", "stupass1", role="student")
    generate_number_audio(1)

    # student logs in → has practice:read, can fetch the clip.
    client.post("/api/v1/auth/login", json={"username": "stu", "password": "stupass1"})
    r = client.get("/api/v1/dictation/numbers/1/audio")
    assert r.status_code == 200
    assert r.content == MP3

    # student lacks words:write → cannot generate.
    gen = client.post(
        "/api/v1/words/audio/generate-numbers",
        headers={"Idempotency-Key": "numbers-stu"},
        json={"limit": 5},
    )
    assert gen.status_code == 403


def test_chinese_number_uses_persistent_default_provider(
    client, monkeypatch, tmp_path
):
    _audio_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("TTS_BASE_URL", "https://mimo.example.invalid/v1")
    monkeypatch.setenv("TTS_API_KEY", "mimo-key")
    get_settings.cache_clear()
    selected: list[str | None] = []
    import app.services.tts as tts

    def fake(text: str, *, provider=None, settings=None, language="en"):
        selected.append(provider)
        return MP3, "Chloe"

    monkeypatch.setattr(tts, "synthesize_word_mp3", fake)
    saved = client.put(
        "/api/v1/system/audio-settings",
        json={"default_provider": "mimo", "expected_version": 1},
    )
    assert saved.status_code == 200, saved.text

    response = client.get("/api/v1/dictation/numbers/1/audio?language=zh")

    assert response.status_code == 200, response.text
    assert selected == ["mimo"]
