from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import ApiClient, ApiClientScope, ApiClientToken


def main() -> None:
    with SessionLocal() as db:
        for client in db.scalars(select(ApiClient).order_by(ApiClient.id)):
            scopes = db.scalars(
                select(ApiClientScope.scope)
                .where(ApiClientScope.api_client_id == client.id)
                .order_by(ApiClientScope.scope)
            ).all()
            print(
                f"client_id={client.id} status={client.status} "
                f"skill={client.skill_name}@{client.skill_version} scopes={','.join(scopes)}"
            )
            for token in db.scalars(
                select(ApiClientToken)
                .where(ApiClientToken.api_client_id == client.id)
                .order_by(ApiClientToken.id)
            ):
                state = "revoked" if token.revoked_at else "active"
                print(
                    f"  token_id={token.id} prefix={token.token_prefix} "
                    f"state={state} expires_at={token.expires_at}"
                )


if __name__ == "__main__":
    main()

