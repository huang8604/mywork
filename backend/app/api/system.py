from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.audit import add_audit
from app.core.auth import Actor, require_web_admin
from app.core.database import engine, get_db
from app.core.errors import AppError
from app.core.responses import envelope

router = APIRouter(prefix="/api/v1/system", tags=["system"])

PRE_RESTORE_FILENAME = "pre-restore.db"
MAX_RESTORE_BYTES = 50 * 1024 * 1024
REQUIRED_TABLES = {
    "words",
    "word_stats",
    "review_logs",
    "practice_sessions",
    "alembic_version",
}


def _driver_connection(db: Session) -> sqlite3.Connection:
    raw = db.connection().connection.driver_connection
    if not isinstance(raw, sqlite3.Connection):
        raise AppError(500, "INVALID_STATE", "数据库备份/还原需要 SQLite 连接")
    return raw


def _live_db_path(db: Session) -> Path:
    """Resolve the on-disk path of the request's SQLite file via its connection."""
    row = _driver_connection(db).execute("PRAGMA database_list").fetchone()
    file_path = row[2] if row else ""
    if not file_path or file_path == ":memory:":
        raise AppError(400, "INVALID_STATE", "当前数据库不是文件型 SQLite,无法备份/还原")
    return Path(file_path)


def _current_revision(db: Session) -> str:
    row = _driver_connection(db).execute("SELECT version_num FROM alembic_version").fetchone()
    return (row[0] if row else "") or ""


def _validate_backup_db(path: Path, current_revision: str) -> None:
    """Open the candidate file read-only and confirm it is one of our databases.

    The schema check guards against restoring an arbitrary / unrelated SQLite
    file over the live library; the alembic revision match guards against
    restoring a backup whose schema the running code cannot speak to.
    """
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise AppError(422, "INVALID_BACKUP", "无法读取备份文件", [{"reason": str(exc)}])
    try:
        try:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError as exc:
            raise AppError(422, "INVALID_BACKUP", "备份文件不是有效的 SQLite 数据库", [{"reason": str(exc)}])
        missing = REQUIRED_TABLES - tables
        if missing:
            raise AppError(
                422,
                "INVALID_BACKUP",
                "备份文件结构不符合本系统",
                [{"missing": sorted(missing)}],
            )
        revision_row = con.execute("SELECT version_num FROM alembic_version").fetchone()
        backup_revision = (revision_row[0] if revision_row else "") or ""
        if backup_revision != current_revision:
            raise AppError(
                409,
                "BACKUP_VERSION_MISMATCH",
                "备份的数据库版本与当前不一致,无法直接还原",
                [{"backup_version": backup_revision, "current_version": current_revision}],
            )
    finally:
        con.close()


@router.get("/backup")
def download_backup(
    _actor: Annotated[Actor, Depends(require_web_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    dst_fd, dst_path = tempfile.mkstemp(suffix=".db", prefix="vocab-backup-")
    os.close(dst_fd)
    try:
        source = _driver_connection(db)
        dst = sqlite3.connect(dst_path)
        try:
            source.backup(dst)  # online snapshot; includes WAL and in-memory databases
        finally:
            dst.close()
    except Exception:
        os.remove(dst_path)
        raise
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return FileResponse(
        dst_path,
        media_type="application/octet-stream",
        filename=f"vocab-{stamp}.db",
        background=BackgroundTask(os.remove, dst_path),
    )


@router.post("/restore")
async def restore_database(
    request: Request,
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    """Restore the whole library from an uploaded SQLite snapshot.

    Pipeline: read+size-check -> validate schema & alembic revision -> auto-backup
    the live DB to ``pre-restore.db`` (consistent snapshot via the live
    connection) -> audit -> dispose the engine pool so nothing pins the old file
    -> drop stale -wal/-shm -> atomically replace the live file. Any failure
    before the swap leaves the live DB untouched.
    """
    upload_bytes = await file.read()
    if not upload_bytes:
        raise AppError(422, "INVALID_BACKUP", "上传文件为空")
    if len(upload_bytes) > MAX_RESTORE_BYTES:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "备份文件过大")

    fd, tmp_path_str = tempfile.mkstemp(suffix=".db", prefix="vocab-restore-")
    tmp_path = Path(tmp_path_str)
    backup_bytes = 0
    try:
        os.write(fd, upload_bytes)
        os.close(fd)

        current_revision = _current_revision(db)
        _validate_backup_db(tmp_path, current_revision)

        live_path = _live_db_path(db)
        pre_restore = live_path.parent / PRE_RESTORE_FILENAME

        # 1. Auto-backup the live DB from the request's own connection.
        pre_restore_dst = sqlite3.connect(str(pre_restore))
        try:
            _driver_connection(db).backup(pre_restore_dst)
        finally:
            pre_restore_dst.close()
        backup_bytes = pre_restore.stat().st_size

        # 2. Record the restore in the OLD database (lands in the pre-restore
        #    snapshot; the restored DB is left pristine).
        add_audit(
            db,
            request_id=request.state.request_id,
            actor=actor,
            action="system.restore",
            outcome="success",
            http_status=200,
            target_type="database",
            target_id=None,
        )
        db.commit()

        # 3. Dispose the pool, drop stale WAL sidecars, then swap the file.
        engine.dispose()
        for suffix in ("-wal", "-shm"):
            side = live_path.with_name(live_path.name + suffix)
            if side.exists():
                side.unlink()
        os.replace(tmp_path, live_path)
        tmp_path = None  # consumed by os.replace
    finally:
        if tmp_path is not None and tmp_path.exists():
            os.remove(tmp_path)

    return envelope(
        request,
        {
            "restored": True,
            "backup_file": PRE_RESTORE_FILENAME,
            "backup_bytes": backup_bytes,
        },
    )


@router.get("/pre-restore-backup")
def download_pre_restore_backup(
    _request: Request,
    _actor: Annotated[Actor, Depends(require_web_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    """Download the single auto-backup captured right before the last restore."""
    pre_restore = _live_db_path(db).parent / PRE_RESTORE_FILENAME
    if not pre_restore.is_file():
        raise AppError(404, "NOT_FOUND", "尚未生成还原前的自动备份")
    return FileResponse(
        str(pre_restore),
        media_type="application/octet-stream",
        filename=PRE_RESTORE_FILENAME,
    )
