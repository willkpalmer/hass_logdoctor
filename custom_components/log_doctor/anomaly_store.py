"""The anomalies on the Log Doctor panel's "Log review" view.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.anomalies`,
with one record per anomaly - a signature grouping the same underlying log
message (see log_parser.py) - updated after every scan:

    {"id" (= signature), "level", "logger", "message", "count", "scans",
     "first_seen", "last_seen", "last_scan", "samples", "known_issue",
     "resolved", "recurred", "ignored", "ignored_count"}

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

Backup messages are left out; they're on the Backups view instead (see
backup_store.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.util import dt as dt_util

from .const import SEVERITY_ORDER
from .review_list import ReviewList

if TYPE_CHECKING:
    from .digest import AnomalyReport
    from .knowledge_base import KnownIssue
    from .log_parser import AnomalyGroup

# Raw log lines kept per anomaly, and the most characters kept per line
# (a line can carry a whole traceback).
MAX_SAMPLES = 5
MAX_SAMPLE_CHARS = 4000


class AnomalyStore(ReviewList):
    storage_key = "log_doctor.anomalies"
    records_key = "anomalies"
    max_records = 5_000

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
            self._upsert_group(by_id, report.group, scanned_at, known_issue=report.known_issue)
        self.async_trim()
        self.async_changed()

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
