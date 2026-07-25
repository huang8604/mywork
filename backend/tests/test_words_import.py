from __future__ import annotations

from app.core.config import get_settings
from app.services import dictionary as dict_mod
from app.services.dictionary import clear_dictionary_cache


def _patch_index(monkeypatch, mapping: dict) -> None:
    monkeypatch.setattr(
        dict_mod,
        "_load_index",
        lambda path: mapping,
    )


def test_dry_run_returns_synchronous_preview(client, monkeypatch):
    # dry_run stays synchronous: it predicts actions without writing.
    _patch_index(
        monkeypatch,
        {"camera": {"t": [{"pos": "n.", "cn": "照相机"}]}, "focus": {"t": [{"pos": "n.", "cn": "焦点"}]}},
    )
    pre = client.post(
        "/api/v1/words",
        json={"en_word": "camera", "cn_meaning": "相机", "is_custom": False, "tags": []},
    )
    assert pre.status_code == 201, pre.text

    resp = client.post(
        "/api/v1/words/import",
        files={"file": ("words.txt", b"camera\nfocus\n", "text/plain")},
        data={"conflict_policy": "skip", "unresolved_policy": "skip", "dry_run": "true"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["dry_run"] is True
    by_word = {r["en_word"]: r for r in data["resolved"]}
    assert by_word["camera"]["action"] == "skipped"
    assert by_word["focus"]["action"] == "created"
    # dry-run never writes, so a would-be-created row has no id yet.
    assert by_word["focus"]["word_id"] is None


def test_real_import_enqueues_and_returns_running(client, monkeypatch):
    _patch_index(monkeypatch, {"focus": {"t": [{"pos": "n.", "cn": "焦点"}]}})

    import app.api.words as words_api

    captured: dict[str, object] = {}

    def fake_enqueue(payloads, *, conflict_policy, unresolved_policy, actor_type, actor_id, request_id, idempotency_key):
        captured["payloads"] = payloads
        captured["conflict_policy"] = conflict_policy
        captured["unresolved_policy"] = unresolved_policy
        return len(payloads)

    def fake_progress():
        return {"state": "running", "total": 1, "processed": 0}

    monkeypatch.setattr(words_api, "enqueue_import", fake_enqueue)
    monkeypatch.setattr(words_api, "import_progress", fake_progress)

    resp = client.post(
        "/api/v1/words/import",
        files={"file": ("words.txt", b"focus\n", "text/plain")},
        data={"conflict_policy": "update", "unresolved_policy": "ai"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["state"] == "running"
    assert data["total"] == 1
    assert captured["conflict_policy"] == "update"
    assert captured["unresolved_policy"] == "ai"
    assert [p.en_word for p in captured["payloads"]] == ["focus"]


def test_import_merges_default_tags_into_rows(client, monkeypatch):
    _patch_index(monkeypatch, {"focus": {"t": [{"pos": "n.", "cn": "焦点"}]}})

    import app.api.words as words_api

    captured: dict[str, object] = {}

    def fake_enqueue(payloads, **_kwargs):
        captured["payloads"] = payloads
        return len(payloads)

    monkeypatch.setattr(words_api, "enqueue_import", fake_enqueue)
    monkeypatch.setattr(words_api, "import_progress", lambda: {"state": "running", "total": 1})

    resp = client.post(
        "/api/v1/words/import",
        files={"file": ("words.txt", b"focus\n", "text/plain")},
        data={"conflict_policy": "update", "tags": "基础, 词汇"},
    )
    assert resp.status_code == 200, resp.text
    [payload] = captured["payloads"]
    # comma + space trimmed, merged into the row's tags.
    assert payload.tags == ["基础", "词汇"]


def test_reject_prescan_refuses_existing_word(client, monkeypatch):
    _patch_index(monkeypatch, {"camera": {"t": [{"pos": "n.", "cn": "照相机"}]}})
    pre = client.post(
        "/api/v1/words",
        json={"en_word": "camera", "cn_meaning": "相机", "is_custom": False, "tags": []},
    )
    assert pre.status_code == 201, pre.text

    import app.api.words as words_api

    called = {"enqueue": False}
    monkeypatch.setattr(
        words_api, "enqueue_import", lambda *a, **k: called.__setitem__("enqueue", True) or 1
    )

    resp = client.post(
        "/api/v1/words/import",
        files={"file": ("words.txt", b"camera\n", "text/plain")},
        data={"conflict_policy": "reject"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "DUPLICATE_WORD"
    # Nothing was enqueued — zero writes guaranteed by the pre-scan.
    assert called["enqueue"] is False


def test_dry_run_marks_unresolved_dropped_words(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DICTIONARY_INDEX_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("AI_BASE_URL", "")
    monkeypatch.setenv("AI_API_KEY", "")
    get_settings.cache_clear()
    clear_dictionary_cache()
    try:
        resp = client.post(
            "/api/v1/words/import",
            files={"file": ("words.txt", b"syzygy\n", "text/plain")},
            data={"conflict_policy": "skip", "unresolved_policy": "skip", "dry_run": "true"},
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
