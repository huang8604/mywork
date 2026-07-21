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
        raise AppError(503, "DICTIONARY_UNAVAILABLE", "dictionary resource is unavailable") from exc
    if not isinstance(data, dict):
        raise AppError(503, "DICTIONARY_UNAVAILABLE", "dictionary resource has an invalid shape")
    normalized = {
        str(key).casefold().strip(): value
        for key, value in data.items()
        if isinstance(value, dict)
    }
    logger.info("dictionary_index_loaded path=%s entries=%s", path, len(normalized))
    return normalized


def clear_dictionary_cache() -> None:
    _load_index.cache_clear()


def enrich_word(payload: WordCreate, *, require_meaning: bool = True) -> tuple[WordCreate, bool]:
    display, normalized = normalize_word(payload.en_word)
    entry = _load_index(get_settings().dictionary_index_path).get(normalized)
    found = entry is not None
    phonetic = payload.phonetic or (_phonetic(entry) if entry else None)
    cn_meaning = payload.cn_meaning or (_meaning(entry) if entry else None)
    example_sentence = payload.example_sentence or (_example(entry) if entry else None)
    if require_meaning and not cn_meaning:
        logger.debug("dictionary_entry_unresolved normalized_word=%s", normalized)
        raise AppError(
            422,
            "DICTIONARY_ENTRY_NOT_FOUND",
            "dictionary has no usable Chinese meaning for this word",
            [{"path": ["body", "en_word"], "reason": "provide cn_meaning manually", "value": display}],
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


def enrich_preview(word: str) -> dict[str, object]:
    enriched, found = enrich_word(WordCreate(en_word=word), require_meaning=False)
    return {
        **enriched.model_dump(mode="json"),
        "dictionary_found": found,
        "source": "dictionary-index" if found else None,
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


def shorten_translations(
    translations: Any,
    *,
    max_senses: int = 3,
    hard_cap: int = 40,
) -> str | None:
    """Collapse a word's translation senses into one short Chinese meaning.

    The raw ``t`` list joins *every* sense — surnames, parenthetical English
    glosses, near-English senses, and duplicates — which inflates meanings to
    hundreds of characters and breaks the printed worksheet. This keeps up to
    ``max_senses`` primary senses and caps total length at ``hard_cap``
    (truncating on a ``；`` boundary). When every sense is filtered out it
    falls back to the raw joined senses, capped, so a word never loses its
    meaning entirely.
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
    if len(text) <= hard_cap:
        return text
    cut = text[:hard_cap]
    boundary = cut.rfind("；")
    if boundary > 8:
        cut = cut[:boundary]
    return cut + "…"


def _meaning(entry: dict[str, Any]) -> str | None:
    return shorten_translations(entry.get("t"))


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
