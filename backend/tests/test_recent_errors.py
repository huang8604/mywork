from __future__ import annotations

from app.models import ReviewLog
from conftest import create_word, seed_credential


def _login(client, username: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def _seed_review(db_session, word_id: int, actor_id: str, reviewed_at: str, event: str, status: str = "unknown") -> None:
    db_session.add(
        ReviewLog(
            word_id=word_id,
            status=status,
            source="quick_review",
            actor_type="web_user",
            actor_id=actor_id,
            client_event_id=event,
            reviewed_at=reviewed_at,
        )
    )
    db_session.commit()


def test_recent_errors_isolated_deduped_ordered_and_capped(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "student", "student1", role="student")
    seed_credential(db_session, "student2", "student2", role="student")
    _login(client, "admin", "supersecret")
    words = [
        create_word(client, {"en_word": f"errword{chr(ord('a') + index)}", "cn_meaning": f"错词{index}", "tags": []})
        for index in range(6)
    ]
    client.post("/api/v1/auth/logout")

    _seed_review(db_session, words[0]["id"], "student", "2026-08-20T01:00:00Z", "s-1a")
    _seed_review(db_session, words[0]["id"], "student", "2026-08-21T01:00:00Z", "s-1b")  # same word, newer wins
    _seed_review(db_session, words[1]["id"], "student", "2026-08-19T01:00:00Z", "s-2")
    _seed_review(db_session, words[1]["id"], "student", "2026-08-22T01:00:00Z", "s-2-known", status="known")  # not an error
    for index in range(2, 6):
        _seed_review(db_session, words[index]["id"], "student", f"2026-08-1{index}T00:00:00Z", f"s-loop-{index}")

    _login(client, "student", "student1")
    data = client.get("/api/v1/stats/my-recent-errors").json()["data"]
    ids = [item["word_id"] for item in data["items"]]
    # student unknowns by reviewed_at desc: w0(08-21) > w1(08-19) > w5(08-15) > w4(08-14) > w3(08-13); w2(08-12) drops at the cap.
    assert ids == [words[0]["id"], words[1]["id"], words[5]["id"], words[4]["id"], words[3]["id"]]
    assert len(set(ids)) == 5  # deduplicated
    first = data["items"][0]
    assert first["en_word"] == "errworda"
    assert first["cn_meaning"] == "错词0"
    assert first["reviewed_at"] == "2026-08-21T01:00:00Z"
    assert words[2]["id"] not in ids  # capped

    client.post("/api/v1/auth/logout")
    _login(client, "student2", "student2")
    assert client.get("/api/v1/stats/my-recent-errors").json()["data"]["items"] == []

    client.post("/api/v1/auth/logout")
    _login(client, "admin", "supersecret")
    admin_items = client.get("/api/v1/stats/my-recent-errors").json()["data"]["items"]
    expected_admin = {word["id"] for word in words} - {words[2]["id"]}
    assert {item["word_id"] for item in admin_items} == expected_admin

    operation = client.get("/openapi.json").json()["paths"]["/api/v1/stats/my-recent-errors"]["get"]
    assert operation["x-required-scopes"] == ["practice:read", "reviews:write"]
