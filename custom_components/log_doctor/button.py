"""Button platform for Log Doctor - manual 'scan now' trigger."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import LogDoctorCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: LogDoctorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LogDoctorScanNowButton(coordinator, entry)])


class LogDoctorScanNowButton(ButtonEntity):
    """Triggers an immediate log scan, outside the daily schedule."""

    _attr_has_entity_name = True
    _attr_name = "Scan now"
    _attr_icon = "mdi:magnify-scan"

    def __init__(self, coordinator: LogDoctorCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_scan_now"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Log Doctor",
            manufacturer="hass_logdoctor",
            model="Log Doctor",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        await self._coordinator.async_request_refresh()
