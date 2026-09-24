"""Real-time automation failure monitor.

Unlike the daily scan, this watches every automation run as it happens and
posts a persistent notification the moment one fails. It never touches the
automation itself - it only reports, like the rest of Log Doctor.

Home Assistant doesn't fire an event when an automation run fails, but
every automation logs its failures through its own child logger,
``homeassistant.components.automation.<object_id>`` (the automation's
action script uses the same logger). So this attaches a logging handler to
the parent ``homeassistant.components.automation`` logger and picks up any
ERROR-or-worse record from one of those child loggers. A single failed run
usually produces two records (the script step's "Error executing script"
plus the automation's own "Error while executing automation"), so records
for the same automation arriving within a short window are coalesced into
one notification.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from homeassistant.core import HomeAssistant, callback

from .const import NOTIFICATION_ID_AUTOMATION_FAILURE_PREFIX

_LOGGER = logging.getLogger(__name__)

_AUTOMATION_LOGGER = "homeassistant.components.automation"

# How long to wait for further records from the same failed run before
# posting the notification.
_COALESCE_SECONDS = 2.0

# Cap on distinct error lines shown in one notification, so a run that
# spews errors (e.g. a repeat loop) can't produce a gigantic notification.
_MAX_ERRORS_PER_NOTIFICATION = 5


@dataclass
class _PendingFailure:
    first_seen: datetime
    errors: list[str] = field(default_factory=list)
    timer: asyncio.TimerHandle | None = None


class _AutomationErrorHandler(logging.Handler):
    """Forwards automation error records onto the event loop.

    emit() can be called from any thread, so it only does the minimum
    needed to identify the record and hands it to the loop thread-safely.
    """

    def __init__(self, monitor: AutomationFailureMonitor) -> None:
        super().__init__(level=logging.ERROR)
        self._monitor = monitor

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith(f"{_AUTOMATION_LOGGER}."):
            return
        object_id = record.name[len(_AUTOMATION_LOGGER) + 1 :]
        try:
            message = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                if str(exc) not in message:
                    message += f" ({type(exc).__name__}: {exc})"
            self._monitor.hass.loop.call_soon_threadsafe(
                self._monitor.async_record, object_id, message, record.created
            )
        except Exception:  # noqa: BLE001 - a logging handler must never raise
            self.handleError(record)


class AutomationFailureMonitor:
    """Posts a persistent notification whenever an automation run fails."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._handler = _AutomationErrorHandler(self)
        self._pending: dict[str, _PendingFailure] = {}
        # Failures per automation since this monitor started (i.e. since the
        # last Home Assistant restart or integration reload).
        self._failure_counts: dict[str, int] = {}

    @callback
    def async_start(self) -> Callable[[], None]:
        """Start watching; returns a callback that stops watching."""
        logging.getLogger(_AUTOMATION_LOGGER).addHandler(self._handler)
        return self._async_stop

    @callback
    def _async_stop(self) -> None:
        logging.getLogger(_AUTOMATION_LOGGER).removeHandler(self._handler)
        for pending in self._pending.values():
            if pending.timer:
                pending.timer.cancel()
        self._pending.clear()

    @callback
    def async_record(self, object_id: str, message: str, created: float) -> None:
        # Other modules in the automation package (e.g. reproduce_state) log
        # under the same parent logger; only count records that belong to an
        # actual automation entity.
        if self.hass.states.get(f"automation.{object_id}") is None:
            return

        pending = self._pending.get(object_id)
        if pending is None:
            pending = _PendingFailure(first_seen=datetime.fromtimestamp(created))
            self._pending[object_id] = pending
            pending.timer = self.hass.loop.call_later(
                _COALESCE_SECONDS, self._async_flush, object_id
            )
        if message not in pending.errors:
            pending.errors.append(message)

    @callback
    def _async_flush(self, object_id: str) -> None:
        pending = self._pending.pop(object_id, None)
        if pending is None:
            return
        self._failure_counts[object_id] = self._failure_counts.get(object_id, 0) + 1
        self.hass.async_create_task(self._async_notify(object_id, pending))

    async def _async_notify(self, object_id: str, pending: _PendingFailure) -> None:
        entity_id = f"automation.{object_id}"
        state = self.hass.states.get(entity_id)
        name = (state and state.attributes.get("friendly_name")) or entity_id
        config_id = state.attributes.get("id") if state else None
        count = self._failure_counts[object_id]

        lines = [
            f"**{name}** (`{entity_id}`) failed at "
            f"{pending.first_seen.strftime('%Y-%m-%d %H:%M:%S')}.",
            "",
        ]
        for error in pending.errors[:_MAX_ERRORS_PER_NOTIFICATION]:
            # Script step errors are prefixed with the automation's name,
            # which the title already shows.
            lines.append(f"- {error.removeprefix(f'{name}: ')}")
        hidden = len(pending.errors) - _MAX_ERRORS_PER_NOTIFICATION
        if hidden > 0:
            lines.append(f"- _…and {hidden} more error(s) - see the log._")
        lines.append("")
        if count > 1:
            lines.append(f"This automation has failed {count} times since Home Assistant started.")
        if config_id:
            lines.append(f"[Open the automation's trace](/config/automation/trace/{config_id})")

        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": f"{NOTIFICATION_ID_AUTOMATION_FAILURE_PREFIX}{object_id}",
                    "title": f"Automation failed: {name}",
                    "message": "\n".join(lines).rstrip(),
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notification failure escalate
            # Deliberately logged under log_doctor's own logger, never the
            # automation one, so this can't feed back into the handler.
            _LOGGER.exception("Failed to post automation failure notification for %s", entity_id)
