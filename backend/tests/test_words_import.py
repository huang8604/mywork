from __future__ import annotations

from app.core.config import get_settings
from app.services import dictionary as dict_mod
from app.services.dictionary import clear_dictionary_cache


def test_import_returns_resolved_word_ids(client, monkeypatch):
    # Pre-create "camera" so the import's conflict_policy=skip skips it. Going
    # through the HTTP endpoint (rather than the service directly) keeps the
    # row visible to the client's request cycle without session/transaction
    # surprises. cn_meaning is supplied so enrichment passes without the index.
    pre = client.post(
        "/api/v1/words",
        json={"en_word": "camera", "cn_meaning": "相机", "is_custom": False, "tags": []},
    )
    assert pre.status_code == 201, pre.text
    camera_id = pre.json()["data"]["id"]

    # Provide dictionary entries so the txt import (which carries no cn_meaning)
    # can enrich both words without depending on the real (git-ignored) index.
    monkeypatch.setattr(
        dict_mod,
        "_load_index",
        lambda path: {
            "camera": {"t": [{"pos": "n.", "cn": "照相机"}]},
            "focus": {"t": [{"pos": "n.", "cn": "焦点"}]},
        },
    )

    resp = client.post(
        "/api/v1/words/import",
        files={"file": ("words.txt", b"camera\nfocus\n", "text/plain")},
        data={"conflict_policy": "skip", "unresolved_policy": "skip"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    resolved = data["resolved"]
    by_word = {r["en_word"]: r for r in resolved}
    assert by_word["camera"]["action"] == "skipped"
    assert by_word["camera"]["word_id"] == camera_id
    assert by_word["focus"]["action"] == "created"
    assert isinstance(by_word["focus"]["word_id"], int)
    # focus got a real new id different from camera's
    assert by_word["focus"]["word_id"] != camera_id


def test_import_in_file_duplicate_resolved_reports_first_id(client, monkeypatch):
    # An in-file duplicate under conflict_policy=skip is counted as skipped and
    # the resolved entry reuses the first occurrence's word_id.
    monkeypatch.setattr(
        dict_mod,
        "_load_index",
        lambda path: {"focus": {"t": [{"pos": "n.", "cn": "焦点"}]}},
    )
    resp = client.post(
        "/api/v1/words/import",
        files={"file": ("words.txt", b"focus\nFOCUS\n", "text/plain")},
        data={"conflict_policy": "skip", "unresolved_policy": "skip"},
    )
    assert resp.status_code == 200, resp.text
    resolved = resp.json()["data"]["resolved"]
    by_word = {r["en_word"]: r for r in resolved}
    assert by_word["focus"]["action"] == "created"
    first_id = by_word["focus"]["word_id"]
    assert isinstance(first_id, int)
    assert by_word["FOCUS"]["action"] == "skipped"
    assert by_word["FOCUS"]["word_id"] == first_id


def test_import_marks_unresolved_dropped_words(client, monkeypatch, tmp_path):
    # No dictionary entry and AI disabled → the word is dropped under
    # unresolved_policy=skip and surfaces in resolved[] with action=unresolved.
    monkeypatch.setenv("DICTIONARY_INDEX_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("AI_BASE_URL", "")
    monkeypatch.setenv("AI_API_KEY", "")
    get_settings.cache_clear()
    clear_dictionary_cache()
    try:
        resp = client.post(
            "/api/v1/words/import",
            files={"file": ("words.txt", b"syzygy\n", "text/plain")},
            data={"conflict_policy": "skip", "unresolved_policy": "skip"},
        )
        assert resp.status_code == 200, resp.text
        resolved = resp.json()["data"]["resolved"]
        assert len(resolved) == 1
        assert resolved[0]["en_word"] == "syzygy"
        assert resolved[0]["action"] == "unresolved"
        assert resolved[0]["word_id"] is None
    finally:
        get_settings.cache_clear()
        clear_dictionary_cache()
