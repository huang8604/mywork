#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ApiFailure(Exception):
    def __init__(self, status: int | None, body: dict):
        super().__init__(str(body.get("message") or body.get("code") or "API request failed"))
        self.status = status
        self.body = body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import words in the background")
    parser.add_argument("file", type=Path, help="UTF-8 TXT, CSV, or JSON file")
    parser.add_argument(
        "--conflict-policy", choices=("skip", "update", "reject"), default="update"
    )
    parser.add_argument(
        "--unresolved-policy", choices=("skip", "reject", "ai"), default="ai"
    )
    parser.add_argument("--tag", action="append", default=[], help="Default tag (repeatable)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-wait", action="store_true", help="Return after the job is queued")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-wait", type=float, default=1800.0)
    parser.add_argument("--idempotency-key", default=None)
    return parser.parse_args()


def validate_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    raise SystemExit("WORD_MEMORY_BASE_URL must use HTTPS (HTTP is allowed only for localhost).")


def decode_response(response) -> dict:
    return json.load(response)


def send(request: Request, *, timeout: float = 30) -> dict:
    try:
        with urlopen(request, timeout=timeout) as response:
            return decode_response(response)
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


def progress_request(base_url: str, token: str) -> dict:
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/words/import/progress",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    return send(request)["data"]


def multipart_body(file: Path, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----word-memory-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file.name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def start_import(
    base_url: str, token: str, file: Path, args: argparse.Namespace, key: str
) -> dict:
    body, content_type = multipart_body(
        file,
        {
            "conflict_policy": args.conflict_policy,
            "unresolved_policy": args.unresolved_policy,
            "dry_run": "true" if args.dry_run else "false",
            "tags": ",".join(args.tag),
        },
    )
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/words/import",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "Idempotency-Key": key,
        },
        method="POST",
    )
    return send(request, timeout=120)["data"]


def wait_for_import(
    base_url: str,
    token: str,
    initial: dict,
    *,
    interval: float,
    max_wait: float,
) -> dict:
    expected_total = initial.get("total")
    deadline = time.monotonic() + max_wait
    progress = initial
    while not progress.get("finished"):
        if time.monotonic() >= deadline:
            raise ApiFailure(
                None,
                {
                    "code": "IMPORT_TIMEOUT",
                    "message": "Import is still running; query /words/import/progress before retrying.",
                    "progress": progress,
                },
            )
        print(
            json.dumps(
                {
                    "state": progress.get("state"),
                    "processed": progress.get("processed"),
                    "total": progress.get("total"),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        time.sleep(max(interval, 0.1))
        progress = progress_request(base_url, token)
        if expected_total is not None and progress.get("total") != expected_total:
            raise ApiFailure(
                None,
                {
                    "code": "PROGRESS_CONFLICT",
                    "message": "Another import replaced the server's global progress snapshot.",
                    "progress": progress,
                },
            )
    return progress


def main() -> int:
    args = parse_args()
    if not args.file.is_file():
        raise SystemExit(f"Import file not found: {args.file}")
    base_url = os.getenv("WORD_MEMORY_BASE_URL", "").strip()
    token = os.getenv("WORD_MEMORY_API_TOKEN", "").strip()
    if not base_url or not token:
        raise SystemExit("WORD_MEMORY_BASE_URL and WORD_MEMORY_API_TOKEN are required.")
    validate_base_url(base_url)
    key = args.idempotency_key or str(uuid.uuid4())
    try:
        if not args.dry_run:
            current = progress_request(base_url, token)
            if current.get("state") == "running":
                raise ApiFailure(
                    409,
                    {
                        "code": "IMPORT_ALREADY_RUNNING",
                        "message": "Wait for the current global import job to finish.",
                        "progress": current,
                    },
                )
        progress = start_import(base_url, token, args.file, args, key)
        if not args.dry_run and not args.no_wait:
            progress = wait_for_import(
                base_url,
                token,
                progress,
                interval=args.poll_interval,
                max_wait=args.max_wait,
            )
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
            {"ok": True, "idempotency_key": key, "progress": progress},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
