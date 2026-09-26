"""The backup messages on the Log Doctor panel's "Backups" view.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.backups`.
Records look like the Log review's (see anomaly_store.py) - one per
signature, with a count, first/last seen and the latest raw lines - plus:

    {"kind": "problem" | "success", "source": "ha" | "gdrive"}

(see backups.py for the sources). They come from:

- every scan: backup warnings and errors (problems), which are left out of
  the Log review, and the GDrive Backup Utility add-on's "backup finished"
  and "uploaded" lines (successes);
- Home Assistant's backup manager, as it happens: each backup it
  completes or fails (see backup_monitor.py).

Grouping by signature keeps the list short: one success record per kind of
success, its last seen time being the latest successful backup. Like
anomalies, an archived problem logged again goes back to the open list
marked recurred; an archived success comes back too, without the mark.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback

from .anomaly_store import AnomalyStore
from .log_parser import AnomalyGroup, LogEntry, make_signature

if TYPE_CHECKING:
    from .digest import AnomalyReport

KIND_PROBLEM = "problem"
KIND_SUCCESS = "success"


class BackupStore(AnomalyStore):
    storage_key = "log_doctor.backups"
    records_key = "backups"
    max_records = 2_000

    async def async_record_logs(
        self,
        problems: list[tuple[str, AnomalyReport]],
        successes: list[tuple[str, AnomalyGroup]],
        scanned_at: datetime,
    ) -> None:
        """Add or update the records for one scan's (source, ...) findings."""
        if not problems and not successes:
            return
        by_id = {record["id"]: record for record in self._records}
        for source, report in problems:
            self._upsert_group(
                by_id,
                report.group,
                scanned_at,
                known_issue=report.known_issue,
                extra={"kind": KIND_PROBLEM, "source": source},
            )
        for source, group in successes:
            self._upsert_group(
                by_id,
                group,
                scanned_at,
                extra={"kind": KIND_SUCCESS, "source": source},
                flag_recurred=False,
            )
        self.async_trim()
        self.async_changed()

    @callback
    def async_record_event(
        self,
        *,
        source: str,
        kind: str,
        level: str,
        logger: str,
        message: str,
        when: datetime,
    ) -> None:
        """Add one backup event that didn't come from a log line."""
        raw = f"{when.astimezone().strftime('%Y-%m-%d %H:%M:%S')} {level} [{logger}] {message}"
        group = AnomalyGroup(
            signature=make_signature(logger, message),
            logger=logger,
            level=level,
            example_message=message,
            count=1,
            first_seen=when,
            last_seen=when,
            entries=[LogEntry(timestamp=when, level=level, logger=logger, message=message, raw=raw)],
        )
        self._upsert_group(
            {record["id"]: record for record in self._records},
            group,
            when,
            extra={"kind": kind, "source": source},
            flag_recurred=kind == KIND_PROBLEM,
            append_samples=True,
        )
        self.async_trim()
        self.async_changed()

    async def async_add_records(self, records: list[dict[str, Any]]) -> None:
        """Take over records moved from another list (see __init__.py)."""
        known = {record["id"] for record in self._records}
        added = [r for r in records if r["id"] not in known]
        if added:
            self._records.extend(added)
            self.async_trim()
            self.async_changed()
