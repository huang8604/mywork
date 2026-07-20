from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.reviews import rebuild_all_stats


def main() -> None:
    with SessionLocal() as db:
        count = rebuild_all_stats(db)
        db.commit()
    print(f"rebuilt statistics for {count} words")


if __name__ == "__main__":
    main()

