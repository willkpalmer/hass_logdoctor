"""The reviewable lists: pruning, automation run updates, restart impact."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.util import dt as dt_util

from custom_components.log_doctor.anomaly_store import AnomalyStore
from custom_components.log_doctor.automation_runs import AutomationRunStore
from custom_components.log_doctor.failure_store import FailureStore
from custom_components.log_doctor.health_store import HealthStore
from custom_components.log_doctor.restart_history import RestartHistoryStore


def _ago(days: float) -> str:
    return (dt_util.utcnow() - timedelta(days=days)).isoformat()


async def test_prune_keeps_what_each_list_keeps(hass):
    anomalies = AnomalyStore(hass)
    anomalies._records = [
        {"id": "old", "last_seen": _ago(40), "resolved": None},
        {"id": "new", "last_seen": _ago(1), "resolved": None},
        {"id": "old-ignored", "last_seen": _ago(40), "ignored": _ago(39), "resolved": None},
    ]
    assert await anomalies.async_prune(30) == 1
    assert [r["id"] for r in anomalies.records] == ["new", "old-ignored"]

    health = HealthStore(hass)
    health._records = [
        {"id": "ended-long-ago", "active": False, "resolved": _ago(40)},
        {"id": "ended-recently", "active": False, "resolved": _ago(2)},
        {"id": "still-there", "active": True, "resolved": _ago(40)},
        {"id": "open", "active": False, "resolved": None},
    ]
    await health.async_prune(30)
    assert [r["id"] for r in health.records] == ["ended-recently", "still-there", "open"]

    failures = FailureStore(hass)
    failures._records = [{"id": "a", "when": _ago(40)}, {"id": "b", "when": _ago(1)}]
    await failures.async_prune(30)
    assert [r["id"] for r in failures.records] == ["b"]
    # 0 keeps everything.
    assert await failures.async_prune(0) == 0


def _event(entity_id: str, source: str | None = "state of sensor.x"):
    return SimpleNamespace(
        data={"entity_id": entity_id, "name": entity_id, "source": source},
        time_fired=dt_util.utcnow(),
    )


async def test_runs_send_deltas_and_drop_the_oldest(hass):
    store = AutomationRunStore(hass)
    store.max_records = 3
    deltas = []
    store.async_subscribe(deltas.append)
    for _ in range(4):
        store.async_add_run(_event("automation.a"))
    store._async_notify()
    assert len(store.records) == 3
    assert deltas == [{"added": store.records, "removed": []}]

    # Already-sent runs dropped later are reported as removed.
    first = store.records[0]["id"]
    store.async_add_run(_event("automation.b", source=None))
    store._async_notify()
    assert deltas[-1]["removed"] == [first]
    assert deltas[-1]["added"][0]["manual"] is True

    # Anything else sends the whole list again.
    await store.async_unmonitor([store.records[-1]["id"]])
    store._async_notify()
    assert deltas[-1] is None
    await store.async_shutdown()


async def test_runs_prune_keeps_excluded(hass):
    store = AutomationRunStore(hass)
    store._records = [
        {"id": "r1", "kind": "run", "entity_id": "automation.a", "when": _ago(40)},
        {"id": "r2", "kind": "run", "entity_id": "automation.a", "when": _ago(1)},
        {"id": "excluded:automation.b", "kind": "excluded", "entity_id": "automation.b", "when": _ago(90)},
    ]
    await store.async_prune(30)
    assert [r["id"] for r in store.records] == ["r2", "excluded:automation.b"]
    await store.async_shutdown()


async def test_restart_impact_adds_up(hass):
    history = RestartHistoryStore(hass)
    history._records = [{"id": "run1", "starting": _ago(1), "resolved": None}]
    await history.async_add_impact(
        {"run1": {"lines": 4, "errors": 1, "signatures": {"a", "b"}}, "gone": {"lines": 1, "errors": 0, "signatures": set()}}
    )
    await history.async_add_impact({"run1": {"lines": 2, "errors": 2, "signatures": {"b", "c"}}})
    record = history.records[0]
    assert (record["messages"], record["errors"]) == (6, 3)
    assert sorted(record["signatures"]) == ["a", "b", "c"]


async def test_unmonitored_device_hides_its_flapping(hass):
    store = HealthStore(hass)
    store._records = [
        {"id": "offline:dev1", "kind": "offline", "unmonitored": _ago(1), "resolved": None, "active": True},
    ]
    await store.async_update(
        {
            "flapping:dev1": {"kind": "flapping", "name": "Plug", "entities": []},
            "flapping:dev2": {"kind": "flapping", "name": "Lamp", "entities": []},
        }
    )
    assert sorted(r["id"] for r in store.records) == ["flapping:dev2", "offline:dev1"]


async def test_settings_schema_defaults(hass):
    from custom_components.log_doctor.config_flow import _build_schema
    from custom_components.log_doctor.const import DEFAULT_INVESTIGATION_MODEL

    schema = _build_schema(hass, {})
    options = schema({})
    assert options["flap_count"] == 3
    assert options["weekly_digest_day"] == "mon"
    assert options["investigation_model"] == DEFAULT_INVESTIGATION_MODEL
    assert options["monitor_stopped_automations"] is True


async def test_diagnostics_redacts_the_api_key(hass):
    from types import SimpleNamespace

    from custom_components.log_doctor.diagnostics import async_get_config_entry_diagnostics

    entry = SimpleNamespace(
        entry_id="x", version=1, data={"openai_api_key": "sk-secret"}, options={"openai_api_key": "sk-secret", "flap_count": 3}
    )
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert "sk-secret" not in str(result)
    assert result["entry"]["options"]["flap_count"] == 3
