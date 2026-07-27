from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _skill_module():
    path = Path(__file__).resolve().parents[2] / "skills" / "add-words" / "scripts" / "add_words.py"
    spec = importlib.util.spec_from_file_location("add_words_skill", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_add_words_skill_previews_and_writes_without_exposing_token(monkeypatch, capsys):
    module = _skill_module()
    calls = []

    def fake_request(base_url, token, path, payload):
        calls.append((base_url, token, path, payload))
        if path == "/words/enrich":
            return {
                "data": [
                    {
                        "en_word": payload["words"][0],
                        "phonetic": "test",
                        "cn_meaning": "测试",
                        "example_sentence": "A test sentence.",
                        "is_custom": False,
                        "tags": [],
                        "dictionary_found": True,
                        "source": "dictionary-index",
                        "missing_fields": [],
                    }
                ]
            }
        return {"data": {"id": 1, **payload}}

    monkeypatch.setattr(module, "api_request", fake_request)
    monkeypatch.setenv("WORD_MEMORY_BASE_URL", "https://words.example")
    monkeypatch.setenv("WORD_MEMORY_API_TOKEN", "secret-token-must-not-leak")
    monkeypatch.setattr(sys, "argv", ["add_words.py", "Abandon", "--tag", "CET4"])

    assert module.main() == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["created"][0]["en_word"] == "Abandon"
    assert calls[1][3]["tags"] == ["CET4"]
    assert "secret-token-must-not-leak" not in output


def test_add_words_skill_uses_manual_meaning_and_only_classifies_duplicate_code(
    monkeypatch, capsys
):
    module = _skill_module()
    calls = []

    def fake_request(base_url, token, path, payload):
        calls.append((path, payload))
        if path == "/words/enrich":
            return {
                "data": [
                    {"en_word": "nonceword", "missing_fields": ["cn_meaning"]},
                    {"en_word": "camera", "missing_fields": []},
                    {"en_word": "abandon", "missing_fields": []},
                ]
            }
        if payload["en_word"] == "camera":
            raise module.ApiFailure(
                409,
                {"code": "DUPLICATE_WORD", "message": "exists", "request_id": "req-dup"},
            )
        if payload["en_word"] == "abandon":
            raise module.ApiFailure(
                409,
                {"code": "REQUEST_IN_PROGRESS", "message": "wait", "request_id": "req-wait"},
            )
        return {"data": {"id": 1, **payload}}

    monkeypatch.setattr(module, "api_request", fake_request)
    monkeypatch.setenv("WORD_MEMORY_BASE_URL", "https://words.example")
    monkeypatch.setenv("WORD_MEMORY_API_TOKEN", "secret-token-must-not-leak")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "add_words.py",
            "nonceword",
            "camera",
            "abandon",
            "--meaning",
            "nonceword=用户释义",
        ],
    )

    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["created"][0]["cn_meaning"] == "用户释义"
    assert result["duplicates"][0]["code"] == "DUPLICATE_WORD"
    assert result["failed"][0]["code"] == "REQUEST_IN_PROGRESS"
    assert calls[1][1]["cn_meaning"] == "用户释义"


def test_add_words_skill_requires_manual_meaning_without_posting_word(monkeypatch, capsys):
    module = _skill_module()
    paths = []

    def fake_request(base_url, token, path, payload):
        paths.append(path)
        return {"data": [{"en_word": "nonceword", "missing_fields": ["cn_meaning"]}]}

    monkeypatch.setattr(module, "api_request", fake_request)
    monkeypatch.setenv("WORD_MEMORY_BASE_URL", "https://words.example")
    monkeypatch.setenv("WORD_MEMORY_API_TOKEN", "secret-token-must-not-leak")
    monkeypatch.setattr(sys, "argv", ["add_words.py", "nonceword"])

    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["failed"][0]["code"] == "MANUAL_MEANING_REQUIRED"
    assert paths == ["/words/enrich"]
