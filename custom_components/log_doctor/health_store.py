"""The problems on the Log Doctor panel's "Devices & integrations" view.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.health`,
filled by health_monitor.py. One record per problem:

    {"id", "kind", "name", "sub", "detail", "since", "link", "entities",
     "active", "resolved", "recurred", "recovered"}

kind is "offline" (a device or entity unavailable), "integration"
(failed to load) or "repair" (a Home Assistant Repairs issue). Low
battery checks were dropped in 0.23.0 (battery data is too unreliable
across integrations); their records are removed on load.

Unlike log anomalies, these are conditions that end by themselves, so each
record tracks whether the problem is still there ("active"):

- A new problem is added to the open list.
- When a problem clears (the device comes back, the integration loads, the repair is fixed or dismissed), its record is
  archived automatically, marked "recovered".
- Marking a problem resolved while it's still there archives it as
  acknowledged; it stays archived for as long as the problem lasts.
- If an archived problem comes back after it had cleared, it returns to
  the open list marked "recurred".
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .review_list import ReviewList

# Fields refreshed from every check.
_DISPLAY_FIELDS = ("name", "sub", "detail", "link", "entities", "kind")


class HealthStore(ReviewList):
    storage_key = "log_doctor.health"
    records_key = "issues"
    max_records = 5_000

    async def async_load(self) -> dict[str, Any] | None:
        data = await super().async_load()
        before = len(self._records)
        self._records = [r for r in self._records if r.get("kind") != "battery"]
        if len(self._records) != before:
            self.async_changed()
        return data

    @staticmethod
    def sort_key(record: dict[str, Any]) -> str:
        return record.get("since") or ""

    async def async_update(self, current: dict[str, dict[str, Any]]) -> None:
        """Reconcile the list with the problems found by one check."""
        now = dt_util.utcnow().isoformat()
        changed = False
        by_id = {record["id"]: record for record in self._records}

        for issue_id, issue in current.items():
            record = by_id.get(issue_id)
            if record is None:
                record = {
                    "id": issue_id,
                    **{key: issue.get(key) for key in _DISPLAY_FIELDS},
                    "since": issue.get("since") or now,
                    "active": True,
                    "resolved": None,
                    "recurred": False,
                    "recovered": False,
                }
                self._records.append(record)
                changed = True
                continue
            for key in _DISPLAY_FIELDS:
                if record.get(key) != issue.get(key):
                    record[key] = issue.get(key)
                    changed = True
            if not record.get("active"):
                # It had cleared and is back.
                record["active"] = True
                record["since"] = issue.get("since") or now
                record["recovered"] = False
                if record.get("resolved"):
                    record["resolved"] = None
                    record["recurred"] = True
                changed = True

        for record in self._records:
            if record["id"] not in current and record.get("active"):
                record["active"] = False
                if not record.get("resolved"):
                    # Cleared by itself: archive it.
                    record["resolved"] = now
                    record["recovered"] = True
                changed = True

        if changed:
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
        """Drop archived problems that ended before the retention window."""
        if retention_days <= 0:
            return
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        before = len(self._records)
        self._records = [
            r
            for r in self._records
            if r.get("active") or not r.get("resolved") or r["resolved"] >= cutoff
        ]
        if len(self._records) != before:
            self.async_changed()
