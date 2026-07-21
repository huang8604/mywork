"""Shorten overly-long cn_meaning strings already stored in the database.

The runtime cleaner (``app.services.dictionary.shorten_translations``) only
affects *new* writes; words imported before it shipped keep their long stored
meanings. This one-shot maintenance script reapplies the same cleaning to
existing ``words.cn_meaning`` rows and bumps ``updated_at`` (it does not touch
``version`` — it is a bulk maintenance op, like ``rebuild_stats.py``).

Dry-run by default; pass ``--apply`` to write. Run against the production DB
via the venv/container:

    python scripts/shorten_word_meanings.py [--apply] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Word  # noqa: E402
from app.models.entities import utc_now_text  # noqa: E402
from app.services.dictionary import shorten_translations  # noqa: E402


def _shorten_stored(meaning: str) -> str | None:
    # Treat the stored "pos cn；pos cn；…" string as one sense per segment and
    # re-run the same cleaner so the rules stay in one place.
    segments = [seg.strip() for seg in meaning.split("；") if seg.strip()]
    fake_t = [{"pos": "", "cn": seg} for seg in segments]
    return shorten_translations(fake_t)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually write changes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=0, help="only process this many rows (0 = all)")
    args = parser.parse_args()

    with SessionLocal() as db:
        stmt = select(Word).where(Word.deleted_at.is_(None))
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = list(db.scalars(stmt))
        changed: list[tuple[int, str, str, str]] = []  # id, word, old, new
        for word in rows:
            if not word.cn_meaning:
                continue
            shortened = _shorten_stored(word.cn_meaning)
            if shortened and shortened != word.cn_meaning and len(shortened) < len(word.cn_meaning):
                changed.append((word.id, word.en_word, word.cn_meaning, shortened))

        print(f"words scanned: {len(rows)}  would-change: {len(changed)}  "
              f"mode: {'APPLY' if args.apply else 'DRY-RUN'}")
        changed.sort(key=lambda row: len(row[2]) - len(row[3]), reverse=True)
        for wid, word, old, new in changed[:20]:
            print(f"  [{wid}] {word}: ({len(old)}) {old[:50]}  ->  ({len(new)}) {new[:50]}")

        if not args.apply:
            print("dry-run; no changes written (pass --apply to write)")
            return
        now = utc_now_text()
        for wid, _word, _old, new in changed:
            db.get(Word, wid).cn_meaning = new
            db.get(Word, wid).updated_at = now
        db.commit()
        print(f"updated {len(changed)} rows")


if __name__ == "__main__":
    main()
