"""A reviewable list: open entries that can be resolved into an archive.

Shared by the lists on the Log Doctor sidebar panel:

- failure_store.py - automation failures ("Automation failures" view)
- anomaly_store.py - anomalies reported by the scans ("Log review" view)
- health_store.py - device and integration problems ("Devices &
  integrations" view)
- backup_store.py - backup problems and successes ("Backups" view)

Each is kept in Home Assistant's storage as a list of records (dicts with
at least an "id" and a "resolved" timestamp, None while open). Marking
records resolved moves them to the archive; restoring moves them back;
clearing the archive deletes every archived record for good. Saves are
debounced, and anyone subscribed (the panel, via websocket_api.py) is told
straight away after every change.
"""
from __future__ import annotations

from typing import Any, Callable

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

# Coalesce bursts of changes into one save.
WRITE_DELAY = 5

Listener = Callable[[], None]


class ReviewList:
    """Base class; subclasses add records and may react to changes."""

    storage_key: str
    # Key of the record list inside the stored data.
    records_key: str
    storage_version = 1
    # Upper bound on stored records, open and archived together; the ones
    # sorting first by sort_key() are dropped first.
    max_records = 10_000

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, self.storage_version, self.storage_key
        )
        self._records: list[dict[str, Any]] = []
        self._listeners: set[Listener] = set()
        # Set on unload; subscribers are told once more so they can
        # re-subscribe to the list that replaces this one.
        self.closed = False

    @property
    def records(self) -> list[dict[str, Any]]:
        return self._records

    @staticmethod
    def sort_key(record: dict[str, Any]) -> str:
        """Oldest first; used when trimming to max_records."""
        return record.get("when", "")

    async def async_load(self) -> dict[str, Any] | None:
        """Load the stored records; returns the raw data (None if new)."""
        data = await self._store.async_load()
        if data is not None:
            self._records = list(data.get(self.records_key, []))
        return data

    @callback
    def async_subscribe(self, listener: Listener) -> CALLBACK_TYPE:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def async_resolve(self, ids: list[str]) -> int:
        """Move open records to the archive."""
        now = dt_util.utcnow().isoformat()
        wanted = set(ids)
        count = 0
        for record in self._records:
            if record["id"] in wanted and not record.get("resolved"):
                record["resolved"] = now
                count += 1
        if count:
            self.async_changed()
        return count

    async def async_restore(self, ids: list[str]) -> int:
        """Move archived records back to the open list."""
        wanted = set(ids)
        count = 0
        for record in self._records:
            if record["id"] in wanted and record.get("resolved"):
                record["resolved"] = None
                count += 1
        if count:
            self.async_changed()
        return count

    async def async_clear_archived(self) -> int:
        """Delete every archived record for good."""
        before = len(self._records)
        self._records = [r for r in self._records if not r.get("resolved")]
        removed = before - len(self._records)
        if removed:
            self.async_changed()
        return removed

    @callback
    def async_trim(self) -> None:
        if len(self._records) > self.max_records:
            self._records.sort(key=self.sort_key)
            del self._records[: len(self._records) - self.max_records]

    async def async_shutdown(self) -> None:
        """On unload: save now, then tell subscribers to re-subscribe.

        Saves are otherwise delayed a few seconds; without saving here, a
        reload inside that window would load the old data from disk and
        lose the latest changes.
        """
        self.closed = True
        await self._store.async_save(self._data_to_save())
        for listener in list(self._listeners):
            listener()
        self._listeners.clear()

    @callback
    def async_changed(self) -> None:
        self._store.async_delay_save(self._data_to_save, WRITE_DELAY)
        for listener in list(self._listeners):
            listener()

    def _data_to_save(self) -> dict[str, Any]:
        return {self.records_key: self._records}
