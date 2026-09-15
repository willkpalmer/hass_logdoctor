"""The Log Doctor integration.

Periodically scans the Home Assistant log for warnings/errors, matches them
against a built-in knowledge base and (optionally) a live GitHub issue
search, and reports what it finds once a day. It never modifies your
configuration or takes any remediation action - it only reports.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_ENABLE_GITHUB_LOOKUP,
    CONF_GITHUB_TOKEN,
    CONF_INCLUDE_SUPERVISOR_LOGS,
    CONF_LOG_PATH,
    CONF_LOOKBACK_HOURS,
    CONF_MAX_GITHUB_QUERIES,
    CONF_MIN_SEVERITY,
    CONF_MOBILE_NOTIFY_SERVICE,
    CONF_REPORT_RETENTION_DAYS,
    CONF_SCAN_TIME,
    DEFAULT_INCLUDE_SUPERVISOR_LOGS,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MAX_GITHUB_QUERIES,
    DEFAULT_MIN_SEVERITY,
    DEFAULT_REPORT_RETENTION_DAYS,
    DEFAULT_SCAN_HOUR,
    DEFAULT_SCAN_MINUTE,
    DOMAIN,
    PLATFORMS,
    SERVICE_CLEAR_HISTORY,
    SERVICE_SCAN_NOW,
)
from .coordinator import LogDoctorCoordinator
from .knowledge_base import async_warm_known_issues
from .store import LogDoctorStore

_LOGGER = logging.getLogger(__name__)


def _parse_scan_time(value: str) -> tuple[int, int, int]:
    parts = [int(p) for p in value.split(":")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Log Doctor from a config entry."""
    options = {**entry.data, **entry.options}

    store = LogDoctorStore(hass, entry.entry_id)
    await store.async_load()
    await async_warm_known_issues(hass)

    github_token = options.get(CONF_GITHUB_TOKEN) or None
    mobile_notify = options.get(CONF_MOBILE_NOTIFY_SERVICE) or None
    if mobile_notify:
        mobile_notify = mobile_notify.removeprefix("notify.")

    coordinator = LogDoctorCoordinator(
        hass,
        log_path=options.get(CONF_LOG_PATH) or hass.config.path("home-assistant.log"),
        lookback_hours=options.get(CONF_LOOKBACK_HOURS, DEFAULT_LOOKBACK_HOURS),
        min_severity=options.get(CONF_MIN_SEVERITY, DEFAULT_MIN_SEVERITY),
        enable_github_lookup=options.get(CONF_ENABLE_GITHUB_LOOKUP, True),
        github_token=github_token,
        max_github_queries=options.get(CONF_MAX_GITHUB_QUERIES, DEFAULT_MAX_GITHUB_QUERIES),
        mobile_notify_service=mobile_notify,
        report_retention_days=options.get(
            CONF_REPORT_RETENTION_DAYS, DEFAULT_REPORT_RETENTION_DAYS
        ),
        include_supervisor_logs=options.get(
            CONF_INCLUDE_SUPERVISOR_LOGS, DEFAULT_INCLUDE_SUPERVISOR_LOGS
        ),
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
