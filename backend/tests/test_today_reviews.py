from __future__ import annotations

from conftest import create_word, seed_credential


def _login(client, username: str, password: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text


def test_today_online_reviews_are_visible_to_the_current_student_only(
    client, db_session, login_mode
):
    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "student", "student1", role="student")
    seed_credential(db_session, "student2", "student2", role="student")
    _login(client, "admin", "supersecret")
    word = create_word(
        client,
        {"en_word": "todayword", "cn_meaning": "今日单词", "tags": []},
    )
    generated = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "today-session"},
        json={
            "new_words_limit": 0,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "word_ids": [word["id"]],
        },
    ).json()["data"]
    client.patch(
        f"/api/v1/practice-sessions/{generated['session_id']}",
        json={
            "title": "今天的练习",
            "note": None,
            "expected_version": generated["version"],
        },
    )
    client.post("/api/v1/auth/logout")

    _login(client, "student", "student1")
    round_data = client.post(
        f"/api/v1/practice-sessions/{generated['session_id']}/review-rounds",
        headers={"Idempotency-Key": "today-round"},
        json={"mode": "online"},
    ).json()["data"]
    saved = client.put(
        f"/api/v1/practice-review-rounds/{round_data['round_id']}/items/"
        f"{generated['items'][0]['item_id']}/result",
        json={"status": "known", "client_event_id": "today-result"},
    )
    assert saved.status_code == 201, saved.text

    today = client.get("/api/v1/reviews/today")
    assert today.status_code == 200, today.text
    data = today.json()["data"]
    assert data["counts"] == {"known": 1, "unknown": 0, "skipped": 0, "total": 1}
    assert data["items"][0]["en_word"] == "todayword"
    assert data["items"][0]["session_title"] == "今天的练习"
    assert data["items"][0]["status"] == "known"

    client.post("/api/v1/auth/logout")
    _login(client, "student2", "student2")
    assert client.get("/api/v1/reviews/today").json()["data"]["items"] == []

    client.post("/api/v1/auth/logout")
    _login(client, "admin", "supersecret")
    assert client.get("/api/v1/reviews/today").json()["data"]["items"] == []

    operation = client.get("/openapi.json").json()["paths"]["/api/v1/reviews/today"]["get"]
    assert operation["x-required-scopes"] == ["reviews:write", "practice:read"]
