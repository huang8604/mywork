from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas import WordCreate
from app.services.ai_enrich import ai_enrich_word
from app.services.domain import normalize_word


logger = logging.getLogger("word_memory.dictionary")


@lru_cache(maxsize=4)
def _load_index(path_text: str) -> dict[str, dict[str, Any]]:
    path = Path(path_text)
    if not path.is_file():
        logger.warning("dictionary_index_missing path=%s", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("dictionary_index_invalid path=%s", path)
        raise AppError(503, "DICTIONARY_UNAVAILABLE", "词典资源暂时不可用") from exc
    if not isinstance(data, dict):
        raise AppError(503, "DICTIONARY_UNAVAILABLE", "词典资源格式异常")
    normalized = {
        str(key).casefold().strip(): value
        for key, value in data.items()
        if isinstance(value, dict)
    }
    logger.info("dictionary_index_loaded path=%s entries=%s", path, len(normalized))
    return normalized


def clear_dictionary_cache() -> None:
    _load_index.cache_clear()


def enrich_word(
    payload: WordCreate,
    *,
    require_meaning: bool = True,
    allow_ai: bool = False,
) -> tuple[WordCreate, bool]:
    display, normalized = normalize_word(payload.en_word)
    entry = _load_index(get_settings().dictionary_index_path).get(normalized)
    found = entry is not None
    phonetic = payload.phonetic or (_phonetic(entry) if entry else None)
    cn_meaning = payload.cn_meaning or (_meaning(entry) if entry else None)
    example_sentence = payload.example_sentence or (_example(entry) if entry else None)
    # Meaning too long and unshorten-able: try AI re-translation before the
    # hard cap. Runs for both create/import and the editor preview so the AI
    # 补全 button can also retranslate an over-long stored meaning.
    if cn_meaning and len(cn_meaning) > 16 and shorten_translations([{"pos": "", "cn": cn_meaning}]) is None:
        if allow_ai and get_settings().ai_enabled:
            ai = ai_enrich_word(display)
            if ai and ai.get("cn_meaning"):
                phonetic = phonetic or ai["phonetic"]
                cn_meaning = ai["cn_meaning"]
                example_sentence = example_sentence or ai["example_sentence"]
        if cn_meaning and len(cn_meaning) > 16:
            # Keep the ellipsis inside the 16-character display budget.
            cn_meaning = cn_meaning[:15].rstrip(_MEANING_PUNCT) + "…"
    if allow_ai and not cn_meaning:
        # Dictionary miss with no manual meaning: try the AI fallback before
        # giving up. Runs for both create/import (require_meaning=True) and the
        # editor's /words/enrich preview (require_meaning=False) so the "AI
        # 补全" button works. ai_enrich_word returns None when disabled, making
        # this a no-op unless AI is configured.
        ai = ai_enrich_word(display)
        if ai:
            phonetic = phonetic or ai["phonetic"]
            cn_meaning = shorten_translations([{"pos": "", "cn": ai["cn_meaning"]}]) or ai["cn_meaning"]
            example_sentence = example_sentence or ai["example_sentence"]
    if require_meaning and not cn_meaning:
        logger.debug("dictionary_entry_unresolved normalized_word=%s", normalized)
        raise AppError(
            422,
            "DICTIONARY_ENTRY_NOT_FOUND",
            "词典未收录该词，且未提供中文释义",
            [{"path": ["body", "en_word"], "reason": "请手动填写中文释义", "value": display}],
        )
    return (
        payload.model_copy(
            update={
                "en_word": display,
                "phonetic": phonetic,
                "cn_meaning": cn_meaning,
                "example_sentence": example_sentence,
            }
        ),
        found,
    )


def enrich_preview(word: str, *, allow_ai: bool = False) -> dict[str, object]:
    enriched, found = enrich_word(
        WordCreate(en_word=word), require_meaning=False, allow_ai=allow_ai
    )
    ai_used = (
        allow_ai
        and not found
        and bool(enriched.cn_meaning or enriched.phonetic or enriched.example_sentence)
    )
    source = "dictionary-index" if found else ("ai" if ai_used else None)
    return {
        **enriched.model_dump(mode="json"),
        "dictionary_found": found,
        "source": source,
        "missing_fields": [
            field
            for field in ("phonetic", "cn_meaning", "example_sentence")
            if not getattr(enriched, field)
        ],
    }


def _phonetic(entry: dict[str, Any]) -> str | None:
    for key in ("p0", "p1"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_MEANING_PUNCT = " ；;,，.。"


def clean_translation_items(
    translations: Any,
    *,
    max_senses: int = 3,
) -> list[dict[str, str]]:
    """Return the surviving ``{pos, cn}`` senses after dropping noise.

    Filters out surname senses (``人名``), parenthetical English glosses
    (``（=laptop computer）``), near-English senses (>75% Latin), and duplicate
    meanings; caps to ``max_senses`` primary senses. Returns an empty list when
    every sense is filtered out (≈17 entries that are only surnames/glosses).
    """
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    if not isinstance(translations, list):
        return items
    for entry in translations:
        if not isinstance(entry, dict):
            continue
        meaning = str(entry.get("cn") or "").strip()
        if not meaning or "人名" in meaning:
            continue
        meaning = _PAREN_RE.sub("", meaning).strip(_MEANING_PUNCT)
        if not meaning:
            continue
        non_latin = len(_LATIN_RE.sub("", meaning))
        if non_latin < max(2, len(meaning) // 4):
            continue  # >75% Latin → almost certainly an English gloss
        if meaning in seen:
            continue
        seen.add(meaning)
        part = str(entry.get("pos") or "").strip()
        items.append({"pos": part, "cn": meaning})
        if len(items) >= max_senses:
            break
    return items


_BOUNDARY_CHARS = " ；;,，.。、"


def shorten_translations(
    translations: Any,
    *,
    max_senses: int = 3,
    target: int = 16,
    min_keep: int = 10,
) -> str | None:
    """Collapse senses into one short Chinese meaning (≤ ``target`` when possible).

    1) join up to ``max_senses`` cleaned senses with ``；``;
    2) if already ≤ ``target``, return it;
    3) else look for the LAST boundary char (``。 ； ， , ; . 、``) whose cut yields
       a length within ``[min_keep, target]``; if found, cut there (trim trailing
       punct);
    4) else return ``None`` — the caller (``enrich_word``) decides the
       AI-retranslate / hard-cap fallback.
    """
    if not isinstance(translations, list):
        return None
    items = clean_translation_items(translations, max_senses=max_senses)
    if items:
        parts = [f"{it['pos']} {it['cn']}".strip() for it in items]
    else:
        parts = []
        for entry in translations:
            if not isinstance(entry, dict):
                continue
            meaning = str(entry.get("cn") or "").strip()
            if not meaning:
                continue
            part = str(entry.get("pos") or "").strip()
            parts.append(f"{part} {meaning}".strip())
    text = "；".join(parts)
    if not text:
        return None
    if len(text) <= target:
        return text
    # Cut at the LAST boundary char (。；，,;.、) whose position yields a length
    # within [min_keep, target]; text[:k] excludes the boundary char itself.
    upper = min(target, len(text) - 1)
    for k in range(upper, min_keep - 1, -1):
        if text[k] in _BOUNDARY_CHARS:
            return text[:k].strip(_MEANING_PUNCT)
    return None


def _meaning(entry: dict[str, Any]) -> str | None:
    translations = entry.get("t")
    if not isinstance(translations, list):
        return None
    shortened = shorten_translations(translations)
    if shortened is not None:
        return shortened
    # shorten_translations returns None when senses exist but every cut leaves
    # the text too long with no boundary in window. Fall back to the raw joined
    # text so ``enrich_word`` can still see the meaning and run its AI/hard-cap
    # branch — without this, a long unshortenable meaning would look identical
    # to a dictionary miss and raise DICTIONARY_ENTRY_NOT_FOUND.
    items = clean_translation_items(translations)
    if not items:
        return None
    parts = [f"{it['pos']} {it['cn']}".strip() for it in items]
    return "；".join(parts) or None


def _example(entry: dict[str, Any]) -> str | None:
    sentences = entry.get("s")
    if not isinstance(sentences, list):
        return None
    for item in sentences:
        if isinstance(item, dict):
            value = str(item.get("c") or "").strip()
            if value:
                return value
    return None
