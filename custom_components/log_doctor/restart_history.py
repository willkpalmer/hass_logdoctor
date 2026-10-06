"""The Log Doctor panel's "Restart history" view.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.restart_history`,
with one record per Home Assistant restart recorded by restarts.py - the
windows it uses to tell startup and shutdown messages from the rest:

    {"id" (= the run's id), "shutdown_start", "starting", "started",
     "window_end", "unclean", "current", "resolved", "auto_archived",
     "messages", "errors", "signatures"}

- shutdown_start - when the previous run's clean shutdown began (None if
  it didn't shut down cleanly - unclean - or wasn't recorded); shutdown
  messages are those from then until starting.
- starting / started - when this run began starting and finished starting;
  window_end is started plus the startup grace period, until when messages
  count as startup messages.
- current - the run Home Assistant is in now.
- messages / errors - how many log lines at or above the minimum severity
  (errors: of them, errors and critical) the scans found in this restart's
  shutdown and startup windows; signatures the distinct anomalies they
  belong to (see anomaly_store.py), so the panel can show the restart's
  impact. Added by each scan (async_add_impact), which only reads lines
  logged since the previous one, so nothing is counted twice.

Times are UTC. The history is a copy for display: archiving or deleting
entries here doesn't change how log messages are classified. Only the
newest open_limit entries stay open; older ones are archived automatically
(auto_archived). Deleted entries are remembered, so they aren't added back
from the restart timeline.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .review_list import ReviewList

if TYPE_CHECKING:
    from .restarts import Run

# Ids of deleted entries remembered (more than the restart timeline keeps).
_MAX_DELETED = 200
# Distinct anomalies remembered per restart.
_MAX_SIGNATURES = 200


def _utc(value: datetime | None) -> str | None:
    """A naive local time (as in the log and restarts.py) as UTC ISO."""
    if value is None:
        return None
    return value.astimezone().astimezone(dt_util.UTC).isoformat()


class RestartHistoryStore(ReviewList):
    storage_key = "log_doctor.restart_history"
    records_key = "restarts"
    max_records = 1_000

    def __init__(self, hass: Any) -> None:
        super().__init__(hass)
        self._deleted: list[str] = []

    @staticmethod
    def sort_key(record: dict[str, Any]) -> str:
        return record.get("starting") or ""

    async def async_load(self) -> dict[str, Any] | None:
        data = await super().async_load()
        if data is not None:
            self._deleted = list(data.get("deleted", []))
        return data

    def _data_to_save(self) -> dict[str, Any]:
        return {**super()._data_to_save(), "deleted": self._deleted[-_MAX_DELETED:]}

    async def async_sync(self, runs: list[Run], grace: timedelta, open_limit: int) -> None:
        """Bring the history in line with the restart timeline."""
        by_id = {record["id"]: record for record in self._records}
        deleted = set(self._deleted)
        changed = False
        for index, run in enumerate(runs):
            if run.id in deleted:
                continue
            previous = runs[index - 1] if index else None
            fields = {
                "shutdown_start": _utc(previous.stopping) if previous else None,
                "starting": _utc(run.starting),
                "started": _utc(run.started),
                "window_end": _utc(run.started + grace) if run.started else None,
                "unclean": previous is not None and previous.stopping is None,
                "current": index == len(runs) - 1 and run.stopping is None,
            }
            record = by_id.get(run.id)
            if record is None:
                record = {"id": run.id, "resolved": None, **fields}
                self._records.append(record)
                by_id[run.id] = record
                changed = True
            elif any(record.get(key) != value for key, value in fields.items()):
                record.update(fields)
                changed = True
        changed |= self._auto_archive(open_limit)
        if changed:
            self.async_trim()
            self.async_changed()

    async def async_add_impact(self, impact: dict[str, dict[str, Any]]) -> None:
        """Add a scan's messages to the restarts they were logged during.

        impact: {run id: {"lines", "errors", "signatures" (a set)}}.
        """
        by_id = {record["id"]: record for record in self._records}
        changed = False
        for run_id, tally in impact.items():
            record = by_id.get(run_id)
            if record is None:
                continue
            record["messages"] = record.get("messages", 0) + tally["lines"]
            record["errors"] = record.get("errors", 0) + tally["errors"]
            signatures = list(record.get("signatures") or [])
            signatures.extend(sorted(set(tally["signatures"]) - set(signatures)))
            record["signatures"] = signatures[-_MAX_SIGNATURES:]
            changed = True
        if changed:
            self.async_changed()

    def _auto_archive(self, open_limit: int) -> bool:
        """Archive open entries beyond the newest open_limit."""
        open_records = sorted(
            (r for r in self._records if not r.get("resolved")),
            key=self.sort_key,
            reverse=True,
        )
        now = dt_util.utcnow().isoformat()
        for record in open_records[max(open_limit, 0):]:
            record["resolved"] = now
            record["auto_archived"] = True
        return len(open_records) > open_limit

    async def async_restore(self, ids: list[str]) -> int:
        count = await super().async_restore(ids)
        wanted = set(ids)
        for record in self._records:
            if record["id"] in wanted:
                record.pop("auto_archived", None)
        return count

    async def async_delete(self, ids: list[str]) -> int:
        """Delete archived entries for good, remembering them."""
        count = await super().async_delete(ids)
        if count:
            self._deleted.extend(i for i in ids if i not in self._deleted)
        return count

    async def async_clear_archived(self, ids: list[str] | None = None) -> int:
        archived = {r["id"] for r in self._records if r.get("resolved")}
        if ids is not None:
            archived &= set(ids)
        count = await super().async_clear_archived(ids)
        if count:
            self._deleted.extend(i for i in archived if i not in self._deleted)
        return count
