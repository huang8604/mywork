from __future__ import annotations

from types import SimpleNamespace

from app.services.domain import calculate_stats, normalize_tag, normalize_word


def log(status: str, reviewed_at: str):
    return SimpleNamespace(status=status, reviewed_at=reviewed_at)


def test_normalization_is_nfkc_casefold_and_whitespace_stable():
    display, normalized = normalize_word("  Ｗarm\t  UP  ")
    assert display == "Warm UP"
    assert normalized == "warm up"
    assert normalize_tag("  Basic  ") == ("Basic", "basic")


def test_three_state_interval_rules_ignore_skipped():
    values = calculate_stats(
        [
            log("known", "2026-07-01T00:00:00.000000Z"),
            log("skipped", "2026-07-02T00:00:00.000000Z"),
            log("known", "2026-07-03T00:00:00.000000Z"),
            log("unknown", "2026-07-04T00:00:00.000000Z"),
        ]
    )
    assert values["known_count"] == 2
    assert values["unknown_count"] == 1
    assert values["skipped_count"] == 1
    assert values["consecutive_known"] == 0
    assert values["consecutive_unknown"] == 1
    assert values["interval_days"] == 1
    assert values["due_at"] == "2026-07-05T00:00:00.000000Z"


def test_known_intervals_cap_at_thirty_days():
    values = calculate_stats(
        [
            log("known", f"2026-07-{day:02d}T00:00:00.000000Z")
            for day in range(1, 7)
        ]
    )
    assert values["consecutive_known"] == 6
    assert values["interval_days"] == 30
    assert values["due_at"] == "2026-08-05T00:00:00.000000Z"

