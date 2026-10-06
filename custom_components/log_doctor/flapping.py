"""Spots devices that keep dropping off and coming back ("flapping").

A device that goes unavailable for a few seconds at a time - a weak Zigbee
or Wi-Fi link, a failing power supply - is usually back before the
5-minute health check (see health_monitor.py) sees it, so it's never
reported as offline. This watches every entity becoming unavailable as it
happens and remembers when, per device (or per entity with no device), in
`.storage/log_doctor.flaps`:

    {"<device id or entity id>": {"times": [UTC ISO, ...],
                                   "entities": [entity ids]}}

The health check reports any that became unavailable at least `count`
times within the last `window` as a "flapping" problem.

Not counted: changes while Home Assistant is starting or stopping, and
entities of an integration that isn't loaded at that moment (being
reloaded, set up or unloaded), which all go unavailable together.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

STORAGE_VERSION = 1
STORAGE_KEY = "log_doctor.flaps"
_SAVE_DELAY = 60
# Most drops remembered per device, and entity ids listed.
_MAX_TIMES = 200
_MAX_ENTITIES = 25
# A device's entities going unavailable within this long count as one drop.
_SAME_DROP = timedelta(seconds=10)


class FlapTracker:
    def __init__(self, hass: HomeAssistant, *, count: int, window: timedelta) -> None:
        self.hass = hass
        self.count = count
        self.window = window
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._groups: dict[str, dict[str, list[str]]] = {}

    async def async_load(self) -> None:
        self._groups = await self._store.async_load() or {}
        self._prune()

    @callback
    def async_start(self) -> Callable[[], None]:
        return self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)

    async def async_shutdown(self) -> None:
        await self._store.async_save(self._groups)

    @callback
    def _async_state_changed(self, event: Event) -> None:
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        if new is None or old is None:
            return
        if new.state != STATE_UNAVAILABLE or old.state == STATE_UNAVAILABLE:
            return
        if self.hass.state is not CoreState.running:
            return
        entity_id = event.data["entity_id"]
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is not None and entry.config_entry_id:
            config_entry = self.hass.config_entries.async_get_entry(entry.config_entry_id)
            if config_entry is None or config_entry.state is not ConfigEntryState.LOADED:
                return  # being reloaded or unloaded: everything goes at once
        group = entry.device_id if entry is not None and entry.device_id else entity_id
        record = self._groups.setdefault(group, {"times": [], "entities": []})
        last = dt_util.parse_datetime(record["times"][-1]) if record["times"] else None
        # Several of a device's entities going at once is one drop.
        if last is None or event.time_fired - last > _SAME_DROP:
            record["times"] = (record["times"] + [event.time_fired.isoformat()])[-_MAX_TIMES:]
        if entity_id not in record["entities"]:
            record["entities"] = (record["entities"] + [entity_id])[-_MAX_ENTITIES:]
        self._store.async_delay_save(lambda: self._groups, _SAVE_DELAY)

    def _prune(self) -> None:
        cutoff = (dt_util.utcnow() - self.window).isoformat()
        for group in list(self._groups):
            times = [t for t in self._groups[group]["times"] if t >= cutoff]
            if times:
                self._groups[group]["times"] = times
            else:
                del self._groups[group]

    def flapping(self) -> dict[str, tuple[list[datetime], list[str]]]:
        """{group: (drop times, entity ids)} for those over the threshold."""
        self._prune()
        if self.count <= 0:
            return {}
        result = {}
        for group, record in self._groups.items():
            if len(record["times"]) >= self.count:
                times = [dt_util.parse_datetime(t) for t in record["times"]]
                result[group] = ([t for t in times if t is not None], list(record["entities"]))
        return result
