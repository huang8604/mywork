from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from app.core.auth import hash_password
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import WebCredential
from app.models.entities import utc_now_text

logger = logging.getLogger("word_memory.bootstrap")


def _read_password(settings) -> str:
    if settings.web_admin_password_file:
        return Path(settings.web_admin_password_file).read_text(encoding="utf-8").strip()
    return (settings.web_admin_password or "").strip()


def ensure_web_admin() -> None:
    """Create the initial admin login from env, idempotently.

    Runs before uvicorn in docker-entrypoint.sh. If an admin already exists this
    is a no-op; if none exists and no password is configured it only warns (login
    stays disabled until `scripts/set_web_password.py` provisions one).
    """
    settings = get_settings()
    with SessionLocal() as db:
        already = db.scalar(
            select(WebCredential.id).where(WebCredential.role == "admin").limit(1)
        )
        if already is not None:
            return
        password = _read_password(settings)
        if len(password) < 8:
            logger.warning(
                "No web admin configured (need WEB_ADMIN_PASSWORD >= 8 chars, or "
                "WEB_ADMIN_PASSWORD_FILE). Login disabled until "
                "scripts/set_web_password.py provisions one."
            )
            return
        username = settings.web_admin_username or "admin"
        now = utc_now_text()
        db.add(
            WebCredential(
                username=username,
                password_hash=hash_password(password),
                role="admin",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        logger.info("Bootstrapped web admin %r.", username)


if __name__ == "__main__":
    ensure_web_admin()
