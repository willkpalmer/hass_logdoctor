"""The problems on the Log Doctor panel's "Devices & integrations" view.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.health`,
filled by health_monitor.py. One record per problem:

    {"id", "kind", "name", "sub", "detail", "since", "link", "entities",
     "active", "resolved", "recurred", "recovered", "ignored",
     "ignored_entities", "unmonitored"}

kind is "offline" (a device or entity unavailable), "unavailable" (some
of a device's entities unavailable), "integration"
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
- Ignoring a problem (ignored = when) moves it to the Ignored tab, for
  entities that are unavailable on purpose but still needed. It keeps
  being checked (active, detail, entities) but stays there whether it
  clears or comes back, and isn't pruned - as long as only the entities
  unavailable when it was ignored (ignored_entities) are. If another of
  its entities becomes unavailable, it returns to the open list marked
  "recurred". Stopping ignoring it moves it back to the open list (or the
  archive, if it has cleared).
- Marking a device (or an entity with no device) not monitored
  (unmonitored = when) stops reporting it altogether: checks leave its
  record alone, whatever becomes unavailable or isn't provided any more,
  and it's listed on the Not monitored tab. Monitoring it again removes
  the record and checks straight away (recheck), so a device that's still
  unavailable is back on the open list as a new problem.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .review_list import ReviewList

# Fields refreshed from every check.
_DISPLAY_FIELDS = ("name", "sub", "detail", "link", "entities", "kind", "integration", "integration_name", "integration_core")


# Kinds that are a device or an entity, which can be marked not monitored.
_DEVICE_KINDS = ("offline", "unavailable")


class HealthStore(ReviewList):
    storage_key = "log_doctor.health"
    # Set by __init__.py to the health monitor's check (see async_monitor).
    recheck: Any = None
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
            if record is not None and record.get("unmonitored"):
                continue  # not reported any more
            if record is not None and record.get("ignored"):
                if self._update_ignored(record, issue, now):
                    changed = True
                continue
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
            if record.get("unmonitored"):
                continue
            if record["id"] not in current and record.get("active") and record.get("ignored"):
                # Cleared while ignored: it stays ignored.
                record["active"] = False
                changed = True
                continue
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

    def _update_ignored(self, record: dict[str, Any], issue: dict[str, Any], now: str) -> bool:
        """One check's finding for an ignored problem. True if it changed."""
        changed = False
        for key in _DISPLAY_FIELDS:
            if record.get(key) != issue.get(key):
                record[key] = issue.get(key)
                changed = True
        if not record.get("active"):
            record["active"] = True
            record["since"] = issue.get("since") or now
            changed = True
        new = set(issue.get("entities") or []) - set(record.get("ignored_entities") or [])
        if new:
            # Something else is unavailable now: show it again.
            record["ignored"] = None
            record.pop("ignored_entities", None)
            record["resolved"] = None
            record["recovered"] = False
            record["recurred"] = True
            changed = True
        return changed

    async def async_unmonitor(self, ids: list[str]) -> int:
        """Stop reporting devices (or entities with no device) altogether."""
        now = dt_util.utcnow().isoformat()
        wanted = set(ids)
        count = 0
        for record in self._records:
            if (
                record["id"] in wanted
                and record.get("kind") in _DEVICE_KINDS
                and not record.get("unmonitored")
            ):
                record["unmonitored"] = now
                record["ignored"] = None
                record.pop("ignored_entities", None)
                record["resolved"] = None
                record["recurred"] = False
                record["recovered"] = False
                count += 1
        if count:
            self.async_changed()
        return count

    async def async_monitor(self, ids: list[str]) -> int:
        """Monitor devices again: forget them, then check straight away."""
        wanted = set(ids)
        before = len(self._records)
        self._records = [
            r for r in self._records if not (r["id"] in wanted and r.get("unmonitored"))
        ]
        count = before - len(self._records)
        if count:
            self.async_changed()
            if self.recheck is not None:
                self.hass.async_create_task(self.recheck())
        return count

    async def async_ignore(self, ids: list[str]) -> int:
        """Move problems to the Ignored tab, from open or archived."""
        now = dt_util.utcnow().isoformat()
        wanted = set(ids)
        count = 0
        for record in self._records:
            if record["id"] in wanted and not record.get("ignored") and not record.get("unmonitored"):
                record["ignored"] = now
                record["ignored_entities"] = list(record.get("entities") or [])
                record["resolved"] = None
                record["recurred"] = False
                record["recovered"] = False
                count += 1
        if count:
            self.async_changed()
        return count

    async def async_unignore(self, ids: list[str]) -> int:
        """Stop ignoring problems: back to the open list, or archived if cleared."""
        now = dt_util.utcnow().isoformat()
        wanted = set(ids)
        count = 0
        for record in self._records:
            if record["id"] in wanted and record.get("ignored"):
                record["ignored"] = None
                record.pop("ignored_entities", None)
                if not record.get("active"):
                    record["resolved"] = now
                    record["recovered"] = True
                count += 1
        if count:
            self.async_changed()
        return count

    async def async_resolve(self, ids: list[str]) -> int:
        # Ignored and unmonitored problems stay where they are.
        ignored = {r["id"] for r in self._records if r.get("ignored") or r.get("unmonitored")}
        ids = [i for i in ids if i not in ignored]
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
            if r.get("active")
            or r.get("ignored")
            or r.get("unmonitored")
            or not r.get("resolved")
            or r["resolved"] >= cutoff
        ]
        if len(self._records) != before:
            self.async_changed()
