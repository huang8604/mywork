from __future__ import annotations

from conftest import create_word


def test_batch_delete_partial_success(client):
    a = create_word(client, {"en_word": "apple", "cn_meaning": "苹果", "tags": []})
    b = create_word(client, {"en_word": "banana", "cn_meaning": "香蕉", "tags": []})
    c = create_word(client, {"en_word": "cherry", "cn_meaning": "樱桃", "tags": []})

    resp = client.post(
        "/api/v1/words/batch/delete",
        json={
            "items": [
                {"id": a["id"], "expected_version": a["version"]},
                {"id": b["id"], "expected_version": b["version"] + 999},  # conflict
                {"id": 999_999, "expected_version": 1},  # missing
                {"id": c["id"], "expected_version": c["version"]},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    deleted_ids = {item["id"] for item in data["deleted"]}
    assert deleted_ids == {a["id"], c["id"]}
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["id"] == b["id"]
    assert data["conflicts"][0]["current_version"] == b["version"]
    assert len(data["missing"]) == 1
    # banana survived the conflict.
    assert client.get(f"/api/v1/words/{b['id']}").status_code == 200


def test_batch_add_tags_unions_and_bumps_version(client):
    a = create_word(
        client, {"en_word": "apple", "cn_meaning": "苹果", "tags": ["fruit"]}
    )
    b = create_word(client, {"en_word": "banana", "cn_meaning": "香蕉", "tags": []})

    resp = client.post(
        "/api/v1/words/batch/tags",
        json={
            "items": [
                {"id": a["id"], "expected_version": a["version"]},
                {"id": b["id"], "expected_version": b["version"]},
            ],
            "tags": ["fruit", "basic"],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["updated"]) == 2

    aa = client.get(f"/api/v1/words/{a['id']}").json()["data"]
    bb = client.get(f"/api/v1/words/{b['id']}").json()["data"]
    # "fruit" already on a → no duplicate; "basic" added. b gets both.
    assert set(aa["tags"]) == {"fruit", "basic"}
    assert set(bb["tags"]) == {"fruit", "basic"}
    assert aa["version"] == a["version"] + 1


def test_batch_add_tags_conflict_collected(client):
    a = create_word(client, {"en_word": "apple", "cn_meaning": "苹果", "tags": []})
    resp = client.post(
        "/api/v1/words/batch/tags",
        json={
            "items": [{"id": a["id"], "expected_version": a["version"] + 999}],
            "tags": ["basic"],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["updated"] == []
    assert len(data["conflicts"]) == 1
    # tag not applied
    assert client.get(f"/api/v1/words/{a['id']}").json()["data"]["tags"] == []


def test_batch_audio_enqueues(client, monkeypatch):
    a = create_word(client, {"en_word": "apple", "cn_meaning": "苹果", "tags": []})
    b = create_word(client, {"en_word": "banana", "cn_meaning": "香蕉", "tags": []})

    import app.api.words as words_api
    from app.core.config import get_settings

    monkeypatch.setenv("VOLC_TTS_BASE_URL", "https://openspeech.example.invalid")
    monkeypatch.setenv("VOLC_TTS_API_KEY", "volc-key")
    get_settings.cache_clear()
    captured: dict[str, object] = {}

    def fake_enqueue(ids, *, force=False, provider=None):
        captured["ids"] = list(ids)
        captured["force"] = force
        return len(ids)

    monkeypatch.setattr(words_api, "enqueue_audio_generation", fake_enqueue)
    try:
        resp = client.post(
            "/api/v1/words/batch/audio",
            json={"word_ids": [a["id"], b["id"]], "provider": "volc"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["queued"] == 2
        assert data["total"] == 2
        assert data["provider"] == "volc"
        assert captured["ids"] == [a["id"], b["id"]]
        assert captured["force"] is False
    finally:
        get_settings.cache_clear()


def test_batch_audio_not_configured(client, monkeypatch):
    monkeypatch.delenv("VOLC_TTS_API_KEY", raising=False)
    monkeypatch.delenv("VOLC_TTS_BASE_URL", raising=False)
    monkeypatch.delenv("TTS_API_KEY", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
    a = create_word(client, {"en_word": "apple", "cn_meaning": "苹果", "tags": []})
    resp = client.post("/api/v1/words/batch/audio", json={"word_ids": [a["id"]]})
    assert resp.status_code == 409
    assert resp.json()["code"] == "TTS_NOT_CONFIGURED"
    get_settings.cache_clear()


def test_batch_reset_progress_skips_missing(client):
    a = create_word(client, {"en_word": "apple", "cn_meaning": "苹果", "tags": []})
    b = create_word(client, {"en_word": "banana", "cn_meaning": "香蕉", "tags": []})
    resp = client.post(
        "/api/v1/words/batch/reset-progress",
        json={"word_ids": [a["id"], b["id"], 999_999]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["reset"] == 2  # the missing id is skipped


def test_batch_student_forbidden(client, db_session, login_mode):
    from conftest import seed_credential

    seed_credential(db_session, "stu", "stupass1", role="student")
    client.post("/api/v1/auth/login", json={"username": "stu", "password": "stupass1"})
    r = client.post(
        "/api/v1/words/batch/delete",
        json={"items": [{"id": 1, "expected_version": 1}]},
    )
    assert r.status_code == 403
