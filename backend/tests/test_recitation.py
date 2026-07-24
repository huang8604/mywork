"""Unit tests for the recitation handout builders (markdown + themed PDF)."""

from types import SimpleNamespace

import pytest

from app.services.recitation import _pdf_html, _theme, build_recitation_md, render_recitation_pdf


def _item(en, ph, cn, ex):
    return SimpleNamespace(
        snapshot_en_word=en,
        snapshot_phonetic=ph,
        snapshot_cn_meaning=cn,
        snapshot_example_sentence=ex,
    )


def _session(generated_at="2026-07-24T00:00:00Z", title=None):
    return SimpleNamespace(generated_at=generated_at, title=title)


def test_md_splits_word_and_phonetic_into_separate_columns():
    md = build_recitation_md(_session(), [_item("camera", "ˈkæmərə", "相机", "I have a camera.")])
    assert "| 单词 | 音标 |" in md
    assert "| camera | /ˈkæmərə/ |" in md
    assert "相机" in md
    assert "I have a camera." in md


def test_md_has_date_and_weekday_header():
    # 2026-07-24 is Friday.
    md = build_recitation_md(_session(generated_at="2026-07-24T00:00:00Z"), [_item("a", "x", "甲", "ex.")])
    assert "2026年07月24日" in md
    assert "周五" in md


def test_md_omits_phonetic_slashes_when_empty():
    md = build_recitation_md(_session(), [_item("focus", None, "焦点", "Stay focused.")])
    assert "| focus |" in md
    assert "//" not in md


def test_md_strips_redundant_slashes_from_phonetic():
    md = build_recitation_md(_session(), [_item("camera", "/ˈkæmərə/", "相机", None)])
    assert "| camera | /ˈkæmərə/ |" in md
    assert "//" not in md


def test_md_uses_session_title_when_present():
    md = build_recitation_md(_session(title="我的单词表"), [_item("a", None, "甲", None)])
    assert "# 📚 我的单词表" in md


def test_theme_returns_morandi_color_per_weekday():
    primary, deep, accent, name = _theme("2026-07-20T00:00:00Z")  # Monday
    assert primary == "#a85a5a"
    assert deep == "#874a4a"
    assert accent == "#c2a370"
    assert name == "周一"


def test_pdf_html_has_themed_hero_and_split_columns():
    body = _pdf_html(_session(), [_item("camera", "ˈkæmərə", "相机", "I have a camera.")])
    assert "linear-gradient(120deg" in body
    assert "<th>音标</th>" in body  # 单词/音标 split into separate columns
    assert "camera" in body and "/ˈkæmərə/" in body
    assert "周五" in body  # 2026-07-24 is Friday


def test_render_recitation_pdf_returns_valid_pdf_bytes():
    try:
        import weasyprint  # noqa: F401
    except ImportError:
        pytest.skip("weasyprint not installed")
    pdf = render_recitation_pdf(_session(), [_item("camera", "ˈkæmərə", "相机", "I have a camera.")])
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"
