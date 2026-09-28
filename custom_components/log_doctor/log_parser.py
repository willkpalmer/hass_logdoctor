"""Parsing and normalization of Home Assistant log files."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

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

# The Supervisor's journal lines (Host, and add-ons when it adds it) start
# with the time in UTC, without an offset, then host and process:
# 2026-09-27 21:47:56.772 homeassistant containerd[652]: <message>
_JOURNAL_PREFIX_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?) \S+ [^\s:]+: "
)

# A level stated by the line itself wins over any keyword in it:
# logfmt (containerd, Docker, Go programs) level=warning, JSON
# "level": "error", or a leading "INFO:" / "[WARNING]" (bashio and Python
# style, optionally after a "[time]" or "time" stamp).
_EXPLICIT_LEVEL_RES = [
    re.compile(r"\blevel=\"?(?P<level>[A-Za-z]+)"),
    re.compile(r"\"(?:level|severity)\"\s*:\s*\"(?P<level>[A-Za-z]+)\""),
    re.compile(
        r"^(?:\[[^\]]*\]\s*|\d{2}:\d{2}:\d{2}\S*\s+)?\[?(?P<level>TRACE|DEBUG|INFO|NOTICE|"
        r"WARNING|WARN|ERROR|ERR|CRITICAL|CRIT|FATAL|PANIC)\]?(?::|\s+-|\])",
        re.IGNORECASE,
    ),
]
_EXPLICIT_LEVELS = {
    "trace": None, "debug": None, "info": None, "notice": None,
    "warn": "WARNING", "warning": "WARNING",
    "err": "ERROR", "error": "ERROR",
    "crit": "CRITICAL", "critical": "CRITICAL", "fatal": "CRITICAL", "panic": "CRITICAL",
}

# Otherwise, best-effort severity detection for lines that don't state one
# (arbitrary add-on output, etc). Matched case-insensitively as a
# standalone word - "Warning:", "error:", "FATAL" count, "errors", "warns",
# "no_error" don't - and not as part of a dotted, dashed or slashed name
# like io.containerd.warning.v1 or error-handler.
_LEVEL_KEYWORD_RE = re.compile(
    r"(?<![\w.\-/])(CRITICAL|FATAL|ERROR|WARNING|WARN)(?![\w\-/]|\.\w)", re.IGNORECASE
)
_LEVEL_ALIASES = {"WARN": "WARNING", "FATAL": "CRITICAL"}


def _journal_timestamp(line: str) -> tuple[datetime | None, str]:
    """(local time, the message after the prefix) for a journal line.

    The journal's time is UTC; converted to local time, naive, like Home
    Assistant's own log. (None, line) if it has no journal prefix.
    """
    match = _JOURNAL_PREFIX_RE.match(line)
    if not match:
        return None, line
    try:
        utc = datetime.strptime(match.group("ts")[:23], "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            utc = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None, line
    local = utc.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return local, line[match.end():]


def _severity(message: str) -> str | None:
    """The level of a line not in Home Assistant's format, or None if it
    isn't a warning or worse."""
    for pattern in _EXPLICIT_LEVEL_RES:
        if match := pattern.search(message):
            level = match.group("level").lower()
            if level in _EXPLICIT_LEVELS:
                return _EXPLICIT_LEVELS[level]
    keyword_match = _LEVEL_KEYWORD_RE.search(message)
    if not keyword_match:
        return None
    keyword = keyword_match.group(1).upper()
    return _LEVEL_ALIASES.get(keyword, keyword)

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
    itself uses it). Otherwise the level the line states itself is used
    (level=info, "level": "error", a leading "WARNING:"), and only failing
    that a keyword-based severity scan; lines below warning are simply not
    anomalies and are skipped. Journal lines (Host) are timed by their UTC
    prefix, so each is only counted by the first scan after it was logged;
    lines without a time get fallback_timestamp. There's no
    traceback-folding here since these sources are fetched as a short,
    bounded tail rather than a full historical file.

    With structured_only, the keyword fallback is skipped and only lines in
    the structured format are kept (used for sources known to always log in
    it, so lines in any other format are old or noise).
    """
    entries: list[LogEntry] = []
    for raw_line in text.splitlines():
        line = _ANSI_RE.sub("", raw_line).strip()
        if not line:
            continue

        journal_time, message = _journal_timestamp(line)
        # Home Assistant's format, whole or after a journal prefix.
        match = _LINE_RE.match(line) or (_LINE_RE.match(message) if journal_time else None)
        if match:
            try:
                timestamp = journal_time or datetime.strptime(match.group("ts"), _TS_FORMAT)
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
        level = _severity(message)
        if level is None:
            continue
        entries.append(
            LogEntry(
                timestamp=journal_time or fallback_timestamp,
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
