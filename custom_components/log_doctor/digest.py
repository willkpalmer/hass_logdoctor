"""Build the human-readable daily digest from a scan's anomalies."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .github_lookup import GitHubLookupResult
from .knowledge_base import KnownIssue
from .log_parser import AnomalyGroup

_LEVEL_EMOJI = {"WARNING": "⚠️", "ERROR": "🛑", "CRITICAL": "🔴"}


@dataclass
class AnomalyReport:
    """Everything Log Doctor found out about a single anomaly group."""

    group: AnomalyGroup
    is_new: bool
    known_issue: KnownIssue | None = None
    github_result: GitHubLookupResult | None = None

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
            "known_fix_title": self.known_issue.title if self.known_issue else None,
            "known_fix": self.known_issue.fix if self.known_issue else None,
            "doc_url": self.known_issue.doc_url if self.known_issue else None,
            "github_matches": (
                [m.__dict__ for m in self.github_result.matches]
                if self.github_result
                else []
            ),
            "github_search_url": self.github_result.search_url if self.github_result else None,
        }


@dataclass
class ScanResult:
    """The full outcome of one scan run."""

    scanned_at: datetime
    reports: list[AnomalyReport] = field(default_factory=list)
    lines_scanned: int = 0
    error: str | None = None

    @property
    def new_reports(self) -> list[AnomalyReport]:
        return [r for r in self.reports if r.is_new]

    @property
    def recurring_reports(self) -> list[AnomalyReport]:
        return [r for r in self.reports if not r.is_new]


def _format_report_line(report: AnomalyReport) -> str:
    emoji = _LEVEL_EMOJI.get(report.group.level, "•")
    lines = [
        f"{emoji} **{report.group.logger}** ({report.group.level}, x{report.group.count})",
        f"  {report.group.example_message[:220]}",
    ]
    if report.known_issue:
        lines.append(f"  📖 *Known issue:* {report.known_issue.title}")
        lines.append(f"     Fix: {report.known_issue.fix}")
        if report.known_issue.doc_url:
            lines.append(f"     Docs: {report.known_issue.doc_url}")
    elif report.github_result and report.github_result.matches:
        lines.append("  🔗 Related GitHub issues:")
        for match in report.github_result.matches:
            state = "✅ closed" if match.state == "closed" else "🟢 open"
            lines.append(f"     - [{state}] {match.title}\n       {match.url}")
    elif report.github_result and report.github_result.error:
        lines.append(f"  🔍 GitHub lookup skipped ({report.github_result.error})")
    elif report.github_result:
        lines.append(f"  🔍 No matching GitHub issues found. Search: {report.github_result.search_url}")
    return "\n".join(lines)


def build_markdown_digest(result: ScanResult) -> str:
    """Build the full markdown digest shown in the persistent notification."""
    if not result.reports:
        return (
            f"No warnings or errors found in the Home Assistant log "
            f"as of {result.scanned_at.strftime('%Y-%m-%d %H:%M')}. ✅"
        )

    parts: list[str] = []
    if result.new_reports:
        parts.append(f"### 🆕 New anomalies ({len(result.new_reports)})")
        parts.extend(_format_report_line(r) for r in result.new_reports)
    if result.recurring_reports:
        parts.append(f"### 🔁 Still occurring ({len(result.recurring_reports)})")
        parts.extend(_format_report_line(r) for r in result.recurring_reports)

    parts.append(
        "\n_Log Doctor only reports issues - it never changes your "
        "configuration or applies fixes automatically._"
    )
    return "\n\n".join(parts)


def build_mobile_summary(result: ScanResult) -> tuple[str, str]:
    """Build a short (title, message) pair suitable for a mobile push notification."""
    if not result.reports:
        return ("Log Doctor: all clear", "No new warnings or errors found today.")

    total = len(result.reports)
    new = len(result.new_reports)
    title = f"Log Doctor: {total} anomal{'y' if total == 1 else 'ies'} found"
    top = result.new_reports[0] if result.new_reports else result.reports[0]
    message = f"{new} new. Top: {top.group.logger} - {top.group.example_message[:120]}"
    return (title, message)
