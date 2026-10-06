"""Spots automations that usually run regularly but have gone quiet.

An automation whose trigger stopped working - a renamed entity, a sensor
that stopped updating, a webhook nobody calls any more - doesn't fail; it
just never runs again, and nothing says so. This looks at the runs
recorded for the Automations page (see automation_runs.py) every
CHECK_INTERVAL and reports an automation as stopped when it hasn't run for
much longer than it ever has before:

- it needs at least MIN_RUNS runs on record, so there's a pattern to go
  by;
- "much longer" is the longest of: 3 times its usual (median) time
  between runs, 1.5 times the longest gap on record, and MIN_SILENCE - so
  an automation that runs irregularly (motion, presence) isn't reported
  for a quiet spell it's had before;
- automations that are turned off, excluded on the Runs list, or gone
  aren't checked.

Each one is reported once per quiet spell, as an entry on the Automations
page's Failures ("Stopped: ...") with a persistent notification (and a
push, if a device is chosen for automation failures); it's reported again
only after it has run again and gone quiet again. Like the rest of Log
Doctor it only reports.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Callable

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_OFF
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .automation_runs import KIND_EXCLUDED, KIND_RUN, AutomationRunStore
from .const import NOTIFICATION_ID_STOPPED_AUTOMATIONS, PANEL_FAILURES_URL
from .failure_log import FailureEntry
from .failure_store import FailureStore
from .mobile_push import resolve_mobile_app_notify_service

_LOGGER = logging.getLogger(__name__)

CHECK_INTERVAL = timedelta(minutes=30)
# First check after Home Assistant has started.
FIRST_CHECK_DELAY = 600
MIN_RUNS = 8
MIN_SILENCE = timedelta(hours=1)
REASON_PREFIX = "Stopped:"


def _human(delta: timedelta) -> str:
    """"45 min", "3 h", "2 days"."""
    minutes = delta.total_seconds() / 60
    if minutes < 90:
        return f"{max(1, round(minutes))} min"
    hours = minutes / 60
    if hours < 48:
        return f"{round(hours)} h"
    return f"{round(hours / 24)} days"


def find_stopped(
    runs: list[dict[str, Any]], now: datetime
) -> dict[str, tuple[datetime, timedelta, timedelta]]:
    """{entity_id: (last run, usual gap, longest gap)} for the stopped ones.

    runs: run records (see automation_runs.py) of the automations to check.
    """
    by_entity: dict[str, list[datetime]] = {}
    for run in runs:
        if run.get("kind") != KIND_RUN or not run.get("when"):
            continue
        when = dt_util.parse_datetime(run["when"])
        if when is not None:
            by_entity.setdefault(run["entity_id"], []).append(when)
    stopped = {}
    for entity_id, times in by_entity.items():
        if len(times) < MIN_RUNS:
            continue
        times.sort()
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        usual = median(gaps)
        longest = max(gaps)
        limit = max(usual * 3, longest * 1.5, MIN_SILENCE)
        if now - times[-1] > limit:
            stopped[entity_id] = (times[-1], usual, longest)
    return stopped


class StoppedAutomationWatch:
    def __init__(
        self,
        hass: HomeAssistant,
        runs: AutomationRunStore,
        failures: FailureStore,
        *,
        notify_device_id: str | None = None,
    ) -> None:
        self.hass = hass
        self.runs = runs
        self.failures = failures
        self.notify_device_id = notify_device_id
        self._unsubs: list[Callable[[], None]] = []

    @callback
    def async_start(self) -> Callable[[], None]:
        @callback
        def _schedule_first(_event: Any = None) -> None:
            self._unsubs.append(async_call_later(self.hass, FIRST_CHECK_DELAY, self._async_check))

        if self.hass.state is CoreState.running:
            _schedule_first()
        else:
            self._unsubs.append(
                self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule_first)
            )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_check, CHECK_INTERVAL)
        )
        return self._async_stop

    @callback
    def _async_stop(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except ValueError:
                pass  # a listen_once that already fired
        self._unsubs = []

    def _reported(self) -> dict[str, str]:
        """{entity_id: when it was last reported as stopped}."""
        reported: dict[str, str] = {}
        for record in self.failures.records:
            if (record.get("reason") or "").startswith(REASON_PREFIX):
                entity_id = record.get("entity_id") or ""
                reported[entity_id] = max(reported.get(entity_id, ""), record["when"])
        return reported

    async def _async_check(self, _now: Any = None) -> None:
        try:
            await self.async_check()
        except Exception:  # noqa: BLE001 - never let a check break anything
            _LOGGER.exception("Log Doctor's stopped automation check failed")

    async def async_check(self) -> list[FailureEntry]:
        now = dt_util.utcnow()
        excluded = {
            r["entity_id"] for r in self.runs.records if r.get("kind") == KIND_EXCLUDED
        }
        candidates = []
        for run in self.runs.records:
            entity_id = run.get("entity_id")
            if entity_id in excluded:
                continue
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is None or state.state == STATE_OFF:
                continue  # gone, or turned off on purpose
            candidates.append(run)
        reported = self._reported()
        names = {r["entity_id"]: (r.get("name"), r.get("config_id")) for r in candidates}
        new: list[FailureEntry] = []
        for entity_id, (last, usual, longest) in find_stopped(candidates, now).items():
            if reported.get(entity_id, "") >= last.isoformat():
                continue  # already reported for this quiet spell
            name, config_id = names.get(entity_id, (entity_id, None))
            new.append(
                FailureEntry(
                    when=now,
                    name=name or entity_id,
                    entity_id=entity_id,
                    config_id=config_id,
                    reason=(
                        f"{REASON_PREFIX} hasn't run for {_human(now - last)} - it usually "
                        f"runs every {_human(usual)} (longest gap before: {_human(longest)})"
                    ),
                )
            )
        if new:
            await self.failures.async_add(new)
            await self._async_notify(new)
        return new

    async def _async_notify(self, stopped: list[FailureEntry]) -> None:
        lines = ["These automations usually run regularly but haven't for much longer than usual:", ""]
        for entry in stopped:
            label = f"**{entry.name}**"
            if entry.config_id:
                label = f"[{entry.name}](/config/automation/edit/{entry.config_id})"
            lines.append(f"- {label} (`{entry.entity_id}`) - {entry.reason.removeprefix(REASON_PREFIX).strip()}")
        lines += ["", f"[See them in Log Doctor]({PANEL_FAILURES_URL})"]
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": NOTIFICATION_ID_STOPPED_AUTOMATIONS,
                    "title": "Automations that stopped running",
                    "message": "\n".join(lines),
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notification failure escalate
            _LOGGER.exception("Failed to post the stopped automations notification")

        if not self.notify_device_id:
            return
        service = resolve_mobile_app_notify_service(self.hass, self.notify_device_id)
        if service is None:
            return
        try:
            await self.hass.services.async_call(
                "notify",
                service,
                {
                    "title": f"{len(stopped)} automation(s) stopped running",
                    "message": ", ".join(entry.name for entry in stopped),
                    "data": {"tag": NOTIFICATION_ID_STOPPED_AUTOMATIONS},
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notification failure escalate
            _LOGGER.exception("Failed to send the stopped automations push via notify.%s", service)
