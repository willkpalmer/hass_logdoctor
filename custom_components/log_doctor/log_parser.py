"""Parsing and normalization of Home Assistant log files."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from .const import SEVERITY_ORDER

# Home Assistant's default log line format, e.g.:
# 2026-09-14 08:00:01.123 ERROR (MainThread) [homeassistant.components.foo] Something broke
_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) "
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL) "
    r"\((?P<thread>[^)]*)\) "
    r"\[(?P<logger>[^\]]*)\] "
    r"(?P<message>.*)$"
)

_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

# Supervisor/Host/add-on log text is often colorized for a terminal.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Best-effort severity detection for sources that aren't formatted like
# Home Assistant Core's own logger (Host journal lines, arbitrary add-on
# stdout, etc). Matched as a whole word, case-insensitively, so "errors" or
# "warns" mid-sentence don't trip it, but "Warning:", "error:", "FATAL" all
# do - non-Python add-ons are inconsistent about casing.
_LEVEL_KEYWORD_RE = re.compile(r"\b(CRITICAL|FATAL|ERROR|WARNING|WARN)\b", re.IGNORECASE)
_LEVEL_ALIASES = {"WARN": "WARNING", "FATAL": "CRITICAL"}

# Patterns used to normalize a message into a stable "signature" so that
# repeated occurrences of the same underlying problem (with different
# entity_ids, numbers, paths, etc.) are grouped together.
_NORMALIZE_PATTERNS = [
    (re.compile(r"0x[0-9a-fA-F]+"), "0xHEX"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "UUID"),
    (re.compile(r"'[^']{1,80}'"), "'...'"),
    (re.compile(r'"[^"]{1,80}"'), '"..."'),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(\+\d{2}:\d{2})?\b"), "TIMESTAMP"),
    (re.compile(r"\b\d+\.\d+\b"), "NUM"),
    (re.compile(r"\b\d+\b"), "NUM"),
    (re.compile(r"(?:[A-Za-z]:\\|/)[^\s,'\"]+"), "PATH"),
]


@dataclass
class LogEntry:
    """A single parsed log line (including any attached traceback)."""

    timestamp: datetime
    level: str
    logger: str
    message: str
    raw: str = ""


@dataclass
class AnomalyGroup:
    """A group of log entries that share the same normalized signature."""

    signature: str
    logger: str
    level: str
    example_message: str
    count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    entries: list[LogEntry] = field(default_factory=list)


def normalize_message(message: str) -> str:
    """Collapse variable parts of a message so similar errors group together."""
    text = message
    for pattern, replacement in _NORMALIZE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()[:300]


def make_signature(logger: str, message: str) -> str:
    """Build a short, stable signature id for a logger + normalized message."""
    normalized = normalize_message(message)
    digest = hashlib.sha1(f"{logger}:{normalized}".encode("utf-8")).hexdigest()[:12]
    return digest


def parse_log_lines(lines: list[str]) -> list[LogEntry]:
    """Parse raw log lines into LogEntry objects, folding in tracebacks."""
    entries: list[LogEntry] = []
    current: LogEntry | None = None

    for line in lines:
        line = line.rstrip("\n")
        match = _LINE_RE.match(line)
        if match:
            if current is not None:
                entries.append(current)
            try:
                timestamp = datetime.strptime(match.group("ts"), _TS_FORMAT)
            except ValueError:
                current = None
                continue
            current = LogEntry(
                timestamp=timestamp,
                level=match.group("level"),
                logger=match.group("logger"),
                message=match.group("message"),
                raw=line,
            )
        elif current is not None:
            # Continuation line (e.g. part of a traceback) - fold into the
            # current entry but keep the grouped message bounded in size.
            if len(current.message) < 4000:
                current.message += "\n" + line
            current.raw += "\n" + line

    if current is not None:
        entries.append(current)

    return entries


def parse_supervisor_log_text(
    text: str,
    source_name: str,
    fallback_timestamp: datetime,
    *,
    structured_only: bool = False,
) -> list[LogEntry]:
    """Parse plain-text logs fetched from the Supervisor API (Host, add-ons, etc).

    These aren't guaranteed to be formatted like Home Assistant Core's own
    logger, so this first tries the same structured format (Supervisor
    itself uses it) and otherwise falls back to a keyword-based severity
    scan. Lines that don't mention a level keyword are simply not anomalies
    and are skipped - there's no traceback-folding here since these sources
    are fetched as a short, bounded tail rather than a full historical file.

    With structured_only, the keyword fallback is skipped and only lines in
    the structured format are kept (used for sources known to always log in
    it, so lines in any other format are old or noise).
    """
    entries: list[LogEntry] = []
    for raw_line in text.splitlines():
        line = _ANSI_RE.sub("", raw_line).strip()
        if not line:
            continue

        match = _LINE_RE.match(line)
        if match:
            try:
                timestamp = datetime.strptime(match.group("ts"), _TS_FORMAT)
            except ValueError:
                timestamp = fallback_timestamp
            entries.append(
                LogEntry(
                    timestamp=timestamp,
                    level=match.group("level"),
                    logger=f"{source_name}:{match.group('logger')}",
                    message=match.group("message"),
                    raw=line,
                )
            )
            continue

        if structured_only:
            continue
        keyword_match = _LEVEL_KEYWORD_RE.search(line)
        if not keyword_match:
            continue
        keyword = keyword_match.group(1).upper()
        level = _LEVEL_ALIASES.get(keyword, keyword)
        entries.append(
            LogEntry(
                timestamp=fallback_timestamp,
                level=level,
                logger=source_name,
                message=line,
                raw=line,
            )
        )

    return entries


def filter_and_group(
    entries: list[LogEntry],
    min_level: str,
    since: datetime | None,
) -> dict[str, AnomalyGroup]:
    """Filter entries by severity/time and group them by signature."""
    min_rank = SEVERITY_ORDER.get(min_level, SEVERITY_ORDER["WARNING"])
    groups: dict[str, AnomalyGroup] = {}

    for entry in entries:
        if SEVERITY_ORDER.get(entry.level, 0) < min_rank:
            continue
        if since is not None and entry.timestamp < since:
            continue

        # Only the first line of the message is used for signature/display;
        # the rest (traceback) is kept for context but not shown by default.
        first_line = entry.message.split("\n", 1)[0]
        signature = make_signature(entry.logger, first_line)

        group = groups.get(signature)
        if group is None:
            group = AnomalyGroup(
                signature=signature,
                logger=entry.logger,
                level=entry.level,
                example_message=first_line,
            )
            groups[signature] = group

        group.count += 1
        group.entries.append(entry)
        if group.first_seen is None or entry.timestamp < group.first_seen:
            group.first_seen = entry.timestamp
        if group.last_seen is None or entry.timestamp > group.last_seen:
            group.last_seen = entry.timestamp
        # Escalate the group's reported level to the worst seen.
        if SEVERITY_ORDER.get(entry.level, 0) > SEVERITY_ORDER.get(group.level, 0):
            group.level = entry.level

    return groups


def component_from_logger(logger: str) -> tuple[str | None, str | None]:
    """Best-effort extraction of (kind, component) from a logger name.

    kind is "core" for built-in homeassistant.components.* loggers, or
    "custom" for custom_components.* loggers. Returns (None, None) if the
    logger name doesn't look like a component logger.
    """
    parts = logger.split(".")
    if len(parts) >= 3 and parts[0] == "homeassistant" and parts[1] == "components":
        return "core", parts[2]
    if len(parts) >= 2 and parts[0] == "custom_components":
        return "custom", parts[1]
    return None, None
