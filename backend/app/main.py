from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.utils import get_openapi
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy import select

from app.api.api_clients import router as api_clients_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.practice import router as practice_router
from app.api.reviews import router as reviews_router
from app.api.system import router as system_router
from app.api.users import router as users_router
from app.api.words import router as words_router
from app.core.auth import ALL_SCOPES
from app.core.config import get_settings
from app.core.database import SessionLocal
import app.models  # noqa: F401
from app.models import AuditLog
from app.services.domain import canonical_json

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="Word Memory Assistant API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts))
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "If-Match",
        "X-Request-ID",
    ],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_bytes(),
    session_cookie="wm_session",
    max_age=settings.session_max_age,
    https_only=settings.public_base_url.startswith("https"),
    same_site="lax",
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    started = time.perf_counter()
    candidate = request.headers.get("X-Request-ID")
    try:
        request_id = str(uuid.UUID(candidate)) if candidate else str(uuid.uuid4())
    except ValueError:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != settings.public_base_url:
            return JSONResponse(
                status_code=403,
                content={
                    "code": "FORBIDDEN_ORIGIN",
                    "message": "请求来源不被允许",
                    "details": [],
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
    response = await call_next(request)
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    logging.getLogger("word_memory.request").info(
        "request_id=%s method=%s route=%s status=%s latency_ms=%s actor_type=%s",
        request_id,
        request.method,
        getattr(request.scope.get("route"), "path", request.url.path),
        response.status_code,
        latency_ms,
        getattr(getattr(request.state, "actor", None), "actor_type", "anonymous"),
    )
    if response.status_code >= 400 and request.url.path.startswith("/api/v1"):
        _audit_failed_request(request, response.status_code, latency_ms)
    elif request.url.path.startswith("/api/v1"):
        _finalize_success_audit(request, latency_ms)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; frame-ancestors 'none'"
    )
    return response


def _audit_failed_request(request: Request, status_code: int, latency_ms: int) -> None:
    db = getattr(request.state, "audit_db", None)
    owns_db = db is None
    if owns_db:
        db = SessionLocal()
    actor = getattr(request.state, "actor", None)
    route = request.scope.get("route")
    action = f"{request.method} {getattr(route, 'path', request.url.path)}"
    try:
        db.rollback()
        db.add(
            AuditLog(
                request_id=request.state.request_id,
                actor_type=getattr(actor, "actor_type", "anonymous"),
                actor_id=getattr(actor, "actor_id", None),
                api_client_id=getattr(actor, "api_client_id", None),
                skill_name=getattr(actor, "skill_name", None),
                skill_version=getattr(actor, "skill_version", None),
                scopes_json=(
                    canonical_json(sorted(actor.scopes)) if actor is not None else None
                ),
                action=action,
                outcome="denied" if status_code in {401, 403, 429} else "failed",
                http_status=status_code,
                error_code=None,
                latency_ms=latency_ms,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        if owns_db:
            db.close()


def _finalize_success_audit(request: Request, latency_ms: int) -> None:
    db = getattr(request.state, "audit_db", None)
    if db is None:
        return
    try:
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.request_id == request.state.request_id)
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        if audit is not None:
            audit.latency_ms = latency_ms
            db.commit()
    except Exception:
        db.rollback()


@app.exception_handler(__import__("app.core.errors", fromlist=["AppError"]).AppError)
async def app_error_handler(request: Request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
            "request_id": request.state.request_id,
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    details = [
        {
            "path": list(error["loc"]),
            "reason": error["msg"],
            **({"value": error["input"]} if _safe_input(error.get("input")) else {}),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "请求参数校验失败",
            "details": details,
            "request_id": request.state.request_id,
        },
    )


def _safe_input(value: object) -> bool:
    return isinstance(value, (str, int, float, bool, type(None))) and len(str(value)) <= 200


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, _exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={
            "code": "INVALID_STATE",
            "message": "数据约束冲突",
            "details": [],
            "request_id": request.state.request_id,
        },
    )


@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError):
    original = exc.orig
    busy = isinstance(original, sqlite3.OperationalError) and (
        "locked" in str(original).lower() or "busy" in str(original).lower()
    )
    status_code = 503 if busy else 500
    code = "SERVICE_BUSY" if busy else "INTERNAL_ERROR"
    headers = {"Retry-After": "1"} if busy else None
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": "数据库繁忙，请稍后重试" if busy else "服务器内部错误",
            "details": [],
            "request_id": request.state.request_id,
        },
        headers=headers,
    )


app.include_router(health_router)
app.include_router(words_router)
app.include_router(reviews_router)
app.include_router(practice_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(api_clients_router)
app.include_router(system_router)

REQUIRED_SCOPES: dict[tuple[str, str], list[str]] = {
    ("POST", "/api/v1/words"): ["words:write"],
    ("POST", "/api/v1/words/enrich"): ["words:write"],
    ("GET", "/api/v1/words"): ["words:read"],
    ("GET", "/api/v1/words/export"): ["words:export"],
    ("POST", "/api/v1/words/import"): ["words:write"],
    ("GET", "/api/v1/words/{word_id}"): ["words:read"],
    ("PUT", "/api/v1/words/{word_id}"): ["words:write"],
    ("DELETE", "/api/v1/words/{word_id}"): ["words:write"],
    ("POST", "/api/v1/words/{word_id}/restore"): ["words:write"],
    ("POST", "/api/v1/reviews"): ["reviews:write", "words:read"],
    ("PATCH", "/api/v1/reviews/{review_id}"): ["reviews:write"],
    ("GET", "/api/v1/reviews"): ["reviews:read"],
    ("GET", "/api/v1/stats/summary"): ["reviews:read"],
    ("GET", "/api/v1/words/{word_id}/stats"): ["words:read", "reviews:read"],
    ("POST", "/api/v1/daily-table/generate"): ["practice:generate"],
    ("GET", "/api/v1/practice-sessions"): ["practice:read"],
    ("GET", "/api/v1/practice-sessions/{session_id}"): ["practice:read"],
    ("PATCH", "/api/v1/practice-sessions/{session_id}"): ["practice:write"],
    ("DELETE", "/api/v1/practice-sessions/{session_id}"): ["practice:write"],
    ("GET", "/api/v1/practice-sessions/{session_id}/recitation"): ["practice:read"],
    ("POST", "/api/v1/practice-sessions/{session_id}/printed"): ["practice:write"],
    ("POST", "/api/v1/practice-sessions/{session_id}/archive"): ["practice:write"],
    (
        "POST",
        "/api/v1/practice-sessions/{session_id}/review-rounds",
    ): ["reviews:write", "practice:read"],
    ("GET", "/api/v1/practice-review-rounds/{round_id}"): ["practice:read"],
    (
        "PUT",
        "/api/v1/practice-review-rounds/{round_id}/items/{item_id}/result",
    ): ["reviews:write"],
    (
        "PUT",
        "/api/v1/practice-review-rounds/{round_id}/results",
    ): ["reviews:write"],
}


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=(
            "Single-user word memory API. Browser requests use a trusted reverse-proxy "
            "identity; external Skills use scoped bearer tokens."
        ),
        routes=app.routes,
    )
    schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "opaque",
        "description": (
            "Managed high-entropy bearer token. Required scopes are listed in "
            "x-required-scopes because this is not an OAuth token endpoint."
        ),
        "x-available-scopes": sorted(ALL_SCOPES),
    }
    schemes["TrustedProxyUser"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Forwarded-User",
        "description": (
            "Only accepted from TRUSTED_PROXY_CIDRS after the proxy strips client-supplied headers."
        ),
    }
    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        # auth/users/api-clients/system are gated by session/role, not Bearer/TrustedProxyUser scopes.
        if (
            path.startswith("/api/v1/auth")
            or path.startswith("/api/v1/users")
            or path.startswith("/api/v1/api-clients")
            or path.startswith("/api/v1/system")
        ):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation["security"] = [{"BearerAuth": []}, {"TrustedProxyUser": []}]
            operation["x-required-scopes"] = REQUIRED_SCOPES.get(
                (method.upper(), path),
                [],
            )
            operation.setdefault(
                "responses",
                {},
            ).setdefault(
                "401",
                {"description": "AUTH_REQUIRED"},
            )
            operation["responses"].setdefault("403", {"description": "FORBIDDEN_SCOPE"})
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

FRONTEND_DIST = Path(settings.frontend_dist)


def _frontend_file(full_path: str) -> Path | None:
    dist = FRONTEND_DIST.resolve()
    candidate = (dist / full_path).resolve()
    if not candidate.is_relative_to(dist) or not candidate.is_file():
        return None
    return candidate


@app.get("/", include_in_schema=False)
@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str = ""):
    """Serve built SPA files and fall back to index for browser deep links."""
    if full_path.startswith(("api/", "healthz/", ".well-known/")):
        raise HTTPException(status_code=404)
    asset = _frontend_file(full_path) if full_path else None
    if asset is not None:
        return FileResponse(asset)
    if full_path.startswith("assets/"):
        raise HTTPException(status_code=404)
    index = _frontend_file("index.html")
    if index is None:
        raise HTTPException(status_code=404)
    return FileResponse(index, media_type="text/html")
