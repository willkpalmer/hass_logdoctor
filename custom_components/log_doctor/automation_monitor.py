"""Real-time automation failure monitor.

Unlike the daily scan, this watches every automation run as it happens and
posts a persistent notification the moment one fails - and, if a Mobile App
device is chosen, a push notification to that phone too. It never touches
the automation itself - it only reports, like the rest of Log Doctor.

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

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import NOTIFICATION_ID_AUTOMATION_FAILURE_PREFIX
from .const import PANEL_FAILURES_URL
from .failure_log import FailureEntry
from .failure_store import FailureStore
from .mobile_push import resolve_mobile_app_notify_service

_LOGGER = logging.getLogger(__name__)

_AUTOMATION_LOGGER = "homeassistant.components.automation"

# How long to wait for further records from the same failed run before
# posting the notification.
_COALESCE_SECONDS = 2.0

# Errors logged before an automation's actions start (so no
# automation_triggered event was fired for that run); for these the failure
# time itself is the trigger time.
_PRE_ACTION_ERRORS = ("Error rendering variables", "Error rendering trigger variables")

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

    def __init__(
        self,
        hass: HomeAssistant,
        failure_store: FailureStore | None = None,
        notify_device_id: str | None = None,
    ) -> None:
        self.hass = hass
        # Every failure is also added to the failure list behind the
        # "Automation failures" panel and its Markdown file.
        self.failure_store = failure_store
        # A device from the Mobile App integration to also push each
        # failure to, if one was chosen in the options.
        self.notify_device_id = notify_device_id
        self._handler = _AutomationErrorHandler(self)
        self._pending: dict[str, _PendingFailure] = {}
        # Failures per automation since this monitor started (i.e. since the
        # last Home Assistant restart or integration reload).
        self._failure_counts: dict[str, int] = {}
        # When each automation's most recent run was triggered, from the
        # automation_triggered event, for the failure log's time column.
        self._triggered_at: dict[str, datetime] = {}
        self._unsub_triggered: Callable[[], None] | None = None

    @callback
    def async_start(self) -> Callable[[], None]:
        """Start watching; returns a callback that stops watching."""
        logging.getLogger(_AUTOMATION_LOGGER).addHandler(self._handler)
        self._unsub_triggered = self.hass.bus.async_listen(
            "automation_triggered", self._async_on_triggered
        )
        return self._async_stop

    @callback
    def _async_on_triggered(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        if isinstance(entity_id, str):
            self._triggered_at[entity_id] = event.time_fired

    @callback
    def _async_stop(self) -> None:
        logging.getLogger(_AUTOMATION_LOGGER).removeHandler(self._handler)
        if self._unsub_triggered is not None:
            self._unsub_triggered()
            self._unsub_triggered = None
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
            pending = _PendingFailure(first_seen=dt_util.utc_from_timestamp(created))
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

        try:
            if self.failure_store is not None:
                await self.failure_store.async_add(
                    [
                        FailureEntry(
                            when=self._run_triggered_at(entity_id, pending),
                            name=name,
                            entity_id=entity_id,
                            config_id=config_id,
                            reason="Failed: "
                            + "; ".join(e.removeprefix(f"{name}: ") for e in pending.errors),
                        )
                    ]
                )
        except Exception:  # noqa: BLE001 - the notification must still go out
            _LOGGER.exception("Could not record the failure of %s", entity_id)

        lines = [
            f"**{name}** (`{entity_id}`) failed at "
            f"{dt_util.as_local(pending.first_seen).strftime('%Y-%m-%d %H:%M:%S')}.",
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
        lines.append(f"[Review all automation failures]({PANEL_FAILURES_URL})")

        notification_id = f"{NOTIFICATION_ID_AUTOMATION_FAILURE_PREFIX}{object_id}"
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": notification_id,
                    "title": f"Automation failed: {name}",
                    "message": "\n".join(lines).rstrip(),
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notification failure escalate
            # Deliberately logged under log_doctor's own logger, never the
            # automation one, so this can't feed back into the handler.
            _LOGGER.exception("Failed to post automation failure notification for %s", entity_id)

        if self.notify_device_id:
            await self._async_push(name, pending, count, config_id, notification_id)

    async def _async_push(
        self,
        name: str,
        pending: _PendingFailure,
        count: int,
        config_id: str | None,
        tag: str,
    ) -> None:
        """Send a short push notification to the chosen Mobile App device."""
        service = resolve_mobile_app_notify_service(self.hass, self.notify_device_id)
        if service is None:
            _LOGGER.warning(
                "Can't send automation failure push: the chosen Mobile App "
                "device (%s) no longer has a notify service - it may have "
                "been removed, or its app isn't set up for notifications",
                self.notify_device_id,
            )
            return

        # Phones show plain text, not Markdown, and truncate long bodies, so
        # only the first error is sent; the persistent notification has all.
        message = pending.errors[0].removeprefix(f"{name}: ")
        if count > 1:
            message += f" (failed {count} times since Home Assistant started)"
        data: dict[str, str] = {
            # Same tag per automation, so a repeat failure replaces the
            # previous push instead of stacking up, like the persistent one.
            "tag": tag,
        }
        if config_id:
            trace_url = f"/config/automation/trace/{config_id}"
            data["url"] = trace_url  # iOS: open on tap
            data["clickAction"] = trace_url  # Android: open on tap

        try:
            await self.hass.services.async_call(
                "notify",
                service,
                {"title": f"Automation failed: {name}", "message": message, "data": data},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notification failure escalate
            _LOGGER.exception("Failed to send automation failure push via notify.%s", service)

    def _run_triggered_at(self, entity_id: str, pending: _PendingFailure) -> datetime:
        """When the failed run was triggered - its scheduled time, for a
        time-scheduled automation.

        That's the latest automation_triggered event for it, if it came
        before the first error. Errors raised before the actions start
        don't get an event at all (the latest one is from an earlier run),
        but they happen at trigger time, so the error time is used instead.
        """
        if any(e.startswith(_PRE_ACTION_ERRORS) for e in pending.errors):
            return pending.first_seen
        triggered = self._triggered_at.get(entity_id)
        if triggered is not None and triggered <= pending.first_seen:
            return triggered
        return pending.first_seen
