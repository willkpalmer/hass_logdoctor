"""Build the human-readable daily digest from a scan's anomalies."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .community_lookup import CommunityLookupResult
from .github_lookup import GitHubLookupResult
from .ha_docs_lookup import DocsLookupResult
from .knowledge_base import KnownIssue
from .log_parser import AnomalyGroup

_LEVEL_EMOJI = {"WARNING": "⚠️", "ERROR": "🛑", "CRITICAL": "🔴"}


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
    github_result: GitHubLookupResult | None = None
    docs_result: DocsLookupResult | None = None
    community_result: CommunityLookupResult | None = None

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
            "docs_matches": (
                [m.__dict__ for m in self.docs_result.matches] if self.docs_result else []
            ),
            "community_matches": (
                [m.__dict__ for m in self.community_result.matches]
                if self.community_result
                else []
            ),
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

    @property
    def github_checked(self) -> int:
        return sum(1 for r in self.reports if r.github_result is not None)

    @property
    def github_found(self) -> int:
        return sum(
            1 for r in self.reports if r.github_result and r.github_result.matches
        )

    @property
    def github_skipped(self) -> int:
        return sum(1 for r in self.reports if r.github_result and r.github_result.error)

    @property
    def docs_checked(self) -> int:
        return sum(1 for r in self.reports if r.docs_result is not None)

    @property
    def docs_found(self) -> int:
        return sum(1 for r in self.reports if r.docs_result and r.docs_result.matches)

    @property
    def community_checked(self) -> int:
        return sum(1 for r in self.reports if r.community_result is not None)

    @property
    def community_found(self) -> int:
        return sum(
            1 for r in self.reports if r.community_result and r.community_result.matches
        )

    @property
    def community_solved(self) -> int:
        return sum(
            1
            for r in self.reports
            if r.community_result
            and any(m.solved for m in r.community_result.matches)
        )


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
        return "\n".join(lines)

    found_anything = False

    if report.docs_result and report.docs_result.matches:
        found_anything = True
        lines.append("  📘 Home Assistant docs:")
        for match in report.docs_result.matches:
            lines.append(f"     - {match.title}")
            if match.snippet:
                lines.append(f'       "{match.snippet}"')
            lines.append(f"       {match.url}")

    if report.community_result and report.community_result.matches:
        found_anything = True
        lines.append("  💬 Community forum:")
        for match in report.community_result.matches:
            status = "✅ solved" if match.solved else f"{match.reply_count} replies"
            lines.append(f"     - [{status}] {match.title}")
            if match.excerpt:
                lines.append(f'       "{match.excerpt}"')
            lines.append(f"       {match.url}")

    if report.github_result and report.github_result.matches:
        found_anything = True
        lines.append("  🔗 GitHub issues:")
        for match in report.github_result.matches:
            state = "✅ closed" if match.state == "closed" else "🟢 open"
            lines.append(f"     - [{state}] {match.title}")
            lines.append(f"       {match.url}")

    if not found_anything:
        errors = sorted(
            {
                r.error
                for r in (report.docs_result, report.community_result, report.github_result)
                if r and r.error
            }
        )
        if errors:
            lines.append(f"  🔍 External lookups skipped ({', '.join(errors)})")
        elif report.docs_result or report.community_result or report.github_result:
            lines.append(
                "  🔍 No matches found in the knowledge base, docs, community, or GitHub."
            )

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
    researched = max(result.docs_checked, result.community_checked, result.github_checked)
    if researched:
        lines.append(f"- Researched online for {researched} unmatched anomalies:")
        lines.append(
            f"  - Home Assistant docs: {result.docs_found} with a related page found"
        )
        lines.append(
            f"  - Community forum: {result.community_found} with related discussion "
            f"found ({result.community_solved} marked solved)"
        )
        lines.append(
            f"  - GitHub: {result.github_found} with related issues found, "
            f"{result.github_skipped} skipped/rate-limited"
        )
    else:
        lines.append(
            "- Researched online: nothing needed it (all matched or lookups disabled)"
        )
    return "\n".join(lines)


def build_markdown_digest(result: ScanResult) -> str:
    """Build the full markdown digest: always a full report, never just a status line."""
    parts: list[str] = [build_summary_section(result)]

    if not result.reports:
        parts.append("### ✅ No anomalies found\nEverything in the window above looked clean.")
    else:
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


def build_notification_digest(result: ScanResult) -> str:
    """Short-form digest for the persistent notification.

    Keeps the full "what was checked" scan summary, but shows only totals
    for new vs. still-occurring anomalies rather than writing each one out
    - that per-anomaly detail (message, known fix, GitHub matches) still
    lives in full in the retained report file and on
    sensor.log_doctor_anomalies's attributes.
    """
    parts: list[str] = [build_summary_section(result)]

    if not result.reports:
        parts.append("### ✅ No anomalies found")
    else:
        parts.append(f"### 🆕 New anomalies: {len(result.new_reports)}")
        parts.append(f"### 🔁 Still occurring: {len(result.recurring_reports)}")
        parts.append(
            "_Details for each one are in the full report and on "
            "`sensor.log_doctor_anomalies`._"
        )

    parts.append(
        "\n_Log Doctor only reports issues - it never changes your "
        "configuration or applies fixes automatically._"
    )
    return "\n\n".join(parts)


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
