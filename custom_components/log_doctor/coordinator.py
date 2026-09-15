"""The scan engine that ties log parsing, the knowledge base, and GitHub together."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_GITHUB_CACHE_DAYS,
    DEFAULT_MAX_GITHUB_QUERIES,
    DEFAULT_REPORT_RETENTION_DAYS,
    DOMAIN,
    NOTIFICATION_ID,
)
from .digest import AnomalyReport, ScanResult, build_markdown_digest, build_mobile_summary
from .github_lookup import GitHubLookupClient
from .knowledge_base import match_known_issue
from .log_parser import filter_and_group, parse_log_lines
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
        enable_github_lookup: bool,
        github_token: str | None,
        max_github_queries: int,
        mobile_notify_service: str | None,
        report_retention_days: int = DEFAULT_REPORT_RETENTION_DAYS,
        store: LogDoctorStore,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.hass = hass
        self.log_path = log_path
        self.lookback_hours = lookback_hours
        self.min_severity = min_severity
        self.enable_github_lookup = enable_github_lookup
        self.github_token = github_token
        self.max_github_queries = max_github_queries
        self.mobile_notify_service = mobile_notify_service
        self.report_retention_days = report_retention_days
        self.store = store

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
        groups = filter_and_group(entries, self.min_severity, since)

        reports: list[AnomalyReport] = []
        github_client = (
            GitHubLookupClient(async_get_clientsession(self.hass), self.github_token)
            if self.enable_github_lookup
            else None
        )
        github_queries_used = 0

        for signature, group in groups.items():
            is_new = self.store.mark_signature_seen(signature, group.last_seen or now)
            known_issue = match_known_issue(group.logger, group.example_message)

            github_result = None
            if github_client is not None and known_issue is None:
                cached = self.store.get_cached_github_result(
                    signature, timedelta(days=DEFAULT_GITHUB_CACHE_DAYS)
                )
                if cached is not None:
                    github_result = cached
                elif github_queries_used < self.max_github_queries:
                    github_result = await github_client.search_issues(
                        group.logger, group.example_message
                    )
                    self.store.store_github_result(signature, github_result)
                    github_queries_used += 1

            reports.append(
                AnomalyReport(
                    group=group,
                    is_new=is_new,
                    known_issue=known_issue,
                    github_result=github_result,
                )
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
        )
        result.report_markdown = build_markdown_digest(result)
        result.report_file = await async_write_report(
            self.hass, result.report_markdown, now, self.report_retention_days
        )

        self.store.data.last_scan = now
        self.store.prune(_SIGNATURE_RETENTION)
        await self.store.async_save()

        await self._async_notify(result)
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
        message = result.report_markdown
        if result.report_file:
            message += f"\n\n_Full copy retained at `{result.report_file}`._"

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
