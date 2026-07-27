#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add English words to Word Memory Assistant")
    parser.add_argument("words", nargs="*", help="English words to add")
    parser.add_argument("--file", type=Path, help="UTF-8 text file with one word per line")
    parser.add_argument("--tag", action="append", default=[], help="Tag applied to every word")
    parser.add_argument("--custom", action="store_true", help="Mark every word as custom")
    parser.add_argument(
        "--meaning",
        action="append",
        default=[],
        metavar="WORD=MEANING",
        help="Manual Chinese meaning for one word (repeatable)",
    )
    parser.add_argument(
        "--meaning-file",
        type=Path,
        help="UTF-8 TSV file with WORD<TAB>MEANING per line",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview enrichment without writing")
    return parser.parse_args()


def collect_words(args: argparse.Namespace) -> list[str]:
    values = list(args.words)
    if args.file:
        values.extend(args.file.read_text(encoding="utf-8-sig").splitlines())
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        word = " ".join(value.strip().split())
        normalized = word.casefold()
        if not word or word.startswith("#") or normalized in seen:
            continue
        seen.add(normalized)
        result.append(word)
    if not result:
        raise SystemExit("No English words were provided.")
    if len(result) > 200:
        raise SystemExit("At most 200 words can be processed at once.")
    return result


def collect_meanings(args: argparse.Namespace, words: list[str]) -> dict[str, str]:
    rows: list[tuple[str, str]] = []
    for value in args.meaning:
        if "=" not in value:
            raise SystemExit("--meaning must use WORD=MEANING.")
        rows.append(tuple(value.split("=", 1)))
    if args.meaning_file:
        for line_no, line in enumerate(
            args.meaning_file.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "\t" not in line:
                raise SystemExit(
                    f"{args.meaning_file}:{line_no}: expected WORD<TAB>MEANING."
                )
            rows.append(tuple(line.split("\t", 1)))

    allowed = {" ".join(word.strip().split()).casefold() for word in words}
    meanings: dict[str, str] = {}
    for raw_word, raw_meaning in rows:
        word = " ".join(raw_word.strip().split())
        meaning = raw_meaning.strip()
        key = word.casefold()
        if not word or not meaning:
            raise SystemExit("Manual meanings require a non-empty word and meaning.")
        if key not in allowed:
            raise SystemExit(f"Manual meaning provided for an unknown input word: {word}")
        if key in meanings and meanings[key] != meaning:
            raise SystemExit(f"Conflicting manual meanings for: {word}")
        meanings[key] = meaning
    return meanings


def api_request(base_url: str, token: str, path: str, payload: object) -> dict:
    request = Request(
        f"{base_url.rstrip('/')}/api/v1{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            body = json.load(exc)
        except (ValueError, json.JSONDecodeError):
            body = {"code": "HTTP_ERROR", "message": str(exc), "request_id": exc.headers.get("X-Request-ID")}
        raise ApiFailure(exc.code, body) from exc
    except URLError as exc:
        raise ApiFailure(None, {"code": "NETWORK_ERROR", "message": str(exc.reason)}) from exc


class ApiFailure(Exception):
    def __init__(self, status: int | None, body: dict):
        super().__init__(str(body.get("message") or body.get("code") or "API request failed"))
        self.status = status
        self.body = body


def validate_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    raise SystemExit("WORD_MEMORY_BASE_URL must use HTTPS (HTTP is allowed only for localhost).")


def main() -> int:
    args = parse_args()
    words = collect_words(args)
    meanings = collect_meanings(args, words)
    base_url = os.getenv("WORD_MEMORY_BASE_URL", "").strip()
    token = os.getenv("WORD_MEMORY_API_TOKEN", "").strip()
    if not base_url or not token:
        raise SystemExit("WORD_MEMORY_BASE_URL and WORD_MEMORY_API_TOKEN are required.")
    validate_base_url(base_url)

    try:
        preview = api_request(base_url, token, "/words/enrich", {"words": words})["data"]
    except ApiFailure as exc:
        print(json.dumps({"ok": False, "status": exc.status, **exc.body}, ensure_ascii=False))
        return 1
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "words": preview}, ensure_ascii=False, indent=2))
        return 0

    results = {"created": [], "duplicates": [], "failed": []}
    for item in preview:
        word = item["en_word"]
        payload = {"en_word": word, "is_custom": args.custom, "tags": args.tag}
        manual_meaning = meanings.get(" ".join(word.strip().split()).casefold())
        if manual_meaning:
            payload["cn_meaning"] = manual_meaning
        elif "cn_meaning" in item.get("missing_fields", []):
            results["failed"].append(
                {
                    "word": word,
                    "status": None,
                    "code": "MANUAL_MEANING_REQUIRED",
                    "message": "Provide a Chinese meaning with --meaning or --meaning-file.",
                    "request_id": None,
                }
            )
            continue
        try:
            created = api_request(base_url, token, "/words", payload)["data"]
            results["created"].append(created)
        except ApiFailure as exc:
            failure = {
                "word": word,
                "status": exc.status,
                "code": exc.body.get("code"),
                "message": exc.body.get("message"),
                "request_id": exc.body.get("request_id"),
            }
            target = "duplicates" if exc.body.get("code") == "DUPLICATE_WORD" else "failed"
            results[target].append(failure)
    print(json.dumps({"ok": not results["failed"], **results}, ensure_ascii=False, indent=2))
    return 1 if results["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
