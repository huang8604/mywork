from __future__ import annotations

import os
import re
import sqlite3
import tempfile

from conftest import create_word, seed_credential
from app.core.config import get_settings


def _login(client, username: str, password: str) -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text


def test_admin_downloads_valid_sqlite(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    create_word(
        client,
        {"en_word": "backupword", "cn_meaning": "备份测试词", "tags": []},
    )

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
            # The snapshot must come from this request's injected database, not a
            # separate database resolved from process-global settings.
            assert con.execute(
                "SELECT count(*) FROM words WHERE en_word = ?", ("backupword",)
            ).fetchone()[0] == 1
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


def test_admin_issue_notes_persist_and_use_optimistic_lock(client, db_session, login_mode):
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    initial = client.get("/api/v1/system/issue-notes")
    assert initial.status_code == 200
    assert initial.json()["data"]["content"] == ""

    saved = client.put(
        "/api/v1/system/issue-notes",
        json={"content": "问题：打印标题不正确\n需求：保留错词", "expected_version": 1},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["version"] == 2
    assert client.get("/api/v1/system/issue-notes").json()["data"]["content"].startswith("问题：")

    stale = client.put(
        "/api/v1/system/issue-notes",
        json={"content": "覆盖", "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"


def test_admin_sets_persistent_default_audio_provider(
    client, db_session, login_mode, monkeypatch
):
    monkeypatch.setenv("TTS_BASE_URL", "https://mimo.example.invalid/v1")
    monkeypatch.setenv("TTS_API_KEY", "mimo-key")
    monkeypatch.setenv("VOLC_TTS_BASE_URL", "https://volc.example.invalid")
    monkeypatch.setenv("VOLC_TTS_API_KEY", "volc-key")
    get_settings.cache_clear()
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    try:
        initial = client.get("/api/v1/system/audio-settings")
        assert initial.status_code == 200, initial.text
        assert {item["id"] for item in initial.json()["data"]["providers"]} == {
            "mimo",
            "volc",
        }

        saved = client.put(
            "/api/v1/system/audio-settings",
            json={"default_provider": "volc", "expected_version": 1},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["default_provider"] == "volc"
        assert saved.json()["data"]["version"] == 2

        providers = client.get("/api/v1/words/audio/providers")
        assert providers.status_code == 200
        assert providers.json()["data"]["current"] == "volc"

        from app.api import system as system_api

        selected: list[str | None] = []

        def fake_start(provider=None):
            selected.append(provider)
            return {
                "state": "running",
                "total": 1,
                "generated": 0,
                "failed": 0,
                "remaining": 1,
                "provider": provider,
                "next_run_at": None,
                "last_error": None,
                "updated_at": None,
                "dictionary_available": True,
            }

        monkeypatch.setattr(system_api, "start_dictionary_audio", fake_start)
        started = client.post("/api/v1/system/dictionary-audio/start", json={})
        assert started.status_code == 200, started.text
        assert selected == ["volc"]

        stale = client.put(
            "/api/v1/system/audio-settings",
            json={"default_provider": "mimo", "expected_version": 1},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "VERSION_CONFLICT"
    finally:
        get_settings.cache_clear()


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
