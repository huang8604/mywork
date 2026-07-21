#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add English words to Word Memory Assistant")
    parser.add_argument("words", nargs="*", help="English words to add")
    parser.add_argument("--file", type=Path, help="UTF-8 text file with one word per line")
    parser.add_argument("--tag", action="append", default=[], help="Tag applied to every word")
    parser.add_argument("--custom", action="store_true", help="Mark every word as custom")
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


def main() -> int:
    args = parse_args()
    words = collect_words(args)
    base_url = os.getenv("WORD_MEMORY_BASE_URL", "").strip()
    token = os.getenv("WORD_MEMORY_API_TOKEN", "").strip()
    if not base_url or not token:
        raise SystemExit("WORD_MEMORY_BASE_URL and WORD_MEMORY_API_TOKEN are required.")

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
            target = "duplicates" if exc.status == 409 else "failed"
            results[target].append(failure)
    print(json.dumps({"ok": not results["failed"], **results}, ensure_ascii=False, indent=2))
    return 1 if results["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
