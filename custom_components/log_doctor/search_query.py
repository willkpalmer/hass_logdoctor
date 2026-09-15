"""Shared helpers for building search queries from a log anomaly.

Used by every external lookup client (GitHub, Home Assistant docs,
Community forum) so they all extract keywords the same way.
"""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "was", "were",
    "has", "have", "had", "not", "are", "you", "your", "self", "none",
    "true", "false", "error", "warning", "exception", "traceback", "line",
}


def keywords_from_message(message: str, limit: int = 6) -> list[str]:
    """Pull a handful of distinctive keywords out of a log message."""
    words = _WORD_RE.findall(message)
    keywords: list[str] = []
    for word in words:
        lower = word.lower()
        if lower in _STOPWORDS or lower in keywords:
            continue
        keywords.append(lower)
        if len(keywords) >= limit:
            break
    return keywords


def build_search_text(logger: str, message: str, component: str | None = None) -> str:
    """Build a plain-text search query string for an anomaly."""
    keywords = keywords_from_message(message)
    terms = list(keywords)
    if component:
        terms.insert(0, component)
    return " ".join(terms) if terms else logger
