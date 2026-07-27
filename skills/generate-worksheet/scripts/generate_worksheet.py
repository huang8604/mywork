#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ApiFailure(Exception):
    def __init__(self, status: int | None, body: dict):
        super().__init__(str(body.get("message") or body.get("code") or "API request failed"))
        self.status = status
        self.body = body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Word Memory worksheet")
    parser.add_argument("--total-words", type=int)
    parser.add_argument("--new", dest="new_words_limit", type=int)
    parser.add_argument("--error", dest="error_words_limit", type=int)
    parser.add_argument("--due", dest="due_words_limit", type=int)
    parser.add_argument("--custom", dest="custom_words_limit", type=int)
    parser.add_argument("--fallback-days", dest="fallback_unreviewed_days", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--word-id", dest="word_ids", action="append", type=int, default=[])
    parser.add_argument(
        "--idempotency-key",
        default=None,
        help="Reuse the same key when retrying an uncertain request",
    )
    return parser.parse_args()


def validate_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    raise SystemExit("WORD_MEMORY_BASE_URL must use HTTPS (HTTP is allowed only for localhost).")


def api_request(base_url: str, token: str, payload: dict, idempotency_key: str) -> dict:
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/daily-table/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
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
            body = {
                "code": "HTTP_ERROR",
                "message": str(exc),
                "request_id": exc.headers.get("X-Request-ID"),
            }
        raise ApiFailure(exc.code, body) from exc
    except URLError as exc:
        raise ApiFailure(None, {"code": "NETWORK_ERROR", "message": str(exc.reason)}) from exc


def build_payload(args: argparse.Namespace) -> dict:
    payload = {}
    for name in (
        "total_words",
        "new_words_limit",
        "error_words_limit",
        "due_words_limit",
        "custom_words_limit",
        "fallback_unreviewed_days",
        "seed",
    ):
        value = getattr(args, name)
        if value is not None:
            payload[name] = value
    if args.word_ids:
        payload["word_ids"] = args.word_ids
    return payload


def main() -> int:
    args = parse_args()
    base_url = os.getenv("WORD_MEMORY_BASE_URL", "").strip()
    token = os.getenv("WORD_MEMORY_API_TOKEN", "").strip()
    if not base_url or not token:
        raise SystemExit("WORD_MEMORY_BASE_URL and WORD_MEMORY_API_TOKEN are required.")
    validate_base_url(base_url)
    key = args.idempotency_key or str(uuid.uuid4())
    try:
        response = api_request(base_url, token, build_payload(args), key)
    except ApiFailure as exc:
        print(
            json.dumps(
                {"ok": False, "status": exc.status, "idempotency_key": key, **exc.body},
                ensure_ascii=False,
            )
        )
        return 1
    print(
        json.dumps(
            {"ok": True, "idempotency_key": key, "worksheet": response["data"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
