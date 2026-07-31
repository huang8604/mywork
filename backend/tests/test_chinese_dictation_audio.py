from __future__ import annotations

from app.core.config import get_settings
from conftest import create_word

MP3 = b"\xff\xf3\x84\xc4" + b"chinese" * 20


def _configure(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_AUDIO_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("VOLC_TTS_BASE_URL", "https://openspeech.example.invalid")
    monkeypatch.setenv("VOLC_TTS_API_KEY", "volc-key")
    monkeypatch.setenv("VOLC_TTS_RESOURCE_ID", "seed-tts-2.0")
    monkeypatch.setenv("VOLC_TTS_VOICE", "zh_female_yingyujiaoxue_uranus_bigtts")
    get_settings.cache_clear()


def _mock_tts(monkeypatch):
    from app.services import tts

    calls: list[tuple[str, str]] = []

    def fake(text: str, *, provider=None, settings=None, language="en"):
        calls.append((text, language))
        return MP3, "zh_female_yingyujiaoxue_uranus_bigtts"

    monkeypatch.setattr(tts, "synthesize_word_mp3", fake)
    return calls


def _session(client):
    word = create_word(
        client, {"en_word": "bright", "cn_meaning": "明亮的；聪明的", "tags": []}
    )
    response = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "zh-dictation-session"},
        json={"word_ids": [word["id"]]},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_chinese_item_audio_is_generated_and_cached_on_first_play(
    client, monkeypatch, tmp_path
):
    _configure(monkeypatch, tmp_path)
    calls = _mock_tts(monkeypatch)
    session = _session(client)
    item = session["items"][0]
    url = (
        f"/api/v1/practice-sessions/{session['session_id']}/items/{item['item_id']}"
        "/audio?language=zh"
    )

    first = client.get(url)
    second = client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content == MP3
    assert calls == [("明亮的；聪明的", "zh")]


def test_chinese_number_one_to_fifty_is_generated_on_demand(client, monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    calls = _mock_tts(monkeypatch)

    first = client.get("/api/v1/dictation/numbers/1/audio?language=zh")
    fiftieth = client.get("/api/v1/dictation/numbers/50/audio?language=zh")
    assert first.status_code == fiftieth.status_code == 200
    assert calls == [("第一题", "zh"), ("第五十题", "zh")]
    assert client.get("/api/v1/dictation/numbers/51/audio?language=zh").status_code == 404
