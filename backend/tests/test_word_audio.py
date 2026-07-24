from __future__ import annotations

from collections.abc import Callable

from app.core.config import get_settings
from conftest import create_word, seed_credential

MP3 = b"\xff\xf3\x84\xc4" + b"audio" * 20


def _enable_tts(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TTS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("TTS_API_KEY", "test-key")
    monkeypatch.setenv("TTS_MODEL", "mimo-v2.5-tts")
    monkeypatch.setenv("TTS_VOICE", "Chloe")
    monkeypatch.setenv("TTS_AUDIO_DIR", str(tmp_path / "audio"))
    get_settings.cache_clear()


def _mock_tts(monkeypatch, impl: Callable[..., bytes] | None = None) -> list[str]:
    import app.services.tts as tts

    calls: list[str] = []

    def fake(text: str, *, settings=None) -> bytes:
        calls.append(text)
        if impl is not None:
            return impl(text, settings=settings)
        return MP3

    monkeypatch.setattr(tts, "synthesize_word_mp3", fake)
    return calls


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
