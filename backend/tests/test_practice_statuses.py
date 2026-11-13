from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models import PracticeSession
from app.services.domain import utc_text
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

    listed = client.get("/api/v1/practice-sessions?online_review=true").json()
    assert listed["meta"]["total"] == 1
    again = client.post(
        f"/api/v1/practice-sessions/{session['session_id']}/review-rounds",
        headers={"Idempotency-Key": "status-round-again"},
        json={"mode": "online"},
    )
    assert again.status_code == 201, again.text
    assert again.json()["data"]["round_id"] != round_response.json()["data"]["round_id"]
    result = client.put(
        f"/api/v1/practice-review-rounds/{again.json()['data']['round_id']}"
        f"/items/{session['items'][0]['item_id']}/result",
        json={"status": "unknown", "client_event_id": "status-result-again"},
    )
    assert result.status_code == 201, result.text
    latest = client.get(f"/api/v1/practice-sessions/{session['session_id']}").json()["data"]
    assert latest["status"] == "completed"
    assert latest["completed_at"] > completed["completed_at"]


@pytest.mark.parametrize(("status", "age_seconds", "visible"), [
    ("not_started", None, False),
    ("active", None, True),
    ("completed", None, False),
    ("completed", 86399, True),
    ("completed", 86400, False),
    ("completed", 86401, False),
    ("archived", 1, False),
])
def test_online_review_visibility(client, db_session, monkeypatch, status, age_seconds, visible):
    from app.api import practice

    session = _generate_one(client)
    now = datetime.now(UTC)
    monkeypatch.setattr(practice, "datetime", SimpleNamespace(now=lambda tz: now))
    stored = db_session.get(PracticeSession, session["session_id"])
    stored.status = status
    stored.completed_at = utc_text(now - timedelta(seconds=age_seconds)) if age_seconds is not None else None
    db_session.commit()

    response = client.get("/api/v1/practice-sessions?online_review=true&size=1")
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["total"] == int(visible)
    assert len(response.json()["data"]) == int(visible)
    # The management list still allows completed worksheets of any age.
    assert client.get(f"/api/v1/practice-sessions?status={status}").json()["meta"]["total"] == 1
