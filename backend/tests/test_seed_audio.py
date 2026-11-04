from __future__ import annotations

import base64
from dataclasses import replace
import io
import json
import urllib.error

import pytest

from app.core.config import get_settings
from app.core.errors import AppError
from app.services import tts
from app.services.system_settings import audio_runtime_settings


MP3 = b"ID3" + b"test-audio" * 20


@pytest.mark.parametrize("language", ["en", "zh"])
def test_seed_audio_uses_create_contract_without_plan_credentials(monkeypatch, language):
    settings = replace(get_settings(), seed_audio_api_key="seed-test-secret")
    captured = {}

    def open_request(request, timeout):
        captured.update(url=request.full_url, headers=dict(request.header_items()),
                        body=json.loads(request.data), timeout=timeout)
        return io.BytesIO(json.dumps({"audio": base64.b64encode(MP3).decode()}).encode())

    monkeypatch.setattr(tts.urllib.request, "urlopen", open_request)
    result = tts.synthesize_word_mp3("相机" if language == "zh" else "camera",
                                     provider="seed_audio", settings=settings, language=language)
    assert result.audio == MP3
    assert (result.provider, result.model) == ("seed_audio", "seed-audio-1.0")
    assert captured["url"] == "https://openspeech.bytedance.com/api/v3/tts/create"
    assert captured["headers"]["X-api-key"] == "seed-test-secret"
    assert "seed-test-secret" not in captured["url"]
    assert "X-api-resource-id" not in captured["headers"]
    assert captured["body"]["model"] == "seed-audio-1.0"
    assert captured["body"]["audio_config"]["format"] == "mp3"
    assert ("普通话" if language == "zh" else "英式英语") in captured["body"]["text_prompt"]
    assert captured["timeout"] == 300


@pytest.mark.parametrize("body", [{}, {"audio": "invalid!"}, {"audio": base64.b64encode(b"not mp3").decode()}])
def test_seed_audio_rejects_missing_or_invalid_audio(monkeypatch, body):
    monkeypatch.setattr(tts.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(body).encode()))
    with pytest.raises(AppError) as error:
        tts.synthesize_word_mp3("camera", provider="seed_audio",
                                settings=replace(get_settings(), seed_audio_api_key="test"))
    assert error.value.code == "TTS_PROVIDER_ERROR"


def test_seed_permission_failure_is_explicit_and_never_falls_back(monkeypatch, caplog):
    calls = []

    def denied(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {},
                                     io.BytesIO(b'{"message":"seed-test-secret"}'))

    monkeypatch.setattr(tts.urllib.request, "urlopen", denied)
    with pytest.raises(AppError) as error:
        tts.synthesize_word_mp3("camera", provider="seed_audio", settings=replace(
            get_settings(), seed_audio_api_key="seed-test-secret", tts_base_url="https://mimo.invalid",
            tts_api_key="mimo-test-key"))
    assert error.value.code == "TTS_ACCESS_DENIED"
    assert len(calls) == 1
    assert "seed-test-secret" not in caplog.text


def test_seed_key_is_persistent_independent_and_write_only(client, db_session):
    saved = client.put("/api/v1/system/audio-settings", json={
        "expected_version": 1, "default_provider": "seed_audio",
        "seed_audio": {"api_key": "seed-private-key", "base_url": "https://seed.example.invalid/",
                       "model": "custom-seed-model", "voice": "custom-seed-speaker"},
        "volc": {"api_key": "volc-private-key"}, "mimo": {"api_key": "mimo-private-key"},
    })
    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    assert data["default_provider"] == "seed_audio"
    provider = next(p for p in data["providers"] if p["id"] == "seed_audio")
    assert provider["model"] == "custom-seed-model"
    assert provider["voice"] == "custom-seed-speaker"
    assert provider["enabled"] is True
    assert "seed-private-key" not in saved.text
    runtime = audio_runtime_settings(db_session)
    assert runtime.seed_audio_api_key == "seed-private-key"
    assert runtime.seed_audio_base_url == "https://seed.example.invalid"
    assert runtime.seed_audio_model == "custom-seed-model"
    assert runtime.seed_audio_voice == "custom-seed-speaker"
    reloaded = client.get("/api/v1/system/audio-settings").json()["data"]
    assert reloaded["default_provider"] == "seed_audio"
    assert (reloaded["model"], reloaded["voice"]) == ("custom-seed-model", "custom-seed-speaker")
    assert runtime.volc_api_key == "volc-private-key"
    assert runtime.tts_api_key == "mimo-private-key"
    kept = client.put("/api/v1/system/audio-settings", json={
        "expected_version": data["version"], "seed_audio": {"api_key": "  "},
    })
    assert kept.status_code == 200
    assert audio_runtime_settings(db_session).seed_audio_api_key == "seed-private-key"


def test_seed_saved_model_and_reference_voice_reach_provider(client, monkeypatch):
    saved = client.put("/api/v1/system/audio-settings", json={
        "expected_version": 1, "default_provider": "seed_audio",
        "seed_audio": {"api_key": "seed-test-key", "model": "custom-model", "voice": "custom-voice"},
    })
    assert saved.status_code == 200
    captured = {}

    def request(req, **kwargs):
        captured.update(json.loads(req.data))
        return io.BytesIO(json.dumps({"audio": base64.b64encode(MP3).decode()}).encode())

    monkeypatch.setattr(tts.urllib.request, "urlopen", request)
    response = client.post("/api/v1/system/audio-settings/test", json={"provider": "seed_audio"})
    assert response.status_code == 200
    assert captured["model"] == "custom-model"
    assert captured["references"] == [{"speaker": "custom-voice"}]
    assert "@音频1" in captured["text_prompt"]
    assert response.headers["x-tts-model"] == "custom-model"
    assert response.headers["x-tts-voice"] == "custom-voice"


def test_seed_test_speech_returns_actual_model_headers(client, monkeypatch):
    saved = client.put("/api/v1/system/audio-settings", json={
        "expected_version": 1, "default_provider": "seed_audio",
        "seed_audio": {"api_key": "seed-test-key"},
    })
    assert saved.status_code == 200
    monkeypatch.setattr(tts.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(
        json.dumps({"audio": base64.b64encode(MP3).decode()}).encode()))
    response = client.post("/api/v1/system/audio-settings/test", json={"provider": "seed_audio"})
    assert response.status_code == 200
    assert response.content == MP3
    assert response.headers["x-tts-provider"] == "seed_audio"
    assert response.headers["x-tts-model"] == "seed-audio-1.0"


@pytest.mark.parametrize("provider", ["mimo", "volc"])
def test_existing_providers_send_custom_model_and_voice(monkeypatch, provider):
    settings = replace(get_settings(), tts_base_url="https://mimo.invalid/v1", tts_api_key="mimo-key",
                       tts_model="custom-mimo", tts_voice="custom-mimo-voice", volc_api_key="volc-key",
                       volc_base_url="https://volc.invalid", volc_model="seed-tts-2.0-standard",
                       volc_voice="custom-volc-voice")
    captured = {}

    def request(req, **kwargs):
        captured.update(json.loads(req.data))
        encoded = base64.b64encode(MP3).decode()
        body = {"data": encoded} if provider == "volc" else {"choices": [{"message": {"audio": {"data": encoded}}}]}
        response = io.BytesIO(json.dumps(body).encode())
        response.headers = {"Content-Type": "application/json"}
        return response

    monkeypatch.setattr(tts.urllib.request, "urlopen", request)
    result = tts.synthesize_word_mp3("camera", provider=provider, settings=settings)
    assert result.provider == provider
    if provider == "volc":
        assert captured["req_params"]["model"] == "seed-tts-2.0-standard"
        assert captured["req_params"]["speaker"] == "custom-volc-voice"
    else:
        assert captured["model"] == "custom-mimo"
        assert captured["audio"]["voice"] == "custom-mimo-voice"
