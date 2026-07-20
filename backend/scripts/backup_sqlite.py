from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from urllib.parse import urlparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and verify an online SQLite backup")
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    destination = Path(args.destination).resolve()
    if source == destination:
        parser.error("source and destination must differ")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = dst.execute("PRAGMA foreign_key_check").fetchall()
    if result != "ok":
        destination.unlink(missing_ok=True)
        raise SystemExit(f"backup integrity check failed: {result}")
    if foreign_key_errors:
        destination.unlink(missing_ok=True)
        raise SystemExit(f"backup foreign key check failed: {len(foreign_key_errors)} errors")
    print(f"backup written to {destination}")


if __name__ == "__main__":
    main()
