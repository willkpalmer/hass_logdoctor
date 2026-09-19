"""Config flow for Log Doctor."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .const import (
    CONF_INCLUDE_SUPERVISOR_LOGS,
    CONF_LOG_PATH,
    CONF_LOOKBACK_HOURS,
    CONF_MAX_INVESTIGATED,
    CONF_MIN_SEVERITY,
    CONF_MOBILE_NOTIFY_SERVICE,
    CONF_OPENAI_API_KEY,
    CONF_REPORT_RETENTION_DAYS,
    CONF_SCAN_TIME,
    DEFAULT_INCLUDE_SUPERVISOR_LOGS,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MAX_INVESTIGATED,
    DEFAULT_MIN_SEVERITY,
    DEFAULT_REPORT_RETENTION_DAYS,
    DEFAULT_SCAN_HOUR,
    DEFAULT_SCAN_MINUTE,
    DOMAIN,
    SEVERITY_LEVELS,
)

_UNIQUE_ID = "log_doctor"


def _default_scan_time() -> str:
    return f"{DEFAULT_SCAN_HOUR:02d}:{DEFAULT_SCAN_MINUTE:02d}:00"


def _build_schema(hass, defaults: dict[str, Any]) -> vol.Schema:
    default_log_path = defaults.get(CONF_LOG_PATH) or hass.config.path("home-assistant.log")
    return vol.Schema(
        {
            vol.Required(CONF_LOG_PATH, default=default_log_path): TextSelector(),
            vol.Required(
                CONF_SCAN_TIME, default=defaults.get(CONF_SCAN_TIME, _default_scan_time())
            ): TimeSelector(),
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
            vol.Optional(
                CONF_OPENAI_API_KEY, default=defaults.get(CONF_OPENAI_API_KEY, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
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
            return self.async_create_entry(title="Log Doctor", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(self.hass, {}),
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
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(self.hass, current),
        )
