"""Stopped automations and flapping devices."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util

from custom_components.log_doctor.automation_runs import AutomationRunStore
from custom_components.log_doctor.failure_store import FailureStore
from custom_components.log_doctor.flapping import FlapTracker
from custom_components.log_doctor.stopped_automations import StoppedAutomationWatch, find_stopped


def _runs(entity_id: str, every: timedelta, count: int, last_ago: timedelta):
    now = dt_util.utcnow()
    return [
        {"kind": "run", "entity_id": entity_id, "name": entity_id, "when": (now - last_ago - every * i).isoformat()}
        for i in range(count)
    ]


def test_find_stopped():
    now = dt_util.utcnow()
    hourly_quiet = _runs("automation.hourly", timedelta(hours=1), 10, timedelta(hours=5))
    hourly_fine = _runs("automation.fine", timedelta(hours=1), 10, timedelta(minutes=30))
    too_few = _runs("automation.new", timedelta(hours=1), 3, timedelta(hours=10))
    stopped = find_stopped(hourly_quiet + hourly_fine + too_few, now)
    assert list(stopped) == ["automation.hourly"]

    # An irregular one: a quiet spell like ones it's had before isn't reported.
    irregular = _runs("automation.motion", timedelta(minutes=10), 10, timedelta(hours=3))
    irregular.append({**irregular[-1], "when": (now - timedelta(hours=20)).isoformat()})
    irregular.append({**irregular[-1], "when": (now - timedelta(hours=26)).isoformat()})
    assert find_stopped(irregular, now) == {}


async def test_stopped_reported_once(hass):
    hass.states.async_set("automation.hourly", "on")
    runs = AutomationRunStore(hass)
    runs._records = _runs("automation.hourly", timedelta(hours=1), 10, timedelta(hours=5))
    failures = FailureStore(hass)
    hass.services.async_register("persistent_notification", "create", lambda call: None)
    watch = StoppedAutomationWatch(hass, runs, failures)
    first = await watch.async_check()
    assert len(first) == 1 and first[0].reason.startswith("Stopped:")
    assert await watch.async_check() == []
    # Turned off: not checked.
    hass.states.async_set("automation.hourly", "off")
    failures._records = []
    assert await watch.async_check() == []
    await runs.async_shutdown()
    await failures.async_shutdown()


async def test_flapping(hass):
    hass.set_state(CoreState.running)
    tracker = FlapTracker(hass, count=3, window=timedelta(hours=24))
    unsub = tracker.async_start()
    for _ in range(3):
        hass.states.async_set("switch.plug", "on")
        await hass.async_block_till_done()
        # Several seconds apart in reality; spread them out here.
        hass.states.async_set("switch.plug", "unavailable")
        await hass.async_block_till_done()
        record = tracker._groups["switch.plug"]
        record["times"][-1] = (dt_util.parse_datetime(record["times"][-1]) - timedelta(minutes=len(record["times"]))).isoformat()
    flapping = tracker.flapping()
    assert list(flapping) == ["switch.plug"]
    assert len(flapping["switch.plug"][0]) == 3
    # A state change while Home Assistant stops isn't counted.
    hass.set_state(CoreState.stopping)
    hass.states.async_set("switch.lamp", "on")
    hass.states.async_set("switch.lamp", "unavailable")
    await hass.async_block_till_done()
    assert "switch.lamp" not in tracker._groups
    unsub()
