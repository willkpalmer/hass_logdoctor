"""The scan engine that ties log parsing together with the built-in
knowledge base, and (optionally) triggers the investigation stage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_INCLUDE_SUPERVISOR_LOGS,
    DEFAULT_MAX_INVESTIGATED,
    DEFAULT_REPORT_RETENTION_DAYS,
    DOMAIN,
    NOTIFICATION_ID,
    NOTIFICATION_ID_INVESTIGATION,
    PANEL_LOGS_URL,
)
from .digest import (
    AnomalyReport,
    LogSourceSummary,
    ScanResult,
    build_markdown_digest,
    build_mobile_summary,
    build_notification_digest,
)
from .hassio_client import async_fetch_all_logs, async_list_all_sources, supervisor_available
from .investigation import async_investigate_report
from .knowledge_base import match_known_issue
from .log_parser import filter_and_group, parse_log_lines, parse_supervisor_log_text
from .anomaly_store import AnomalyStore
from .failure_store import FailureStore
from .report_files import async_write_report
from .store import LogDoctorStore

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

        sources_checked: list[LogSourceSummary] = []
        if self.include_supervisor_logs and supervisor_available():
            sources = await async_list_all_sources(self.hass)
            fetched = await async_fetch_all_logs(self.hass, sources)
            for log_path, (name, text) in fetched.items():
                if text is None:
                    sources_checked.append(
                        LogSourceSummary(name=name, lines_read=0, ok=False)
                    )
                    continue
                source_lines = text.splitlines()
                entries.extend(
                    parse_supervisor_log_text(text, name, fallback_timestamp=now)
                )
                sources_checked.append(
                    LogSourceSummary(name=name, lines_read=len(source_lines), ok=True)
                )

        groups = filter_and_group(entries, self.min_severity, since)

        reports: list[AnomalyReport] = []
        for signature, group in groups.items():
            is_new = self.store.mark_signature_seen(signature, group.last_seen or now)
            known_issue = match_known_issue(group.logger, group.example_message)
            reports.append(
                AnomalyReport(group=group, is_new=is_new, known_issue=known_issue)
            )

        # Worst-first, then most frequent.
        severity_rank = {"CRITICAL": 3, "ERROR": 2, "WARNING": 1}
        reports.sort(
            key=lambda r: (severity_rank.get(r.group.level, 0), r.group.count),
            reverse=True,
        )

        result = ScanResult(
            scanned_at=now,
            log_path=self.log_path,
            since=since,
            reports=reports,
            lines_scanned=len(lines),
            sources_checked=sources_checked,
        )
        result.report_markdown = build_markdown_digest(result)
        result.report_file = await async_write_report(
            self.hass, result.report_markdown, now, self.report_retention_days
        )
        if self.anomaly_store is not None:
            # Feeds the Log review view of the sidebar panel.
            try:
                await self.anomaly_store.async_record_scan(result.reports, now)
                await self.anomaly_store.async_prune(self.report_retention_days)
            except Exception:  # noqa: BLE001 - never let the review list break the scan
                _LOGGER.exception("Could not update the Log review list")
        if self.failure_store is not None:
            # Old automation failures go on the same retention window as
            # old reports.
            await self.failure_store.async_prune(self.report_retention_days)

        self.store.data.last_scan = now
        self.store.prune(_SIGNATURE_RETENTION)
        await self.store.async_save()

        await self._async_notify(result)

        if (
            self.openai_api_key
            and self.store.data.auto_investigate
            and result.reports
            and result.report_file
        ):
            self.hass.async_create_task(self._async_investigate(result))

        return result

    def _read_log_lines(self) -> list[str]:
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.readlines()
        except FileNotFoundError:
            _LOGGER.warning("Log file not found at %s", self.log_path)
            return []

    async def _async_notify(self, result: ScanResult) -> None:
        title = f"Log Doctor Report - {result.scanned_at.strftime('%Y-%m-%d %H:%M')}"
        message = build_notification_digest(result)
        if result.report_file:
            message += f"\n\n_Full report retained at `{result.report_file}`._"
        if self.anomaly_store is not None and result.reports:
            message += f"\n\n[Review, archive and clear these in Log Doctor]({PANEL_LOGS_URL})"

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
