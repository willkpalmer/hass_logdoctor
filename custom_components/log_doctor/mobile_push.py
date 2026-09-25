"""Helpers for pushing notifications to a Mobile App (Companion app) device."""
from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import slugify


@callback
def resolve_mobile_app_notify_service(hass: HomeAssistant, device_id: str) -> str | None:
    """Resolve a Mobile App device to its notify.mobile_app_* service name.

    The Mobile App integration names each phone's notify service after the
    device name the app registered with (not any name the device was later
    renamed to in the UI), i.e. "mobile_app_<slug of that name>" - the same
    name shown in Developer Tools > Actions. Returns None if the device is
    gone or has no notify service (e.g. notifications aren't set up).
    """
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != "mobile_app":
            continue
        device_name = entry.data.get("device_name")
        if not device_name:
            continue
        service = slugify(f"mobile_app_{device_name}")
        if hass.services.has_service("notify", service):
            return service
    return None
