from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.auth import Actor, require_web_admin
from app.core.config import get_settings

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _sqlite_path(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        return database_url[len("sqlite:///"):]
    if database_url.startswith("sqlite://"):
        return database_url[len("sqlite://"):]
    return database_url or "vocab.db"


@router.get("/backup")
def download_backup(_actor: Annotated[Actor, Depends(require_web_admin)]):
    src_path = _sqlite_path(get_settings().database_url)
    dst_fd, dst_path = tempfile.mkstemp(suffix=".db", prefix="vocab-backup-")
    os.close(dst_fd)
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)  # online snapshot; includes WAL contents
    finally:
        dst.close()
        src.close()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return FileResponse(
        dst_path,
        media_type="application/octet-stream",
        filename=f"vocab-{stamp}.db",
        background=BackgroundTask(os.remove, dst_path),
    )
