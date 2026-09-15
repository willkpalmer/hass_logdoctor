"""Look up suggested reading for log anomalies in the Home Assistant docs.

This module is strictly read-only: it only ever performs search requests
against Home Assistant's own documentation and never takes any action
against Home Assistant or any external service.

Uses the public, search-only Algolia DocSearch key that home-assistant.io
embeds in every docs page (view-source on https://www.home-assistant.io/docs/
and look for the `docsearch({...})` call) to power its own search box -
appId "FBHBYS3J0U", index "home-assistant". This is the exact same
mechanism the site's own search bar uses: a search-only key that Algolia
DocSearch deliberately publishes client-side, not a private credential.
If home-assistant.io ever rotates this key, lookups simply start failing
closed (returned as an `error`, never raised) rather than breaking scans.
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

_ALGOLIA_APP_ID = "FBHBYS3J0U"
_ALGOLIA_API_KEY = "fcd41bf156f5ee0e390f8b860e3a2489"
_ALGOLIA_INDEX = "home-assistant"
_ALGOLIA_URL = f"https://{_ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{_ALGOLIA_INDEX}/query"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "")


@dataclass
class DocsMatch:
    """A single matching Home Assistant docs page/section."""

    title: str
    url: str
    snippet: str


@dataclass
class DocsLookupResult:
    """Result of looking up an anomaly signature against the HA docs."""

    query: str
    matches: list[DocsMatch] = field(default_factory=list)
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
    def from_dict(cls, data: dict[str, Any]) -> "DocsLookupResult":
        return cls(
            query=data["query"],
            matches=[DocsMatch(**m) for m in data.get("matches", [])],
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
            error=data.get("error"),
        )


class HADocsLookupClient:
    """Thin async client for the Home Assistant docs' public DocSearch index."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def search(
        self, logger: str, message: str, per_page: int = 3
    ) -> DocsLookupResult:
        """Search the Home Assistant docs for a message related to this log entry."""
        _, component = component_from_logger(logger)
        query = build_search_text(logger, message, component)

        try:
            async with self._session.post(
                _ALGOLIA_URL,
                headers={
                    "X-Algolia-API-Key": _ALGOLIA_API_KEY,
                    "X-Algolia-Application-Id": _ALGOLIA_APP_ID,
                    "Content-Type": "application/json",
                },
                json={"query": query, "hitsPerPage": per_page},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return DocsLookupResult(query=query, error=f"http_{resp.status}")
                payload = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("HA docs lookup failed for %r: %s", query, err)
            return DocsLookupResult(query=query, error=str(err))

        matches: list[DocsMatch] = []
        for hit in payload.get("hits", [])[:per_page]:
            hierarchy = hit.get("hierarchy") or {}
            title_parts = [hierarchy.get(f"lvl{i}") for i in range(3)]
            title = " › ".join(p for p in title_parts if p)

            snippet_result = (hit.get("_snippetResult") or {}).get("content") or {}
            snippet = _strip_html(snippet_result.get("value") or hit.get("content") or "")

            matches.append(
                DocsMatch(
                    title=title or hit.get("url", "Home Assistant docs"),
                    url=hit.get("url", ""),
                    snippet=snippet[:300],
                )
            )
        return DocsLookupResult(query=query, matches=matches)
