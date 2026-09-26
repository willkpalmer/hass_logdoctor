"""Build the markdown scan report from a scan's anomalies.

Per anomaly, the report lists the raw log data (all matching occurrences,
up to a cap) rather than any synthesized summary - that diagnosis step is
left to the separate companion app (see companion/), which researches each
one with an OpenAI model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .const import MAX_LOG_ENTRIES_PER_ANOMALY
from .knowledge_base import KnownIssue
from .log_parser import AnomalyGroup

_LEVEL_EMOJI = {"WARNING": "⚠️", "ERROR": "🛑", "CRITICAL": "🔴"}
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class LogSourceSummary:
    """What Log Doctor found when it checked one Supervisor-managed log source."""

    name: str
    lines_read: int
    ok: bool
    note: str = ""


@dataclass
class AnomalyReport:
    """Everything Log Doctor found out about a single anomaly group."""

    group: AnomalyGroup
    is_new: bool
    known_issue: KnownIssue | None = None

    @property
    def signature(self) -> str:
        return self.group.signature

    def as_attr_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "level": self.group.level,
            "logger": self.group.logger,
            "message": self.group.example_message,
            "count": self.group.count,
            "is_new": self.is_new,
            "first_seen": self.group.first_seen.isoformat() if self.group.first_seen else None,
            "last_seen": self.group.last_seen.isoformat() if self.group.last_seen else None,
            "description": (
                self.known_issue.explanation if self.known_issue else "No information available"
            ),
            "known_fix_title": self.known_issue.title if self.known_issue else None,
            "known_fix": self.known_issue.fix if self.known_issue else None,
            "doc_url": self.known_issue.doc_url if self.known_issue else None,
        }


@dataclass
class ScanResult:
    """The full outcome of one scan run."""

    scanned_at: datetime
    log_path: str = ""
    since: datetime | None = None
    reports: list[AnomalyReport] = field(default_factory=list)
    lines_scanned: int = 0
    error: str | None = None
    report_markdown: str = ""
    report_file: str | None = None
    sources_checked: list[LogSourceSummary] = field(default_factory=list)

    @property
    def new_reports(self) -> list[AnomalyReport]:
        return [r for r in self.reports if r.is_new]

    @property
    def recurring_reports(self) -> list[AnomalyReport]:
        return [r for r in self.reports if not r.is_new]

    @property
    def total_occurrences(self) -> int:
        """Total matching log lines across all anomaly groups (pre-dedup)."""
        return sum(r.group.count for r in self.reports)

    @property
    def known_issue_matches(self) -> int:
        return sum(1 for r in self.reports if r.known_issue is not None)


def _format_ts(ts: datetime | None) -> str:
    return ts.strftime(_TS_FORMAT) if ts else "unknown"


def _format_anomaly_block(report: AnomalyReport) -> str:
    """One anomaly as a heading + metadata + a fenced block of its raw log lines.

    Deliberately a plain data dump, not a summary - the companion app reads
    this same structure to research each anomaly with an OpenAI model.
    """
    group = report.group
    emoji = _LEVEL_EMOJI.get(group.level, "•")
    lines = [
        f"#### {emoji} {group.level} × {group.count} — {group.logger}",
        f"- Signature: `{group.signature}`",
        f"- First seen: {_format_ts(group.first_seen)}",
        f"- Last seen: {_format_ts(group.last_seen)}",
        "",
        "```text",
    ]

    shown = group.entries[:MAX_LOG_ENTRIES_PER_ANOMALY]
    for i, entry in enumerate(shown):
        if i > 0:
            lines.append("")
        lines.append(entry.raw)

    remaining = len(group.entries) - len(shown)
    if remaining > 0:
        lines.append("")
        occurrence = "occurrence" if remaining == 1 else "occurrences"
        lines.append(f"... ({remaining} more {occurrence} of this signature not shown)")

    lines.append("```")
    return "\n".join(lines)


def _format_since(since: datetime | None) -> str:
    return since.strftime("%Y-%m-%d %H:%M") if since else "(beginning of retained log)"


def _plural_lines(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


def build_summary_section(result: ScanResult) -> str:
    """Build the "what did Log Doctor actually check" section.

    Always included, even (especially) when nothing was found, so a clean
    run is evidence of a real check rather than an empty message.
    """
    distinct = len(result.reports)
    lines = [
        "## 🩺 Scan summary",
        f"- Home Assistant Core log: `{result.log_path}` ({_plural_lines(result.lines_scanned)})",
        f"- Window checked (Core log): {_format_since(result.since)} → {result.scanned_at.strftime('%Y-%m-%d %H:%M')}",
    ]
    if result.sources_checked:
        lines.append(f"- Other sources checked ({len(result.sources_checked)}):")
        for source in result.sources_checked:
            if source.ok:
                lines.append(f"  - {source.name}: {_plural_lines(source.lines_read)}")
            else:
                lines.append(f"  - {source.name}: unavailable ({source.note or 'no response'})")
    else:
        lines.append(
            "- Other sources checked: none (Supervisor API not reachable - "
            "this isn't a Home Assistant OS/Supervised install, or the "
            "check is disabled)"
        )
    lines += [
        f"- Matching log lines (WARNING+): {result.total_occurrences} across {distinct} distinct anomal{'y' if distinct == 1 else 'ies'}",
        f"- Matched to built-in knowledge base: {result.known_issue_matches}",
    ]
    return "\n".join(lines)


def build_markdown_digest(result: ScanResult) -> str:
    """Build the full markdown report: always a full report, never just a status line."""
    parts: list[str] = [build_summary_section(result)]

    if not result.reports:
        parts.append("### ✅ No anomalies found\nEverything in the window above looked clean.")
    else:
        if result.new_reports:
            parts.append(f"### 🆕 New anomalies ({len(result.new_reports)})")
            parts.extend(_format_anomaly_block(r) for r in result.new_reports)
        if result.recurring_reports:
            parts.append(f"### 🔁 Still occurring ({len(result.recurring_reports)})")
            parts.extend(_format_anomaly_block(r) for r in result.recurring_reports)

    parts.append(
        "\n_Log Doctor only reports issues - it never changes your "
        "configuration or applies fixes automatically._"
    )
    return "\n\n".join(parts)


def build_notification_digest(result: ScanResult) -> str:
    """Short-form digest for the persistent notification.

    Only the anomaly counts: new vs. still occurring. The "what was
    checked" scan summary is on the Log Doctor panel's Settings page (see
    build_scan_summary), per-anomaly detail is in the Log review and the
    retained report file. Only posted when a scan finds something new (see
    coordinator.py).
    """
    return "\n\n".join(
        [
            f"### 🆕 New anomalies: {len(result.new_reports)}",
            f"### 🔁 Still occurring: {len(result.recurring_reports)}",
        ]
    )


def build_scan_summary(result: ScanResult) -> dict[str, Any]:
    """What the scan checked and found, as data for the Settings page.

    The same facts as the report's "Scan summary" section
    (build_summary_section), kept with the scan history so the page can
    show them even after a restart, before the next scan.
    """
    return {
        "scanned_at": result.scanned_at.isoformat(),
        "since": result.since.isoformat() if result.since else None,
        "log_path": result.log_path,
        "lines_scanned": result.lines_scanned,
        "sources": [
            {"name": s.name, "lines_read": s.lines_read, "ok": s.ok, "note": s.note}
            for s in result.sources_checked
        ],
        "matching_lines": result.total_occurrences,
        "anomalies": len(result.reports),
        "new": len(result.new_reports),
        "recurring": len(result.recurring_reports),
        "known_issue_matches": result.known_issue_matches,
        "report_file": result.report_file,
    }


def build_mobile_summary(result: ScanResult) -> tuple[str, str]:
    """Build a short (title, message) pair suitable for a mobile push notification."""
    if not result.reports:
        return (
            "Log Doctor: all clear",
            f"Checked {result.lines_scanned} log lines, nothing found.",
        )

    total = len(result.reports)
    new = len(result.new_reports)
    title = f"Log Doctor: {total} anomal{'y' if total == 1 else 'ies'} found"
    top = result.new_reports[0] if result.new_reports else result.reports[0]
    message = f"{new} new. Top: {top.group.logger} - {top.group.example_message[:120]}"
    return (title, message)
