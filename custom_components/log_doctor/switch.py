"""Switch platform for Log Doctor - toggle for the automatic investigation
stage that otherwise runs after every scan.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_NAME, DOMAIN
from .coordinator import LogDoctorCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: LogDoctorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LogDoctorAutoInvestigateSwitch(coordinator, entry)])


class LogDoctorAutoInvestigateSwitch(SwitchEntity):
    """Turns the automatic investigation stage on or off.

    Only has any effect when an OpenAI API key is configured - without one,
    investigation never runs regardless of this switch. Investigating isn't
    free (one OpenAI call per anomaly, every scan), so this lets you keep
    the key configured but pause automatic runs without clearing it. State
    persists across restarts via the same store as scan history.
    """

    _attr_has_entity_name = True
    _attr_name = "Auto-investigate"
    _attr_icon = "mdi:auto-fix"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: LogDoctorCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_auto_investigate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer="hass_logdoctor",
            model=DEVICE_NAME,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return self._coordinator.store.data.auto_investigate

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        self._coordinator.store.data.auto_investigate = value
        await self._coordinator.store.async_save()
        self.async_write_ha_state()
