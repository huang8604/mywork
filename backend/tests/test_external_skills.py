from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _skill_module(skill: str, script: str):
    path = Path(__file__).resolve().parents[2] / "skills" / skill / "scripts" / script
    spec = importlib.util.spec_from_file_location(f"skill_{skill.replace('-', '_')}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _configure(monkeypatch):
    monkeypatch.setenv("WORD_MEMORY_BASE_URL", "https://words.example")
    monkeypatch.setenv("WORD_MEMORY_API_TOKEN", "secret-token-must-not-leak")


def test_generate_worksheet_builds_weighted_request(monkeypatch, capsys):
    module = _skill_module("generate-worksheet", "generate_worksheet.py")
    captured = {}

    def fake_request(base_url, token, payload, idempotency_key):
        captured.update(payload=payload, key=idempotency_key)
        return {"data": {"session_id": 42, "actual_counts": {"unique_total": 20}}}

    monkeypatch.setattr(module, "api_request", fake_request)
    _configure(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_worksheet.py",
            "--total-words",
            "20",
            "--new",
            "10",
            "--error",
            "5",
            "--due",
            "5",
            "--custom",
            "0",
            "--idempotency-key",
            "worksheet-test",
        ],
    )

    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert captured["payload"] == {
        "total_words": 20,
        "new_words_limit": 10,
        "error_words_limit": 5,
        "due_words_limit": 5,
        "custom_words_limit": 0,
    }
    assert captured["key"] == "worksheet-test"
    assert result["worksheet"]["session_id"] == 42


def test_import_words_waits_for_background_result(monkeypatch, capsys, tmp_path):
    module = _skill_module("import-words", "import_words.py")
    word_file = tmp_path / "words.txt"
    word_file.write_text("abandon\ncamera\n", encoding="utf-8")
    calls = []

    def fake_progress(base_url, token):
        calls.append("progress")
        return {"state": "idle", "finished": False}

    def fake_start(base_url, token, file, args, key):
        calls.append(("start", file, args.tag, key))
        return {"state": "running", "total": 2, "processed": 0, "finished": False}

    def fake_wait(base_url, token, initial, *, interval, max_wait):
        calls.append(("wait", initial["total"]))
        return {
            "state": "idle",
            "total": 2,
            "processed": 2,
            "created": 2,
            "finished": True,
        }

    monkeypatch.setattr(module, "progress_request", fake_progress)
    monkeypatch.setattr(module, "start_import", fake_start)
    monkeypatch.setattr(module, "wait_for_import", fake_wait)
    _configure(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_words.py", str(word_file), "--tag", "CET4", "--idempotency-key", "import-test"],
    )

    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert calls[0] == "progress"
    assert calls[1][2] == ["CET4"]
    assert result["progress"]["created"] == 2


def test_import_words_multipart_contains_file_and_options(tmp_path):
    module = _skill_module("import-words", "import_words.py")
    word_file = tmp_path / "words.txt"
    word_file.write_text("abandon\n", encoding="utf-8")

    body, content_type = module.multipart_body(
        word_file,
        {"conflict_policy": "skip", "unresolved_policy": "ai", "dry_run": "false"},
    )

    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="words.txt"' in body
    assert b'name="conflict_policy"' in body
    assert b"abandon" in body


def test_record_review_results_creates_round_and_submits_atomic_batch(monkeypatch, capsys):
    module = _skill_module("record-review-results", "record_review_results.py")
    calls = []

    def fake_request(base_url, token, method, path, *, payload=None, idempotency_key=None):
        calls.append((method, path, payload, idempotency_key))
        if path.endswith("/review-rounds"):
            return {"data": {"round_id": 77}}
        return {
            "data": {
                "round": {"round_id": 77, "status": "completed", "answered_count": 2},
                "items": [],
            }
        }

    monkeypatch.setattr(module, "api_request", fake_request)
    _configure(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "record_review_results.py",
            "--session-id",
            "42",
            "--result",
            "501=known",
            "--result",
            "502=unknown",
            "--operation-id",
            "review-test",
        ],
    )

    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert calls[0][1] == "/practice-sessions/42/review-rounds"
    assert calls[0][3] == "record-round:review-test"
    assert calls[1][1] == "/practice-review-rounds/77/results"
    assert calls[1][2]["items"] == [
        {
            "item_id": 501,
            "status": "known",
            "client_event_id": "record-review:review-test:501",
        },
        {
            "item_id": 502,
            "status": "unknown",
            "client_event_id": "record-review:review-test:502",
        },
    ]
    assert result["round_id"] == 77
