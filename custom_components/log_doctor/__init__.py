"""The Log Doctor integration.

Periodically scans the Home Assistant log for warnings/errors, matches them
against a built-in knowledge base, and reports what it finds once a day. It
never modifies your configuration or takes any remediation action - it only
reports. Separately, it watches every automation run in real time and
posts a persistent notification whenever one fails (see
automation_monitor.py), and after each restart reports any time-scheduled
automation runs missed while Home Assistant was offline (see
missed_schedules.py). When an OpenAI API key is configured and the
"Auto-investigate" switch is on (see switch.py), it also automatically
investigates the anomalies found with an OpenAI model right after each scan
(see investigation.py). The separate companion app (see companion/) offers the
same research on demand, against any report file, independent of this
automatic stage.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE,
    CONF_INCLUDE_SUPERVISOR_LOGS,
    CONF_LOG_PATH,
    CONF_LOOKBACK_HOURS,
    CONF_MAX_INVESTIGATED,
    CONF_MIN_SEVERITY,
    CONF_MISSED_SCHEDULE_MIN_PATTERN_MINUTES,
    CONF_MOBILE_NOTIFY_SERVICE,
    CONF_MONITOR_AUTOMATIONS,
    CONF_MONITOR_MISSED_SCHEDULES,
    CONF_OPENAI_API_KEY,
    CONF_REPORT_RETENTION_DAYS,
    CONF_SCAN_TIME,
    DEFAULT_INCLUDE_SUPERVISOR_LOGS,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MAX_INVESTIGATED,
    DEFAULT_MIN_SEVERITY,
    DEFAULT_MISSED_SCHEDULE_MIN_PATTERN_MINUTES,
    DEFAULT_MONITOR_AUTOMATIONS,
    DEFAULT_MONITOR_MISSED_SCHEDULES,
    DEFAULT_REPORT_RETENTION_DAYS,
    DEFAULT_SCAN_HOUR,
    DEFAULT_SCAN_MINUTE,
    DEVICE_NAME,
    DOMAIN,
    PLATFORMS,
    SERVICE_CLEAR_HISTORY,
    SERVICE_SCAN_NOW,
)
from .automation_monitor import AutomationFailureMonitor
from .coordinator import LogDoctorCoordinator
from .knowledge_base import async_warm_known_issues
from .missed_schedules import MissedScheduleWatch
from .paths import migrate_legacy_folder_sync
from .store import LogDoctorStore

_LOGGER = logging.getLogger(__name__)


def _parse_scan_time(value: str) -> tuple[int, int, int]:
    parts = [int(p) for p in value.split(":")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Log Doctor from a config entry."""
    # Entries created before the "WP" rename keep their original title
    # forever unless updated explicitly - the manifest/config_flow rename
    # only affects newly created entries.
    if entry.title == "Log Doctor":
        hass.config_entries.async_update_entry(entry, title=DEVICE_NAME)

    options = {**entry.data, **entry.options}

    # Pre-0.15.0 installs kept everything in log_doctor_reports/.
    await hass.async_add_executor_job(
        migrate_legacy_folder_sync, Path(hass.config.config_dir)
    )

    store = LogDoctorStore(hass, entry.entry_id)
    await store.async_load()
    await async_warm_known_issues(hass)

    mobile_notify = options.get(CONF_MOBILE_NOTIFY_SERVICE) or None
    if mobile_notify:
        mobile_notify = mobile_notify.removeprefix("notify.")

    coordinator = LogDoctorCoordinator(
        hass,
        log_path=options.get(CONF_LOG_PATH) or hass.config.path("home-assistant.log"),
        lookback_hours=options.get(CONF_LOOKBACK_HOURS, DEFAULT_LOOKBACK_HOURS),
        min_severity=options.get(CONF_MIN_SEVERITY, DEFAULT_MIN_SEVERITY),
        mobile_notify_service=mobile_notify,
        report_retention_days=options.get(
            CONF_REPORT_RETENTION_DAYS, DEFAULT_REPORT_RETENTION_DAYS
        ),
        include_supervisor_logs=options.get(
            CONF_INCLUDE_SUPERVISOR_LOGS, DEFAULT_INCLUDE_SUPERVISOR_LOGS
        ),
        openai_api_key=options.get(CONF_OPENAI_API_KEY) or None,
        # NumberSelector hands back a float, but this gets used as a list
        # slice index in investigation.py, which requires an actual int.
        max_investigated=int(options.get(CONF_MAX_INVESTIGATED, DEFAULT_MAX_INVESTIGATED)),
        store=store,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    scan_time = options.get(CONF_SCAN_TIME)
    if scan_time:
        hour, minute, second = _parse_scan_time(scan_time)
    else:
        hour, minute, second = DEFAULT_SCAN_HOUR, DEFAULT_SCAN_MINUTE, 0

    async def _scheduled_scan(_now) -> None:
        await coordinator.async_request_refresh()

    unsub_time = async_track_time_change(
        hass, _scheduled_scan, hour=hour, minute=minute, second=second
    )
    entry.async_on_unload(unsub_time)

    notify_device_id = options.get(CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE) or None
    if options.get(CONF_MONITOR_AUTOMATIONS, DEFAULT_MONITOR_AUTOMATIONS):
        monitor = AutomationFailureMonitor(hass, notify_device_id=notify_device_id)
        entry.async_on_unload(monitor.async_start())

    if options.get(CONF_MONITOR_MISSED_SCHEDULES, DEFAULT_MONITOR_MISSED_SCHEDULES):
        watch = MissedScheduleWatch(
            hass,
            entry.entry_id,
            notify_device_id=notify_device_id,
            min_pattern_interval=timedelta(
                minutes=int(
                    options.get(
                        CONF_MISSED_SCHEDULE_MIN_PATTERN_MINUTES,
                        DEFAULT_MISSED_SCHEDULE_MIN_PATTERN_MINUTES,
                    )
                )
            ),
        )
        await watch.async_start()
        entry.async_on_unload(watch.async_stop)

    async def _async_scan_now(_call: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    async def _async_clear_history(_call: ServiceCall) -> None:
        await store.async_clear_history()

    if not hass.services.has_service(DOMAIN, SERVICE_SCAN_NOW):
        hass.services.async_register(DOMAIN, SERVICE_SCAN_NOW, _async_scan_now)
    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_HISTORY):
        hass.services.async_register(DOMAIN, SERVICE_CLEAR_HISTORY, _async_clear_history)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Log Doctor config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SCAN_NOW)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_HISTORY)
    return unload_ok
