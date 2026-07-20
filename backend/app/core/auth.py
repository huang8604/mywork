from __future__ import annotations

import ipaddress
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import ApiClient, ApiClientScope, ApiClientToken, AuditLog
from app.services.domain import parse_utc, utc_text
from app.services.reviews import ActorLike


ALL_SCOPES = {
    "words:read",
    "words:write",
    "words:export",
    "practice:generate",
    "practice:read",
    "practice:write",
    "reviews:write",
    "reviews:read",
}

password_hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)
_rate_lock = threading.Lock()
_rate_events: dict[str, deque[float]] = defaultdict(deque)


@dataclass(frozen=True)
class Actor(ActorLike):
    scopes: frozenset[str]
    api_client_id: int | None = None
    skill_name: str | None = None
    skill_version: str | None = None


def hash_token(token: str, settings: Settings | None = None) -> str:
    config = settings or get_settings()
    material = token.encode("utf-8") + b"\x00" + config.token_pepper_bytes()
    return password_hasher.hash(material)


def verify_token_hash(token_hash: str, token: str, settings: Settings) -> bool:
    material = token.encode("utf-8") + b"\x00" + settings.token_pepper_bytes()
    try:
        return password_hasher.verify(token_hash, material)
    except VerifyMismatchError:
        return False


def generate_token() -> str:
    return "wm_" + secrets.token_urlsafe(40)


def token_prefix(token: str) -> str:
    return token[:16]


def _trusted_peer(request: Request, settings: Settings) -> bool:
    if request.client is None:
        return False
    try:
        peer = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    return any(
        peer in ipaddress.ip_network(network, strict=False)
        for network in settings.trusted_proxy_cidrs
    )


def _local_peer(request: Request) -> bool:
    if request.client is None:
        return False
    if request.client.host == "testclient":
        return True
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def _check_rate_limit(request: Request, identity: str, settings: Settings) -> None:
    peer = request.client.host if request.client else "unknown"
    key = f"{peer}:{identity}"
    now = time.monotonic()
    with _rate_lock:
        events = _rate_events[key]
        while events and events[0] <= now - 60:
            events.popleft()
        if len(events) >= settings.api_rate_limit_per_minute:
            retry_after = max(1, int(60 - (now - events[0])))
            raise AppError(
                429,
                "RATE_LIMITED",
                "request rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        events.append(now)


def _authenticate_bearer(
    db: Session, token: str, settings: Settings, request: Request
) -> Actor:
    _check_rate_limit(request, "unauthenticated", settings)
    candidates = db.scalars(
        select(ApiClientToken).where(ApiClientToken.token_prefix == token_prefix(token))
    ).all()
    matched = next(
        (candidate for candidate in candidates if verify_token_hash(candidate.token_hash, token, settings)),
        None,
    )
    now = datetime.now(UTC)
    if (
        matched is None
        or matched.revoked_at is not None
        or parse_utc(matched.expires_at) <= now
    ):
        raise AppError(401, "AUTH_REQUIRED", "invalid or expired bearer token")
    client = db.get(ApiClient, matched.api_client_id)
    if client is None or client.status != "active":
        raise AppError(401, "AUTH_REQUIRED", "API client is disabled")
    _check_rate_limit(request, f"client:{client.id}", settings)
    scopes = frozenset(
        db.scalars(
            select(ApiClientScope.scope).where(ApiClientScope.api_client_id == client.id)
        ).all()
    )
    matched.last_used_at = utc_text()
    db.commit()
    return Actor(
        actor_type="api_client",
        actor_id=str(client.id),
        scopes=scopes,
        api_client_id=client.id,
        skill_name=client.skill_name,
        skill_version=client.skill_version,
    )


def get_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> Actor:
    request.state.audit_db = db
    settings = get_settings()
    if credentials is not None:
        if credentials.scheme.lower() != "bearer":
            raise AppError(401, "AUTH_REQUIRED", "bearer token required")
        actor = _authenticate_bearer(db, credentials.credentials, settings, request)
        request.state.actor = actor
        return actor
    if settings.trusted_local_web and _local_peer(request):
        actor = Actor("web_user", "local-admin", frozenset(ALL_SCOPES))
        request.state.actor = actor
        return actor
    if not _trusted_peer(request, settings):
        raise AppError(401, "AUTH_REQUIRED", "trusted proxy required")
    forwarded_user = request.headers.get("X-Forwarded-User", "").strip()
    if not forwarded_user or len(forwarded_user) > 128:
        raise AppError(401, "AUTH_REQUIRED", "trusted web identity required")
    actor = Actor("web_user", forwarded_user, frozenset(ALL_SCOPES))
    request.state.actor = actor
    return actor


def require_scopes(*required: str):
    def dependency(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
        missing = set(required) - actor.scopes
        if missing:
            raise AppError(
                403,
                "FORBIDDEN_SCOPE",
                "insufficient API client scope",
                [{"missing_scopes": sorted(missing)}],
            )
        return actor

    return dependency


def create_api_client_token(
    db: Session,
    *,
    name: str,
    skill_name: str,
    skill_version: str,
    scopes: list[str],
    expires_days: int,
    description: str | None = None,
) -> tuple[ApiClient, ApiClientToken, str]:
    unknown = set(scopes) - ALL_SCOPES
    if unknown:
        raise ValueError(f"unknown scopes: {sorted(unknown)}")
    now = datetime.now(UTC)
    client = ApiClient(
        name=name,
        description=description,
        skill_name=skill_name,
        skill_version=skill_version,
        created_at=utc_text(now),
        updated_at=utc_text(now),
    )
    db.add(client)
    db.flush()
    for scope in sorted(set(scopes)):
        db.add(ApiClientScope(api_client_id=client.id, scope=scope))
    raw_token = generate_token()
    token = ApiClientToken(
        api_client_id=client.id,
        token_prefix=token_prefix(raw_token),
        token_hash=hash_token(raw_token),
        created_at=utc_text(now),
        expires_at=utc_text(now + timedelta(days=expires_days)),
    )
    db.add(token)
    db.add(
        AuditLog(
            request_id=str(uuid.uuid4()),
            actor_type="system",
            action="api_client.create",
            target_type="api_client",
            target_id=str(client.id),
            outcome="success",
            http_status=200,
            latency_ms=0,
        )
    )
    db.commit()
    return client, token, raw_token
