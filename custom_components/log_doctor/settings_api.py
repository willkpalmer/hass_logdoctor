"""WebSocket commands for the Log Doctor panel's Settings view.

Everything the integration's Configure dialog and its entities offer, on
one page:

- log_doctor/settings/get - current settings, the choices some of them
  need (Mobile App devices, notify services), and the last scan's status
- log_doctor/settings/update - save settings; validated with the same
  schema as the Configure dialog, then stored as the entry's options, which
  reloads the integration just as saving that dialog does
- log_doctor/settings/set_auto_investigate - the Auto-investigate switch
- log_doctor/settings/scan_now - the Scan now button
- log_doctor/settings/clear_history - the log_doctor.clear_history service

The OpenAI API key is never sent to the browser: the page only learns
whether one is set, and sends a new key (or a request to remove it) only
when the user changes it.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .config_flow import _build_schema
from .const import (
    CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE,
    CONF_OPENAI_API_KEY,
    DOMAIN,
    SEVERITY_LEVELS,
)
from .paths import failure_log_path, reviews_dir

WS_GET = "log_doctor/settings/get"
WS_UPDATE = "log_doctor/settings/update"
WS_SET_AUTO_INVESTIGATE = "log_doctor/settings/set_auto_investigate"
WS_SCAN_NOW = "log_doctor/settings/scan_now"
WS_CLEAR_HISTORY = "log_doctor/settings/clear_history"


@callback
def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_get)
    websocket_api.async_register_command(hass, websocket_update)
    websocket_api.async_register_command(hass, websocket_set_auto_investigate)
    websocket_api.async_register_command(hass, websocket_scan_now)
    websocket_api.async_register_command(hass, websocket_clear_history)


def _entry(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int
) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg_id, "not_loaded", "WP Log Doctor isn't set up")
        return None
    return entries[0]


def _coordinator(hass: HomeAssistant, entry: ConfigEntry) -> Any:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id)


def _current_options(entry: ConfigEntry) -> dict[str, Any]:
    return {**entry.data, **entry.options}


def _mobile_devices(hass: HomeAssistant) -> list[dict[str, str]]:
    registry = dr.async_get(hass)
    devices = []
    for mobile_entry in hass.config_entries.async_entries("mobile_app"):
        for device in dr.async_entries_for_config_entry(registry, mobile_entry.entry_id):
            devices.append({"id": device.id, "name": device.name_by_user or device.name or device.id})
    return sorted(devices, key=lambda d: d["name"].lower())


def _status(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = _coordinator(hass, entry)
    status: dict[str, Any] = {
        "loaded": coordinator is not None,
        "reviews_dir": str(reviews_dir(hass)),
        "failure_log": str(failure_log_path(hass)),
    }
    if coordinator is None:
        return status
    last_scan = coordinator.store.data.last_scan
    status["last_scan"] = last_scan.isoformat() if last_scan else None
    summary = coordinator.store.data.last_summary
    status["summary"] = summary
    if summary:
        status["anomalies"] = summary.get("anomalies")
        status["new"] = summary.get("new")
        status["report_file"] = summary.get("report_file")
    status["auto_investigate"] = coordinator.store.data.auto_investigate
    status["openai_configured"] = bool(coordinator.openai_api_key)
    return status


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_GET})
@callback
def websocket_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (entry := _entry(hass, connection, msg["id"])) is None:
        return
    options = _current_options(entry)
    # Settings added in later versions aren't stored on older installs yet;
    # show their defaults, as the Configure dialog would.
    for key in _build_schema(hass, options).schema:
        if key not in options and key.default is not vol.UNDEFINED:
            options[str(key)] = key.default()
    api_key_set = bool(options.pop(CONF_OPENAI_API_KEY, None))
    connection.send_result(
        msg["id"],
        {
            "options": options,
            "openai_api_key_set": api_key_set,
            "severity_levels": SEVERITY_LEVELS,
            "default_log_path": hass.config.path("home-assistant.log"),
            "mobile_devices": _mobile_devices(hass),
            "notify_services": sorted(hass.services.async_services().get("notify", {})),
            "status": _status(hass, entry),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_UPDATE,
        vol.Required("options"): dict,
        vol.Optional("clear_openai_api_key", default=False): bool,
    }
)
@callback
def websocket_update(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (entry := _entry(hass, connection, msg["id"])) is None:
        return
    current = _current_options(entry)
    new = {**current, **msg["options"]}
    if msg["clear_openai_api_key"]:
        new[CONF_OPENAI_API_KEY] = ""
    # An optional device picked as "none" is left out, as the Configure
    # dialog does, then stored as explicitly empty (see config_flow.py).
    device = new.pop(CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE, None) or None
    if device is not None:
        new[CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE] = device
    try:
        validated = _build_schema(hass, current)(new)
    except vol.Invalid as err:
        path = " → ".join(str(p) for p in err.path) if err.path else ""
        connection.send_error(
            msg["id"], "invalid_format", f"{path}: {err.msg}" if path else str(err)
        )
        return
    validated.setdefault(CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE, None)
    changed = validated != current
    if changed:
        # Same as saving the Configure dialog: stored as options, and the
        # entry's update listener reloads the integration.
        hass.config_entries.async_update_entry(entry, options=validated)
    connection.send_result(msg["id"], {"changed": changed})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): WS_SET_AUTO_INVESTIGATE, vol.Required("enabled"): bool}
)
@websocket_api.async_response
async def websocket_set_auto_investigate(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (entry := _entry(hass, connection, msg["id"])) is None:
        return
    # Go through the switch entity when it exists, so its state (and
    # anything automating on it) stays in step with the page.
    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_auto_investigate"
    )
    if entity_id and hass.states.get(entity_id) is not None:
        await hass.services.async_call(
            "switch",
            "turn_on" if msg["enabled"] else "turn_off",
            {"entity_id": entity_id},
            blocking=True,
            context=connection.context(msg),
        )
    elif (coordinator := _coordinator(hass, entry)) is not None:
        coordinator.store.data.auto_investigate = msg["enabled"]
        await coordinator.store.async_save()
    else:
        connection.send_error(msg["id"], "not_loaded", "WP Log Doctor isn't loaded")
        return
    connection.send_result(msg["id"], {"enabled": msg["enabled"]})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_SCAN_NOW})
@websocket_api.async_response
async def websocket_scan_now(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (entry := _entry(hass, connection, msg["id"])) is None:
        return
    if (coordinator := _coordinator(hass, entry)) is None:
        connection.send_error(msg["id"], "not_loaded", "WP Log Doctor isn't loaded")
        return
    await coordinator.async_refresh()
    connection.send_result(msg["id"], {"status": _status(hass, entry)})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_CLEAR_HISTORY})
@websocket_api.async_response
async def websocket_clear_history(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (entry := _entry(hass, connection, msg["id"])) is None:
        return
    if (coordinator := _coordinator(hass, entry)) is None:
        connection.send_error(msg["id"], "not_loaded", "WP Log Doctor isn't loaded")
        return
    await coordinator.store.async_clear_history()
    connection.send_result(msg["id"])
