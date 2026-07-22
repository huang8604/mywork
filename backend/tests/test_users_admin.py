from __future__ import annotations

from conftest import seed_credential


def _login(client, username: str, password: str) -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text


def test_admin_can_create_patch_reset_and_list_users(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    created = client.post(
        "/api/v1/users",
        json={"username": "stu", "password": "stupass1", "role": "student"},
    )
    assert created.status_code == 201
    stu = created.json()["data"]
    assert stu["role"] == "student"
    assert stu["disabled_at"] is None
    user_id = stu["id"]

    listed = client.get("/api/v1/users").json()["data"]
    assert {u["username"] for u in listed} >= {"admin", "stu"}

    # admin resets the student's password
    assert (
        client.post(
            f"/api/v1/users/{user_id}/password", json={"new_password": "newstupw1"}
        ).status_code
        == 200
    )
    # admin disables the student
    disabled = client.patch(f"/api/v1/users/{user_id}", json={"disabled": True})
    assert disabled.status_code == 200
    assert disabled.json()["data"]["disabled_at"] is not None

    # the disabled student (with the reset password) cannot log in
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "stu", "password": "newstupw1"}
        ).status_code
        == 401
    )

    # re-enable, and the reset password works
    client.patch(f"/api/v1/users/{user_id}", json={"disabled": False})
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "stu", "password": "newstupw1"}
        ).status_code
        == 200
    )


def test_student_is_forbidden_from_user_management(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "stu", "stupass1", role="student")
    _login(client, "stu", "stupass1")
    assert client.get("/api/v1/users").status_code == 403
    assert (
        client.post(
            "/api/v1/users",
            json={"username": "x", "password": "12345678", "role": "student"},
        ).status_code
        == 403
    )


def test_cannot_delete_or_disable_self(client, db_session, login_mode):
    admin = seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    assert client.delete(f"/api/v1/users/{admin.id}").status_code == 409
    assert (
        client.patch(f"/api/v1/users/{admin.id}", json={"disabled": True}).status_code
        == 409
    )


def test_cannot_remove_last_admin(client, db_session, login_mode):
    admin = seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    # only one admin; demoting/disabling/deleting must all be refused
    assert (
        client.patch(f"/api/v1/users/{admin.id}", json={"role": "student"}).status_code
        == 409
    )


def test_second_admin_can_be_removed(client, db_session, login_mode):
    a1 = seed_credential(db_session, "admin", "supersecret")
    a2 = seed_credential(db_session, "admin2", "supersecret2")
    _login(client, "admin", "supersecret")
    # two admins now; removing the non-self one is allowed
    assert client.delete(f"/api/v1/users/{a2.id}").status_code == 204
    # a1 (self) still cannot be removed (last admin + self)
    assert client.delete(f"/api/v1/users/{a1.id}").status_code == 409


def test_duplicate_username_is_409(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    resp = client.post(
        "/api/v1/users",
        json={"username": "admin", "password": "anotherpw1", "role": "student"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "DUPLICATE_USER"
