"""Recitation handout: render a practice session as a 单词背诵表 handout.

Two outputs, both driven by the same Morandi weekday theme (keyed off the
session ``generated_at``):

* ``build_recitation_md`` — a 4-column markdown table (单词 | 音标 | 中文 | 例句)
  with a title + date/weekday header that mirrors the HTML handout.
* ``render_recitation_pdf`` — a themed HTML document (hero header + rounded
  table) matching the repo-root ``test2.html`` reference, converted via
  WeasyPrint (the ``[pdf]`` extra).

Cell content comes from each ``PracticeSessionItem``'s snapshot fields so the
handout stays stable as the word library changes. PDF/Markdown imports are
deferred so this module imports fine even when the optional deps are absent.
"""

from __future__ import annotations

import datetime as _dt
import html
from typing import Iterable, Protocol

from app.models import PracticeSessionItem

_ACCENT = "#c2a370"
# isoweekday (1=Mon … 7=Sun) -> (primary, deep, weekday name)
_MORANDI: dict[int, tuple[str, str, str]] = {
    1: ("#a85a5a", "#874a4a", "周一"),
    2: ("#a9744f", "#855c3d", "周二"),
    3: ("#9c8a4e", "#7c6d3b", "周三"),
    4: ("#6f8a66", "#556d4f", "周四"),
    5: ("#5e8787", "#476a6a", "周五"),
    6: ("#5e7691", "#475d74", "周六"),
    7: ("#856b94", "#685276", "周日"),
}


class _SessionLike(Protocol):
    generated_at: str | None
    title: str | None


def _weekday(generated_at: str | None) -> int:
    if not generated_at:
        return _dt.datetime.now().isoweekday()
    try:
        return _dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00")).isoweekday()
    except ValueError:
        return _dt.datetime.now().isoweekday()


def _theme(generated_at: str | None) -> tuple[str, str, str, str]:
    primary, deep, name = _MORANDI.get(_weekday(generated_at), _MORANDI[1])
    return primary, deep, _ACCENT, name


def _date_text(generated_at: str | None) -> str:
    if not generated_at:
        return _dt.datetime.now().strftime("%Y年%m月%d日")
    try:
        return _dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00")).strftime("%Y年%m月%d日")
    except ValueError:
        return generated_at[:10]


def _cell(value: str | None) -> str:
    if not value:
        return ""
    # Escape pipe (table cell separator) and collapse newlines.
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _format_phonetic(p: str | None) -> str:
    """Wrap a phonetic in slashes, tolerating already-slashed or empty input."""
    if not p:
        return ""
    t = p.strip().strip("/")
    return f"/{t}/" if t else ""


def build_recitation_md(session: _SessionLike, items: Iterable[PracticeSessionItem]) -> str:
    _primary, _deep, _accent, weekday = _theme(getattr(session, "generated_at", None))
    date_text = _date_text(getattr(session, "generated_at", None))
    title = (getattr(session, "title", None) or "单词背诵表").strip()
    lines = [
        f"# 📚 {title}",
        "",
        f"> 日期：{date_text} {weekday}",
        "",
        "| 序号 | 单词 | 音标 | 中文 | 例句 |",
        "| :---: | :--- | :--- | :--- | :--- |",
    ]
    for index, item in enumerate(items, 1):
        lines.append(
            f"| {index} | {_cell(item.snapshot_en_word)} | {_format_phonetic(item.snapshot_phonetic)} "
            f"| {_cell(item.snapshot_cn_meaning)} | {_cell(item.snapshot_example_sentence)} |"
        )
    lines.extend(["", "> 💡 遮住中文，看单词与音标回忆释义，反复 3 遍即可牢记！", ""])
    return "\n".join(lines)


def _pdf_html(session: _SessionLike, items: list[PracticeSessionItem]) -> str:
    primary, deep, accent, weekday = _theme(getattr(session, "generated_at", None))
    date_text = _date_text(getattr(session, "generated_at", None))
    title = html.escape((getattr(session, "title", None) or "单词背诵表").strip())
    rows: list[str] = []
    for index, item in enumerate(items, 1):
        rows.append(
            "<tr>"
            f'<td class="col-no">{index}</td>'
            f'<td class="col-word">{html.escape(item.snapshot_en_word or "")}</td>'
            f'<td class="col-pho">{html.escape(_format_phonetic(item.snapshot_phonetic))}</td>'
            f'<td class="col-zh">{html.escape(item.snapshot_cn_meaning or "")}</td>'
            f'<td class="col-eg">{html.escape(item.snapshot_example_sentence or "")}</td>'
            "</tr>"
        )
    rows_html = "\n".join(rows)
    total = len(items)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
@page {{ size: A4 portrait; margin: 9mm 10mm; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; color:#1f2d3d; font-family: "Noto Sans CJK SC","Noto Sans SC","Source Han Sans SC",sans-serif; }}
.hero {{ display:flex; align-items:center; justify-content:space-between; min-height:24mm; padding:4.5mm 6mm;
  color:#fff; background:{deep}; background:linear-gradient(120deg,{deep},{primary}); border-bottom:2.2mm solid {accent}; }}
.title-group .eyebrow {{ margin-bottom:1mm; font-size:7.5pt; font-weight:700; letter-spacing:2.1px; opacity:.76; }}
.hero h1 {{ margin:0; font-size:20pt; line-height:1.05; letter-spacing:1px; }}
.hero .subtitle {{ margin-top:1.4mm; font-size:8.5pt; opacity:.86; }}
.date-card {{ min-width:40mm; padding:2.5mm 3.5mm; text-align:center; color:{deep}; background:rgba(255,255,255,.94);
  border-radius:2.5mm; box-shadow:0 1.5mm 4mm rgba(0,0,0,.12); }}
.date-card .label {{ display:block; margin-bottom:.6mm; color:#66758a; font-size:7pt; font-weight:700; letter-spacing:1.4px; }}
.date-card .value {{ font-size:10.5pt; font-weight:800; white-space:nowrap; }}
.content {{ padding:4mm 0 0; }}
table {{ width:100%; table-layout:fixed; border-spacing:0; border-collapse:separate;
  border:.35mm solid #dce5f0; border-radius:2.2mm; overflow:hidden; background:#fff; }}
thead {{ display:table-header-group; }}
tr {{ break-inside:avoid; page-break-inside:avoid; }}
th,td {{ border-right:.25mm solid #dce5f0; border-bottom:.25mm solid #dce5f0; vertical-align:middle; }}
th:last-child,td:last-child {{ border-right:0; }}
tbody tr:last-child td {{ border-bottom:0; }}
th {{ height:9.4mm; padding:1.8mm 2mm; color:#fff; background:{primary}; font-size:9.2pt; font-weight:700; text-align:left; }}
td {{ height:11.25mm; padding:1.35mm 2mm; font-size:9.2pt; line-height:1.16; }}
tbody tr:nth-child(even) td {{ background:#f6f9fd; }}
.col-no {{ width:7%; text-align:center; color:{primary}; font-weight:800; }}
.col-word {{ width:20%; color:{deep}; font-weight:800; }}
.col-pho {{ width:20%; color:#59687b; }}
.col-zh {{ width:19%; color:#2e4055; font-weight:700; }}
.col-eg {{ width:34%; color:#4f5d6d; font-style:italic; }}
.footer-note {{ display:flex; align-items:center; justify-content:space-between; padding:2.4mm 0 0; color:#7a8798; font-size:7.3pt; }}
.footer-note strong {{ color:{primary}; }}
</style></head>
<body>
<header class="hero">
  <div class="title-group">
    <div class="eyebrow">VOCABULARY REVIEW</div>
    <h1>{title}</h1>
    <div class="subtitle">{date_text} · {weekday} · 共 {total} 词</div>
  </div>
  <div class="date-card"><span class="label">DATE / 日期</span><span class="value">{date_text}</span></div>
</header>
<section class="content">
<table>
<thead><tr><th class="col-no">序号</th><th>单词</th><th>音标</th><th>中文</th><th>例句</th></tr></thead>
<tbody>
{rows_html}
</tbody></table>
<div class="footer-note"><span><strong>Tip:</strong> 遮住中文释义，再尝试读出单词和例句。</span><span>{total} / {total} WORDS</span></div>
</section>
</body></html>"""


def render_recitation_pdf(session: _SessionLike, items: Iterable[PracticeSessionItem]) -> bytes:
    from weasyprint import HTML

    item_list = list(items)
    return HTML(string=_pdf_html(session, item_list)).write_pdf()
