"""Look up suggested fixes for log anomalies from GitHub (issues search).

This module is strictly read-only: it only ever performs GET requests
against the public GitHub API to find existing issues/discussions that
match an error, and never takes any action against Home Assistant or
GitHub itself.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import GITHUB_API_BASE, GITHUB_CORE_REPO
from .log_parser import component_from_logger

_LOGGER = logging.getLogger(__name__)

# Strip stack-trace punctuation/paths down to a short, search-friendly
# phrase - GitHub's search treats long free text poorly.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "was", "were",
    "has", "have", "had", "not", "are", "you", "your", "self", "none",
    "true", "false", "error", "warning", "exception", "traceback", "line",
}


@dataclass
class GitHubMatch:
    """A single matching GitHub issue found for an anomaly."""

    title: str
    url: str
    state: str  # "open" or "closed"
    repo: str


@dataclass
class GitHubLookupResult:
    """Result of looking up an anomaly signature on GitHub."""

    query: str
    search_url: str
    matches: list[GitHubMatch] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "search_url": self.search_url,
            "matches": [m.__dict__ for m in self.matches],
            "fetched_at": self.fetched_at.isoformat(),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GitHubLookupResult":
        return cls(
            query=data["query"],
            search_url=data["search_url"],
            matches=[GitHubMatch(**m) for m in data.get("matches", [])],
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
            error=data.get("error"),
        )


def _keywords_from_message(message: str, limit: int = 6) -> list[str]:
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


def build_query(logger: str, message: str) -> tuple[str, str | None]:
    """Build a GitHub issue-search query string and an optional repo scope."""
    keywords = _keywords_from_message(message)
    kind, component = component_from_logger(logger)

    repo: str | None = None
    terms = list(keywords)
    if kind == "core":
        repo = GITHUB_CORE_REPO
        if component:
            terms.insert(0, component)
    elif kind == "custom" and component:
        terms.insert(0, component)

    query = " ".join(terms) if terms else logger
    return query, repo


class GitHubLookupClient:
    """Thin async client for the GitHub issue search API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str | None = None,
    ) -> None:
        self._session = session
        self._token = token
        self._rate_limited_until: datetime | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @property
    def rate_limited(self) -> bool:
        return (
            self._rate_limited_until is not None
            and datetime.now(timezone.utc) < self._rate_limited_until
        )

    async def search_issues(
        self, logger: str, message: str, per_page: int = 3
    ) -> GitHubLookupResult:
        """Search GitHub issues for a message related to this log entry."""
        query, repo = build_query(logger, message)
        search_terms = f'"{query}" in:title,body is:issue'
        if repo:
            search_terms += f" repo:{repo}"
        search_url = "https://github.com/search?q=" + _url_encode(search_terms) + "&type=issues"

        if self.rate_limited:
            return GitHubLookupResult(
                query=query, search_url=search_url, error="rate_limited"
            )

        params = {"q": search_terms, "per_page": str(per_page), "sort": "updated"}
        try:
            async with self._session.get(
                f"{GITHUB_API_BASE}/search/issues",
                params=params,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 403 or resp.status == 429:
                    reset = resp.headers.get("X-RateLimit-Reset")
                    if reset:
                        self._rate_limited_until = datetime.fromtimestamp(
                            int(reset), tz=timezone.utc
                        )
                    else:
                        self._rate_limited_until = datetime.now(
                            timezone.utc
                        ) + timedelta(minutes=5)
                    return GitHubLookupResult(
                        query=query, search_url=search_url, error="rate_limited"
                    )
                if resp.status != 200:
                    return GitHubLookupResult(
                        query=query,
                        search_url=search_url,
                        error=f"http_{resp.status}",
                    )
                payload = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("GitHub lookup failed for %r: %s", query, err)
            return GitHubLookupResult(query=query, search_url=search_url, error=str(err))

        matches = [
            GitHubMatch(
                title=item.get("title", "(no title)"),
                url=item.get("html_url", ""),
                state=item.get("state", "unknown"),
                repo=repo or _repo_from_url(item.get("html_url", "")),
            )
            for item in payload.get("items", [])[:per_page]
        ]
        return GitHubLookupResult(query=query, search_url=search_url, matches=matches)


def _repo_from_url(url: str) -> str:
    parts = url.split("/")
    if len(parts) >= 5 and "github.com" in parts:
        idx = parts.index("github.com")
        try:
            return f"{parts[idx + 1]}/{parts[idx + 2]}"
        except IndexError:
            return ""
    return ""


def _url_encode(text: str) -> str:
    from urllib.parse import quote

    return quote(text, safe="")
