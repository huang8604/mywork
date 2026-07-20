from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.auth import ALL_SCOPES, create_api_client_token
from app.core.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an API client and one-time token")
    parser.add_argument("--name", required=True)
    parser.add_argument("--skill-name", required=True)
    parser.add_argument("--skill-version", required=True)
    parser.add_argument("--scope", action="append", required=True, choices=sorted(ALL_SCOPES))
    parser.add_argument("--expires-days", type=int, default=365)
    parser.add_argument("--description")
    args = parser.parse_args()
    if args.expires_days <= 0:
        parser.error("--expires-days must be positive")
    with SessionLocal() as db:
        client, token, raw = create_api_client_token(
            db,
            name=args.name,
            skill_name=args.skill_name,
            skill_version=args.skill_version,
            scopes=args.scope,
            expires_days=args.expires_days,
            description=args.description,
        )
    print(f"client_id={client.id}")
    print(f"token_id={token.id}")
    print(f"token={raw}")
    print("Store this token now; it will not be shown again.")


if __name__ == "__main__":
    main()

