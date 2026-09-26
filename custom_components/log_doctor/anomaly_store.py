"""The anomalies on the Log Doctor panel's "Log review" view.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.anomalies`,
with one record per anomaly - a signature grouping the same underlying log
message (see log_parser.py) - updated after every scan:

    {"id" (= signature), "level", "logger", "message", "count", "scans",
     "first_seen", "last_seen", "last_scan", "samples", "known_issue",
     "resolved", "recurred"}

- count is the total number of matching log lines across all scans (each
  scan only counts lines since the previous one), scans how many scans
  found it.
- samples are the raw lines (with tracebacks) from the latest scan that
  found it, a few at most.
- Marking an anomaly resolved archives it. If a later scan finds it again
  with lines logged *after* it was resolved, it goes back to the open list
  with recurred set, so a fix that didn't hold doesn't go unnoticed.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .const import SEVERITY_ORDER
from .review_list import ReviewList

if TYPE_CHECKING:
    from .digest import AnomalyReport

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
        scan_iso = self._to_utc(scanned_at, scanned_at)
        by_id = {record["id"]: record for record in self._records}
        for report in reports:
            group = report.group
            first_seen = self._to_utc(group.first_seen, scanned_at)
            last_seen = self._to_utc(group.last_seen, scanned_at)
            samples = [
                (entry.raw or entry.message)[:MAX_SAMPLE_CHARS]
                for entry in group.entries[-MAX_SAMPLES:]
            ]
            known = report.known_issue
            known_issue = (
                {
                    "title": known.title,
                    "explanation": known.explanation,
                    "fix": known.fix,
                    "doc_url": known.doc_url,
                }
                if known
                else None
            )

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

            record["count"] += group.count
            record["scans"] += 1
            record["first_seen"] = min(record["first_seen"], first_seen)
            record["last_seen"] = max(record["last_seen"], last_seen)
            record["last_scan"] = scan_iso
            record["message"] = group.example_message
            record["samples"] = samples
            record["known_issue"] = known_issue
            if SEVERITY_ORDER.get(group.level, 0) > SEVERITY_ORDER.get(record["level"], 0):
                record["level"] = group.level
            if record.get("resolved") and last_seen > record["resolved"]:
                # Logged again after it was marked resolved.
                record["resolved"] = None
                record["recurred"] = True

        self.async_trim()
        self.async_changed()

    async def async_resolve(self, ids: list[str]) -> int:
        count = await super().async_resolve(ids)
        wanted = set(ids)
        for record in self._records:
            if record["id"] in wanted and record.get("resolved"):
                record["recurred"] = False
        return count

    async def async_prune(self, retention_days: int) -> None:
        """Drop anomalies not seen within the retention window (0 = keep all)."""
        if retention_days <= 0:
            return
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        before = len(self._records)
        self._records = [r for r in self._records if (r.get("last_seen") or "") >= cutoff]
        if len(self._records) != before:
            self.async_changed()
