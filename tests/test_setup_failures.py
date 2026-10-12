"""Integration setup failures: the log messages and the health check."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import CoreState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import DATA_ENTITY_PLATFORM

from custom_components.log_doctor.anomaly_store import AnomalyStore
from custom_components.log_doctor.health_monitor import HealthMonitor
from custom_components.log_doctor.health_store import HealthStore
from custom_components.log_doctor.setup_failures import setup_failure_domain


def test_setup_failure_domain():
    cases = [
        ("homeassistant.setup", "Setup failed for custom integration 'tuya_local': Unable to import component", "tuya_local"),
        ("homeassistant.setup", "Setup failed for 'zha': Integration failed to initialize.", "zha"),
        ("homeassistant.config_entries", "Error setting up entry Living room for hue", "hue"),
        ("homeassistant.config_entries", "Config entry 'Router' for fritz integration not ready yet: timeout; Retrying in background", "fritz"),
        ("homeassistant.components.sensor", "Error while setting up tuya platform for sensor: boom", "tuya"),
        ("homeassistant.components.light", "Platform hue not ready yet: x; Retrying in background in 30 seconds", "hue"),
        # Not setup failures.
        ("homeassistant.setup", "Setup of zha is taking over 10 seconds.", None),
        ("custom_components.foo", "Error setting up entry X for foo", None),
        ("homeassistant.components.zha", "Something else failed", None),
    ]
    for logger, message, expected in cases:
        assert setup_failure_domain(logger, message) == expected, message


async def test_old_records_move_back_to_the_log_review(hass):
    store = AnomalyStore(hass)
    await store._store.async_save(
        {
            "anomalies": [
                {"id": "a", "logger": "homeassistant.setup", "message": "Setup failed for 'zha': Integration failed to initialize.",
                 "category": "restart", "last_logged": None},
                {"id": "b", "logger": "homeassistant.setup", "message": "Setup failed for 'hue': x",
                 "category": "restart", "category_manual": True, "last_logged": None},
                {"id": "c", "logger": "homeassistant.components.zha", "message": "Startup noise",
                 "category": "restart", "last_logged": None},
            ]
        }
    )
    await store.async_load()
    by_id = {r["id"]: r for r in store.records}
    assert (by_id["a"]["category"], by_id["a"]["setup_domain"]) == ("operational", "zha")
    assert by_id["b"]["category"] == "restart"  # moved there by hand
    assert by_id["c"]["category"] == "restart"
    await store.async_set_category(["a"], "restart")
    assert store.is_manual_restart("a")
    await store.async_shutdown()


def _entry(hass, domain, state):
    entry = ConfigEntry(
        version=1, minor_version=1, domain=domain, title=domain.title(), data={}, options={},
        source="user", unique_id=None, discovery_keys={}, subentries_data=None,
    )
    object.__setattr__(entry, "state", state)
    hass.config_entries._entries[entry.entry_id] = entry
    return entry


async def test_not_loaded_and_failed_platform(hass):
    hass.set_state(CoreState.running)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    broken = _entry(hass, "broken", ConfigEntryState.NOT_LOADED)
    partial = _entry(hass, "partial", ConfigEntryState.LOADED)
    hub = dev_reg.async_get_or_create(config_entry_id=broken.entry_id, identifiers={("broken", "1")}, name="Hub")
    lamp = dev_reg.async_get_or_create(config_entry_id=partial.entry_id, identifiers={("partial", "1")}, name="Lamp")
    ent_reg.async_get_or_create("sensor", "broken", "1", config_entry=broken, device_id=hub.id)
    sensor = ent_reg.async_get_or_create("sensor", "partial", "s1", config_entry=partial, device_id=lamp.id)
    light = ent_reg.async_get_or_create("light", "partial", "l1", config_entry=partial, device_id=lamp.id)
    hass.states.async_set(sensor.entity_id, "unavailable", {"restored": True})
    hass.states.async_set(light.entity_id, "on")
    # The sensor platform failed to set up; the light platform loaded.
    hass.data[DATA_ENTITY_PLATFORM] = {
        "partial": [
            SimpleNamespace(config_entry=partial, domain="sensor", _setup_complete=False),
            SimpleNamespace(config_entry=partial, domain="light", _setup_complete=True),
        ]
    }
    anomalies = AnomalyStore(hass)
    anomalies._records = [
        {"id": "s", "level": "ERROR", "logger": "homeassistant.setup", "message": "Setup failed for 'broken': boom",
         "setup_domain": "broken", "last_seen": "2026-10-01T00:00:00+00:00"},
        {"id": "o", "level": "WARNING", "logger": "custom_components.broken.api", "message": "Can't reach it",
         "last_seen": "2026-10-02T00:00:00+00:00"},
    ]
    store = HealthStore(hass)
    monitor = HealthMonitor(hass, store, offline_after=timedelta(hours=1), anomalies=anomalies)
    await monitor.async_check()
    # Not loaded only counts from the second check (it may be reloading).
    assert f"integration:{broken.entry_id}" not in {r["id"] for r in store.records}
    await monitor.async_check()
    by_id = {r["id"]: r for r in store.records}

    not_loaded = by_id[f"integration:{broken.entry_id}"]
    assert not_loaded["detail"] == "Not loaded · 1 device affected"
    assert not_loaded["devices"] == ["Hub"]
    assert [m["id"] for m in not_loaded["log_messages"]] == ["s", "o"]

    platform = by_id[f"platform:{partial.entry_id}"]
    assert platform["detail"] == "sensor platform not loaded · 1 device affected"
    assert platform["entities"] == [sensor.entity_id]

    device = by_id[f"offline:{lamp.id}"]
    assert "not loaded (integration problem)" in device["detail"]
    assert "no longer provided" not in device["detail"]
    # Its broken integration's devices aren't reported one by one.
    assert f"offline:{hub.id}" not in by_id


async def test_setup_failure_at_startup_stays_on_the_log_review(hass, tmp_path):
    from datetime import datetime

    from custom_components.log_doctor.coordinator import LogDoctorCoordinator
    from custom_components.log_doctor.digest import AnomalyReport
    from custom_components.log_doctor.log_parser import filter_and_group, parse_log_lines
    from custom_components.log_doctor.restarts import RestartTracker, Run

    start = datetime(2026, 10, 12, 8, 0, 0)
    tracker = RestartTracker(hass, log_path=str(tmp_path / "x.log"), grace=timedelta(minutes=3))
    tracker.runs = [Run(start, start + timedelta(minutes=1))]
    lines = [
        "2026-10-12 08:00:30.000 ERROR (MainThread) [homeassistant.setup] Setup failed for 'zha': Integration failed to initialize.\n",
        "2026-10-12 08:00:31.000 WARNING (MainThread) [homeassistant.components.mqtt] Connecting while starting\n",
    ]
    groups = filter_and_group(parse_log_lines(lines), "WARNING", None)
    reports = [AnomalyReport(group=g, is_new=True) for g in groups.values()]
    fake = SimpleNamespace(restarts=tracker, anomaly_store=AnomalyStore(hass))
    LogDoctorCoordinator._classify_restarts(fake, reports)
    restart = {r.group.logger: r.restart for r in reports}
    assert restart == {"homeassistant.setup": False, "homeassistant.components.mqtt": True}
