from __future__ import annotations

import time
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas import WordCreate
from app.services import dictionary_audio
from app.services.words import create_word, word_audio_file

MP3 = b"\xff\xf3\x84\xc4" + b"dictionary-audio" * 8


def _wait_for_state(expected: str, timeout: float = 3) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = dictionary_audio._store.state(create=False)
        if state.get("state") == expected:
            return state
        time.sleep(0.01)
    raise AssertionError(f"dictionary audio did not reach {expected}")


def test_dictionary_audio_waits_five_hours_then_resumes_and_is_reused(
    db_session, monkeypatch, tmp_path
):
    monkeypatch.setenv("TTS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("TTS_API_KEY", "test-key")
    monkeypatch.setenv("TTS_AUDIO_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("DICTIONARY_AUDIO_QUOTA_WAIT_SECONDS", "18000")
    get_settings.cache_clear()
    monkeypatch.setattr(dictionary_audio, "dictionary_words", lambda: ("camera",))
    monkeypatch.setattr(dictionary_audio, "_attach_existing_words", lambda _word: None)

    def quota(*_args, **_kwargs):
        raise AppError(429, "TTS_QUOTA_EXHAUSTED", "quota")

    monkeypatch.setattr(dictionary_audio.tts_service, "synthesize_word_mp3", quota)
    worker = dictionary_audio._DictionaryAudioWorker()
    try:
        worker.start("mimo")
        waiting = _wait_for_state("waiting_quota")
        retry_at = datetime.fromisoformat(str(waiting["next_run_at"]).replace("Z", "+00:00"))
        assert 17_990 <= (retry_at - datetime.now(UTC)).total_seconds() <= 18_000

        assert worker.pause()["state"] == "paused"
        monkeypatch.setattr(
            dictionary_audio.tts_service,
            "synthesize_word_mp3",
            lambda *_args, **_kwargs: (MP3, "Chloe"),
        )
        worker.resume()
        completed = _wait_for_state("completed")
        assert completed["generated"] == 1

        word = create_word(db_session, WordCreate(en_word="camera", cn_meaning="相机"))
        assert word.audio_path and word.audio_path.startswith("dictionary/")
        assert word.audio_bytes == len(MP3)
        assert word_audio_file(word) is not None
    finally:
        worker.stop()
        get_settings.cache_clear()


def test_dictionary_audio_system_routes_expose_controls(client, monkeypatch):
    from app.api import system

    base = {
        "state": "running", "total": 10, "generated": 3, "failed": 0,
        "remaining": 7, "provider": "mimo", "model": "mimo-v2.5-tts", "voice": "Chloe",
        "last_provider": None, "last_model": None, "last_voice": None, "next_run_at": None,
        "last_error": None, "updated_at": None, "dictionary_available": True,
    }
    monkeypatch.setattr(system, "dictionary_audio_progress", lambda: base)
    monkeypatch.setattr(
        system,
        "start_dictionary_audio",
        lambda provider=None, *, force=False: {**base, "provider": provider or "mimo"},
    )
    monkeypatch.setattr(system, "pause_dictionary_audio", lambda: {**base, "state": "paused"})
    monkeypatch.setattr(system, "resume_dictionary_audio", lambda: base)

    assert client.get("/api/v1/system/dictionary-audio/progress").json()["data"]["generated"] == 3
    assert client.post("/api/v1/system/dictionary-audio/start", json={"provider": "volc"}).json()["data"]["provider"] == "volc"
    assert client.post("/api/v1/system/dictionary-audio/pause").json()["data"]["state"] == "paused"
    assert client.post("/api/v1/system/dictionary-audio/resume").json()["data"]["state"] == "running"
