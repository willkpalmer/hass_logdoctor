"""The list of automation failures behind the "Automation failures" panel.

Kept in Home Assistant's storage (`.storage/log_doctor.failures`). Each
failure is a record:

    {"id", "when", "name", "entity_id", "config_id", "reason", "resolved"}

`when` and `resolved` are ISO timestamps (UTC); `resolved` is None while a
failure is open and set when it's marked resolved, which moves it to the
archive. Clearing the archive deletes resolved failures for good.

After every change the Markdown file (failure_log.py) is rewritten to match
- debounced, so a burst of failures means one write - and anyone
subscribed (the panel, via websocket_api.py) is told straight away.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any, Callable

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .failure_log import (
    FailureEntry,
    clean_reason,
    parse_markdown_rows,
    render_markdown,
    write_markdown_sync,
)
from .paths import failure_log_path

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_STORAGE_KEY = "log_doctor.failures"
# Coalesce bursts of changes into one save / one Markdown rewrite.
_WRITE_DELAY = 5

# Upper bound on stored failures, open and archived together; the oldest
# are dropped first. Keeps the panel and the Markdown file responsive even
# if something fails every few seconds for weeks.
MAX_RECORDS = 10_000

Listener = Callable[[], None]


class FailureStore:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._records: list[dict[str, Any]] = []
        self._listeners: set[Listener] = set()
        self._unsub_markdown: CALLBACK_TYPE | None = None
        # Set on unload; subscribers are told once more so they can
        # re-subscribe to the store that replaces this one.
        self.closed = False

    @property
    def records(self) -> list[dict[str, Any]]:
        return self._records

    async def async_load(self) -> None:
        """Load the list; on first run, import a 0.16.0 Markdown log."""
        data = await self._store.async_load()
        if data is not None:
            self._records = list(data.get("failures", []))
        else:
            imported = await self.hass.async_add_executor_job(self._read_old_markdown)
            if imported:
                self._records = [_record(entry) for entry in imported]
                _LOGGER.info("Imported %d failures from the old failure log", len(imported))
            self._store.async_delay_save(self._data_to_save, 0)
        # Always rewrite the file on start, so it matches the store even if
        # a debounced write was lost at shutdown.
        await self._async_write_markdown()

    def _read_old_markdown(self) -> list[FailureEntry]:
        try:
            text = failure_log_path(self.hass).read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        return parse_markdown_rows(text)

    @callback
    def async_subscribe(self, listener: Listener) -> CALLBACK_TYPE:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def async_add(self, entries: list[FailureEntry]) -> None:
        if not entries:
            return
        for entry in sorted(entries, key=lambda e: e.when):
            self._records.append(_record(entry))
        if len(self._records) > MAX_RECORDS:
            self._records.sort(key=lambda r: r["when"])
            del self._records[: len(self._records) - MAX_RECORDS]
        self._async_changed()

    async def async_resolve(self, ids: list[str]) -> int:
        """Move open failures to the archive."""
        now = dt_util.utcnow().isoformat()
        wanted = set(ids)
        count = 0
        for record in self._records:
            if record["id"] in wanted and not record.get("resolved"):
                record["resolved"] = now
                count += 1
        if count:
            self._async_changed()
        return count

    async def async_restore(self, ids: list[str]) -> int:
        """Move archived failures back to the open list."""
        wanted = set(ids)
        count = 0
        for record in self._records:
            if record["id"] in wanted and record.get("resolved"):
                record["resolved"] = None
                count += 1
        if count:
            self._async_changed()
        return count

    async def async_clear_archived(self) -> int:
        """Delete every archived failure from the log for good."""
        before = len(self._records)
        self._records = [r for r in self._records if not r.get("resolved")]
        removed = before - len(self._records)
        if removed:
            self._async_changed()
        return removed

    async def async_prune(self, retention_days: int) -> None:
        """Drop failures older than the retention window (0 = keep all)."""
        if retention_days <= 0:
            return
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        before = len(self._records)
        self._records = [r for r in self._records if r["when"] >= cutoff]
        if len(self._records) != before:
            self._async_changed()

    @callback
    def async_shutdown(self) -> None:
        """On unload: flush a pending Markdown write, tell subscribers."""
        self.closed = True
        if self._unsub_markdown is not None:
            self._unsub_markdown()
            self._unsub_markdown = None
            self.hass.async_create_task(self._async_write_markdown())
        for listener in list(self._listeners):
            listener()
        self._listeners.clear()

    @callback
    def _async_changed(self) -> None:
        self._store.async_delay_save(self._data_to_save, _WRITE_DELAY)
        if self._unsub_markdown is None:
            self._unsub_markdown = async_call_later(
                self.hass, _WRITE_DELAY, self._async_write_markdown_later
            )
        for listener in list(self._listeners):
            listener()

    def _data_to_save(self) -> dict[str, Any]:
        return {"failures": self._records}

    async def _async_write_markdown_later(self, _now: Any) -> None:
        self._unsub_markdown = None
        await self._async_write_markdown()

    async def _async_write_markdown(self) -> None:
        text = render_markdown(self._records)
        path = failure_log_path(self.hass)
        try:
            await self.hass.async_add_executor_job(write_markdown_sync, path, text)
        except OSError:
            _LOGGER.exception("Could not write the automation failure log %s", path)


def _record(entry: FailureEntry) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "when": dt_util.as_utc(entry.when).isoformat(),
        "name": entry.name,
        "entity_id": entry.entity_id,
        "config_id": entry.config_id,
        "reason": clean_reason(entry.reason),
        "resolved": None,
    }
