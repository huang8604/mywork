from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.auth import hash_password
from app.core.database import SessionLocal
from app.models import WebCredential
from app.models.entities import utc_now_text

ROLES = ("admin", "student")


def _read_password(args: argparse.Namespace) -> str:
    if args.password_file:
        return Path(args.password_file).read_text(encoding="utf-8").strip()
    if args.password is not None:
        return args.password
    once = getpass.getpass("Password: ")
    again = getpass.getpass("Confirm:  ")
    if once != again:
        sys.exit("passwords do not match")
    return once


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or update a web login credential (admin or student)"
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", help="password (prompted if omitted and no --password-file)")
    parser.add_argument("--password-file", help="read password from this file")
    parser.add_argument("--role", choices=ROLES, default="admin")
    args = parser.parse_args()

    password = _read_password(args)
    if len(password) < 8:
        parser.error("password must be at least 8 characters")

    with SessionLocal() as db:
        cred = db.scalar(
            select(WebCredential).where(WebCredential.username == args.username)
        )
        now = utc_now_text()
        if cred is None:
            cred = WebCredential(
                username=args.username,
                password_hash=hash_password(password),
                role=args.role,
                created_at=now,
                updated_at=now,
            )
            db.add(cred)
            print(f"created user {args.username!r} (role={args.role})")
        else:
            cred.password_hash = hash_password(password)
            cred.role = args.role
            cred.updated_at = now
            print(f"updated user {args.username!r} (role={args.role})")
        db.commit()


if __name__ == "__main__":
    main()
