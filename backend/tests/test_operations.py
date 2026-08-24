from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text


def _run_alembic(backend: Path, environment: dict[str, str], *args: str):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_real_alembic_upgrade_creates_current_consistent_schema(tmp_path):
    database = tmp_path / "migrated.db"
    backend = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database}",
        "API_TOKEN_PEPPER": "migration-test-pepper-at-least-16",
    }
    result = _run_alembic(backend, environment, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0010"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {
        "words",
        "review_logs",
        "practice_sessions",
        "audit_logs",
        "system_issue_notes",
        "system_audio_settings",
    } <= tables


def test_alembic_upgrades_released_revision_0006_to_current(tmp_path):
    database = tmp_path / "released-0006.db"
    backend = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database}",
        "API_TOKEN_PEPPER": "migration-test-pepper-at-least-16",
    }
    released = _run_alembic(backend, environment, "upgrade", "0006")
    assert released.returncode == 0, released.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0006"

    result = _run_alembic(backend, environment, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0010"
        assert db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_audio_settings'"
        ).fetchone() == (1,)


def test_alembic_upgrades_released_revision_0009_to_0010(tmp_path):
    database = tmp_path / "released-0009.db"
    backend = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database}",
        "API_TOKEN_PEPPER": "migration-test-pepper-at-least-16",
    }
    released = _run_alembic(backend, environment, "upgrade", "0009")
    assert released.returncode == 0, released.stderr
    result = _run_alembic(backend, environment, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0010"
        columns = {row[1] for row in db.execute("PRAGMA table_info(system_audio_settings)").fetchall()}
    assert {
        "custom_base_url",
        "custom_api_key",
    } <= columns


def test_health_readiness_requires_current_migration(client, db_session):
    assert client.get("/healthz/live").status_code == 200
    unavailable = client.get("/healthz/ready")
    assert unavailable.status_code == 503
    db_session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    db_session.execute(text("INSERT INTO alembic_version VALUES ('0010')"))
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


def test_spa_deep_link_fallback_excludes_api_and_health(client, tmp_path, monkeypatch):
    import app.main as main_module

    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main>spa shell</main>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr(main_module, "FRONTEND_DIST", dist)

    deep_link = client.get("/daily/sessions/42")
    assert deep_link.status_code == 200
    assert "spa shell" in deep_link.text
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.text == "console.log('ok')"
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/not-a-route").status_code == 404
    assert client.get("/healthz/not-a-route").status_code == 404
