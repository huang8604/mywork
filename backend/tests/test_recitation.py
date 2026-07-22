"""Unit tests for the recitation handout markdown builder."""

from types import SimpleNamespace

from app.services.recitation import build_recitation_md


def _item(en, ph, cn, ex):
    return SimpleNamespace(
        snapshot_en_word=en,
        snapshot_phonetic=ph,
        snapshot_cn_meaning=cn,
        snapshot_example_sentence=ex,
    )


def test_recitation_md_merges_word_and_phonetic_with_slashes():
    md = build_recitation_md([_item("camera", "ˈkæmərə", "相机", "I have a camera.")])
    assert "| camera /ˈkæmərə/ |" in md
    assert "| 相机 |" in md
    assert "I have a camera." in md


def test_recitation_md_omits_slashes_when_no_phonetic():
    md = build_recitation_md([_item("focus", None, "焦点", "Stay focused.")])
    assert "| focus |" in md
    assert "//" not in md


def test_recitation_md_header_is_three_columns():
    md = build_recitation_md([_item("camera", "ˈkæmərə", "相机", None)])
    assert "|单词 /音标/|中文|例句|" in md


def test_recitation_md_strips_redundant_slashes_from_phonetic():
    """A phonetic already stored with surrounding slashes should not be doubled."""
    md = build_recitation_md([_item("camera", "/ˈkæmərə/", "相机", None)])
    assert "| camera /ˈkæmərə/ |" in md
    assert "//" not in md


def test_recitation_md_first_cell_falls_back_to_phonetic_when_word_empty():
    md = build_recitation_md([_item("", "ˈkæmərə", "相机", None)])
    assert "| /ˈkæmərə/ |" in md
