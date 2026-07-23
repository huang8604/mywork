from __future__ import annotations

from sqlalchemy import func, select

from app.models import ApiClientScope, ApiClientToken, AuditLog
from conftest import seed_credential


def _login(client, username: str, password: str) -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text


def _create_client(client, **overrides) -> dict:
    payload: dict = {
        "name": "add-words",
        "skill_name": "add-words",
        "skill_version": "1.0.0",
        "scopes": ["words:read", "words:write"],
        "expires_days": 30,
    }
    payload.update(overrides)
    resp = client.post("/api/v1/api-clients", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def test_admin_creates_client_and_gets_plaintext_token_once(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    data = _create_client(client)
    assert data["token"].startswith("wm_")
    cid = data["id"]
    assert data["status"] == "active"
    assert "words:write" in data["scopes"]
    assert data["skill_name"] == "add-words"

    # listing must NOT include the plaintext token or any hash
    listing = client.get("/api/v1/api-clients")
    assert listing.status_code == 200
    item = next(x for x in listing.json()["data"] if x["id"] == cid)
    assert "token" not in item
    assert "token_hash" not in item
    for token_info in item["tokens"]:
        assert "token_hash" not in token_info
        assert "token" not in token_info
    assert "words:write" in item["scopes"]


def test_student_is_forbidden_from_api_client_management(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "stu", "stupass1", role="student")
    _login(client, "admin", "supersecret")
    cid = _create_client(client)["id"]
    client.post("/api/v1/auth/logout")
    _login(client, "stu", "stupass1")

    assert client.get("/api/v1/api-clients").status_code == 403
    assert client.delete(f"/api/v1/api-clients/{cid}/permanent").status_code == 403
    assert (
        client.post(
            "/api/v1/api-clients",
            json={
                "name": "x",
                "skill_name": "x",
                "skill_version": "1",
                "scopes": ["words:read"],
            },
        ).status_code
        == 403
    )


def test_unauthenticated_is_401(client, login_mode):
    # No cookie login -> WEB_LOGIN_REQUIRED=true -> 401 (not the trusted-proxy fallback).
    assert client.get("/api/v1/api-clients").status_code == 401


def test_rotate_returns_new_token_and_revokes_old(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    created = _create_client(client)
    cid = created["id"]
    old_token = created["token"]

    # the old token authenticates before rotation (words:read is in scopes)
    pre = client.get("/api/v1/words", headers={"Authorization": f"Bearer {old_token}"})
    assert pre.status_code == 200

    rotate = client.post(f"/api/v1/api-clients/{cid}/tokens")
    assert rotate.status_code == 200
    new_token = rotate.json()["data"]["token"]
    assert new_token.startswith("wm_")
    assert new_token != old_token

    # the old token no longer authenticates
    old_resp = client.get(
        "/api/v1/words", headers={"Authorization": f"Bearer {old_token}"}
    )
    assert old_resp.status_code == 401

    # the new token works
    new_resp = client.get(
        "/api/v1/words", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert new_resp.status_code == 200

    # the listed old token's state is "revoked"; the new one is "active"
    listing = client.get("/api/v1/api-clients").json()["data"]
    item = next(x for x in listing if x["id"] == cid)
    states = {t["prefix"]: t["state"] for t in item["tokens"]}
    assert states[old_token[:16]] == "revoked"
    assert states[new_token[:16]] == "active"


def test_patch_status_disabled_reflects_in_list(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    cid = _create_client(client)["id"]

    patched = client.patch(f"/api/v1/api-clients/{cid}", json={"status": "disabled"})
    assert patched.status_code == 200
    assert patched.json()["data"]["status"] == "disabled"

    item = next(
        x for x in client.get("/api/v1/api-clients").json()["data"] if x["id"] == cid
    )
    assert item["status"] == "disabled"

    # a disabled client's token can no longer authenticate even if not revoked
    # (need to create one to test the disabled-client branch directly)
    cid2_data = _create_client(client, name="other", scopes=["words:read"])
    live_token = cid2_data["token"]
    assert (
        client.get("/api/v1/words", headers={"Authorization": f"Bearer {live_token}"})
    ).status_code == 200
    client.patch(f"/api/v1/api-clients/{cid2_data['id']}", json={"status": "disabled"})
    assert (
        client.get("/api/v1/words", headers={"Authorization": f"Bearer {live_token}"})
    ).status_code == 401


def test_patch_updates_scopes_and_description(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    cid = _create_client(client)["id"]
    patched = client.patch(
        f"/api/v1/api-clients/{cid}",
        json={"scopes": ["reviews:read"], "description": "rotated scopes"},
    )
    assert patched.status_code == 200
    data = patched.json()["data"]
    assert data["scopes"] == ["reviews:read"]
    assert data["description"] == "rotated scopes"


def test_delete_disables_client(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    cid = _create_client(client)["id"]
    deleted = client.delete(f"/api/v1/api-clients/{cid}")
    assert deleted.status_code == 204

    item = next(
        x for x in client.get("/api/v1/api-clients").json()["data"] if x["id"] == cid
    )
    assert item["status"] == "disabled"


def test_permanent_delete_removes_client_and_invalidates_tokens(
    client, db_session, login_mode
):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    created = _create_client(client, name="delete-me", scopes=["words:read"])
    cid = created["id"]
    raw_token = created["token"]
    deleted = client.delete(f"/api/v1/api-clients/{cid}/permanent")
    assert deleted.status_code == 204

    assert db_session.scalar(
        select(func.count()).select_from(ApiClientToken).where(ApiClientToken.api_client_id == cid)
    ) == 0
    assert db_session.scalar(
        select(func.count()).select_from(ApiClientScope).where(ApiClientScope.api_client_id == cid)
    ) == 0
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "api_client.delete").order_by(AuditLog.id.desc())
    )
    assert audit is not None
    assert audit.target_id == str(cid)

    listing = client.get("/api/v1/api-clients").json()["data"]
    assert all(item["id"] != cid for item in listing)
    denied = client.get(
        "/api/v1/words", headers={"Authorization": f"Bearer {raw_token}"}
    )
    assert denied.status_code == 401


def test_revoke_token_marks_state_revoked(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    cid = _create_client(client)["id"]
    listed = client.get("/api/v1/api-clients").json()["data"]
    item = next(x for x in listed if x["id"] == cid)
    active_token = next(t for t in item["tokens"] if t["state"] == "active")
    token_id = active_token["id"]

    revoked = client.delete(f"/api/v1/api-clients/{cid}/tokens/{token_id}")
    assert revoked.status_code == 204

    listed2 = client.get("/api/v1/api-clients").json()["data"]
    item2 = next(x for x in listed2 if x["id"] == cid)
    token_after = next(t for t in item2["tokens"] if t["id"] == token_id)
    assert token_after["state"] == "revoked"


def test_revoke_unknown_token_is_404(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    cid = _create_client(client)["id"]
    resp = client.delete(f"/api/v1/api-clients/{cid}/tokens/999999")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_unknown_scope_in_create_is_422(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    resp = client.post(
        "/api/v1/api-clients",
        json={
            "name": "x",
            "skill_name": "x",
            "skill_version": "1",
            "scopes": ["words:read", "bogus:scope"],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_unknown_scope_in_update_is_422(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    cid = _create_client(client)["id"]
    resp = client.patch(
        f"/api/v1/api-clients/{cid}", json={"scopes": ["bogus:scope"]}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_update_requires_at_least_one_field(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    cid = _create_client(client)["id"]
    # All-None payload → Pydantic model_validator raises → RequestValidationError → 422
    resp = client.patch(f"/api/v1/api-clients/{cid}", json={})
    assert resp.status_code == 422


def test_unknown_client_404(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    assert client.patch("/api/v1/api-clients/9999", json={"status": "disabled"}).status_code == 404
    assert client.delete("/api/v1/api-clients/9999").status_code == 404
    assert client.delete("/api/v1/api-clients/9999/permanent").status_code == 404
    assert client.post("/api/v1/api-clients/9999/tokens").status_code == 404


def test_openapi_skips_security_for_api_clients(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    schema = client.get("/openapi.json").json()
    for path, item in schema["paths"].items():
        if not path.startswith("/api/v1/api-clients"):
            continue
        for method, op in item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            # The custom_openapi loop must NOT have added BearerAuth/TrustedProxyUser
            # security or x-required-scopes for these role-gated routes (they behave
            # like /api/v1/users). FastAPI still auto-attaches HTTPBearer from the
            # dependency tree — that's expected and harmless.
            for sec in op.get("security", []):
                assert "TrustedProxyUser" not in sec, (path, method, sec)
                assert "BearerAuth" not in sec, (path, method, sec)
            assert op.get("x-required-scopes", []) == [], (path, method)
