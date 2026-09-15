"""The scan engine that ties log parsing, the knowledge base, and online
research (GitHub, Home Assistant docs, Community forum) together.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .community_lookup import CommunityLookupClient, CommunityLookupResult
from .const import (
    DEFAULT_GITHUB_CACHE_DAYS,
    DEFAULT_INCLUDE_SUPERVISOR_LOGS,
    DEFAULT_MAX_GITHUB_QUERIES,
    DEFAULT_REPORT_RETENTION_DAYS,
    DOMAIN,
    NOTIFICATION_ID,
)
from .digest import (
    AnomalyReport,
    LogSourceSummary,
    ScanResult,
    build_markdown_digest,
    build_mobile_summary,
    build_notification_digest,
)
from .github_lookup import GitHubLookupClient, GitHubLookupResult
from .ha_docs_lookup import DocsLookupResult, HADocsLookupClient
from .hassio_client import async_fetch_all_logs, async_list_all_sources, supervisor_available
from .knowledge_base import match_known_issue
from .log_parser import AnomalyGroup, filter_and_group, parse_log_lines, parse_supervisor_log_text
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
        include_supervisor_logs: bool = DEFAULT_INCLUDE_SUPERVISOR_LOGS,
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
        self.include_supervisor_logs = include_supervisor_logs
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
        session = async_get_clientsession(self.hass)
        github_client = (
            GitHubLookupClient(session, self.github_token)
            if self.enable_github_lookup
            else None
        )
        docs_client = HADocsLookupClient(session) if self.enable_github_lookup else None
        community_client = (
            CommunityLookupClient(session) if self.enable_github_lookup else None
        )
        research_used = 0

        for signature, group in groups.items():
            is_new = self.store.mark_signature_seen(signature, group.last_seen or now)
            known_issue = match_known_issue(group.logger, group.example_message)

            github_result = docs_result = community_result = None
            if known_issue is None and (github_client or docs_client or community_client):
                allow_fetch = research_used < self.max_github_queries
                github_result, docs_result, community_result, fetched = (
                    await self._research_anomaly(
                        signature,
                        group,
                        github_client,
                        docs_client,
                        community_client,
                        allow_fetch=allow_fetch,
                    )
                )
                if fetched:
                    research_used += 1

            reports.append(
                AnomalyReport(
                    group=group,
                    is_new=is_new,
                    known_issue=known_issue,
                    github_result=github_result,
                    docs_result=docs_result,
                    community_result=community_result,
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
            sources_checked=sources_checked,
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

    async def _research_anomaly(
        self,
        signature: str,
        group: AnomalyGroup,
        github_client: GitHubLookupClient | None,
        docs_client: HADocsLookupClient | None,
        community_client: CommunityLookupClient | None,
        allow_fetch: bool,
    ) -> tuple[
        GitHubLookupResult | None, DocsLookupResult | None, CommunityLookupResult | None, bool
    ]:
        """Look up an anomaly with no built-in known-issue match online.

        Checks GitHub issues, the Home Assistant docs, and the Community
        forum together for every anomaly that needs it (each cached
        independently). `allow_fetch` gates whether *new* network lookups
        may happen this scan (the per-scan research budget); when it's
        False, only already-cached results are returned. Returns
        (github_result, docs_result, community_result, fetched) where
        `fetched` is True if this call made any fresh network request (so
        the caller can count it against the budget).
        """
        cache_ttl = timedelta(days=DEFAULT_GITHUB_CACHE_DAYS)
        github_result = (
            self.store.get_cached_github_result(signature, cache_ttl) if github_client else None
        )
        docs_result = (
            self.store.get_cached_docs_result(signature, cache_ttl) if docs_client else None
        )
        community_result = (
            self.store.get_cached_community_result(signature, cache_ttl)
            if community_client
            else None
        )

        needs = {
            "github": github_client is not None and github_result is None,
            "docs": docs_client is not None and docs_result is None,
            "community": community_client is not None and community_result is None,
        }
        if not any(needs.values()) or not allow_fetch:
            return github_result, docs_result, community_result, False

        tasks: dict[str, asyncio.Task] = {}
        if needs["github"]:
            tasks["github"] = asyncio.ensure_future(
                github_client.search_issues(group.logger, group.example_message)
            )
        if needs["docs"]:
            tasks["docs"] = asyncio.ensure_future(
                docs_client.search(group.logger, group.example_message)
            )
        if needs["community"]:
            tasks["community"] = asyncio.ensure_future(
                community_client.search(group.logger, group.example_message)
            )

        fetched_results = await asyncio.gather(*tasks.values())
        fetched = dict(zip(tasks.keys(), fetched_results, strict=True))

        if "github" in fetched:
            github_result = fetched["github"]
            self.store.store_github_result(signature, github_result)
        if "docs" in fetched:
            docs_result = fetched["docs"]
            self.store.store_docs_result(signature, docs_result)
        if "community" in fetched:
            community_result = fetched["community"]
            self.store.store_community_result(signature, community_result)

        return github_result, docs_result, community_result, True

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
