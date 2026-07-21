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
