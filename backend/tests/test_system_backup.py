from __future__ import annotations

import os
import re
import sqlite3
import tempfile

from conftest import seed_credential


def _login(client, username: str, password: str) -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text


def test_admin_downloads_valid_sqlite(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    resp = client.get("/api/v1/system/backup")
    assert resp.status_code == 200, resp.text
    cd = resp.headers["content-disposition"]
    assert re.fullmatch(r'attachment; filename="vocab-\d{14}\.db"', cd), cd

    # body is a valid SQLite file: write to a temp path and inspect it.
    fd, path = tempfile.mkstemp(suffix=".db")
    try:
        os.write(fd, resp.content)
        os.close(fd)
        con = sqlite3.connect(path)
        try:
            assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            # words table exists and is queryable post-alembic (test DB is migrated).
            assert con.execute("SELECT count(*) FROM words").fetchone()[0] >= 0
        finally:
            con.close()
    finally:
        os.remove(path)


def test_student_forbidden(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "stu", "stupass1", role="student")
    _login(client, "stu", "stupass1")

    assert client.get("/api/v1/system/backup").status_code == 403


def test_unauthenticated_is_401(client, login_mode):
    # No cookie login -> WEB_LOGIN_REQUIRED=true -> 401 (not the trusted-proxy fallback).
    assert client.get("/api/v1/system/backup").status_code == 401


def test_openapi_skips_security_for_system(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    schema = client.get("/openapi.json").json()
    for path, item in schema["paths"].items():
        if not path.startswith("/api/v1/system"):
            continue
        for method, op in item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            # The custom_openapi loop must NOT have added BearerAuth/TrustedProxyUser
            # security or x-required-scopes for these role-gated routes.
            for sec in op.get("security", []):
                assert "TrustedProxyUser" not in sec, (path, method, sec)
                assert "BearerAuth" not in sec, (path, method, sec)
            assert op.get("x-required-scopes", []) == [], (path, method)
