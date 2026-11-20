"""Backups watched by Uptime Kuma, on the Backups view.

Some backups run outside Home Assistant - e.g. a script on another machine
cloning its disk to an NVMe drive - and report to an Uptime Kuma push
monitor: up when a run succeeds, down when one fails, and down when no run
has reported in time (a missed run, which logs no error at all). Home
Assistant's Uptime Kuma integration makes each monitor a device with a
Status sensor (up, down, pending or maintenance).

Every Uptime Kuma monitor with "backup" in its name (e.g. "utils.camelot
NVMe Backup") is watched: when its status changes to down, a problem goes
on the Backups view (and, if turned on, a backup failure notification is
sent); when it changes to up, a success. Only changes count - Uptime Kuma
says whether the backup is OK, not each run - so Home Assistant restarting,
or the integration reloading, doesn't add anything when the status is what
was last recorded. Pending (a retry) and maintenance are left alone.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .backup_notify import BackupFailureNotifier
from .backup_store import KIND_PROBLEM, KIND_SUCCESS, BackupStore
from .backups import SOURCE_KUMA

_LOGGER = logging.getLogger(__name__)

KUMA_DOMAIN = "uptime_kuma"
# The Status sensor's unique id ends with this (<entry>_<monitor>_status).
_STATUS_SUFFIX = "_status"
_UP, _DOWN = "up", "down"


def _monitor_name(hass: HomeAssistant, entity_id: str) -> str | None:
    """The monitor's name if entity_id is a watched backup monitor's Status sensor."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != KUMA_DOMAIN or not str(entry.unique_id).endswith(_STATUS_SUFFIX):
        return None
    device = dr.async_get(hass).async_get(entry.device_id) if entry.device_id else None
    name = (device.name_by_user or device.name) if device is not None else None
    name = name or entry.original_name or entity_id
    return name if "backup" in name.lower() else None


def logger_name(monitor: str) -> str:
    """What the Backups view shows under the source for a monitor: its name."""
    return monitor


class UptimeKumaBackupWatch:
    def __init__(
        self, hass: HomeAssistant, store: BackupStore, notifier: BackupFailureNotifier | None = None
    ) -> None:
        self.hass = hass
        self.store = store
        self.notifier = notifier
        # Monitors seen (for diagnostics), by entity id.
        self.monitors: dict[str, str] = {}

    @callback
    def async_start(self) -> Callable[[], None]:
        unsub_state = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, self._on_state_changed, event_filter=self._is_status_sensor
        )
        unsub_started = async_at_started(self.hass, self._async_check_all)

        @callback
        def _stop() -> None:
            unsub_state()
            unsub_started()

        return _stop

    @callback
    def _is_status_sensor(self, event_data: Any) -> bool:
        entity_id = event_data.get("entity_id") or ""
        return entity_id.startswith("sensor.") and _monitor_name(self.hass, entity_id) is not None

    async def _async_check_all(self, _hass: HomeAssistant | None = None) -> None:
        """At start: record any status that differs from the last recorded."""
        for entry in list(er.async_get(self.hass).entities.values()):
            if entry.platform != KUMA_DOMAIN or entry.domain != "sensor":
                continue
            if (state := self.hass.states.get(entry.entity_id)) is not None:
                self._async_status(entry.entity_id, state.state, notify=True)

    @callback
    def _on_state_changed(self, event: Event) -> None:
        new = event.data.get("new_state")
        if new is not None:
            self._async_status(event.data["entity_id"], new.state, notify=True)

    def _last_kind(self, logger: str) -> str | None:
        """Problem or success: whichever was recorded for the monitor last."""
        latest = None
        for record in self.store.records:
            if record.get("source") != SOURCE_KUMA or record.get("logger") != logger:
                continue
            when = record.get("last_seen") or ""
            if latest is None or when > latest[0]:
                latest = (when, record.get("kind"))
        return latest[1] if latest else None

    @callback
    def _async_status(self, entity_id: str, status: str, *, notify: bool) -> None:
        if status not in (_UP, _DOWN):
            return
        if (monitor := _monitor_name(self.hass, entity_id)) is None:
            return
        self.monitors[entity_id] = monitor
        logger = logger_name(monitor)
        kind = KIND_SUCCESS if status == _UP else KIND_PROBLEM
        if self._last_kind(logger) == kind:
            return
        now = dt_util.now()
        if kind == KIND_SUCCESS:
            message = f"{monitor}: OK (Uptime Kuma reports it up)"
            level = "INFO"
        else:
            message = f"{monitor}: failed or didn't run in time (Uptime Kuma reports it down)"
            level = "ERROR"
        self.store.async_record_event(
            source=SOURCE_KUMA, kind=kind, level=level, logger=logger, message=message, when=now
        )
        if kind == KIND_PROBLEM and notify and self.notifier is not None:
            self.notifier.async_failed(
                SOURCE_KUMA,
                [message],
                dt_util.as_utc(now),
                title=f"Backup failed: {monitor}",
                key=f"{SOURCE_KUMA}_{slugify(monitor)}",
            )
