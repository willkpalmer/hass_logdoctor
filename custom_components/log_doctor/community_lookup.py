"""Look up related discussions for log anomalies on the Home Assistant
Community forum (community.home-assistant.io).

This module is strictly read-only: it only ever performs search requests
against the forum's own public search API and never posts, replies, or
takes any other action against it.

Uses Discourse's public `search.json` endpoint - the same one the forum's
own search box calls - which needs no API key for a public search.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .log_parser import component_from_logger
from .search_query import build_search_text

_LOGGER = logging.getLogger(__name__)

_SEARCH_URL = "https://community.home-assistant.io/search.json"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "")


@dataclass
class CommunityMatch:
    """A single matching Community forum topic."""

    title: str
    url: str
    excerpt: str
    solved: bool
    reply_count: int


@dataclass
class CommunityLookupResult:
    """Result of looking up an anomaly signature against the Community forum."""

    query: str
    matches: list[CommunityMatch] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "matches": [m.__dict__ for m in self.matches],
            "fetched_at": self.fetched_at.isoformat(),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommunityLookupResult":
        return cls(
            query=data["query"],
            matches=[CommunityMatch(**m) for m in data.get("matches", [])],
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
            error=data.get("error"),
        )


class CommunityLookupClient:
    """Thin async client for the Community forum's public Discourse search."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def search(
        self, logger: str, message: str, per_page: int = 3
    ) -> CommunityLookupResult:
        """Search the Community forum for a message related to this log entry."""
        _, component = component_from_logger(logger)
        query = build_search_text(logger, message, component)

        try:
            async with self._session.get(
                _SEARCH_URL,
                params={"q": query},
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return CommunityLookupResult(query=query, error=f"http_{resp.status}")
                payload = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Community forum lookup failed for %r: %s", query, err)
            return CommunityLookupResult(query=query, error=str(err))

        topics = (payload.get("topics") or [])[:per_page]
        matches = [
            CommunityMatch(
                title=topic.get("title", "(untitled)"),
                url=f"https://community.home-assistant.io/t/{topic.get('slug', 'topic')}/{topic['id']}",
                excerpt=_strip_html(topic.get("excerpt", ""))[:300],
                solved=bool(topic.get("has_accepted_answer")),
                reply_count=topic.get("reply_count", 0),
            )
            for topic in topics
            if topic.get("id")
        ]
        return CommunityLookupResult(query=query, matches=matches)
