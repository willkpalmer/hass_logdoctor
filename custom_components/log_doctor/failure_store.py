"""The automation failures on the Log Doctor panel's "Automation failures" view.

A ReviewList (see review_list.py) kept in `.storage/log_doctor.failures`.
Each failure is a record:

    {"id", "when", "name", "entity_id", "config_id", "reason", "resolved"}

`when` and `resolved` are ISO timestamps (UTC). After every change the
Markdown file (failure_log.py) is rewritten to match - debounced, so a
burst of failures means one write.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .failure_log import (
    FailureEntry,
    clean_reason,
    parse_markdown_rows,
    render_markdown,
    write_markdown_sync,
)
from .paths import failure_log_path
from .review_list import WRITE_DELAY, ReviewList

_LOGGER = logging.getLogger(__name__)

# Kept for callers/tests that refer to the cap.
MAX_RECORDS = ReviewList.max_records


class FailureStore(ReviewList):
    storage_key = "log_doctor.failures"
    records_key = "failures"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass)
        self._unsub_markdown: CALLBACK_TYPE | None = None

    async def async_load(self) -> dict[str, Any] | None:
        """Load the list; on first run, import a 0.16.0 Markdown log."""
        data = await super().async_load()
        if data is None:
            imported = await self.hass.async_add_executor_job(self._read_old_markdown)
            if imported:
                self._records = [_record(entry) for entry in imported]
                _LOGGER.info("Imported %d failures from the old failure log", len(imported))
            self._store.async_delay_save(self._data_to_save, 0)
        # Always rewrite the file on start, so it matches the store even if
        # a debounced write was lost at shutdown.
        await self._async_write_markdown()
        return data

    def _read_old_markdown(self) -> list[FailureEntry]:
        try:
            text = failure_log_path(self.hass).read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        return parse_markdown_rows(text)

    async def async_add(self, entries: list[FailureEntry]) -> None:
        if not entries:
            return
        for entry in sorted(entries, key=lambda e: e.when):
            self._records.append(_record(entry))
        self.async_trim()
        self.async_changed()

    async def async_prune(self, retention_days: int) -> None:
        """Drop failures older than the retention window (0 = keep all)."""
        if retention_days <= 0:
            return
        cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
        before = len(self._records)
        self._records = [r for r in self._records if r["when"] >= cutoff]
        if len(self._records) != before:
            self.async_changed()

    async def async_shutdown(self) -> None:
        """On unload: write a pending Markdown update, save, tell subscribers."""
        if self._unsub_markdown is not None:
            self._unsub_markdown()
            self._unsub_markdown = None
            await self._async_write_markdown()
        await super().async_shutdown()

    @callback
    def async_changed(self) -> None:
        if self._unsub_markdown is None:
            self._unsub_markdown = async_call_later(
                self.hass, WRITE_DELAY, self._async_write_markdown_later
            )
        super().async_changed()

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
