"""Every automation run and scene activation, in the order they happened,
for the History section of the panel's Automations page.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.automation_runs`
with one record per automation run, recorded as it happens from Home
Assistant's automation_triggered event - fired when an automation's actions
start, so runs stopped by their conditions aren't included:

    {"id", "kind": "run", "entity_id", "name", "config_id", "when",
     "trigger", "trigger_name", "manual", "by", "by_kind", "by_entity",
     "by_config_id"}

and one per scene activation, from the scene's state changing (a scene's
state is when it was last activated):

    {"id", "kind": "scene", "entity_id", "name", "config_id", "when",
     "by", "by_kind", "by_entity", "by_config_id"}

by is who or what started it (see activity_context.py): a person
("Will", by_kind "user"), an automation or script (by_kind "automation" /
"script", by_entity and by_config_id to link to it), or None when it can't
be told (a device, an integration, Home Assistant itself). For an
automation run that's who pressed Run (or which automation or script
started it), or for a triggered one, who caused its trigger, if anyone.

- trigger is Home Assistant's description of what triggered it (e.g.
  "sun event sunset"), trigger_name which of the automation's triggers it
  was: its alias, or a description of its config like "Sunset +00:15:00"
  (see trigger_names.py; None when that can't be worked out, and on runs
  recorded before 0.41.0). A run started by hand - the Run button or the
  automation.trigger action - has neither and is marked manual.
- config_id addresses the automation's editor and traces.

Automations and scenes can be excluded ("Stop monitoring"): their runs or
activations are removed and no more are recorded until they're included
again. Each excluded automation has a
record of its own, listed on the Excluded tab:

    {"id": "excluded:<entity_id>", "kind": "excluded", "entity_id", "name",
     "config_id", "when", "unmonitored"}

Runs older than the report retention window are pruned with each scan,
and at most max_records are kept (the oldest runs go first). Automations
can run many times a minute, so saves are delayed longer than other lists'
and subscribers are told about changes at most once a second - and when
all that happened was new runs (and the oldest dropped to make room), only
those, as a delta, rather than the whole list again.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .activity_context import ContextTracker
from .review_list import ReviewList
from .trigger_names import run_trigger_name

_LOGGER = logging.getLogger(__name__)

EVENT_AUTOMATION_TRIGGERED = "automation_triggered"

KIND_RUN = "run"
KIND_SCENE = "scene"
# What the history lists (as opposed to excluded automations and scenes).
ACTIVITY_KINDS = (KIND_RUN, KIND_SCENE)
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
        # What's changed since subscribers were last told: runs added and
        # ids removed, or (full) anything else, which sends the whole list.
        self._added: list[dict[str, Any]] = []
        self._removed: list[str] = []
        self._full = False
        # Who or what started things (set by async_record_runs).
        self.contexts: ContextTracker | None = None

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
        record = {
            "id": uuid.uuid4().hex,
            "kind": KIND_RUN,
            "entity_id": entity_id,
            "name": event.data.get("name") or entity_id,
            "config_id": state.attributes.get("id") if state else None,
            "when": event.time_fired.isoformat(),
            "trigger": trigger,
            "trigger_name": run_trigger_name(self.hass, event) if trigger else None,
            "manual": not trigger,
            "resolved": None,
        }
        record.update(self._by(event.context, skip=entity_id))
        self._add(record)

    @callback
    def async_add_scene(self, event: Event) -> None:
        """A scene activated: its state (when it was last activated) changed."""
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        entity_id = event.data.get("entity_id") or ""
        if not entity_id.startswith("scene.") or new is None or old is None:
            return  # added or removed, not activated
        if new.state in ("unavailable", "unknown") or new.state == old.state:
            return
        if entity_id in self._excluded():
            return
        record = {
            "id": uuid.uuid4().hex,
            "kind": KIND_SCENE,
            "entity_id": entity_id,
            "name": new.name or entity_id,
            "config_id": new.attributes.get("id"),
            "when": new.last_changed.isoformat(),
            "trigger": None,
            "trigger_name": None,
            "manual": False,
            "resolved": None,
        }
        record.update(self._by(new.context))
        self._add(record)

    def _by(self, context: Any, skip: str | None = None) -> dict[str, Any]:
        found = self.contexts.describe(context, skip=skip) if self.contexts is not None else None
        return found or {"by": None, "by_kind": None}

    @callback
    def _add(self, record: dict[str, Any]) -> None:
        self._records.append(record)
        self._added.append(record)
        self._drop_oldest_runs()
        self._store.async_delay_save(self._data_to_save, _SAVE_DELAY)
        self._schedule_notify()

    def _drop_oldest_runs(self) -> None:
        """Keep at most max_records, dropping the oldest runs.

        Runs are added as they happen, so the oldest are the first in the
        list; no sorting needed.
        """
        excess = len(self._records) - self.max_records
        if excess <= 0:
            return
        dropped: set[str] = set()
        for record in self._records:
            if len(dropped) >= excess:
                break
            if record.get("kind") in ACTIVITY_KINDS:
                dropped.add(record["id"])
        self._records = [r for r in self._records if r["id"] not in dropped]
        # Runs added and dropped before subscribers heard of them: neither.
        added_ids = {r["id"] for r in self._added}
        self._removed.extend(i for i in dropped if i not in added_ids)
        self._added = [r for r in self._added if r["id"] not in dropped]

    async def async_unmonitor(self, ids: list[str]) -> int:
        """Exclude the automations (and scenes) of the given entries: remove them, stop recording."""
        wanted = set(ids)
        chosen = {
            r["entity_id"]: r
            for r in sorted(self._records, key=lambda r: r.get("when") or "")
            if r["id"] in wanted and r.get("kind") in ACTIVITY_KINDS
        }
        excluded = self._excluded()
        new = {entity_id: r for entity_id, r in chosen.items() if entity_id not in excluded}
        if not new:
            return 0
        now = dt_util.utcnow().isoformat()
        self._records = [
            r for r in self._records if not (r.get("kind") in ACTIVITY_KINDS and r["entity_id"] in new)
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

    def _prune_time(self, record: dict[str, Any]) -> str | None:
        """Runs age by when they ran; excluded automations stay."""
        if record.get("kind") == KIND_EXCLUDED:
            return None
        return record.get("when") or ""

    @callback
    def async_changed(self) -> None:
        """Anything but new runs: subscribers get the whole list again."""
        self._full = True
        self._store.async_delay_save(self._data_to_save, _SAVE_DELAY)
        self._schedule_notify()

    @callback
    def _schedule_notify(self) -> None:
        # Coalesced: a busy system can log many runs a minute.
        if self._notify_unsub is None:
            self._notify_unsub = async_call_later(self.hass, _NOTIFY_DELAY, self._async_notify)

    @callback
    def _async_notify(self, _now: Any = None) -> None:
        self._notify_unsub = None
        if self._full:
            delta = None
        else:
            delta = {"added": self._added, "removed": self._removed}
        self._added, self._removed, self._full = [], [], False
        if delta is None or delta["added"] or delta["removed"]:
            self._notify(delta)

    async def async_shutdown(self) -> None:
        if self._notify_unsub is not None:
            self._notify_unsub()
            self._notify_unsub = None
        await super().async_shutdown()


@callback
def async_record_runs(hass: HomeAssistant, store: AutomationRunStore) -> Callable[[], None]:
    """Record every automation run and scene activation into store; returns the unsubscribe."""
    contexts = ContextTracker(hass)
    store.contexts = contexts
    # The tracker first, so a run's own context is known when it's recorded.
    unsubs = [
        contexts.async_start(),
        hass.bus.async_listen(EVENT_AUTOMATION_TRIGGERED, store.async_add_run),
        hass.bus.async_listen(EVENT_STATE_CHANGED, store.async_add_scene, event_filter=_is_scene),
    ]

    @callback
    def _stop() -> None:
        for unsub in unsubs:
            unsub()
        store.contexts = None

    return _stop


@callback
def _is_scene(event_data: Any) -> bool:
    return str(event_data.get("entity_id", "")).startswith("scene.")
