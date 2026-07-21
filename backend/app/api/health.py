from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import Actor, get_actor
from app.core.config import get_settings
from app.core.database import get_db
from app.core.responses import envelope

router = APIRouter()


@router.get("/healthz/live", include_in_schema=False)
def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/healthz/ready", include_in_schema=False)
def ready(db: Annotated[Session, Depends(get_db)]):
    try:
        db.execute(text("SELECT 1"))
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != "0002":
            raise RuntimeError("migration is not current")
    except (SQLAlchemyError, RuntimeError):
        from fastapi.responses import JSONResponse

        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}


@router.get("/.well-known/word-review-api", include_in_schema=False)
def discovery() -> dict[str, object]:
    base = get_settings().public_base_url
    return {
        "service": "word-review",
        "stable_api_version": "v1",
        "api_base_url": f"{base}/api/v1",
        "openapi_url": f"{base}/openapi.json",
        "capabilities_url": f"{base}/api/v1/capabilities",
        "auth": ["bearer"],
    }


@router.get("/api/v1/capabilities")
def capabilities(
    request: Request,
    _actor: Annotated[Actor, Depends(get_actor)],
):
    settings = get_settings()
    return envelope(
        request,
        {
            "api_version": "v1",
            "server_time": datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "server_timezone": settings.app_timezone,
            "review_statuses": ["known", "unknown", "skipped"],
            "review_modes": ["offline", "online"],
            "max_practice_words": settings.max_practice_words,
            "max_batch_results": settings.max_batch_results,
            "max_import_bytes": settings.max_import_bytes,
            "max_import_rows": settings.max_import_rows,
            "idempotency_retention_days": settings.idempotency_retention_days,
            "features": [
                "practice_generate",
                "review_rounds",
                "batch_results",
                "review_correction",
            ],
        },
    )

