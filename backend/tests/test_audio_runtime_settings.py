from __future__ import annotations

from app.core.config import get_settings
from app.services.system_settings import audio_runtime_settings
from conftest import seed_credential


def _login(client, username: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def _put(client, version: int, **overrides):
    payload: dict[str, object] = {"default_provider": "mimo", "expected_version": version}
    payload.update(overrides)
    return client.put("/api/v1/system/audio-settings", json=payload)


def test_put_persists_volc_tuning_and_import_toggle(client, db_session, login_mode, monkeypatch):
    monkeypatch.setenv("TTS_BASE_URL", "https://mimo.example.invalid/v1")
    monkeypatch.setenv("TTS_API_KEY", "mimo-key")
    get_settings.cache_clear()
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    try:
        first = _put(
            client,
            1,
            volc={
                "resource_id": "seed-tts-2.0",
                "speech_rate": -20,
                "loudness_rate": 30,
                "silence_ms": 800,
            },
            auto_generate_on_import=False,
        )
        assert first.status_code == 200, first.text
        data = first.json()["data"]
        assert data["auto_generate_on_import"] is False
        assert data["volc_tuning"] == {
            "resource_id": "seed-tts-2.0",
            "speech_rate": -20,
            "loudness_rate": 30,
            "silence_ms": 800,
        }
        assert audio_runtime_settings(db_session).tts_auto_generate_on_import is False
        assert audio_runtime_settings(db_session).volc_speech_rate == -20
    finally:
        get_settings.cache_clear()


def test_volc_tuning_null_clears_override_back_to_env(client, db_session, login_mode, monkeypatch):
    monkeypatch.setenv("TTS_BASE_URL", "https://mimo.example.invalid/v1")
    monkeypatch.setenv("TTS_API_KEY", "mimo-key")
    get_settings.cache_clear()
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    try:
        assert _put(client, 1, volc={"speech_rate": -20}, auto_generate_on_import=True).status_code == 200
        cleared = _put(client, 2, volc={"speech_rate": None})
        assert cleared.status_code == 200, cleared.text
        settings = audio_runtime_settings(db_session)
        assert settings.volc_speech_rate == -10  # env default
        assert settings.tts_auto_generate_on_import is True  # untouched when omitted
    finally:
        get_settings.cache_clear()


def test_volc_tuning_bounds_rejected(client, db_session, login_mode, monkeypatch):
    monkeypatch.setenv("TTS_BASE_URL", "https://mimo.example.invalid/v1")
    monkeypatch.setenv("TTS_API_KEY", "mimo-key")
    get_settings.cache_clear()
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    try:
        assert _put(client, 1, volc={"speech_rate": 500}).status_code == 422
        assert _put(client, 1, volc={"silence_ms": -1}).status_code == 422
        assert _put(client, 1, volc={"resource_id": "x" * 65}).status_code == 422
    finally:
        get_settings.cache_clear()


def test_get_reports_effective_tuning(client, db_session, login_mode, monkeypatch):
    monkeypatch.setenv("TTS_BASE_URL", "https://mimo.example.invalid/v1")
    monkeypatch.setenv("TTS_API_KEY", "mimo-key")
    get_settings.cache_clear()
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    try:
        response = client.get("/api/v1/system/audio-settings")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["auto_generate_on_import"] is True  # env default
        assert data["volc_tuning"]["resource_id"] == "seed-tts-2.0"
        assert data["volc_tuning"]["silence_ms"] == 500
    finally:
        get_settings.cache_clear()
