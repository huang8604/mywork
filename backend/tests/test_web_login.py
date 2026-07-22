from __future__ import annotations

from conftest import create_word, seed_credential


def test_login_wrong_password_is_401_and_grants_no_session(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_REQUIRED"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_sets_cookie_and_admin_can_manage_words(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "supersecret"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "username": "admin",
        "role": "admin",
        "actor_type": "web_user",
    }
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["username"] == "admin"
    assert me.json()["data"]["role"] == "admin"
    # admin holds words:write via ALL_SCOPES
    word = create_word(client)
    assert word["en_word"]


def test_logout_clears_session(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "supersecret"}
    )
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_disabled_account_cannot_login(client, db_session, login_mode):
    from app.models.entities import utc_now_text

    cred = seed_credential(db_session, "admin", "supersecret")
    cred.disabled_at = utc_now_text()
    db_session.commit()
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "supersecret"}
    )
    assert resp.status_code == 401


def test_change_password_rotates_credential(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "supersecret"}
    )
    resp = client.post(
        "/api/v1/auth/password",
        json={"old_password": "supersecret", "new_password": "abc123"},
    )
    assert resp.status_code == 200
    client.post("/api/v1/auth/logout")
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "supersecret"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "abc123"}
        ).status_code
        == 200
    )


def test_change_password_rejects_five_characters(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "supersecret"}
    )
    response = client.post(
        "/api/v1/auth/password",
        json={"old_password": "supersecret", "new_password": "abc12"},
    )
    assert response.status_code == 422


def test_student_role_can_review_but_not_manage(client, db_session, login_mode):
    seed_credential(db_session, "stu", "studentpw1", role="student")
    client.post(
        "/api/v1/auth/login", json={"username": "stu", "password": "studentpw1"}
    )
    me = client.get("/api/v1/auth/me").json()["data"]
    assert me["role"] == "student"
    # words:write not in student scopes -> 403
    resp = client.post(
        "/api/v1/words", json={"en_word": "cat", "cn_meaning": "猫", "tags": []}
    )
    assert resp.status_code == 403
    # words:export not in student scopes -> 403
    assert client.get("/api/v1/words/export").status_code == 403
    # practice:generate IS in student scopes -> 201 (empty session, no words yet)
    gen = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "stu-generate"},
        json={
            "new_words_limit": 0,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "seed": 1,
        },
    )
    assert gen.status_code == 201


def test_unauthenticated_blocked_when_login_required(client, login_mode):
    # No cookie, WEB_LOGIN_REQUIRED=true -> no proxy fallback, just 401.
    assert client.get("/api/v1/words").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401
