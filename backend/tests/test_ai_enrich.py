from __future__ import annotations

from types import SimpleNamespace

from app.services import ai_enrich


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        ai_base_url="https://ai.local/v1",
        ai_api_key="test-key",
        ai_model="test-model",
        ai_enabled=True,
    )


class _FakeResp:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"cn_meaning":"相机","phonetic":null,"example_sentence":null}'
                    }
                }
            ]
        }


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.captured: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, *, headers, json):
        self.captured["url"] = url
        self.captured["headers"] = headers
        self.captured["body"] = json
        return _FakeResp()


def test_prompt_requires_meaning_within_16_chars(monkeypatch):
    captured: dict = {}

    class Client(_FakeClient):
        def post(self, url, *, headers, json):
            captured["body"] = json
            return _FakeResp()

    monkeypatch.setattr(ai_enrich.httpx, "Client", Client)
    monkeypatch.setattr(ai_enrich, "get_settings", lambda: _settings())

    result = ai_enrich.ai_enrich_word("camera")
    assert result is not None
    body_text = str(captured["body"])
    assert "16" in body_text  # prompt mentions the 16-char limit


def test_ai_enrich_caps_long_meaning_to_16(monkeypatch):
    class LongResp(_FakeResp):
        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"cn_meaning":"这是一个非常非常非常非常非常非常非常长的中文释义","phonetic":null,"example_sentence":null}'
                        }
                    }
                ]
            }

    class Client(_FakeClient):
        def post(self, url, *, headers, json):
            return LongResp()

    monkeypatch.setattr(ai_enrich.httpx, "Client", Client)
    monkeypatch.setattr(ai_enrich, "get_settings", lambda: _settings())

    result = ai_enrich.ai_enrich_word("longword")
    assert result is not None
    # 16-char body + ellipsis = 17 max
    assert len(result["cn_meaning"]) <= 17
    assert result["cn_meaning"].endswith("…")


def test_ai_enrich_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(
        ai_enrich,
        "get_settings",
        lambda: SimpleNamespace(
            ai_base_url="", ai_api_key="", ai_model="m", ai_enabled=False
        ),
    )
    assert ai_enrich.ai_enrich_word("camera") is None
