from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Iterable

from app.core.errors import validation

_WHITESPACE = re.compile(r"\s+")


def normalize_display(value: str, *, maximum: int, field: str) -> str:
    normalized = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).strip())
    if not normalized:
        raise validation(["body", field], "不能为空")
    if len(normalized) > maximum:
        raise validation(["body", field], f"不能超过 {maximum} 个字符")
    return normalized


def normalize_word(value: str) -> tuple[str, str]:
    display = normalize_display(value, maximum=200, field="en_word")
    return display, display.casefold()


def normalize_tag(value: str) -> tuple[str, str]:
    display = normalize_display(value, maximum=50, field="tags")
    return display, display.casefold()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def utc_text(value: datetime | None = None) -> str:
    moment = value or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("timezone is required")
    moment = moment.astimezone(UTC)
    return moment.isoformat(timespec="microseconds").replace("+00:00", "Z")


def reviewed_at_text(value: datetime | None = None) -> str:
    moment = value or datetime.now(UTC)
    if moment.tzinfo is None:
        raise validation(["body", "reviewed_at"], "时间需要包含时区信息")
    moment = moment.astimezone(UTC)
    if moment > datetime.now(UTC) + timedelta(minutes=5):
        raise validation(["body", "reviewed_at"], "不能超过当前时间 5 分钟")
    return utc_text(moment)


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def add_days(value: str, days: int) -> str:
    return utc_text(parse_utc(value) + timedelta(days=days))


def interval_for_known(consecutive_known: int) -> int:
    return (1, 3, 7, 14, 30)[min(max(consecutive_known, 1), 5) - 1]


def calculate_stats(logs: Iterable[object]) -> dict[str, object]:
    known = unknown = skipped = consecutive_known = consecutive_unknown = 0
    last_status = last_reviewed_at = None
    last_effective_status = last_effective_reviewed_at = None
    interval_days = 0
    due_at = None
    for log in logs:
        status = str(log.status)
        reviewed_at = str(log.reviewed_at)
        last_status = status
        last_reviewed_at = reviewed_at
        if status == "skipped":
            skipped += 1
            continue
        last_effective_status = status
        last_effective_reviewed_at = reviewed_at
        if status == "unknown":
            unknown += 1
            consecutive_unknown += 1
            consecutive_known = 0
            interval_days = 1
        else:
            known += 1
            consecutive_known += 1
            consecutive_unknown = 0
            interval_days = interval_for_known(consecutive_known)
        due_at = add_days(reviewed_at, interval_days)
    return {
        "known_count": known,
        "unknown_count": unknown,
        "skipped_count": skipped,
        "consecutive_known": consecutive_known,
        "consecutive_unknown": consecutive_unknown,
        "last_status": last_status,
        "last_reviewed_at": last_reviewed_at,
        "last_effective_status": last_effective_status,
        "last_effective_reviewed_at": last_effective_reviewed_at,
        "interval_days": interval_days,
        "due_at": due_at,
    }
