"""AI fallback enrichment for words the local dictionary can't resolve.

Calls an OpenAI-compatible ``/chat/completions`` endpoint (configured via
``AI_BASE_URL`` / ``AI_API_KEY`` / ``AI_MODEL``) to produce a concise Chinese
meaning, phonetic, and example sentence. The result is returned raw; the caller
(``dictionary.enrich_word``) runs the meaning through ``shorten_translations``
so the same length cap applies as the local dictionary.

This module never raises and never logs the API key: on any failure (disabled,
timeout, HTTP error, unparseable body) it returns ``None`` and the caller falls
back to treating the word as unresolved.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("word_memory.ai_enrich")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def ai_enabled() -> bool:
    return get_settings().ai_enabled


def ai_enrich_word(en_word: str) -> dict[str, str | None] | None:
    """Return ``{cn_meaning, phonetic, example_sentence}`` for ``en_word``.

    ``cn_meaning`` is guaranteed non-empty when a dict is returned. Returns
    ``None`` when AI is disabled or the call/parse fails.
    """
    settings = get_settings()
    if not settings.ai_enabled:
        return None
    prompt = (
        f"给出英文单词「{en_word}」用于单词记忆卡的内容，要求："
        "1) cn_meaning 为简明中文释义（主要词义，不超过 40 字）；"
        "2) phonetic 为国际音标；"
        "3) example 为一句简短英文例句。"
        '严格只返回 JSON，不要任何解释：{"cn_meaning":"...","phonetic":"...","example":"..."}'
    )
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                f"{settings.ai_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.ai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.ai_model,
                    "messages": [
                        {"role": "system", "content": "你是英文单词词典助手，只输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.warning("ai_enrich_failed word=%s", en_word, exc_info=True)
        return None

    parsed = _parse_json(_extract_content(data))
    if not parsed:
        logger.debug("ai_enrich_unparseable word=%s", en_word)
        return None
    cn_meaning = str(parsed.get("cn_meaning") or "").strip()
    if not cn_meaning:
        return None
    logger.debug("ai_enrich_hit word=%s", en_word)
    return {
        "cn_meaning": cn_meaning,
        "phonetic": str(parsed.get("phonetic") or "").strip() or None,
        "example_sentence": str(parsed.get("example") or "").strip() or None,
    }


def _extract_content(data: Any) -> str:
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _parse_json(content: str) -> dict[str, Any] | None:
    if not content:
        return None
    text = content.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    elif text[:1] != "{":
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
