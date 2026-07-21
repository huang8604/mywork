from __future__ import annotations

import json
import logging
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


def _meaning(entry: dict[str, Any]) -> str | None:
    translations = entry.get("t")
    if not isinstance(translations, list):
        return None
    values = []
    for item in translations:
        if not isinstance(item, dict):
            continue
        meaning = str(item.get("cn") or "").strip()
        part = str(item.get("pos") or "").strip()
        if meaning:
            values.append(f"{part} {meaning}".strip())
    return "；".join(values) or None


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
