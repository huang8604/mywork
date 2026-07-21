from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import IdempotencyRecord
from app.services.domain import canonical_json, utc_text
from app.services.reviews import ActorLike


def request_hash(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass
class IdempotencyClaim:
    record: IdempotencyRecord
    replay_data: dict[str, object] | list[object] | None
    replay_status: int | None

    @property
    def replayed(self) -> bool:
        return self.replay_status is not None


def claim(
    db: Session,
    *,
    actor: ActorLike,
    method: str,
    route_template: str,
    key: str | None,
    payload: object,
    required: bool,
) -> IdempotencyClaim | None:
    if not key:
        if required:
            raise AppError(422, "VALIDATION_ERROR", "需要提供 Idempotency-Key")
        return None
    if not 1 <= len(key) <= 128:
        raise AppError(422, "VALIDATION_ERROR", "Idempotency-Key 长度无效")
    digest = request_hash(payload)
    now_text = utc_text()
    existing = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_type == actor.actor_type,
            IdempotencyRecord.actor_id == actor.actor_id,
            IdempotencyRecord.method == method,
            IdempotencyRecord.route_template == route_template,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if existing is not None and existing.expires_at <= now_text:
        db.delete(existing)
        db.flush()
        existing = None
    if existing is not None:
        if existing.request_hash != digest:
            raise AppError(409, "IDEMPOTENCY_KEY_REUSE", "该 Idempotency-Key 已用于不同的请求")
        if existing.state == "processing":
            raise AppError(
                409,
                "REQUEST_IN_PROGRESS",
                "请求仍在处理中，请稍后重试",
                headers={"Retry-After": "1"},
            )
        return IdempotencyClaim(
            existing,
            json.loads(existing.response_json or "null"),
            existing.response_status,
        )
    expires = datetime.now(UTC) + timedelta(days=get_settings().idempotency_retention_days)
    values = {
        "actor_type": actor.actor_type,
        "actor_id": actor.actor_id,
        "method": method,
        "route_template": route_template,
        "idempotency_key": key,
        "request_hash": digest,
        "state": "processing",
        "created_at": now_text,
        "expires_at": utc_text(expires),
    }
    result = db.execute(
        sqlite_insert(IdempotencyRecord)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[
                "actor_type",
                "actor_id",
                "method",
                "route_template",
                "idempotency_key",
            ]
        )
    )
    record = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_type == actor.actor_type,
            IdempotencyRecord.actor_id == actor.actor_id,
            IdempotencyRecord.method == method,
            IdempotencyRecord.route_template == route_template,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if record is None:
        raise AppError(503, "SERVICE_BUSY", "无法占用幂等键，请稍后重试")
    if result.rowcount == 0:
        if record.request_hash != digest:
            raise AppError(409, "IDEMPOTENCY_KEY_REUSE", "该 Idempotency-Key 已用于不同的请求")
        if record.state == "processing":
            raise AppError(
                409,
                "REQUEST_IN_PROGRESS",
                "请求仍在处理中，请稍后重试",
                headers={"Retry-After": "1"},
            )
        return IdempotencyClaim(
            record,
            json.loads(record.response_json or "null"),
            record.response_status,
        )
    return IdempotencyClaim(record, None, None)


def complete(
    claim_: IdempotencyClaim | None,
    *,
    data: dict[str, object] | list[object],
    status_code: int,
    resource_type: str | None = None,
    resource_id: object | None = None,
) -> None:
    if claim_ is None:
        return
    claim_.record.state = "succeeded"
    claim_.record.response_status = status_code
    claim_.record.response_json = canonical_json(data)
    claim_.record.resource_type = resource_type
    claim_.record.resource_id = str(resource_id) if resource_id is not None else None
