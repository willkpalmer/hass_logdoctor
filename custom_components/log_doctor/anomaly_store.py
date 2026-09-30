"""The anomalies on the Log Doctor panel's "Log review" view.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.anomalies`,
with one record per anomaly - a signature grouping the same underlying log
message (see log_parser.py) - updated after every scan:

    {"id" (= signature), "level", "logger", "message", "count", "scans",
     "first_seen", "last_seen", "last_scan", "samples", "known_issue",
     "resolved", "recurred", "ignored", "ignored_count", "category",
     "phases", "restarts", "restart_runs", "while_running", "last_logged"}

- last_seen is the latest of its lines' times; a line without a time of
  its own (some Supervisor sources) gets the scan's. last_logged is the
  latest time a line itself says it was logged (None if none said), and
  last_scan when a scan last found it.

- count is the total number of matching log lines across all scans (each
  scan only counts lines since the previous one), scans how many scans
  found it.
- samples are the raw lines (with tracebacks) from the latest scan that
  found it, a few at most.
- Marking an anomaly resolved archives it. If a later scan finds it again
  with lines logged *after* it was resolved, it goes back to the open list
  with recurred set, so a fix that didn't hold doesn't go unnoticed.
- Ignoring an anomaly (ignored = when) moves it to the Ignored tab, for
  recurring messages that are harmless or can't be fixed. Scans keep
  updating it (count, last seen, samples) and ignored_count counts the
  lines logged since it was ignored, but it never goes back to the open
  list by itself; stopping ignoring it does. Ignored anomalies aren't
  pruned, so one that's quiet for a while isn't reported as new again.

category splits the list between two panel views (see restarts.py):
"operational" (the Log review; also records from before 0.29.0, which have
none) and "restart" (the Startup & shutdown view):

- A new anomaly whose lines were all logged during a startup or shutdown
  is a "restart" one; otherwise it's "operational".
- A "restart" anomaly logged again while Home Assistant was running
  normally becomes "operational", with while_running set to when, so the
  panel can mark it. An operational one never moves the other way by
  itself.
- The panel can move anomalies either way by hand (async_set_category).
- phases are the phases it was logged in ("startup", "shutdown"),
  restarts how many restarts it was logged during, and restart_runs the
  latest of those restarts' ids, so one split across two scans is only
  counted once.

Backup messages are left out; they're on the Backups view instead (see
backup_store.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.util import dt as dt_util

from .const import SEVERITY_ORDER
from .log_parser import line_timestamp
from .review_list import ReviewList

if TYPE_CHECKING:
    from .digest import AnomalyReport
    from .knowledge_base import KnownIssue
    from .log_parser import AnomalyGroup

# Raw log lines kept per anomaly, and the most characters kept per line
# (a line can carry a whole traceback).
MAX_SAMPLES = 5
MAX_SAMPLE_CHARS = 4000
# Restart ids remembered per anomaly (see _apply_restarts).
MAX_RESTART_RUNS = 20

CATEGORY_OPERATIONAL = "operational"
CATEGORY_RESTART = "restart"


class AnomalyStore(ReviewList):
    storage_key = "log_doctor.anomalies"
    records_key = "anomalies"
    max_records = 5_000

    async def async_load(self) -> dict[str, Any] | None:
        data = await super().async_load()
        # Records from before 0.32.0: last_logged from their kept lines.
        filled = False
        for record in self._records:
            if "last_logged" in record:
                continue
            times = [t for raw in record.get("samples") or [] if (t := line_timestamp(raw))]
            record["last_logged"] = self._to_utc(max(times), max(times)) if times else None
            filled = True
        if filled:
            self.async_changed()
        return data

    @staticmethod
    def sort_key(record: dict[str, Any]) -> str:
        return record.get("last_seen") or ""

    @staticmethod
    def _to_utc(value: datetime | None, fallback: datetime) -> str:
        """Store timestamps as UTC.

        Log timestamps (and the scan's datetime.now()) are naive, in the
        machine's local time - that's what Python's logging writes - which
        isn't necessarily Home Assistant's configured time zone (e.g. a
        Docker install without TZ set), so astimezone() is used rather than
        attaching the configured zone.
        """
        if value is None:
            value = fallback
        if value.tzinfo is None:
            value = value.astimezone()
        return dt_util.as_utc(value).isoformat()

    async def async_record_scan(self, reports: list[AnomalyReport], scanned_at: datetime) -> None:
        """Add or update one record per anomaly a scan reported."""
        if not reports:
            return
        by_id = {record["id"]: record for record in self._records}
        for report in reports:
            record = self._upsert_group(
                by_id, report.group, scanned_at, known_issue=report.known_issue
            )
            self._apply_restarts(record, report, scanned_at)
        self.async_trim()
        self.async_changed()

    def is_restart_only(self, signature: str, restart_lines_only: bool) -> bool:
        """Whether a scan's anomaly belongs on the Startup & shutdown view.

        restart_lines_only: all its lines this scan were logged during a
        startup or shutdown. A known anomaly keeps its category unless
        it's now been logged while running.
        """
        if not restart_lines_only:
            return False
        record = next((r for r in self._records if r["id"] == signature), None)
        return record is None or record.get("category") == CATEGORY_RESTART

    def is_restart_category(self, signature: str) -> bool:
        """Whether a known anomaly is on the Startup & shutdown view."""
        record = next((r for r in self._records if r["id"] == signature), None)
        return record is not None and record.get("category") == CATEGORY_RESTART

    def _apply_restarts(
        self, record: dict[str, Any], report: AnomalyReport, scanned_at: datetime
    ) -> None:
        if report.restart:
            record["category"] = CATEGORY_RESTART
        else:
            if record.get("category") == CATEGORY_RESTART:
                # Logged while running: it isn't just a restart message.
                record["while_running"] = self._to_utc(scanned_at, scanned_at)
            record["category"] = CATEGORY_OPERATIONAL
        if report.phases:
            record["phases"] = sorted(set(record.get("phases") or []) | set(report.phases))
        runs = list(record.get("restart_runs") or [])
        for run in report.restart_runs:
            if run not in runs:
                runs.append(run)
                record["restarts"] = record.get("restarts", 0) + 1
        if runs:
            record["restart_runs"] = runs[-MAX_RESTART_RUNS:]

    async def async_set_category(self, ids: list[str], category: str) -> int:
        """Move records between the Log review and Startup & shutdown views."""
        wanted = set(ids)
        count = 0
        for record in self._records:
            if record["id"] in wanted and record.get("category", CATEGORY_OPERATIONAL) != category:
                record["category"] = category
                record.pop("while_running", None)
                count += 1
        if count:
            self.async_changed()
        return count

    def _upsert_group(
        self,
        by_id: dict[str, dict[str, Any]],
        group: AnomalyGroup,
        scanned_at: datetime,
        *,
        known_issue: KnownIssue | None = None,
        extra: dict[str, Any] | None = None,
        flag_recurred: bool = True,
        append_samples: bool = False,
    ) -> dict[str, Any]:
        """Add or update the record for one group of log lines.

        samples are replaced by the group's lines, or with append_samples
        added to the ones already kept.
        """
        scan_iso = self._to_utc(scanned_at, scanned_at)
        first_seen = self._to_utc(group.first_seen, scanned_at)
        last_seen = self._to_utc(group.last_seen, scanned_at)
        samples = [
            (entry.raw or entry.message)[:MAX_SAMPLE_CHARS]
            for entry in group.entries[-MAX_SAMPLES:]
        ]

        record = by_id.get(group.signature)
        if record is None:
            record = {
                "id": group.signature,
                "level": group.level,
                "logger": group.logger,
                "message": group.example_message,
                "count": 0,
                "scans": 0,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "resolved": None,
                "recurred": False,
            }
            self._records.append(record)
            by_id[group.signature] = record

        record.update(extra or {})
        record["count"] += group.count
        record["scans"] += 1
        record["first_seen"] = min(record["first_seen"], first_seen)
        record["last_seen"] = max(record["last_seen"], last_seen)
        record["last_scan"] = scan_iso
        record["message"] = group.example_message
        logged = [entry.timestamp for entry in group.entries if entry.timed]
        if logged:
            newest = self._to_utc(max(logged), scanned_at)
            record["last_logged"] = max(record.get("last_logged") or "", newest)
        else:
            record.setdefault("last_logged", None)
        if append_samples:
            samples = (record.get("samples", []) + samples)[-MAX_SAMPLES:]
        record["samples"] = samples
        record["known_issue"] = (
            {
                "title": known_issue.title,
                "explanation": known_issue.explanation,
                "fix": known_issue.fix,
                "doc_url": known_issue.doc_url,
            }
            if known_issue
            else None
        )
        if SEVERITY_ORDER.get(group.level, 0) > SEVERITY_ORDER.get(record["level"], 0):
            record["level"] = group.level
        if record.get("ignored"):
            record["ignored_count"] = record.get("ignored_count", 0) + group.count
        elif record.get("resolved") and last_seen > record["resolved"]:
            # Logged again after it was marked resolved.
            record["resolved"] = None
            record["recurred"] = flag_recurred
        return record

    async def async_resolve(self, ids: list[str]) -> int:
        # Ignored records stay ignored.
        ignored = {r["id"] for r in self._records if r.get("ignored")}
        ids = [i for i in ids if i not in ignored]
        count = await super().async_resolve(ids)
        wanted = set(ids)
        for record in self._records:
            if record["id"] in wanted and record.get("resolved"):
                record["recurred"] = False
                record.pop("while_running", None)
        return count

    async def async_ignore(self, ids: list[str]) -> int:
        """Move records to the Ignored tab, from open or archived."""
        now = dt_util.utcnow().isoformat()
        wanted = set(ids)
        count = 0
        for record in self._records:
            if record["id"] in wanted and not record.get("ignored"):
                record["ignored"] = now
                record["ignored_count"] = 0
                record["resolved"] = None
                record["recurred"] = False
                count += 1
        if count:
            self.async_changed()
        return count

    async def async_unignore(self, ids: list[str]) -> int:
        """Stop ignoring records; they go back to the open list."""
        wanted = set(ids)
        count = 0
        for record in self._records:
            if record["id"] in wanted and record.get("ignored"):
                record["ignored"] = None
                record.pop("ignored_count", None)
                count += 1
        if count:
            self.async_changed()
        return count

    async def async_prune(self, retention_days: int) -> None:
        """Drop anomalies not seen within the retention window (0 = keep all)."""
        if retention_days <= 0:
            return
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        before = len(self._records)
        self._records = [
            r for r in self._records if r.get("ignored") or (r.get("last_seen") or "") >= cutoff
        ]
        if len(self._records) != before:
            self.async_changed()

    async def async_take(self, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        """Remove and return the records matching predicate."""
        taken = [r for r in self._records if predicate(r)]
        if taken:
            self._records = [r for r in self._records if not predicate(r)]
            self.async_changed()
        return taken
