from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.auth import ALL_SCOPES
from app.core.database import SessionLocal
from app.models import ApiClient, ApiClientScope, AuditLog
from app.services.domain import canonical_json, utc_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace an API client's scopes")
    parser.add_argument("--client-id", type=int, required=True)
    parser.add_argument("--scope", action="append", required=True, choices=sorted(ALL_SCOPES))
    args = parser.parse_args()
    scopes = sorted(set(args.scope))
    with SessionLocal() as db:
        client = db.get(ApiClient, args.client_id)
        if client is None:
            parser.error("client not found")
        old = sorted(
            row.scope
            for row in db.query(ApiClientScope)
            .filter(ApiClientScope.api_client_id == client.id)
            .all()
        )
        db.query(ApiClientScope).filter(
            ApiClientScope.api_client_id == client.id
        ).delete(synchronize_session=False)
        for scope in scopes:
            db.add(ApiClientScope(api_client_id=client.id, scope=scope))
        client.scope_version += 1
        client.updated_at = utc_text()
        db.add(
            AuditLog(
                request_id=str(uuid.uuid4()),
                actor_type="system",
                action="api_client.scope_change",
                target_type="api_client",
                target_id=str(client.id),
                outcome="success",
                http_status=200,
                latency_ms=0,
                metadata_json=canonical_json({"old_scopes": old, "new_scopes": scopes}),
            )
        )
        db.commit()
    print(f"client_id={client.id} scope_version={client.scope_version}")


if __name__ == "__main__":
    main()

