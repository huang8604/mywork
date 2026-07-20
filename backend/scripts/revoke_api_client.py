from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.models import ApiClient, ApiClientToken, AuditLog
from app.services.domain import utc_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Revoke an API token or disable a client")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--token-id", type=int)
    group.add_argument("--client-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.token_id is not None:
            token = db.get(ApiClientToken, args.token_id)
            if token is None:
                parser.error("token not found")
            if token.revoked_at is None:
                token.revoked_at = utc_text()
            print(f"revoked token {token.id}")
            action = "api_token.revoke"
            target_type = "api_client_token"
            target_id = token.id
        else:
            client = db.get(ApiClient, args.client_id)
            if client is None:
                parser.error("client not found")
            client.status = "disabled"
            client.updated_at = utc_text()
            print(f"disabled client {client.id}")
            action = "api_client.disable"
            target_type = "api_client"
            target_id = client.id
        db.add(
            AuditLog(
                request_id=str(uuid.uuid4()),
                actor_type="system",
                action=action,
                target_type=target_type,
                target_id=str(target_id),
                outcome="success",
                http_status=200,
                latency_ms=0,
            )
        )
        db.commit()


if __name__ == "__main__":
    main()
