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

STATUSES = {"known", "unknown", "skipped"}


class ApiFailure(Exception):
    def __init__(self, status: int | None, body: dict):
        super().__init__(str(body.get("message") or body.get("code") or "API request failed"))
        self.status = status
        self.body = body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record worksheet review results")
    parser.add_argument("--session-id", type=int)
    parser.add_argument("--round-id", type=int, help="Reuse an existing open round")
    parser.add_argument("--mode", choices=("offline", "online"), default="offline")
    parser.add_argument("--show-items", action="store_true")
    parser.add_argument(
        "--result",
        action="append",
        default=[],
        metavar="ITEM_ID=STATUS",
        help="Record known, unknown, or skipped (repeatable)",
    )
    parser.add_argument(
        "--results-file",
        type=Path,
        help="UTF-8 TSV: ITEM_ID<TAB>STATUS<TAB>DURATION_MS(optional)",
    )
    parser.add_argument(
        "--operation-id",
        help="Reuse this identifier to safely retry round creation and batch submission",
    )
    return parser.parse_args()


def validate_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    raise SystemExit("WORD_MEMORY_BASE_URL must use HTTPS (HTTP is allowed only for localhost).")


def api_request(
    base_url: str,
    token: str,
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(
        f"{base_url.rstrip('/')}/api/v1{path}",
        data=data,
        headers=headers,
        method=method,
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


def collect_results(args: argparse.Namespace) -> list[dict]:
    rows: list[tuple[str, str, str | None]] = []
    for value in args.result:
        if "=" not in value:
            raise SystemExit("--result must use ITEM_ID=STATUS.")
        item_id, status = value.split("=", 1)
        rows.append((item_id, status, None))
    if args.results_file:
        for line_no, line in enumerate(
            args.results_file.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) not in {2, 3}:
                raise SystemExit(
                    f"{args.results_file}:{line_no}: expected ITEM_ID<TAB>STATUS<TAB>DURATION_MS(optional)."
                )
            rows.append((fields[0], fields[1], fields[2] if len(fields) == 3 else None))

    results: list[dict] = []
    seen: set[int] = set()
    for raw_item_id, raw_status, raw_duration in rows:
        try:
            item_id = int(raw_item_id.strip())
        except ValueError as exc:
            raise SystemExit(f"Invalid item ID: {raw_item_id}") from exc
        status = raw_status.strip().casefold()
        if item_id <= 0 or status not in STATUSES:
            raise SystemExit(f"Invalid result: {raw_item_id}={raw_status}")
        if item_id in seen:
            raise SystemExit(f"Duplicate item ID: {item_id}")
        seen.add(item_id)
        result = {"item_id": item_id, "status": status}
        if raw_duration is not None and raw_duration.strip():
            try:
                duration = int(raw_duration.strip())
            except ValueError as exc:
                raise SystemExit(f"Invalid duration for item {item_id}: {raw_duration}") from exc
            if not 0 <= duration <= 86_400_000:
                raise SystemExit(f"Duration out of range for item {item_id}")
            result["duration_ms"] = duration
        results.append(result)
    return results


def show_items(base_url: str, token: str, session_id: int) -> dict:
    session = api_request(
        base_url, token, "GET", f"/practice-sessions/{session_id}"
    )["data"]
    return {
        "session_id": session["session_id"],
        "status": session["status"],
        "completed_at": session.get("completed_at"),
        "items": [
            {
                "item_id": item["item_id"],
                "position": item["position"],
                "word": item["word"]["en_word"],
                "meaning": item["word"].get("cn_meaning"),
            }
            for item in session.get("items", [])
        ],
    }


def main() -> int:
    args = parse_args()
    base_url = os.getenv("WORD_MEMORY_BASE_URL", "").strip()
    token = os.getenv("WORD_MEMORY_API_TOKEN", "").strip()
    if not base_url or not token:
        raise SystemExit("WORD_MEMORY_BASE_URL and WORD_MEMORY_API_TOKEN are required.")
    validate_base_url(base_url)

    if args.show_items:
        if not args.session_id:
            raise SystemExit("--show-items requires --session-id.")
        try:
            data = show_items(base_url, token, args.session_id)
        except ApiFailure as exc:
            print(json.dumps({"ok": False, "status": exc.status, **exc.body}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, **data}, ensure_ascii=False, indent=2))
        return 0

    results = collect_results(args)
    if not results:
        raise SystemExit("Provide at least one --result or --results-file.")
    if not args.round_id and not args.session_id:
        raise SystemExit("Provide --session-id to create a round, or --round-id to reuse one.")
    operation_id = args.operation_id or str(uuid.uuid4())
    if not 1 <= len(operation_id) <= 80:
        raise SystemExit("--operation-id must contain 1 to 80 characters.")

    round_id = args.round_id
    try:
        if round_id is None:
            round_data = api_request(
                base_url,
                token,
                "POST",
                f"/practice-sessions/{args.session_id}/review-rounds",
                payload={"mode": args.mode},
                idempotency_key=f"record-round:{operation_id}",
            )["data"]
            round_id = round_data["round_id"]
        batch_items = [
            {
                **item,
                "client_event_id": f"record-review:{operation_id}:{item['item_id']}",
            }
            for item in results
        ]
        data = api_request(
            base_url,
            token,
            "PUT",
            f"/practice-review-rounds/{round_id}/results",
            payload={"items": batch_items},
            idempotency_key=f"record-results:{operation_id}",
        )["data"]
    except ApiFailure as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": exc.status,
                    "operation_id": operation_id,
                    "round_id": round_id,
                    **exc.body,
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "operation_id": operation_id,
                "round_id": round_id,
                "result": data,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
