"""Every automation run, for the Runs section of the panel's Automations page.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.automation_runs`
with one record per run, recorded as it happens from Home Assistant's
automation_triggered event - fired when an automation's actions start, so
runs stopped by their conditions aren't included:

    {"id", "kind": "run", "entity_id", "name", "config_id", "when",
     "trigger", "manual"}

- trigger is Home Assistant's description of what triggered it (e.g.
  "state of binary_sensor.door"). A run started by hand - the Run button or
  the automation.trigger action - has none and is marked manual.
- config_id addresses the automation's editor and traces.

Automations can be excluded: their runs are removed and no more are
recorded until they're included again. Each excluded automation has a
record of its own, listed on the Excluded tab:

    {"id": "excluded:<entity_id>", "kind": "excluded", "entity_id", "name",
     "config_id", "when", "unmonitored"}

Runs older than the report retention window are pruned with each scan,
and at most max_records are kept. Automations can run many times a minute,
so saves are delayed longer than other lists' and subscribers are told
about changes at most once a second.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any, Callable

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .review_list import ReviewList

_LOGGER = logging.getLogger(__name__)

EVENT_AUTOMATION_TRIGGERED = "automation_triggered"

KIND_RUN = "run"
KIND_EXCLUDED = "excluded"

_SAVE_DELAY = 30
_NOTIFY_DELAY = 1.0


def _excluded_id(entity_id: str) -> str:
    return f"excluded:{entity_id}"


class AutomationRunStore(ReviewList):
    storage_key = "log_doctor.automation_runs"
    records_key = "runs"
    max_records = 10_000

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)
        self._notify_unsub: CALLBACK_TYPE | None = None

    @staticmethod
    def sort_key(record: dict[str, Any]) -> str:
        # Excluded automations sort last, so trimming drops old runs first.
        return ("1" if record.get("kind") == KIND_EXCLUDED else "0") + (record.get("when") or "")

    def _excluded(self) -> set[str]:
        return {r["entity_id"] for r in self._records if r.get("kind") == KIND_EXCLUDED}

    @callback
    def async_add_run(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        if not entity_id or entity_id in self._excluded():
            return
        state = self.hass.states.get(entity_id)
        trigger = event.data.get("source")
        self._records.append(
            {
                "id": uuid.uuid4().hex,
                "kind": KIND_RUN,
                "entity_id": entity_id,
                "name": event.data.get("name") or entity_id,
                "config_id": state.attributes.get("id") if state else None,
                "when": event.time_fired.isoformat(),
                "trigger": trigger,
                "manual": not trigger,
                "resolved": None,
            }
        )
        self.async_trim()
        self.async_changed()

    async def async_unmonitor(self, ids: list[str]) -> int:
        """Exclude the automations of the given runs: remove their runs, stop recording."""
        wanted = set(ids)
        chosen = {
            r["entity_id"]: r
            for r in sorted(self._records, key=lambda r: r.get("when") or "")
            if r["id"] in wanted and r.get("kind") == KIND_RUN
        }
        excluded = self._excluded()
        new = {entity_id: r for entity_id, r in chosen.items() if entity_id not in excluded}
        if not new:
            return 0
        now = dt_util.utcnow().isoformat()
        self._records = [
            r for r in self._records if not (r.get("kind") == KIND_RUN and r["entity_id"] in new)
        ]
        for entity_id, run in new.items():
            self._records.append(
                {
                    "id": _excluded_id(entity_id),
                    "kind": KIND_EXCLUDED,
                    "entity_id": entity_id,
                    "name": run.get("name") or entity_id,
                    "config_id": run.get("config_id"),
                    # Its last run before it was excluded.
                    "when": run.get("when"),
                    "trigger": None,
                    "manual": False,
                    "unmonitored": now,
                    "resolved": None,
                }
            )
        self.async_changed()
        return len(new)

    async def async_monitor(self, ids: list[str]) -> int:
        """Include excluded automations again: their next runs are recorded."""
        wanted = set(ids)
        before = len(self._records)
        self._records = [
            r for r in self._records if not (r["id"] in wanted and r.get("kind") == KIND_EXCLUDED)
        ]
        count = before - len(self._records)
        if count:
            self.async_changed()
        return count

    async def async_prune(self, retention_days: int) -> None:
        """Drop runs older than the retention window (excluded automations stay)."""
        if retention_days <= 0:
            return
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        before = len(self._records)
        self._records = [
            r
            for r in self._records
            if r.get("kind") == KIND_EXCLUDED or (r.get("when") or "") >= cutoff
        ]
        if len(self._records) != before:
            self.async_changed()

    @callback
    def async_changed(self) -> None:
        # Coalesced: a busy system can log many runs a minute, and every
        # change sends the whole list to open panels.
        self._store.async_delay_save(self._data_to_save, _SAVE_DELAY)
        if self._notify_unsub is None:
            self._notify_unsub = async_call_later(self.hass, _NOTIFY_DELAY, self._async_notify)

    @callback
    def _async_notify(self, _now: Any = None) -> None:
        self._notify_unsub = None
        for listener in list(self._listeners):
            listener()

    async def async_shutdown(self) -> None:
        if self._notify_unsub is not None:
            self._notify_unsub()
            self._notify_unsub = None
        await super().async_shutdown()


@callback
def async_record_runs(hass: HomeAssistant, store: AutomationRunStore) -> Callable[[], None]:
    """Record every automation run into store; returns the unsubscribe."""
    return hass.bus.async_listen(EVENT_AUTOMATION_TRIGGERED, store.async_add_run)
