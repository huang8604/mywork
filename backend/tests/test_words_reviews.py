from __future__ import annotations

import io
import json

from sqlalchemy import text

from app.api.words import _decode_safe_csv, _safe_csv
from conftest import create_word


def test_sqlite_pragmas_are_enabled(db_session):
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    assert db_session.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
    assert db_session.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000


def test_word_crud_soft_delete_restore_and_global_uniqueness(client, word_payload):
    word = create_word(client, word_payload)
    duplicate = client.post(
        "/api/v1/words",
        json={**word_payload, "en_word": "  warm  "},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "DUPLICATE_WORD"

    updated = client.put(
        f"/api/v1/words/{word['id']}",
        json={**word_payload, "cn_meaning": "暖和的", "expected_version": word["version"]},
    )
    assert updated.status_code == 200
    current = updated.json()["data"]
    deleted = client.delete(
        f"/api/v1/words/{word['id']}",
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/words/{word['id']}").status_code == 404
    deleted_duplicate = client.post("/api/v1/words", json=word_payload)
    assert deleted_duplicate.status_code == 409
    assert deleted_duplicate.json()["code"] == "WORD_DELETED"

    version = current["version"] + 1
    restored = client.post(
        f"/api/v1/words/{word['id']}/restore",
        json={"expected_version": version},
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["deleted_at"] is None


def test_quick_reviews_are_idempotent_and_correction_rebuilds_stats(client):
    word = create_word(client)
    event = {
        "word_id": word["id"],
        "status": "known",
        "source": "quick_review",
        "client_event_id": "event-1",
        "reviewed_at": "2026-07-01T00:00:00Z",
    }
    first = client.post("/api/v1/reviews", json=event)
    assert first.status_code == 201
    replay = client.post("/api/v1/reviews", json=event)
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    log = first.json()["data"]
    assert log["stats"]["known_count"] == 1

    correction = client.patch(
        f"/api/v1/reviews/{log['id']}",
        json={
            "status": "unknown",
            "client_event_id": "event-1",
            "expected_version": log["version"],
            "reviewed_at": "2026-07-01T00:00:00Z",
        },
    )
    assert correction.status_code == 200
    corrected = correction.json()["data"]
    assert corrected["id"] == log["id"]
    assert corrected["version"] == 2
    assert corrected["stats"]["known_count"] == 0
    assert corrected["stats"]["unknown_count"] == 1
    stale = client.patch(
        f"/api/v1/reviews/{log['id']}",
        json={
            "status": "known",
            "client_event_id": "event-1",
            "expected_version": 1,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"


def test_atomic_import_and_safe_csv_export(client):
    raw = (
        "en_word,phonetic,cn_meaning,example_sentence,is_custom,tags\n"
        "=formula,,公式词,,false,basic\n"
        "horse,,马,,true,animal\n"
    ).encode()
    response = client.post(
        "/api/v1/words/import",
        files={"file": ("words.csv", raw, "text/csv")},
        data={"conflict_policy": "reject", "dry_run": "false"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["created"] == 2
    exported = client.get("/api/v1/words/export?format=csv")
    assert exported.status_code == 200
    assert exported.content.startswith(b"\xef\xbb\xbf")
    assert "'=formula" in exported.text
    json_export = client.get("/api/v1/words/export?format=json&tag=animal")
    assert json_export.status_code == 200
    json_words = json.loads(json_export.content)
    assert [item["en_word"] for item in json_words] == ["horse"]

    invalid = client.post(
        "/api/v1/words/import",
        files={
            "file": (
                "words.json",
                b'[{"en_word":"valid","cn_meaning":"ok"},{"en_word":"","cn_meaning":"bad"}]',
                "application/json",
            )
        },
        data={"conflict_policy": "reject"},
    )
    assert invalid.status_code == 422
    words = client.get("/api/v1/words?keyword=valid").json()["data"]
    assert words == []


def test_csv_formula_protection_is_reversible():
    values = ["=SUM(A1:A2)", " +command", "-1", "@mention", "'literal", "plain"]
    for value in values:
        assert _decode_safe_csv(_safe_csv(value)) == value
