from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

from app.core.database import Base, build_engine
from conftest import create_word, seed_credential

REVISION = "0003"


def _login(client, username: str, password: str) -> None:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def _seed_alembic(db_session, revision: str = REVISION) -> None:
    """conftest builds the schema via create_all (no alembic_version table); add it."""
    db_session.connection().exec_driver_sql(
        "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
    )
    db_session.connection().exec_driver_sql(
        f"INSERT INTO alembic_version (version_num) VALUES ('{revision}')"
    )
    db_session.commit()


def _build_replacement_snapshot(
    target: Path,
    *,
    revision: str = REVISION,
    word: str = "restored-word",
    meaning: str = "还原词",
    drop_table: str | None = None,
) -> Path:
    """Create a self-contained .db that looks like one of our backups.

    Built in WAL mode then snapshotted via sqlite backup() so the main file holds
    all committed data (no dangling -wal). ``drop_table`` removes a required table
    to exercise the schema guard.
    """
    scratch = target.with_suffix(".scratch.db")
    eng = build_engine(f"sqlite:///{scratch}")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": revision},
        )
        conn.execute(
            text(
                "INSERT INTO words (en_word, normalized_en_word, phonetic, cn_meaning, "
                "example_sentence, is_custom, created_at, updated_at, version) "
                "VALUES (:en, :norm, NULL, :cn, NULL, 0, "
                "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 1)"
            ),
            {"en": word, "norm": word.lower(), "cn": meaning},
        )
        if drop_table:
            conn.execute(text(f"DROP TABLE {drop_table}"))
    eng.dispose()

    src = sqlite3.connect(str(scratch))
    dst = sqlite3.connect(str(target))
    src.backup(dst)
    dst.close()
    src.close()
    for suffix in ("", "-wal", "-shm"):
        side = scratch.with_name(scratch.name + suffix)
        if side.exists():
            side.unlink()
    return target


def _live_path(db_session) -> Path:
    row = db_session.connection().connection.driver_connection.execute(
        "PRAGMA database_list"
    ).fetchone()
    return Path(row[2])


def _read_words(path: Path) -> set[str]:
    con = sqlite3.connect(str(path))
    try:
        return {row[0] for row in con.execute("SELECT en_word FROM words")}
    finally:
        con.close()


def test_restore_replaces_live_db_and_auto_backs_up(client, db_session, tmp_path, login_mode):
    _seed_alembic(db_session)
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")
    create_word(client, {"en_word": "live-word", "cn_meaning": "现场词", "tags": []})

    live = _live_path(db_session)
    assert _read_words(live) == {"live-word"}

    backup_file = tmp_path / "replacement.db"
    _build_replacement_snapshot(backup_file, word="restored-word")

    with backup_file.open("rb") as fh:
        resp = client.post(
            "/api/v1/system/restore",
            files={"file": ("replacement.db", fh, "application/octet-stream")},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["restored"] is True
    assert body["backup_file"] == "pre-restore.db"

    # The live file was swapped to the uploaded content...
    assert _read_words(live) == {"restored-word"}
    # ...and the pre-restore snapshot captured the previous data.
    assert _read_words(live.parent / "pre-restore.db") == {"live-word"}


def test_restore_rejects_non_sqlite_file(client, db_session, login_mode):
    _seed_alembic(db_session)
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    resp = client.post(
        "/api/v1/system/restore",
        files={"file": ("junk.db", b"this is not a database", "application/octet-stream")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_BACKUP"


def test_restore_rejects_missing_required_table(client, db_session, tmp_path, login_mode):
    _seed_alembic(db_session)
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    backup_file = tmp_path / "partial.db"
    _build_replacement_snapshot(backup_file, drop_table="review_logs")
    with backup_file.open("rb") as fh:
        resp = client.post(
            "/api/v1/system/restore",
            files={"file": ("partial.db", fh, "application/octet-stream")},
        )
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_BACKUP"


def test_restore_rejects_version_mismatch(client, db_session, tmp_path, login_mode):
    _seed_alembic(db_session)
    seed_credential(db_session, "admin", "supersecret")
    _login(client, "admin", "supersecret")

    backup_file = tmp_path / "older.db"
    _build_replacement_snapshot(backup_file, revision="0001")
    with backup_file.open("rb") as fh:
        resp = client.post(
            "/api/v1/system/restore",
            files={"file": ("older.db", fh, "application/octet-stream")},
        )
    assert resp.status_code == 409
    assert resp.json()["code"] == "BACKUP_VERSION_MISMATCH"


def test_restore_is_admin_only(client, db_session, tmp_path, login_mode):
    _seed_alembic(db_session)
    seed_credential(db_session, "admin", "supersecret")
    seed_credential(db_session, "stu", "stupass1", role="student")
    _login(client, "stu", "stupass1")

    backup_file = tmp_path / "replacement.db"
    _build_replacement_snapshot(backup_file)
    with backup_file.open("rb") as fh:
        resp = client.post(
            "/api/v1/system/restore",
            files={"file": ("replacement.db", fh, "application/octet-stream")},
        )
    assert resp.status_code == 403


def test_restore_unauthenticated_is_401(client, login_mode):
    assert client.post("/api/v1/system/restore", files={"file": ("x.db", b"", "application/octet-stream")}).status_code == 401
