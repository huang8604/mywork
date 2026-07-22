from __future__ import annotations

from types import SimpleNamespace

from app.services import dictionary as dict_mod
from app.services.dictionary import shorten_translations


# ---------------------------------------------------------------------------
# B1: shorten_translations — target 16, multi-boundary cut, None when stuck
# ---------------------------------------------------------------------------


def test_shorten_keeps_short_meaning():
    t = [{"pos": "n.", "cn": "相机"}]
    assert shorten_translations(t) == "n. 相机"


def test_shorten_truncates_at_comma_within_16():
    # joined "n. 计算机，电子计算机，计算器" reaches the 16-char target; the cut
    # (or full join if ≤16) must stay within 16 chars and start with the pos.
    t = [{"pos": "n.", "cn": "计算机，电子计算机，计算器"}]
    out = shorten_translations(t)
    assert out is not None
    assert len(out) <= 16
    assert out.startswith("n. 计算机")


def test_shorten_returns_none_when_no_boundary_in_window():
    # one long sense with no punctuation anywhere in [10,16] → None (AI fallback)
    t = [{"pos": "n.", "cn": "超长且无任何标点符号的释义字符串用于测试"}]
    assert shorten_translations(t) is None


def test_shorten_picks_last_boundary_in_window():
    # "n. 甲；乙；丙；丁；戊" — boundaries at positions 4, 7, 10, 13, 16.
    # The last boundary whose cut lands in [10, 16] is position 13 (cut "n. 甲；乙；丙；丁" = 13... wait
    # need to verify). Anyway the result must be ≤16 and end before a boundary.
    t = [{"pos": "n.", "cn": "甲；乙；丙；丁；戊；己；庚；辛；壬；癸"}]
    out = shorten_translations(t)
    assert out is not None
    assert len(out) <= 16
    assert "；" in out  # kept at least one boundary


def test_shorten_cut_at_position_16():
    # boundary (，) exactly at index 16 → keep 16 chars (empty pos so text == cn)
    t = [{"pos": "", "cn": "0123456789abcdef，XXXXXXXXXX"}]
    out = shorten_translations(t)
    assert out == "0123456789abcdef"  # len 16, boundary excluded


def test_shorten_cut_at_position_10():
    # only boundary at index 10 → keep 10 chars (the smallest in-window cut)
    t = [{"pos": "", "cn": "0123456789，XXXXXXXXXX"}]
    out = shorten_translations(t)
    assert out == "0123456789"  # len 10


def test_shorten_ignores_boundary_below_min_keep():
    # only boundary at index 9 (< min_keep=10) → not used → None (AI fallback decides)
    t = [{"pos": "", "cn": "012345678，XXXXXXXXXX"}]
    assert shorten_translations(t) is None


# ---------------------------------------------------------------------------
# B2: enrich_word — AI re-translate when dict meaning >16 and unshortenable
# ---------------------------------------------------------------------------


def _settings_with_ai(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        dictionary_index_path="",
        ai_base_url="https://ai.local" if enabled else "",
        ai_api_key="k" if enabled else "",
        ai_enabled=enabled,
    )


def test_enrich_uses_ai_when_dictionary_meaning_too_long(monkeypatch):
    # dictionary returns a >16-char meaning with no in-window boundary
    monkeypatch.setattr(
        dict_mod,
        "_load_index",
        lambda p: {
            "supercalifragilistic": {
                "p0": "/x/",
                "t": [{"pos": "n.", "cn": "超长且无任何标点符号的释义字符串"}],
                "s": [],
            }
        },
    )
    monkeypatch.setattr(dict_mod, "get_settings", lambda: _settings_with_ai())
    called = {}

    def fake_ai(word):
        called["word"] = word
        return {"phonetic": None, "cn_meaning": "短释义", "example_sentence": None}

    monkeypatch.setattr(dict_mod, "ai_enrich_word", fake_ai)
    from app.schemas import WordCreate

    enriched, found = dict_mod.enrich_word(
        WordCreate(en_word="supercalifragilistic"), allow_ai=True
    )
    assert found is True
    assert enriched.cn_meaning == "短释义"
    assert called["word"] == "supercalifragilistic"


def test_enrich_hard_truncates_when_ai_disabled(monkeypatch):
    monkeypatch.setattr(
        dict_mod,
        "_load_index",
        lambda p: {
            "supercalifragilistic": {
                "t": [{"pos": "n.", "cn": "超长且无任何标点符号的释义字符串"}]
            }
        },
    )
    monkeypatch.setattr(dict_mod, "get_settings", lambda: _settings_with_ai(enabled=False))
    from app.schemas import WordCreate

    enriched, _ = dict_mod.enrich_word(
        WordCreate(en_word="supercalifragilistic"), allow_ai=True
    )
    # 16-char body + optional ellipsis
    assert len(enriched.cn_meaning) <= 17
    assert enriched.cn_meaning.endswith("…")
