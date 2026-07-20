from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.core.auth import Actor
from app.models import AuditLog
from app.services.domain import canonical_json


def add_audit(
    db: Session,
    *,
    request_id: str,
    actor: Actor,
    action: str,
    outcome: str,
    http_status: int,
    target_type: str | None = None,
    target_id: object | None = None,
    error_code: str | None = None,
    remote_addr: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLog(
            request_id=request_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            api_client_id=actor.api_client_id,
            skill_name=actor.skill_name,
            skill_version=actor.skill_version,
            scopes_json=canonical_json(sorted(actor.scopes)),
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            outcome=outcome,
            http_status=http_status,
            error_code=error_code,
            latency_ms=0,
            remote_addr_hash=(
                hashlib.sha256(remote_addr.encode("utf-8")).hexdigest()
                if remote_addr
                else None
            ),
            metadata_json=canonical_json(metadata) if metadata else None,
        )
    )

