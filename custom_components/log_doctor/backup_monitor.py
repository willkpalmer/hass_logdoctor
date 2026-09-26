"""Watches Home Assistant's built-in backup as it runs.

Home Assistant's backup manager doesn't log a successful backup, so the
scans can't see one. Instead this subscribes to the manager's events - the
same ones the backup integration's "Automatic backup" event entity and
the Backups page use - and adds each backup it completes or fails to the
Backups view (backup_store.py) straight away. Manual and automatic backups
both count, as do backups another app (e.g. the GDrive Backup Utility
add-on) asks Home Assistant to make.

The backup manager isn't a public API, so everything here is looked up
defensively: if it's missing or has changed, the view simply goes without
these events and the scans' log lines still come through.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .backup_store import KIND_PROBLEM, KIND_SUCCESS, BackupStore
from .backups import SOURCE_HA

_LOGGER = logging.getLogger(__name__)

# hass.data key of the backup integration's BackupManager.
_BACKUP_DOMAIN = "backup"
_LOGGER_NAME = "homeassistant.components.backup"


class BackupEventMonitor:
    def __init__(self, hass: HomeAssistant, store: BackupStore) -> None:
        self.hass = hass
        self.store = store
        self._unsubs: list[CALLBACK_TYPE] = []

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        if not self._async_subscribe():
            # Set up after Log Doctor (or not yet at all): wait for it.
            @callback
            def _on_loaded(event: Event) -> None:
                if event.data.get("component") == _BACKUP_DOMAIN:
                    self._async_subscribe()

            self._unsubs.append(self.hass.bus.async_listen(EVENT_COMPONENT_LOADED, _on_loaded))
        return self._async_stop

    @callback
    def _async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _async_subscribe(self) -> bool:
        manager = self.hass.data.get(_BACKUP_DOMAIN)
        subscribe = getattr(manager, "async_subscribe_events", None)
        if subscribe is None:
            return False
        try:
            self._unsubs.append(subscribe(self._on_event))
        except Exception:  # noqa: BLE001 - an internal API; never break setup
            _LOGGER.warning("Could not watch Home Assistant's backups", exc_info=True)
            return False
        return True

    @callback
    def _on_event(self, event: Any) -> None:
        # CreateBackupEvent: manager_state "create_backup", state
        # "in_progress" / "completed" / "failed", reason an error code.
        if str(getattr(event, "manager_state", "")) != "create_backup":
            return
        state = str(getattr(event, "state", ""))
        if state == "completed":
            self.store.async_record_event(
                source=SOURCE_HA,
                kind=KIND_SUCCESS,
                level="INFO",
                logger=_LOGGER_NAME,
                message="Backup completed",
                when=dt_util.now(),
            )
        elif state == "failed":
            reason = getattr(event, "reason", None) or "unknown_error"
            self.store.async_record_event(
                source=SOURCE_HA,
                kind=KIND_PROBLEM,
                level="ERROR",
                logger=_LOGGER_NAME,
                message=f"Backup failed: {str(reason).replace('_', ' ')}",
                when=dt_util.now(),
            )
