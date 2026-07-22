"""Recitation handout: render a practice session as the 单词背诵表.md format and
optionally convert it to PDF.

The markdown mirrors the repo-root `单词背诵表.md` template — a 3-column table
(单词 /音标/ | 中文 | 例句) with a title and a footer hint. The phonetic is
folded into the first cell wrapped in slashes (omitted entirely when the
snapshot has no phonetic, so we never emit a stray ``//``). Cell content comes
from each ``PracticeSessionItem``'s snapshot fields so the handout stays stable
as the word library changes.

PDF conversion uses ``markdown`` + ``weasyprint`` (the ``[pdf]`` extra); those
imports are deferred into ``render_recitation_pdf`` so this module imports fine
even when the optional deps are absent.
"""

from __future__ import annotations

from typing import Iterable

from app.models import PracticeSessionItem


def _cell(value: str | None) -> str:
    if not value:
        return ""
    # Escape pipe (table cell separator) and collapse newlines.
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _format_phonetic(p: str | None) -> str:
    """Wrap a phonetic in slashes, tolerating already-slashed or empty input.

    Returns an empty string when there is nothing to show so the caller can
    simply concatenate without producing a stray ``//``.
    """
    if not p:
        return ""
    t = p.strip().strip("/")
    return f"/{t}/" if t else ""


def build_recitation_md(items: Iterable[PracticeSessionItem]) -> str:
    lines = [
        "# 📚 单词背诵表",
        "",
        "|单词 /音标/|中文|例句|",
        "|---|---|---|",
    ]
    for item in items:
        word_cell = _cell(item.snapshot_en_word)
        phonetic = _format_phonetic(item.snapshot_phonetic)
        first = f"{word_cell} {phonetic}".strip()
        lines.append(
            f"| {first} | {_cell(item.snapshot_cn_meaning)} "
            f"| {_cell(item.snapshot_example_sentence)} |"
        )
    lines.extend(["", "> 💡 遮住右侧，看中文回忆英文，反复 3 遍即可牢记！", ""])
    return "\n".join(lines)


_PDF_CSS = """
@page { size: A4; margin: 16mm; }
body { font-family: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", sans-serif; font-size: 12pt; color: #111; }
h1 { font-size: 18pt; text-align: center; margin: 0 0 14pt; }
table { width: 100%; border-collapse: collapse; }
thead { display: table-header-group; }
th, td { border: 1px solid #888; padding: 6pt 8pt; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
th { background: #edf3ef; }
blockquote { margin-top: 16pt; color: #555; font-size: 11pt; }
"""


def render_recitation_pdf(md_text: str) -> bytes:
    import markdown
    from weasyprint import HTML

    body = markdown.markdown(md_text, extensions=["tables"])
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_PDF_CSS}</style></head><body>{body}</body></html>"
    )
    return HTML(string=html).write_pdf()
