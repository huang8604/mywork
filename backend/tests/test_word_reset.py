from __future__ import annotations

from conftest import create_word, seed_credential


def _review(client, word_id: int, status: str = "known", event_id: str = "ev-1"):
    return client.post(
        "/api/v1/reviews",
        json={
            "word_id": word_id,
            "status": status,
            "source": "quick_review",
            "client_event_id": event_id,
            "reviewed_at": "2026-07-01T00:00:00Z",
        },
    )


def test_reset_clears_review_history_and_zeroes_stats(client):
    word = create_word(client, {"en_word": "resetme", "cn_meaning": "重置", "tags": []})
    review = _review(client, word["id"], status="unknown")
    assert review.status_code == 201
    assert review.json()["data"]["stats"]["unknown_count"] == 1

    reset = client.post(f"/api/v1/words/{word['id']}/reset-progress")
    assert reset.status_code == 200, reset.text
    stats = reset.json()["data"]["stats"]
    assert stats["known_count"] == 0
    assert stats["unknown_count"] == 0
    assert stats["last_reviewed_at"] is None

    # The review log stream for this word is gone.
    history = client.get("/api/v1/reviews", params={"word_id": word["id"]})
    assert history.status_code == 200
    assert history.json()["data"] == []


def test_reset_makes_word_re_enter_new_pool(client):
    word = create_word(client, {"en_word": "flaky", "cn_meaning": "易脱落的", "tags": []})
    _review(client, word["id"], status="unknown", event_id="flaky-known")

    # Reviewed -> it is now error/due, NOT 新词.
    before = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "gen-before-reset"},
        json={"new_words_limit": 1, "error_words_limit": 1, "due_words_limit": 1, "custom_words_limit": 0, "fallback_unreviewed_days": 3},
    )
    assert before.status_code == 201, before.text
    item_before = before.json()["data"]["items"][0]
    assert "new" not in item_before["source_categories"]

    reset = client.post(f"/api/v1/words/{word['id']}/reset-progress")
    assert reset.status_code == 200

    # After reset the word is 新词 again and is picked by a new-only session.
    after = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "gen-after-reset"},
        json={"new_words_limit": 1, "error_words_limit": 0, "due_words_limit": 0, "custom_words_limit": 0, "fallback_unreviewed_days": 3},
    )
    assert after.status_code == 201, after.text
    item_after = after.json()["data"]["items"][0]
    assert item_after["word_id"] == word["id"]
    assert "new" in item_after["source_categories"]


def test_reset_is_idempotent_for_never_reviewed_word(client):
    word = create_word(client, {"en_word": "fresh", "cn_meaning": "新鲜", "tags": []})
    reset = client.post(f"/api/v1/words/{word['id']}/reset-progress")
    assert reset.status_code == 200
    assert reset.json()["data"]["stats"]["known_count"] == 0


def test_reset_missing_word_is_404(client):
    response = client.post("/api/v1/words/9999/reset-progress")
    assert response.status_code == 404


def test_reset_requires_words_write_scope(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "stu", "stupass1", role="student")
    # Create the word as admin (loopback admin is disabled under login_mode).
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "supersecret"})
    word = create_word(client, {"en_word": "scoped", "cn_meaning": "受限", "tags": []})
    # Switch to the student session and confirm reset is refused.
    client.post("/api/v1/auth/login", json={"username": "stu", "password": "stupass1"})
    response = client.post(f"/api/v1/words/{word['id']}/reset-progress")
    assert response.status_code == 403
