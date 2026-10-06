"""The scan engine that ties log parsing together with the built-in
knowledge base, and (optionally) triggers the investigation stage.

Home Assistant starts a new log file on every start, moving the old one to
<log>.1, so when the previous log was written to after the last scan, the
lines since that scan are read from it too - otherwise everything logged
between the last scan and a restart, the shutdown included, would be
missed. Anomalies logged only while Home Assistant was starting or shutting
down (see restarts.py) are kept apart from the rest, for the panel's
Startup & shutdown view.
"""
from __future__ import annotations

import hashlib
import logging
import os
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_INCLUDE_SUPERVISOR_LOGS,
    DEFAULT_INVESTIGATION_MODEL,
    DEFAULT_MAX_INVESTIGATED,
    DEFAULT_REPORT_RETENTION_DAYS,
    DOMAIN,
    NOTIFICATION_ID,
    NOTIFICATION_ID_INVESTIGATION,
    PANEL_BACKUPS_URL,
    PANEL_LOGS_URL,
    PANEL_RESTARTS_URL,
    WEEKDAYS,
)
from .digest import (
    AnomalyReport,
    LogSourceSummary,
    ScanResult,
    build_markdown_digest,
    build_mobile_summary,
    build_notification_digest,
    build_scan_summary,
)
from .hassio_client import async_fetch_all_logs, async_list_all_sources, supervisor_available
from .investigation import async_investigate_report
from .knowledge_base import match_known_issue
from .log_parser import (
    AnomalyGroup,
    LogEntry,
    filter_and_group,
    parse_log_lines,
    parse_supervisor_log_text,
)
from .anomaly_store import AnomalyStore
from .automation_runs import AutomationRunStore
from .backup_store import BackupStore
from .backups import is_backup_success, is_gdrive_addon, split_backup_entries
from .failure_store import FailureStore
from .health_store import HealthStore
from .report_files import async_write_report
from .restarts import RestartTracker
from .stats import StatsStore
from .store import LogDoctorStore
from .weekly_digest import WeeklyDigest, async_send_digest

_LOGGER = logging.getLogger(__name__)

# Signatures already reported are dropped from history after this long
# without reoccurring, to keep the store from growing forever.
_SIGNATURE_RETENTION = timedelta(days=90)


class LogDoctorCoordinator(DataUpdateCoordinator[ScanResult]):
    """Runs on demand (never on a fixed poll interval) to scan the log."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        log_path: str,
        lookback_hours: int,
        min_severity: str,
        mobile_notify_service: str | None,
        report_retention_days: int = DEFAULT_REPORT_RETENTION_DAYS,
        include_supervisor_logs: bool = DEFAULT_INCLUDE_SUPERVISOR_LOGS,
        openai_api_key: str | None = None,
        max_investigated: int = DEFAULT_MAX_INVESTIGATED,
        store: LogDoctorStore,
        failure_store: FailureStore | None = None,
        anomaly_store: AnomalyStore | None = None,
        health_store: HealthStore | None = None,
        backup_store: BackupStore | None = None,
        restarts: RestartTracker | None = None,
        run_store: AutomationRunStore | None = None,
        stats: StatsStore | None = None,
        investigation_model: str = DEFAULT_INVESTIGATION_MODEL,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.hass = hass
        self.log_path = log_path
        self.lookback_hours = lookback_hours
        self.min_severity = min_severity
        self.mobile_notify_service = mobile_notify_service
        self.report_retention_days = report_retention_days
        self.include_supervisor_logs = include_supervisor_logs
        self.openai_api_key = openai_api_key
        self.max_investigated = max_investigated
        self.store = store
        self.failure_store = failure_store
        self.anomaly_store = anomaly_store
        self.health_store = health_store
        self.backup_store = backup_store
        self.restarts = restarts
        self.run_store = run_store
        self.stats = stats
        self.investigation_model = investigation_model

    async def _async_update_data(self) -> ScanResult:
        try:
            return await self._async_scan()
        except OSError as err:
            raise UpdateFailed(f"Could not read log file: {err}") from err

    async def _async_scan(self) -> ScanResult:
        now = datetime.now()
        lines = await self.hass.async_add_executor_job(self._read_log_lines)

        entries = parse_log_lines(lines)
        since = self.store.data.last_scan or (now - timedelta(hours=self.lookback_hours))

        previous_path = f"{self.log_path}.1"
        previous_lines = await self.hass.async_add_executor_job(
            self._read_previous_log_lines, previous_path, since
        )
        if previous_lines:
            # Only what the current log doesn't have.
            cutoff = entries[0].timestamp if entries else None
            entries = [
                entry
                for entry in parse_log_lines(previous_lines)
                if cutoff is None or entry.timestamp < cutoff
            ] + entries

        sources_checked: list[LogSourceSummary] = []
        supervisor_sources: set[str] = set()
        if self.include_supervisor_logs and supervisor_available():
            sources = await async_list_all_sources(self.hass)
            # The GDrive Backup Utility add-on's log: only lines in Home
            # Assistant's format, which drops lines from before its v0.9.0.
            gdrive_paths = {
                path
                for path, name in sources
                if path.startswith("addons/") and is_gdrive_addon(path.split("/")[1], name)
            }
            fetched = await async_fetch_all_logs(self.hass, sources)
            supervisor_sources = {name for name, _text in fetched.values()}
            for log_path, (name, text) in fetched.items():
                if text is None:
                    sources_checked.append(
                        LogSourceSummary(name=name, lines_read=0, ok=False)
                    )
                    continue
                source_lines = text.splitlines()
                parsed = parse_supervisor_log_text(
                    text,
                    name,
                    fallback_timestamp=now,
                    structured_only=log_path in gdrive_paths,
                )
                entries.extend(self._skip_untimed_repeats(name, parsed))
                sources_checked.append(
                    LogSourceSummary(name=name, lines_read=len(source_lines), ok=True)
                )
            # Sources that are gone (e.g. an add-on removed) are forgotten.
            for gone in set(self.store.data.untimed_seen) - supervisor_sources:
                del self.store.data.untimed_seen[gone]

        if self.stats is not None:
            # Warnings and errors over time, for Insights and the weekly digest.
            self.stats.record(entries, since, supervisor_sources)
            self.stats.prune(self.report_retention_days)

        # Backup messages go to the Backups view instead of the Log review.
        entries, backup_entries = split_backup_entries(entries)

        reports = self._reports(filter_and_group(entries, self.min_severity, since), now)
        impact = self._classify_restarts(reports)
        restart_reports = [report for report in reports if report.restart]
        reports = [report for report in reports if not report.restart]
        backup_reports: list[tuple[str, AnomalyReport]] = []
        backup_successes: list[tuple[str, AnomalyGroup]] = []
        for source, source_entries in backup_entries.items():
            backup_reports.extend(
                (source, report)
                for report in self._reports(
                    filter_and_group(source_entries, self.min_severity, since), now
                )
            )
            successes = [e for e in source_entries if is_backup_success(source, e)]
            backup_successes.extend(
                (source, group)
                for group in filter_and_group(successes, "INFO", since).values()
            )

        result = ScanResult(
            scanned_at=now,
            log_path=self.log_path,
            since=since,
            reports=reports,
            lines_scanned=len(lines),
            sources_checked=sources_checked,
            backup_reports=[report for _source, report in backup_reports],
            backup_successes=sum(group.count for _source, group in backup_successes),
            restart_reports=restart_reports,
            previous_log_lines=len(previous_lines),
            previous_log_path=previous_path,
        )
        result.report_markdown = build_markdown_digest(result)
        result.report_file = await async_write_report(
            self.hass, result.report_markdown, now, self.report_retention_days
        )
        if self.anomaly_store is not None:
            # Feeds the Log review view of the sidebar panel.
            try:
                await self.anomaly_store.async_record_scan(
                    result.reports + result.restart_reports, now
                )
                await self.anomaly_store.async_prune(self.report_retention_days)
            except Exception:  # noqa: BLE001 - never let the review list break the scan
                _LOGGER.exception("Could not update the Log review list")
        if self.backup_store is not None:
            # Feeds the Backups view of the sidebar panel.
            try:
                await self.backup_store.async_record_logs(backup_reports, backup_successes, now)
                await self.backup_store.async_prune(self.report_retention_days)
            except Exception:  # noqa: BLE001 - never let the review list break the scan
                _LOGGER.exception("Could not update the Backups list")
        if impact and self.restarts is not None and self.restarts.history is not None:
            # Each restart's messages, on the Restart history.
            try:
                await self.restarts.history.async_add_impact(impact)
            except Exception:  # noqa: BLE001 - never let the history break the scan
                _LOGGER.exception("Could not update the Restart history")
        if self.health_store is not None:
            await self.health_store.async_prune(self.report_retention_days)
        if self.failure_store is not None:
            # Old automation failures go on the same retention window as
            # old reports.
            await self.failure_store.async_prune(self.report_retention_days)
        if self.run_store is not None:
            # And so do the recorded automation runs.
            await self.run_store.async_prune(self.report_retention_days)

        self.store.data.last_scan = now
        self.store.data.last_summary = build_scan_summary(result)
        self.store.prune(_SIGNATURE_RETENTION)
        await self.store.async_save()

        await self._async_notify(result)

        if (
            self.openai_api_key
            and self.store.data.auto_investigate
            and (result.reports or result.restart_reports)
            and result.report_file
        ):
            self.hass.async_create_task(self._async_investigate(result))

        return result

    def _skip_untimed_repeats(self, source: str, entries: list[LogEntry]) -> list[LogEntry]:
        """Drop untimed lines that were in this source's last fetch.

        Lines that don't say when they were logged are given the scan's
        time, so the "since the last scan" cut can't tell old from new; the
        Supervisor returns the same newest lines each time, so without this
        every scan would count them again. Lines are matched by content,
        as many times as they appeared last time: a line logged once more
        since is still counted.
        """
        previous = Counter(self.store.data.untimed_seen.get(source, {}))
        current: Counter[str] = Counter()
        kept: list[LogEntry] = []
        for entry in entries:
            if entry.timed:
                kept.append(entry)
                continue
            key = hashlib.sha1((entry.raw or entry.message).encode()).hexdigest()[:16]
            current[key] += 1
            if previous[key] > 0:
                previous[key] -= 1
                continue
            kept.append(entry)
        if current:
            self.store.data.untimed_seen[source] = dict(current)
        else:
            self.store.data.untimed_seen.pop(source, None)
        return kept

    def _reports(self, groups: dict[str, AnomalyGroup], now: datetime) -> list[AnomalyReport]:
        """One report per group, worst-first, then most frequent."""
        reports: list[AnomalyReport] = []
        for signature, group in groups.items():
            is_new = self.store.mark_signature_seen(signature, group.last_seen or now)
            known_issue = match_known_issue(group.logger, group.example_message)
            reports.append(
                AnomalyReport(group=group, is_new=is_new, known_issue=known_issue)
            )
        severity_rank = {"CRITICAL": 3, "ERROR": 2, "WARNING": 1}
        reports.sort(
            key=lambda r: (severity_rank.get(r.group.level, 0), r.group.count),
            reverse=True,
        )
        return reports

    def _classify_restarts(self, reports: list[AnomalyReport]) -> dict[str, dict[str, Any]]:
        """Mark the anomalies that belong on the Startup & shutdown view.

        Returns each restart's messages from this scan, for the Restart
        history: {run id: {"lines", "errors", "signatures"}}.
        """
        impact: dict[str, dict[str, Any]] = {}
        if self.restarts is None or self.anomaly_store is None:
            return impact
        for report in reports:
            phases: set[str] = set()
            runs: set[str] = set()
            while_running = False
            timed = False
            for entry in report.group.entries:
                if not entry.timed:
                    # When it was really logged is unknown: it can't say
                    # whether this happens at restarts or while running.
                    continue
                timed = True
                found = self.restarts.phase_of(entry.timestamp)
                if found is None:
                    while_running = True
                else:
                    phases.add(found[0])
                    runs.add(found[1])
                    tally = impact.setdefault(
                        found[1], {"lines": 0, "errors": 0, "signatures": set()}
                    )
                    tally["lines"] += 1
                    if entry.level in ("ERROR", "CRITICAL"):
                        tally["errors"] += 1
                    tally["signatures"].add(report.signature)
            report.phases = sorted(phases)
            report.restart_runs = sorted(runs)
            if timed:
                report.restart = self.anomaly_store.is_restart_only(
                    report.signature, restart_lines_only=not while_running
                )
            else:
                # Nothing to go on: it stays where it is (new ones: Log review).
                report.restart = self.anomaly_store.is_restart_category(report.signature)
        return impact

    @staticmethod
    def _read_previous_log_lines(path: str, since: datetime) -> list[str]:
        """The previous log's lines, if it was written to after `since`."""
        try:
            if datetime.fromtimestamp(os.path.getmtime(path)) < since:
                return []
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.readlines()
        except OSError:
            return []

    def _read_log_lines(self) -> list[str]:
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.readlines()
        except FileNotFoundError:
            _LOGGER.warning("Log file not found at %s", self.log_path)
            return []

    async def _async_notify(self, result: ScanResult) -> None:
        # Only speak up when there's something new; the scan summary is on
        # the Log Doctor panel's Settings page after every scan either way.
        if (
            not result.new_reports
            and not result.new_backup_reports
            and not result.new_restart_reports
        ):
            return

        title = f"Log Doctor Report - {result.scanned_at.strftime('%Y-%m-%d %H:%M')}"
        message = build_notification_digest(result)
        if self.anomaly_store is not None and result.new_reports:
            message += f"\n\n[Review, archive and clear these in Log Doctor]({PANEL_LOGS_URL})"
        if self.backup_store is not None and result.new_backup_reports:
            message += f"\n\n[See the backup problems in Log Doctor]({PANEL_BACKUPS_URL})"
        if self.anomaly_store is not None and result.new_restart_reports:
            message += f"\n\n[See the startup and shutdown messages in Log Doctor]({PANEL_RESTARTS_URL})"

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {"notification_id": NOTIFICATION_ID, "title": title, "message": message},
            blocking=True,
        )

        if self.mobile_notify_service:
            mobile_title, mobile_message = build_mobile_summary(result)
            try:
                await self.hass.services.async_call(
                    "notify",
                    self.mobile_notify_service,
                    {"title": mobile_title, "message": mobile_message},
                    blocking=True,
                )
            except Exception:  # noqa: BLE001 - never let a bad notify target break the scan
                _LOGGER.exception(
                    "Failed to send mobile notification via notify.%s",
                    self.mobile_notify_service,
                )

    async def async_send_weekly_digest(self) -> WeeklyDigest:
        """Send the weekly digest now (see weekly_digest.py)."""
        digest = await async_send_digest(
            self.hass,
            mobile_notify_service=self.mobile_notify_service,
            retention_days=self.report_retention_days,
        )
        self.store.data.last_digest = dt_util.utcnow().isoformat()
        await self.store.async_save()
        return digest

    def weekly_digest_due(self, weekday: str) -> bool:
        """Whether today is the digest day and it hasn't gone out today."""
        today = dt_util.now()
        if WEEKDAYS[today.weekday()] != weekday:
            return False
        last = dt_util.parse_datetime(self.store.data.last_digest or "")
        return last is None or dt_util.as_local(last).date() != today.date()

    async def _async_investigate(self, result: ScanResult) -> None:
        """Run the investigation stage against the report this scan just wrote.

        Scheduled as its own background task (never awaited by _async_scan)
        so a slow investigation - one OpenAI call per anomaly - never delays
        the scan itself or the "Scan now" service call returning. Always
        posts its own persistent notification when it finishes, separate
        from the scan's, whether it found something, found nothing to
        investigate, or failed.
        """
        try:
            investigation = await async_investigate_report(
                self.hass,
                Path(result.report_file),
                self.openai_api_key,
                self.max_investigated,
                self.report_retention_days,
                self.investigation_model,
            )
        except Exception:  # noqa: BLE001 - never let a bad investigation go unreported
            _LOGGER.exception("Log Doctor investigation stage failed unexpectedly")
            investigation = None

        title = f"Log Doctor Investigation - {result.scanned_at.strftime('%Y-%m-%d %H:%M')}"

        if investigation is None:
            message = "⚠️ The investigation stage failed unexpectedly. Check the Home Assistant log for details."
        elif investigation.error:
            message = f"⚠️ Investigation failed: {investigation.error}"
        elif investigation.investigated == 0:
            message = "No anomalies in this scan needed investigating."
        else:
            plural = "y" if investigation.investigated == 1 else "ies"
            message = (
                f"Investigated {investigation.investigated} anomal{plural} from "
                f"`{result.report_file}`."
            )
            if investigation.skipped_over_cap:
                skipped_plural = "y" if investigation.skipped_over_cap == 1 else "ies"
                message += (
                    f"\n\n{investigation.skipped_over_cap} more "
                    f"anomal{skipped_plural} skipped (over the "
                    f"{self.max_investigated}-per-scan limit)."
                )
            if investigation.findings_file:
                message += f"\n\nFindings retained at `{investigation.findings_file}`."

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": NOTIFICATION_ID_INVESTIGATION,
                "title": title,
                "message": message,
            },
            blocking=True,
        )
