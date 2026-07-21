"""Rewrite dictionary-index.json so each entry's ``t`` list is pre-cleaned.

Drops surname senses, parenthetical English glosses, near-English senses, and
duplicates, capping each word to its primary senses — so the canonical
dictionary file itself is short and auditable, independent of the runtime
cleaner in ``app.services.dictionary`` (which already shortens on the fly).

The original file is backed up once to ``<input>.full.json`` before the first
overwrite; re-running will not clobber that true original.

Run from the repo root against the venv/container:

    python scripts/rebuild_dictionary_meanings.py [--input PATH] [--output PATH]
        [--max-senses N] [--dry-run]

The dictionary file is git-ignored (license undocumented), so this only edits
your local copy.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.dictionary import (  # noqa: E402
    clean_translation_items,
    shorten_translations,
)


def _dist(values: list[int]) -> str:
    if not values:
        return "n=0"
    values = sorted(values)
    return (
        f"n={len(values)} min={values[0]} p50={values[len(values) // 2]} "
        f"p90={values[int(len(values) * 0.9)]} p99={values[int(len(values) * 0.99)]} "
        f"max={values[-1]}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_path = get_settings().dictionary_index_path
    parser.add_argument("--input", default=default_path, help=f"default: {default_path}")
    parser.add_argument("--output", default=None, help="default: same as --input")
    parser.add_argument("--max-senses", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output or args.input)
    if not input_path.is_file():
        sys.exit(f"dictionary file not found: {input_path}")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        sys.exit("dictionary root must be an object keyed by word")

    changed = 0
    biggest: list[tuple[int, str, str, str]] = []  # (reduction, word, old_raw, new_raw)
    old_display_lens: list[int] = []
    new_raw_lens: list[int] = []

    for word, entry in data.items():
        if not isinstance(entry, dict):
            continue
        old_t = entry.get("t")
        old_display = shorten_translations(old_t)
        if old_display:
            old_display_lens.append(len(old_display))
        old_raw = _raw_join(old_t)
        items = clean_translation_items(old_t, max_senses=args.max_senses)
        new_t = items if items else old_t  # keep original on full-filter fallback
        if new_t and new_t != old_t:
            entry["t"] = new_t
            changed += 1
        new_raw = _raw_join(new_t)
        if new_raw:
            new_raw_lens.append(len(new_raw))
        reduction = len(old_raw) - len(new_raw)
        if reduction > 0:
            biggest.append((reduction, word, old_raw, new_raw))

    print(f"entries: {len(data)}  rewritten: {changed}  (max_senses={args.max_senses})")
    print(f"displayed meaning length (runtime cleaner): {_dist(old_display_lens)}")
    print(f"raw t-join length after rewrite:            {_dist(new_raw_lens)}")
    biggest.sort(reverse=True)
    print("biggest raw reductions (word: old -> new):")
    for _, word, old_raw, new_raw in biggest[:20]:
        print(f"  {word}: ({len(old_raw)}) {old_raw[:60]}  ->  ({len(new_raw)}) {new_raw[:60]}")

    if args.dry_run:
        print("dry-run; no file written")
        return

    backup = input_path.with_suffix(input_path.suffix + ".full.json")
    if input_path == output_path and not backup.exists():
        backup.write_text(input_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"backed up original to {backup}")
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output_path}")


def _raw_join(translations: object) -> str:
    if not isinstance(translations, list):
        return ""
    parts: list[str] = []
    for entry in translations:
        if not isinstance(entry, dict):
            continue
        meaning = str(entry.get("cn") or "").strip()
        if not meaning:
            continue
        part = str(entry.get("pos") or "").strip()
        parts.append(f"{part} {meaning}".strip())
    return "；".join(parts)


if __name__ == "__main__":
    main()
