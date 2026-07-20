from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.auth import generate_token, hash_token, token_prefix
from app.core.database import SessionLocal
from app.models import ApiClient, ApiClientToken, AuditLog
from app.services.domain import parse_utc, utc_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate an API client token")
    parser.add_argument("--client-id", type=int, required=True)
    parser.add_argument("--expires-days", type=int, default=365)
    args = parser.parse_args()
    if args.expires_days <= 0:
        parser.error("--expires-days must be positive")
    now = datetime.now(UTC)
    overlap_end = now + timedelta(minutes=10)
    with SessionLocal() as db:
        client = db.get(ApiClient, args.client_id)
        if client is None or client.status != "active":
            parser.error("active client not found")
        existing_tokens = db.scalars(
            select(ApiClientToken).where(
                ApiClientToken.api_client_id == client.id,
                ApiClientToken.revoked_at.is_(None),
            )
        ).all()
        for token in existing_tokens:
            if parse_utc(token.expires_at) > overlap_end:
                token.expires_at = utc_text(overlap_end)
        raw = generate_token()
        token = ApiClientToken(
            api_client_id=client.id,
            token_prefix=token_prefix(raw),
            token_hash=hash_token(raw),
            created_at=utc_text(now),
            expires_at=utc_text(now + timedelta(days=args.expires_days)),
        )
        db.add(token)
        db.flush()
        db.add(
            AuditLog(
                request_id=str(uuid.uuid4()),
                actor_type="system",
                action="api_token.rotate",
                target_type="api_client_token",
                target_id=str(token.id),
                outcome="success",
                http_status=200,
                latency_ms=0,
                metadata_json='{"overlap_minutes":10}',
            )
        )
        db.commit()
    print(f"token_id={token.id}")
    print(f"token={raw}")
    print("Old active tokens expire within 10 minutes. Store this token now.")


if __name__ == "__main__":
    main()

