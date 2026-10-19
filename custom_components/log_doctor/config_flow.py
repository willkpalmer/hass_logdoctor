"""Config flow for Log Doctor."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .schedule import (
    MODE_INTERVAL,
    MODE_TIMES,
    UNIT_HOURS,
    UNIT_MINUTES,
    format_scan_times,
    parse_scan_times,
    scan_interval,
)
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL_UNIT,
    CONF_SCAN_MODE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_UNIT,
    DEFAULT_SCAN_MODE,
    CONF_FLAP_COUNT,
    CONF_FLAP_HOURS,
    CONF_INVESTIGATION_MODEL,
    CONF_MONITOR_STOPPED_AUTOMATIONS,
    CONF_WEEKLY_DIGEST,
    CONF_WEEKLY_DIGEST_DAY,
    DEFAULT_FLAP_COUNT,
    DEFAULT_FLAP_HOURS,
    DEFAULT_INVESTIGATION_MODEL,
    DEFAULT_MONITOR_STOPPED_AUTOMATIONS,
    DEFAULT_WEEKLY_DIGEST,
    DEFAULT_WEEKLY_DIGEST_DAY,
    WEEKDAYS,
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
    DOMAIN,
    SEVERITY_LEVELS,
)

_UNIQUE_ID = "log_doctor"


def _scan_time_text(value: str | None) -> str:
    """Stored scan times as shown ("08:00:00" from before 0.45.0 → "08:00")."""
    try:
        return format_scan_times(parse_scan_times(value))
    except ValueError:
        return _default_scan_time()


def _default_scan_time() -> str:
    return f"{DEFAULT_SCAN_HOUR:02d}:{DEFAULT_SCAN_MINUTE:02d}"


def validate_schedule(options: dict[str, Any]) -> dict[str, str]:
    """Errors in the scan schedule, by field, for the form; tidies scan_time.

    The schema's selectors can't check a list of times or the interval's
    range, so they're checked here (also by settings_api.py).
    """
    errors: dict[str, str] = {}
    if options.get(CONF_SCAN_MODE, DEFAULT_SCAN_MODE) == MODE_INTERVAL:
        try:
            scan_interval(options.get(CONF_SCAN_INTERVAL), options.get(CONF_SCAN_INTERVAL_UNIT))
        except ValueError:
            errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"
    try:
        options[CONF_SCAN_TIME] = format_scan_times(parse_scan_times(options.get(CONF_SCAN_TIME)))
    except ValueError:
        if options.get(CONF_SCAN_MODE, DEFAULT_SCAN_MODE) != MODE_INTERVAL:
            errors[CONF_SCAN_TIME] = "invalid_scan_time"
    return errors


def _build_schema(hass, defaults: dict[str, Any]) -> vol.Schema:
    default_log_path = defaults.get(CONF_LOG_PATH) or hass.config.path("home-assistant.log")
    return vol.Schema(
        {
            vol.Required(CONF_LOG_PATH, default=default_log_path): TextSelector(),
            vol.Required(
                CONF_SCAN_MODE, default=defaults.get(CONF_SCAN_MODE, DEFAULT_SCAN_MODE)
            ): SelectSelector(
                SelectSelectorConfig(options=[MODE_TIMES, MODE_INTERVAL], translation_key="scan_mode")
            ),
            # One or more times, comma-separated (see schedule.py).
            vol.Required(
                CONF_SCAN_TIME, default=_scan_time_text(defaults.get(CONF_SCAN_TIME))
            ): TextSelector(),
            vol.Required(
                CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=1440, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_SCAN_INTERVAL_UNIT,
                default=defaults.get(CONF_SCAN_INTERVAL_UNIT, DEFAULT_SCAN_INTERVAL_UNIT),
            ): SelectSelector(
                SelectSelectorConfig(options=[UNIT_MINUTES, UNIT_HOURS], translation_key="scan_interval_unit")
            ),
            vol.Required(
                CONF_MIN_SEVERITY,
                default=defaults.get(CONF_MIN_SEVERITY, DEFAULT_MIN_SEVERITY),
            ): SelectSelector(SelectSelectorConfig(options=SEVERITY_LEVELS)),
            vol.Required(
                CONF_LOOKBACK_HOURS,
                default=defaults.get(CONF_LOOKBACK_HOURS, DEFAULT_LOOKBACK_HOURS),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=168, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_RESTART_GRACE_MINUTES,
                default=defaults.get(CONF_RESTART_GRACE_MINUTES, DEFAULT_RESTART_GRACE_MINUTES),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=60, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="min"
                )
            ),
            vol.Required(
                CONF_RESTART_HISTORY_OPEN,
                default=defaults.get(CONF_RESTART_HISTORY_OPEN, DEFAULT_RESTART_HISTORY_OPEN),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=500, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_MOBILE_NOTIFY_SERVICE,
                default=defaults.get(CONF_MOBILE_NOTIFY_SERVICE, ""),
            ): TextSelector(),
            vol.Required(
                CONF_REPORT_RETENTION_DAYS,
                default=defaults.get(
                    CONF_REPORT_RETENTION_DAYS, DEFAULT_REPORT_RETENTION_DAYS
                ),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=365, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_INCLUDE_SUPERVISOR_LOGS,
                default=defaults.get(
                    CONF_INCLUDE_SUPERVISOR_LOGS, DEFAULT_INCLUDE_SUPERVISOR_LOGS
                ),
            ): BooleanSelector(),
            vol.Required(
                CONF_MONITOR_AUTOMATIONS,
                default=defaults.get(
                    CONF_MONITOR_AUTOMATIONS, DEFAULT_MONITOR_AUTOMATIONS
                ),
            ): BooleanSelector(),
            vol.Required(
                CONF_MONITOR_MISSED_SCHEDULES,
                default=defaults.get(
                    CONF_MONITOR_MISSED_SCHEDULES, DEFAULT_MONITOR_MISSED_SCHEDULES
                ),
            ): BooleanSelector(),
            vol.Required(
                CONF_MISSED_SCHEDULE_MIN_PATTERN_MINUTES,
                default=defaults.get(
                    CONF_MISSED_SCHEDULE_MIN_PATTERN_MINUTES,
                    DEFAULT_MISSED_SCHEDULE_MIN_PATTERN_MINUTES,
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=1440,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
            vol.Required(
                CONF_MONITOR_STOPPED_AUTOMATIONS,
                default=defaults.get(
                    CONF_MONITOR_STOPPED_AUTOMATIONS, DEFAULT_MONITOR_STOPPED_AUTOMATIONS
                ),
            ): BooleanSelector(),
            vol.Required(
                CONF_MONITOR_HEALTH,
                default=defaults.get(CONF_MONITOR_HEALTH, DEFAULT_MONITOR_HEALTH),
            ): BooleanSelector(),
            vol.Required(
                CONF_OFFLINE_HOURS,
                default=defaults.get(CONF_OFFLINE_HOURS, DEFAULT_OFFLINE_HOURS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=168, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="h"
                )
            ),
            vol.Required(
                CONF_FLAP_COUNT,
                default=defaults.get(CONF_FLAP_COUNT, DEFAULT_FLAP_COUNT),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_FLAP_HOURS,
                default=defaults.get(CONF_FLAP_HOURS, DEFAULT_FLAP_HOURS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=168, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="h"
                )
            ),
            vol.Required(
                CONF_WEEKLY_DIGEST,
                default=defaults.get(CONF_WEEKLY_DIGEST, DEFAULT_WEEKLY_DIGEST),
            ): BooleanSelector(),
            vol.Required(
                CONF_WEEKLY_DIGEST_DAY,
                default=defaults.get(CONF_WEEKLY_DIGEST_DAY, DEFAULT_WEEKLY_DIGEST_DAY),
            ): SelectSelector(SelectSelectorConfig(options=WEEKDAYS, translation_key="weekday")),
            # Optional and clearable, so use a suggested value rather than a
            # default (a default would be re-applied when cleared).
            vol.Optional(
                CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE,
                description={
                    "suggested_value": defaults.get(CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE)
                },
            ): DeviceSelector(DeviceSelectorConfig(integration="mobile_app")),
            vol.Optional(
                CONF_OPENAI_API_KEY, default=defaults.get(CONF_OPENAI_API_KEY, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            vol.Required(
                CONF_INVESTIGATION_MODEL,
                default=defaults.get(CONF_INVESTIGATION_MODEL, DEFAULT_INVESTIGATION_MODEL),
            ): TextSelector(),
            vol.Required(
                CONF_MAX_INVESTIGATED,
                default=defaults.get(CONF_MAX_INVESTIGATED, DEFAULT_MAX_INVESTIGATED),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)
            ),
        }
    )


class LogDoctorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of Log Doctor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        await self.async_set_unique_id(_UNIQUE_ID)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_schedule(user_input)
            if not errors:
                return self.async_create_entry(title="WP Log Doctor", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(self.hass, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "LogDoctorOptionsFlow":
        return LogDoctorOptionsFlow(config_entry)


class LogDoctorOptionsFlow(OptionsFlow):
    """Handle Log Doctor options (all settings are editable after setup)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_schedule(user_input)
            if not errors:
                # A cleared optional field is left out of user_input entirely;
                # store it as explicitly empty so the value chosen during the
                # initial setup (in entry.data) doesn't come back.
                user_input.setdefault(CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE, None)
                return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options, **(user_input or {})}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(self.hass, current),
            errors=errors,
        )
