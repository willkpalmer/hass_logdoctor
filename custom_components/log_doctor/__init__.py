"""The Log Doctor integration.

Periodically scans the Home Assistant log for warnings/errors, matches them
against a built-in knowledge base, and reports what it finds once a day. It
never modifies your configuration or takes any remediation action - it only
reports. Separately, it watches every automation run in real time and
posts a persistent notification whenever one fails (see
automation_monitor.py), and after each restart reports any time-scheduled
automation runs missed while Home Assistant was offline (see
missed_schedules.py). Log messages from Home Assistant starting or shutting
down are kept apart on a Startup & shutdown view (see restarts.py). Backup problems and successes - Home Assistant's own
and the GDrive Backup Utility add-on's - are kept apart from the rest on a
Backups view (see backups.py, backup_store.py, backup_monitor.py). Each
scan also counts warnings and errors over time (see stats.py) for the
Insights page and the weekly digest (see weekly_digest.py). When an
OpenAI API key is configured and the "Auto-investigate" switch is on (see
switch.py), it also automatically investigates the anomalies found with an
OpenAI model right after each scan (see investigation.py). The separate
companion app (see companion/) offers the same research on demand, against
any report file, independent of this automatic stage.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_FLAP_COUNT,
    CONF_FLAP_HOURS,
    CONF_INVESTIGATION_MODEL,
    CONF_MONITOR_STOPPED_AUTOMATIONS,
    CONF_WEEKLY_DIGEST,
    CONF_WEEKLY_DIGEST_DAY,
    DATA_FLAPS,
    DATA_STATS,
    DEFAULT_FLAP_COUNT,
    DEFAULT_FLAP_HOURS,
    DEFAULT_INVESTIGATION_MODEL,
    DEFAULT_MONITOR_STOPPED_AUTOMATIONS,
    DEFAULT_WEEKLY_DIGEST,
    DEFAULT_WEEKLY_DIGEST_DAY,
    SERVICE_SEND_WEEKLY_DIGEST,
    CONF_MONITOR_HEALTH,
    CONF_OFFLINE_HOURS,
    DEFAULT_MONITOR_HEALTH,
    DEFAULT_OFFLINE_HOURS,
    CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE,
    CONF_INCLUDE_SUPERVISOR_LOGS,
    CONF_LOG_PATH,
    CONF_LOOKBACK_HOURS,
    CONF_MAX_INVESTIGATED,
    CONF_MIN_SEVERITY,
    CONF_MISSED_SCHEDULE_MIN_PATTERN_MINUTES,
    CONF_RESTART_GRACE_MINUTES,
    DEFAULT_RESTART_GRACE_MINUTES,
    CONF_RESTART_HISTORY_OPEN,
    DEFAULT_RESTART_HISTORY_OPEN,
    DATA_RESTART_HISTORY,
    DATA_RUN_STORE,
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
    DATA_ANOMALY_STORE,
    DATA_BACKUP_STORE,
    DATA_HEALTH_STORE,
    DATA_FAILURE_STORE,
    DOMAIN,
    PLATFORMS,
    SERVICE_CLEAR_HISTORY,
    SERVICE_SCAN_NOW,
)
from .automation_monitor import AutomationFailureMonitor
from .automation_runs import AutomationRunStore, async_record_runs
from .coordinator import LogDoctorCoordinator
from .knowledge_base import async_warm_known_issues
from .missed_schedules import MissedScheduleWatch
from .failure_log import convert_legacy_failure_log_sync
from .anomaly_store import AnomalyStore
from .backup_monitor import BackupEventMonitor
from .backup_store import KIND_PROBLEM, BackupStore
from .backups import backup_source
from .health_monitor import HealthMonitor
from .health_store import HealthStore
from .failure_store import FailureStore
from .flapping import FlapTracker
from .panel import async_register_panel, async_remove_panel
from .paths import logdoctor_dir, migrate_legacy_folder_sync
from .restart_history import RestartHistoryStore
from .restarts import RestartTracker
from .stats import StatsStore
from .stopped_automations import StoppedAutomationWatch
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

    # Pre-0.15.0 installs kept everything in log_doctor_reports/, and
    # pre-0.16.0 ones a plain-text failure log.
    await hass.async_add_executor_job(
        migrate_legacy_folder_sync, Path(hass.config.config_dir)
    )
    try:
        await hass.async_add_executor_job(
            convert_legacy_failure_log_sync, logdoctor_dir(hass)
        )
    except OSError:
        _LOGGER.warning("Could not convert the old automation failure log", exc_info=True)

    # The automation failure list (and its Markdown file), shared by the
    # monitors, the daily scan's pruning and the sidebar panel.
    failure_store = FailureStore(hass)
    await failure_store.async_load()
    hass.data[DATA_FAILURE_STORE] = failure_store
    # The anomalies the scans report, for the panel's Log review view.
    anomaly_store = AnomalyStore(hass)
    await anomaly_store.async_load()
    hass.data[DATA_ANOMALY_STORE] = anomaly_store
    # Offline devices, failed integrations and Repairs, for
    # the panel's Devices & integrations view.
    health_store = HealthStore(hass)
    await health_store.async_load()
    hass.data[DATA_HEALTH_STORE] = health_store
    # Backup problems and successes, for the panel's Backups view.
    backup_store = BackupStore(hass)
    await backup_store.async_load()
    hass.data[DATA_BACKUP_STORE] = backup_store
    # Backup problems found before the Backups view existed move there
    # from the Log review.
    moved = await anomaly_store.async_take(lambda r: backup_source(r["logger"]) is not None)
    if moved:
        for record in moved:
            record["kind"] = KIND_PROBLEM
            record["source"] = backup_source(record["logger"])
        await backup_store.async_add_records(moved)

    store = LogDoctorStore(hass, entry.entry_id)
    await store.async_load()
    await async_warm_known_issues(hass)

    mobile_notify = options.get(CONF_MOBILE_NOTIFY_SERVICE) or None
    if mobile_notify:
        mobile_notify = mobile_notify.removeprefix("notify.")

    log_path = options.get(CONF_LOG_PATH) or hass.config.path("home-assistant.log")
    # Every automation run, for the panel's Automations page (Runs).
    run_store = AutomationRunStore(hass)
    await run_store.async_load()
    await run_store.async_prune(
        int(options.get(CONF_REPORT_RETENTION_DAYS, DEFAULT_REPORT_RETENTION_DAYS))
    )
    hass.data[DATA_RUN_STORE] = run_store
    entry.async_on_unload(async_record_runs(hass, run_store))
    # Warnings and errors over time, for Insights and the weekly digest.
    stats = StatsStore(hass)
    await stats.async_load()
    hass.data[DATA_STATS] = stats
    # The panel's Restart history view.
    restart_history = RestartHistoryStore(hass)
    await restart_history.async_load()
    hass.data[DATA_RESTART_HISTORY] = restart_history
    # Home Assistant's starts and stops, to tell startup and shutdown
    # messages apart from the rest.
    restarts = RestartTracker(
        hass,
        log_path=log_path,
        grace=timedelta(
            minutes=int(options.get(CONF_RESTART_GRACE_MINUTES, DEFAULT_RESTART_GRACE_MINUTES))
        ),
        history=restart_history,
        history_open_limit=int(
            options.get(CONF_RESTART_HISTORY_OPEN, DEFAULT_RESTART_HISTORY_OPEN)
        ),
    )
    await restarts.async_start()
    entry.async_on_unload(restarts.async_stop)

    coordinator = LogDoctorCoordinator(
        hass,
        log_path=log_path,
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
        failure_store=failure_store,
        anomaly_store=anomaly_store,
        health_store=health_store,
        backup_store=backup_store,
        restarts=restarts,
        run_store=run_store,
        stats=stats,
        investigation_model=options.get(CONF_INVESTIGATION_MODEL) or DEFAULT_INVESTIGATION_MODEL,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    scan_time = options.get(CONF_SCAN_TIME)
    if scan_time:
        hour, minute, second = _parse_scan_time(scan_time)
    else:
        hour, minute, second = DEFAULT_SCAN_HOUR, DEFAULT_SCAN_MINUTE, 0

    weekly_digest = options.get(CONF_WEEKLY_DIGEST, DEFAULT_WEEKLY_DIGEST)
    weekly_digest_day = options.get(CONF_WEEKLY_DIGEST_DAY, DEFAULT_WEEKLY_DIGEST_DAY)

    async def _scheduled_scan(_now) -> None:
        await coordinator.async_refresh()
        # The weekly digest goes out after the scan on its day, so it
        # includes that scan.
        if weekly_digest and coordinator.weekly_digest_due(weekly_digest_day):
            try:
                await coordinator.async_send_weekly_digest()
            except Exception:  # noqa: BLE001 - never let the digest break anything
                _LOGGER.exception("Could not send the weekly digest")

    unsub_time = async_track_time_change(
        hass, _scheduled_scan, hour=hour, minute=minute, second=second
    )
    entry.async_on_unload(unsub_time)

    notify_device_id = options.get(CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE) or None
    if options.get(CONF_MONITOR_AUTOMATIONS, DEFAULT_MONITOR_AUTOMATIONS):
        monitor = AutomationFailureMonitor(
            hass, failure_store, notify_device_id=notify_device_id
        )
        entry.async_on_unload(monitor.async_start())

    if options.get(CONF_MONITOR_MISSED_SCHEDULES, DEFAULT_MONITOR_MISSED_SCHEDULES):
        watch = MissedScheduleWatch(
            hass,
            entry.entry_id,
            failure_store=failure_store,
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

    if options.get(CONF_MONITOR_STOPPED_AUTOMATIONS, DEFAULT_MONITOR_STOPPED_AUTOMATIONS):
        stopped = StoppedAutomationWatch(
            hass, run_store, failure_store, notify_device_id=notify_device_id
        )
        entry.async_on_unload(stopped.async_start())

    if options.get(CONF_MONITOR_HEALTH, DEFAULT_MONITOR_HEALTH):
        flaps = None
        flap_count = int(options.get(CONF_FLAP_COUNT, DEFAULT_FLAP_COUNT))
        if flap_count > 0:
            # Devices that keep dropping off and coming back.
            flaps = FlapTracker(
                hass,
                count=flap_count,
                window=timedelta(hours=int(options.get(CONF_FLAP_HOURS, DEFAULT_FLAP_HOURS))),
            )
            await flaps.async_load()
            entry.async_on_unload(flaps.async_start())
            hass.data[DATA_FLAPS] = flaps
        health_monitor = HealthMonitor(
            hass,
            health_store,
            offline_after=timedelta(
                hours=int(options.get(CONF_OFFLINE_HOURS, DEFAULT_OFFLINE_HOURS))
            ),
            flaps=flaps,
        )
        entry.async_on_unload(health_monitor.async_start())
        # "Monitor again" on the panel checks straight away.
        health_store.recheck = health_monitor.async_check

    # Home Assistant's own backups, as they complete or fail.
    entry.async_on_unload(BackupEventMonitor(hass, backup_store).async_start())

    async def _async_scan_now(_call: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    async def _async_clear_history(_call: ServiceCall) -> None:
        await store.async_clear_history()

    async def _async_send_weekly_digest(_call: ServiceCall) -> None:
        await coordinator.async_send_weekly_digest()

    if not hass.services.has_service(DOMAIN, SERVICE_SCAN_NOW):
        hass.services.async_register(DOMAIN, SERVICE_SCAN_NOW, _async_scan_now)
    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_HISTORY):
        hass.services.async_register(DOMAIN, SERVICE_CLEAR_HISTORY, _async_clear_history)
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_WEEKLY_DIGEST):
        hass.services.async_register(DOMAIN, SERVICE_SEND_WEEKLY_DIGEST, _async_send_weekly_digest)

    await async_register_panel(hass)

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
        async_remove_panel(hass)
        for key in (
            DATA_FAILURE_STORE,
            DATA_ANOMALY_STORE,
            DATA_HEALTH_STORE,
            DATA_BACKUP_STORE,
            DATA_RESTART_HISTORY,
            DATA_RUN_STORE,
            DATA_STATS,
            DATA_FLAPS,
        ):
            if (stored := hass.data.pop(key, None)) is not None:
                await stored.async_shutdown()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SCAN_NOW)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_HISTORY)
            hass.services.async_remove(DOMAIN, SERVICE_SEND_WEEKLY_DIGEST)
    return unload_ok
