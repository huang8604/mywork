from __future__ import annotations

from conftest import create_word


def _generate_one(client):
    create_word(client, {"en_word": "status", "cn_meaning": "状态", "tags": []})
    response = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "status-generate"},
        json={
            "new_words_limit": 1,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _patch_status(client, session: dict, status: str) -> dict:
    response = client.patch(
        f"/api/v1/practice-sessions/{session['session_id']}",
        json={
            "title": session.get("title"),
            "note": session.get("note"),
            "status": status,
            "expected_version": session["version"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_session_has_explicit_manual_lifecycle(client):
    session = _generate_one(client)
    assert session["status"] == "not_started"
    assert session["completed_at"] is None

    listed = client.get("/api/v1/practice-sessions").json()["data"]
    assert [item["session_id"] for item in listed] == [session["session_id"]]

    session = _patch_status(client, session, "active")
    assert session["status"] == "active"
    assert client.get("/api/v1/practice-sessions?status=active").json()["meta"]["total"] == 1

    session = _patch_status(client, session, "completed")
    assert session["status"] == "completed"
    assert session["completed_at"] is not None

    session = _patch_status(client, session, "not_started")
    assert session["status"] == "not_started"
    assert session["completed_at"] is None

    session = _patch_status(client, session, "archived")
    assert session["status"] == "archived"
    assert session["archived_at"] is not None
    assert client.get("/api/v1/practice-sessions").json()["meta"]["total"] == 0
    assert client.get("/api/v1/practice-sessions?status=archived").json()["meta"]["total"] == 1


def test_round_transitions_not_started_to_active_to_completed(client):
    session = _generate_one(client)
    round_response = client.post(
        f"/api/v1/practice-sessions/{session['session_id']}/review-rounds",
        headers={"Idempotency-Key": "status-round"},
        json={"mode": "online"},
    )
    assert round_response.status_code == 201, round_response.text
    active = client.get(
        f"/api/v1/practice-sessions/{session['session_id']}"
    ).json()["data"]
    assert active["status"] == "active"

    result = client.put(
        f"/api/v1/practice-review-rounds/{round_response.json()['data']['round_id']}"
        f"/items/{session['items'][0]['item_id']}/result",
        json={"status": "known", "client_event_id": "status-result"},
    )
    assert result.status_code == 201, result.text
    completed = client.get(
        f"/api/v1/practice-sessions/{session['session_id']}"
    ).json()["data"]
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None
