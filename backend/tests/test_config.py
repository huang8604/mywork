from __future__ import annotations

import pytest

from app.core.config import Settings


def test_ai_api_key_file_takes_precedence_over_inline_env(monkeypatch, tmp_path) -> None:
    secret_file = tmp_path / "ai-api-key"
    secret_file.write_text("  file-secret-key\n", encoding="utf-8")
    monkeypatch.setenv("AI_BASE_URL", "https://ai.example.test/v1/")
    monkeypatch.setenv("AI_API_KEY", "inline-secret-key")
    monkeypatch.setenv("AI_API_KEY_FILE", str(secret_file))

    settings = Settings.from_env()

    assert settings.ai_api_key_file == str(secret_file)
    assert settings.ai_api_key == "file-secret-key"
    assert settings.ai_base_url == "https://ai.example.test/v1"
    assert settings.ai_enabled is True


def test_ai_api_key_file_rejects_empty_secret(monkeypatch, tmp_path) -> None:
    secret_file = tmp_path / "ai-api-key"
    secret_file.write_text(" \n", encoding="utf-8")
    monkeypatch.setenv("AI_BASE_URL", "https://ai.example.test/v1")
    monkeypatch.setenv("AI_API_KEY_FILE", str(secret_file))

    with pytest.raises(ValueError, match="AI_API_KEY_FILE must not be empty"):
        Settings.from_env()
