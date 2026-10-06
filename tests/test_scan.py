"""The scan: untimed Supervisor lines, stats, the weekly digest."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from custom_components.log_doctor import coordinator as coordinator_module
from custom_components.log_doctor.anomaly_store import AnomalyStore
from custom_components.log_doctor.const import DATA_ANOMALY_STORE, DATA_STATS
from custom_components.log_doctor.knowledge_base import async_warm_known_issues
from custom_components.log_doctor.log_parser import LogEntry
from custom_components.log_doctor.stats import KIND_INTEGRATION, KIND_OTHER, KIND_SOURCE, StatsStore, noise_source
from custom_components.log_doctor.store import LogDoctorStore
from custom_components.log_doctor.weekly_digest import async_build_digest


async def _coordinator(hass, tmp_path, text_holder, stats=None):
    log = tmp_path / "home-assistant.log"
    log.write_text("")
    coordinator_module.supervisor_available = lambda: True

    async def sources(_hass):
        return [("addons/core_mosquitto/logs", "Mosquitto broker")]

    async def fetch(_hass, wanted):
        return {path: (name, text_holder[0]) for path, name in wanted}

    coordinator_module.async_list_all_sources = sources
    coordinator_module.async_fetch_all_logs = fetch
    anomalies = AnomalyStore(hass)
    store = LogDoctorStore(hass, "test")
    await async_warm_known_issues(hass)
    coordinator = coordinator_module.LogDoctorCoordinator(
        hass,
        log_path=str(log),
        lookback_hours=24,
        min_severity="WARNING",
        mobile_notify_service=None,
        include_supervisor_logs=True,
        store=store,
        anomaly_store=anomalies,
        stats=stats,
    )

    async def no_notify(_result):
        return None

    coordinator._async_notify = no_notify
    return coordinator, anomalies


async def test_untimed_lines_are_counted_once(hass, tmp_path):
    line = "[12:00:00] WARNING: Could not reach the broker, retrying"
    text = [line]
    coordinator, anomalies = await _coordinator(hass, tmp_path, text)
    await coordinator._async_scan()
    assert anomalies.records[0]["count"] == 1
    # The same tail again: nothing new.
    await coordinator._async_scan()
    assert anomalies.records[0]["count"] == 1
    # Logged once more since: counted once more.
    text[0] = f"{line}\n{line}"
    await coordinator._async_scan()
    assert anomalies.records[0]["count"] == 2


def test_noise_sources():
    assert noise_source("homeassistant.components.zha.core") == ("zha", KIND_INTEGRATION)
    assert noise_source("custom_components.hacs.base") == ("hacs", KIND_INTEGRATION)
    assert noise_source("Mosquitto broker:mqtt", ["Mosquitto broker"]) == ("Mosquitto broker", KIND_SOURCE)
    assert noise_source("Host", ["Host"]) == ("Host", KIND_SOURCE)
    assert noise_source("aiohttp.server") == ("aiohttp", KIND_OTHER)


async def test_stats_rank_the_noisiest(hass):
    stats = StatsStore(hass)
    now = datetime.now()

    def entry(logger, level, hours_ago=1):
        return LogEntry(timestamp=now - timedelta(hours=hours_ago), level=level, logger=logger, message="x")

    since = now - timedelta(days=1)
    stats.record(
        [
            entry("homeassistant.components.zha", "WARNING"),
            entry("homeassistant.components.zha", "WARNING"),
            entry("homeassistant.components.hue", "ERROR"),
            entry("homeassistant.components.hue", "INFO"),  # not counted
            entry("homeassistant.components.mqtt", "ERROR", hours_ago=48),  # before since
        ],
        since,
    )
    ranking = stats.ranking(7)
    assert [(r["source"], r["total"]) for r in ranking] == [("hue", 1), ("zha", 2)]
    assert sum(point["WARNING"] for point in stats.hourly(24)) == 2
    assert stats.totals(7) == {"WARNING": 2, "ERROR": 1, "CRITICAL": 0}
    await stats.async_shutdown()


async def test_weekly_digest(hass):
    stats = StatsStore(hass)
    stats.record(
        [LogEntry(timestamp=datetime.now(), level="ERROR", logger="homeassistant.components.zha", message="x")],
        None,
    )
    hass.data[DATA_STATS] = stats
    anomalies = AnomalyStore(hass)
    now = dt_util.utcnow().isoformat()
    anomalies._records = [
        {"id": "a", "level": "ERROR", "logger": "x", "message": "Boom", "count": 3, "first_seen": now, "resolved": None},
        {"id": "b", "level": "WARNING", "logger": "y", "message": "Old", "count": 1, "first_seen": "2020-01-01T00:00:00+00:00", "resolved": None},
    ]
    hass.data[DATA_ANOMALY_STORE] = anomalies
    digest = await async_build_digest(hass)
    assert digest.data["logs"]["new"] == 1
    assert digest.data["logs"]["open"] == 2
    assert digest.data["noise"][0]["source"] == "zha"
    assert "Noisiest integrations" in digest.markdown
    assert "Boom" in digest.markdown
    await stats.async_shutdown()
