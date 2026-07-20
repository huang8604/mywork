from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text


def test_real_alembic_upgrade_creates_current_consistent_schema(tmp_path):
    database = tmp_path / "migrated.db"
    backend = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database}",
        "API_TOKEN_PEPPER": "migration-test-pepper-at-least-16",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0001"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {"words", "review_logs", "practice_sessions", "audit_logs"} <= tables


def test_health_readiness_requires_current_migration(client, db_session):
    assert client.get("/healthz/live").status_code == 200
    unavailable = client.get("/healthz/ready")
    assert unavailable.status_code == 503
    db_session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    db_session.execute(text("INSERT INTO alembic_version VALUES ('0001')"))
    db_session.commit()
    ready = client.get("/healthz/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_wrong_origin_is_rejected_before_write(client):
    response = client.post(
        "/api/v1/words",
        headers={"Origin": "https://attacker.example"},
        json={"en_word": "blocked", "cn_meaning": "拦截", "tags": []},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ORIGIN"

