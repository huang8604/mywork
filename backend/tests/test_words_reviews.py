from __future__ import annotations

import json

from sqlalchemy import select, text

from app.api.words import _decode_safe_csv, _safe_csv
from app.core.config import get_settings
from app.models import ReviewLog, WordStats
from app.services.dictionary import clear_dictionary_cache
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
    # Re-creating a soft-deleted word restores it (same id, undeleted) instead
    # of failing with WORD_DELETED.
    recreated = client.post("/api/v1/words", json=word_payload)
    assert recreated.status_code == 201
    assert recreated.json()["data"]["id"] == word["id"]
    assert recreated.json()["data"]["deleted_at"] is None

    # The explicit /restore endpoint still works on a freshly deleted word.
    current2 = recreated.json()["data"]
    client.delete(
        f"/api/v1/words/{word['id']}",
        headers={"If-Match": f'"{current2["version"]}"'},
    )
    restored = client.post(
        f"/api/v1/words/{word['id']}/restore",
        json={"expected_version": current2["version"] + 1},
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["deleted_at"] is None


def test_word_create_and_txt_import_reject_non_english_values(client):
    direct = client.post("/api/v1/words", json={"en_word": "中文", "cn_meaning": "错误"})
    assert direct.status_code == 422
    imported = client.post(
        "/api/v1/words/import",
        files={"file": ("words.txt", "valid\n中文\n".encode(), "text/plain")},
        data={"conflict_policy": "reject"},
    )
    assert imported.status_code == 422
    assert client.get("/api/v1/words?keyword=valid").json()["data"] == []


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
        "formula,,公式词,,false,basic\n"
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
    assert "formula" in exported.text
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


def test_import_skip_policy_dedupes_in_file_duplicates(client):
    rows = [
        {"en_word": "warm", "cn_meaning": "暖", "is_custom": False, "tags": []},
        {"en_word": "warm", "cn_meaning": "暖", "is_custom": False, "tags": []},
    ]
    skipped_resp = client.post(
        "/api/v1/words/import",
        files={"file": ("words.json", json.dumps(rows).encode(), "application/json")},
        data={"conflict_policy": "skip"},
    )
    assert skipped_resp.status_code == 200, skipped_resp.text
    summary = skipped_resp.json()["data"]
    assert (summary["created"], summary["skipped"], summary["total"]) == (1, 1, 2)

    rejected = client.post(
        "/api/v1/words/import",
        files={
            "file": (
                "words.json",
                json.dumps(
                    [
                        {"en_word": "hot", "cn_meaning": "热", "is_custom": False, "tags": []},
                        {"en_word": "hot", "cn_meaning": "热", "is_custom": False, "tags": []},
                    ]
                ).encode(),
                "application/json",
            )
        },
        data={"conflict_policy": "reject"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["message"] == "导入文件内存在重复单词"


def test_import_unresolved_policy_skip_avoids_zero_write(client, monkeypatch, tmp_path):
    # No dictionary configured: a word with cn_meaning still imports; a word
    # without one is "unresolved". Under skip the rest imports (no zero-write);
    # under reject (default) the whole batch still aborts.
    monkeypatch.setenv("DICTIONARY_INDEX_PATH", str(tmp_path / "missing.json"))
    get_settings.cache_clear()
    clear_dictionary_cache()
    try:
        rows = [
            {"en_word": "warm", "cn_meaning": "暖", "is_custom": False, "tags": []},
            {"en_word": "flibbertigibbet", "is_custom": False, "tags": []},
        ]
        skipped = client.post(
            "/api/v1/words/import",
            files={"file": ("words.json", json.dumps(rows).encode(), "application/json")},
            data={"conflict_policy": "reject", "unresolved_policy": "skip"},
        )
        assert skipped.status_code == 200, skipped.text
        summary = skipped.json()["data"]
        assert (summary["created"], summary["unresolved"], summary["total"]) == (1, 1, 2)
        assert summary["unresolved_words"] == ["flibbertigibbet"]
        assert client.get("/api/v1/words?keyword=warm").json()["data"]

        rejected = client.post(
            "/api/v1/words/import",
            files={"file": ("words.json", json.dumps(rows).encode(), "application/json")},
            data={"conflict_policy": "reject"},
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "DICTIONARY_ENTRY_NOT_FOUND"
    finally:
        get_settings.cache_clear()
        clear_dictionary_cache()


def test_shorten_translations_drops_surnames_glosses_and_caps_length():
    from app.services.dictionary import shorten_translations

    # surname sense dropped, primary sense kept
    camera = [
        {"pos": "n.", "cn": "照相机；摄影机"},
        {"pos": "n.", "cn": "（Camera）人名；（英、意、西）卡梅拉"},
    ]
    assert shorten_translations(camera) == "n. 照相机；摄影机"

    # English parenthetical gloss stripped
    laptop = [{"pos": "n.", "cn": "膝上型计算机，便携式电脑（=laptop computer）"}]
    assert shorten_translations(laptop) == "n. 膝上型计算机，便携式电脑"

    # length cap truncates on a ；boundary and adds an ellipsis
    long_cn = "；".join("释义文字" for _ in range(20))
    capped = shorten_translations([{"pos": "n.", "cn": long_cn}])
    assert len(capped) <= 40 and capped.endswith("…")

    # max_senses limits the number of kept senses
    many = [{"pos": "n.", "cn": c} for c in ("甲等", "乙等", "丙等", "丁等", "戊等")]
    assert shorten_translations(many, max_senses=2) == "n. 甲等；n. 乙等"

    # an entry whose every sense is a surname falls back to the raw sense
    fallback = shorten_translations([{"pos": "n.", "cn": "（Foo）人名"}])
    assert fallback is not None and "人名" in fallback


def test_import_restores_deleted_word(client, word_payload):
    word = create_word(client, word_payload)
    current = client.get(f"/api/v1/words/{word['id']}").json()["data"]
    deleted = client.delete(
        f"/api/v1/words/{word['id']}",
        headers={"If-Match": f'"{current["version"]}"'},
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/words/{word['id']}").status_code == 404

    # Re-importing a soft-deleted word restores it instead of failing with
    # WORD_DELETED — cn_meaning is supplied so enrichment passes without AI.
    rows = [
        {
            "en_word": word["en_word"],
            "cn_meaning": word["cn_meaning"],
            "is_custom": False,
            "tags": [],
        }
    ]
    resp = client.post(
        "/api/v1/words/import",
        files={"file": ("words.json", json.dumps(rows).encode(), "application/json")},
        data={"conflict_policy": "reject"},
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()["data"]
    assert summary["updated"] == 1
    assert summary["created"] == 0
    restored = client.get(f"/api/v1/words/{word['id']}").json()["data"]
    assert restored["deleted_at"] is None


def test_create_uses_ai_fallback_when_configured(client, monkeypatch, tmp_path):
    # No local dictionary + AI configured: an unknown word is enriched by AI.
    monkeypatch.setenv("DICTIONARY_INDEX_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("AI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_MODEL", "test-model")
    get_settings.cache_clear()
    clear_dictionary_cache()

    def fake_ai(word):
        return {
            "cn_meaning": "测试的释义",
            "phonetic": "/tɛst/",
            "example_sentence": "This is a test sentence.",
        }

    monkeypatch.setattr("app.services.dictionary.ai_enrich_word", fake_ai)
    try:
        created = client.post("/api/v1/words", json={"en_word": "syzygy"})
        assert created.status_code == 201, created.text
        data = created.json()["data"]
        assert data["cn_meaning"] == "测试的释义"
        assert data["phonetic"] == "/tɛst/"
        assert data["example_sentence"] == "This is a test sentence."

        # When AI returns nothing, the word degrades to unresolved (422).
        monkeypatch.setattr("app.services.dictionary.ai_enrich_word", lambda w: None)
        failed = client.post("/api/v1/words", json={"en_word": "other"})
        assert failed.status_code == 422
        assert failed.json()["code"] == "DICTIONARY_ENTRY_NOT_FOUND"
    finally:
        get_settings.cache_clear()
        clear_dictionary_cache()


def test_import_ai_policy_resolves_unresolved_words(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DICTIONARY_INDEX_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("AI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    get_settings.cache_clear()
    clear_dictionary_cache()
    monkeypatch.setattr(
        "app.services.dictionary.ai_enrich_word",
        lambda w: {"cn_meaning": "AI 释义", "phonetic": None, "example_sentence": None},
    )
    try:
        rows = [{"en_word": "syzygy", "is_custom": False, "tags": []}]
        resp = client.post(
            "/api/v1/words/import",
            files={"file": ("words.json", json.dumps(rows).encode(), "application/json")},
            data={"conflict_policy": "reject", "unresolved_policy": "ai"},
        )
        assert resp.status_code == 200, resp.text
        summary = resp.json()["data"]
        assert summary["created"] == 1
        assert summary["unresolved"] == 0
    finally:
        get_settings.cache_clear()
        clear_dictionary_cache()


def test_english_only_create_preview_and_txt_import_use_local_dictionary(
    client, tmp_path, monkeypatch
):
    dictionary = tmp_path / "dictionary-index.json"
    dictionary.write_text(
        json.dumps(
            {
                "abandon": {
                    "w": "abandon",
                    "p0": "əˈbændən",
                    "p1": "",
                    "t": [{"pos": "v.", "cn": "放弃；抛弃"}],
                    "s": [{"c": "Never abandon hope.", "cn": "永远不要放弃希望。"}],
                },
                "camera": {
                    "w": "camera",
                    "p0": "ˈkæmərə",
                    "p1": "",
                    "t": [{"pos": "n.", "cn": "照相机"}],
                    "s": [{"c": "She bought a camera.", "cn": "她买了一台相机。"}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DICTIONARY_INDEX_PATH", str(dictionary))
    get_settings.cache_clear()
    clear_dictionary_cache()
    try:
        preview = client.post("/api/v1/words/enrich", json={"words": ["Abandon"]})
        assert preview.status_code == 200, preview.text
        assert preview.json()["data"][0] == {
            "en_word": "Abandon",
            "phonetic": "əˈbændən",
            "cn_meaning": "v. 放弃；抛弃",
            "example_sentence": "Never abandon hope.",
            "is_custom": False,
            "tags": [],
            "dictionary_found": True,
            "source": "dictionary-index",
            "missing_fields": [],
        }

        created = client.post("/api/v1/words", json={"en_word": "abandon"})
        assert created.status_code == 201, created.text
        assert created.json()["data"]["cn_meaning"] == "v. 放弃；抛弃"

        imported = client.post(
            "/api/v1/words/import",
            files={"file": ("words.txt", b"camera\n", "text/plain")},
            data={"conflict_policy": "reject", "dry_run": "false"},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["data"]["dictionary_matches"] == 1
        camera = client.get("/api/v1/words?keyword=camera").json()["data"][0]
        assert camera["example_sentence"] == "She bought a camera."

        unresolved = client.post("/api/v1/words", json={"en_word": "not-in-dictionary"})
        assert unresolved.status_code == 422
        assert unresolved.json()["code"] == "DICTIONARY_ENTRY_NOT_FOUND"
    finally:
        get_settings.cache_clear()
        clear_dictionary_cache()


def test_csv_formula_protection_is_reversible():
    values = ["=SUM(A1:A2)", " +command", "-1", "@mention", "'literal", "plain"]
    for value in values:
        assert _decode_safe_csv(_safe_csv(value)) == value


def test_enrich_preview_supports_ai_fallback(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DICTIONARY_INDEX_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("AI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    get_settings.cache_clear()
    clear_dictionary_cache()
    monkeypatch.setattr(
        "app.services.dictionary.ai_enrich_word",
        lambda w: {"cn_meaning": "AI 释义", "phonetic": "/x/", "example_sentence": "an example"},
    )
    try:
        resp = client.post("/api/v1/words/enrich", json={"words": ["syzygy"], "allow_ai": True})
        assert resp.status_code == 200, resp.text
        draft = resp.json()["data"][0]
        assert draft["source"] == "ai"
        assert draft["dictionary_found"] is False
        assert draft["cn_meaning"] == "AI 释义"
        assert draft["phonetic"] == "/x/"

        # Without allow_ai the same unresolved word gets no source.
        plain = client.post("/api/v1/words/enrich", json={"words": ["syzygy"]})
        assert plain.json()["data"][0]["source"] is None
    finally:
        get_settings.cache_clear()
        clear_dictionary_cache()


def test_recitation_md_and_pdf_export(client):
    import pytest

    word = create_word(client)
    gen = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "gen-recitation"},
        json={
            "new_words_limit": 0,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "word_ids": [word["id"]],
        },
    )
    assert gen.status_code == 201, gen.text
    session_id = gen.json()["data"]["session_id"]

    md = client.get(f"/api/v1/practice-sessions/{session_id}/recitation?format=md")
    assert md.status_code == 200, md.text
    assert "text/markdown" in md.headers["content-type"]
    assert "|单词|音标|中文|例句|" in md.text
    assert word["en_word"] in md.text

    pytest.importorskip("weasyprint")
    pdf = client.get(f"/api/v1/practice-sessions/{session_id}/recitation?format=pdf")
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")


def _session_with_word(client, *, key):
    word = create_word(client)
    gen = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": key},
        json={
            "new_words_limit": 0,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "word_ids": [word["id"]],
        },
    )
    assert gen.status_code == 201, gen.text
    return gen.json()["data"]


def test_update_session_title_and_note_with_version_check(client):
    session = _session_with_word(client, key="gen-update-session")
    sid = session["session_id"]
    version = session["version"]
    updated = client.patch(
        f"/api/v1/practice-sessions/{sid}",
        json={"title": "考前冲刺", "note": "重点复习", "expected_version": version},
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["title"] == "考前冲刺"
    assert data["note"] == "重点复习"
    assert data["version"] == version + 1
    assert client.get(f"/api/v1/practice-sessions/{sid}").json()["data"]["title"] == "考前冲刺"

    stale = client.patch(
        f"/api/v1/practice-sessions/{sid}",
        json={"title": "旧版本", "expected_version": version},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"


def test_delete_session_removes_reviews_and_rebuilds_stats(client, db_session):
    session = _session_with_word(client, key="gen-delete-session")
    sid = session["session_id"]
    item_id = session["items"][0]["item_id"]
    word_id = session["items"][0]["word_id"]

    rnd = client.post(
        f"/api/v1/practice-sessions/{sid}/review-rounds",
        headers={"Idempotency-Key": "round-delete"},
        json={"mode": "offline"},
    )
    assert rnd.status_code == 201, rnd.text
    rid = rnd.json()["data"]["round_id"]
    batch = client.put(
        f"/api/v1/practice-review-rounds/{rid}/results",
        headers={"Idempotency-Key": "batch-delete"},
        json={"items": [{"item_id": item_id, "status": "known", "client_event_id": "del-ev-1"}]},
    )
    assert batch.status_code == 200, batch.text
    assert db_session.get(WordStats, word_id).known_count == 1

    # Creating the round + saving results bumps the session version; re-read it.
    current_version = client.get(f"/api/v1/practice-sessions/{sid}").json()["data"]["version"]
    deleted = client.delete(f"/api/v1/practice-sessions/{sid}?expected_version={current_version}")
    assert deleted.status_code == 204

    db_session.expire_all()
    assert client.get(f"/api/v1/practice-sessions/{sid}").status_code == 404
    assert db_session.scalar(select(ReviewLog).where(ReviewLog.word_id == word_id)) is None
    assert db_session.get(WordStats, word_id).known_count == 0
