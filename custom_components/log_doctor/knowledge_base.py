"""Local built-in knowledge base of well-known Home Assistant log issues."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_LOGGER = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).parent / "data" / "known_issues.yaml"


@dataclass
class KnownIssue:
    """A single built-in known-issue entry."""

    id: str
    pattern: re.Pattern
    title: str
    explanation: str
    fix: str
    doc_url: str | None = None


@lru_cache(maxsize=1)
def _load_known_issues() -> list[KnownIssue]:
    try:
        raw_text = _DATA_FILE.read_text(encoding="utf-8")
    except OSError:
        _LOGGER.exception("Could not read built-in known issues file")
        return []

    raw_entries = yaml.safe_load(raw_text) or []
    issues: list[KnownIssue] = []
    for entry in raw_entries:
        try:
            issues.append(
                KnownIssue(
                    id=entry["id"],
                    pattern=re.compile(entry["pattern"], re.IGNORECASE),
                    title=entry["title"].strip(),
                    explanation=" ".join(entry["explanation"].split()),
                    fix=" ".join(entry["fix"].split()),
                    doc_url=entry.get("doc_url"),
                )
            )
        except (KeyError, re.error):
            _LOGGER.warning("Skipping malformed known-issue entry: %s", entry)
    return issues


async def async_warm_known_issues(hass) -> None:
    """Load (and cache) the knowledge base via the executor.

    Must be awaited once before `match_known_issue` is called from the
    event loop, since the underlying YAML read is blocking I/O and
    `_load_known_issues` is only cheap once `lru_cache` has it warm.
    """
    await hass.async_add_executor_job(_load_known_issues)


def match_known_issue(logger: str, message: str) -> KnownIssue | None:
    """Return the first built-in known issue matching this log message, if any."""
    haystack = f"{logger}: {message}"
    for issue in _load_known_issues():
        if issue.pattern.search(haystack):
            return issue
    return None
