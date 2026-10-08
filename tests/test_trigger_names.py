"""Which trigger started an automation run (trigger_names.py)."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import CoreState
from homeassistant.setup import async_setup_component

from custom_components.log_doctor.automation_runs import AutomationRunStore, async_record_runs
from custom_components.log_doctor.trigger_names import describe_trigger


def test_describe_trigger(hass):
    hass.states.async_set("binary_sensor.front_door", "off", {"friendly_name": "Front door"})
    cases = [
        ({"trigger": "sun", "event": "sunset", "offset": "00:15:00"}, "Sunset +00:15:00"),
        ({"platform": "sun", "event": "sunrise", "offset": timedelta(minutes=-30)}, "Sunrise -00:30:00"),
        ({"trigger": "sun", "event": "sunset"}, "Sunset"),
        ({"trigger": "time", "at": "07:30:00"}, "At 07:30"),
        ({"trigger": "time", "at": ["07:30", "input_datetime.wake"], "weekday": ["mon", "tue"]}, "At 07:30, input_datetime.wake (mon, tue)"),
        ({"trigger": "time_pattern", "minutes": "/15"}, "Time pattern: every 15 minutes"),
        ({"trigger": "state", "entity_id": "binary_sensor.front_door", "to": "on", "for": {"minutes": 2}}, "Front door → on for 00:02:00"),
        ({"trigger": "state", "entity_id": ["binary_sensor.front_door"]}, "Front door changed"),
        ({"trigger": "numeric_state", "entity_id": "sensor.temp", "above": 20}, "sensor.temp above 20"),
        ({"trigger": "homeassistant", "event": "start"}, "Home Assistant started"),
        ({"trigger": "event", "event_type": "my_event"}, "Event my_event"),
        ({"trigger": "something_new"}, None),
    ]
    for conf, expected in cases:
        assert describe_trigger(hass, conf) == expected, conf


async def _runs_for(hass, automation_config):
    hass.set_state(CoreState.running)
    assert await async_setup_component(hass, "automation", {"automation": [automation_config]})
    await hass.async_block_till_done()
    store = AutomationRunStore(hass)
    unsub = async_record_runs(hass, store)
    return store, unsub


async def test_trigger_name_from_the_trace(hass):
    store, unsub = await _runs_for(
        hass,
        {
            "id": "lights",
            "alias": "Lights",
            "triggers": [
                {"trigger": "event", "event_type": "first"},
                {"trigger": "event", "event_type": "second", "alias": "The second one"},
                {"trigger": "state", "entity_id": "input_boolean.x", "to": "on"},
            ],
            "actions": [],
        },
    )
    hass.states.async_set("input_boolean.x", "off", {"friendly_name": "Guest mode"})
    hass.bus.async_fire("first")
    hass.bus.async_fire("second")
    hass.states.async_set("input_boolean.x", "on", {"friendly_name": "Guest mode"})
    await hass.async_block_till_done()
    names = [r["trigger_name"] for r in store.records]
    assert names == ["Event first", "The second one", "Guest mode → on"]
    assert all(r["trigger"] for r in store.records)
    unsub()
    await store.async_shutdown()


async def test_trigger_name_without_traces(hass):
    store, unsub = await _runs_for(
        hass,
        {
            "id": "quiet",
            "alias": "Quiet",
            "trace": {"stored_traces": 0},
            "triggers": [
                {"trigger": "event", "event_type": "first"},
                {"trigger": "state", "entity_id": "input_boolean.x", "to": "on", "for": "00:00:00"},
            ],
            "actions": [],
        },
    )
    # Only one state trigger: found by its kind.
    hass.states.async_set("input_boolean.x", "off", {"friendly_name": "Guest mode"})
    hass.states.async_set("input_boolean.x", "on", {"friendly_name": "Guest mode"})
    await hass.async_block_till_done()
    assert store.records[-1]["trigger_name"] == "Guest mode → on"
    unsub()
    await store.async_shutdown()
