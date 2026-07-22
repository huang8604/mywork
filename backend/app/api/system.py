from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.auth import Actor, require_web_admin
from app.core.database import get_db

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/backup")
def download_backup(
    _actor: Annotated[Actor, Depends(require_web_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    dst_fd, dst_path = tempfile.mkstemp(suffix=".db", prefix="vocab-backup-")
    os.close(dst_fd)
    try:
        source = db.connection().connection.driver_connection
        if not isinstance(source, sqlite3.Connection):
            raise RuntimeError("database backup requires a SQLite connection")
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
