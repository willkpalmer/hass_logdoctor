"""History: automation runs and scene activations, and who or what started them."""
from __future__ import annotations

from homeassistant.core import Context, CoreState
from homeassistant.setup import async_setup_component

from custom_components.log_doctor.automation_runs import AutomationRunStore, async_record_runs


async def test_history_says_who_or_what(hass):
    from homeassistant.auth import auth_manager_from_config

    hass.set_state(CoreState.running)
    hass.auth = await auth_manager_from_config(hass, [], [])
    user = await hass.auth.async_create_user("Will")
    hass.states.async_set("light.hall", "off")
    for service in ("turn_on", "turn_off"):
        hass.services.async_register("light", service, lambda call: None)
    assert await async_setup_component(hass, "scene", {"scene": [
        {"id": "evening", "name": "Evening", "entities": {"light.hall": "on"}},
        {"id": "night", "name": "Night", "entities": {"light.hall": "off"}},
    ]})
    assert await async_setup_component(hass, "script", {"script": {
        "bedtime": {"alias": "Bedtime", "sequence": [{"action": "scene.turn_on", "target": {"entity_id": "scene.night"}}]},
    }})
    assert await async_setup_component(hass, "automation", {"automation": [{
        "id": "dusk", "alias": "Dusk",
        "triggers": [{"trigger": "event", "event_type": "dusk"}],
        "actions": [{"action": "scene.turn_on", "target": {"entity_id": "scene.evening"}}],
    }]})
    await hass.async_block_till_done()
    store = AutomationRunStore(hass)
    unsub = async_record_runs(hass, store)
    await hass.async_block_till_done()

    # A person activates a scene; an automation activates one; a script does;
    # a person runs the automation by hand.
    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.evening"}, blocking=True, context=Context(user_id=user.id))
    hass.bus.async_fire("dusk")
    await hass.async_block_till_done()
    await hass.services.async_call("script", "bedtime", blocking=True)
    await hass.services.async_call("automation", "trigger", {"entity_id": "automation.dusk"}, blocking=True, context=Context(user_id=user.id))
    await hass.async_block_till_done()

    got = [(r["kind"], r["name"], r.get("by_kind"), r.get("by")) for r in store.records]
    assert got == [
        ("scene", "Evening", "user", "Will"),
        ("run", "Dusk", None, None),
        ("scene", "Evening", "automation", "Dusk"),
        ("scene", "Night", "script", "Bedtime"),
        ("run", "Dusk", "user", "Will"),
        ("scene", "Evening", "automation", "Dusk"),
    ], got
    assert store.records[1]["trigger_name"] == "Event dusk"
    assert store.records[4]["manual"] is True
    assert store.records[2]["by_config_id"] == "dusk"
    assert store.records[0]["config_id"] == "evening"

    # Stop monitoring a scene: its activations go and aren't recorded.
    assert await store.async_unmonitor([store.records[0]["id"]]) == 1
    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.evening"}, blocking=True)
    await hass.async_block_till_done()
    assert not [r for r in store.records if r["kind"] == "scene" and r["entity_id"] == "scene.evening"]
    unsub()
    await store.async_shutdown()
