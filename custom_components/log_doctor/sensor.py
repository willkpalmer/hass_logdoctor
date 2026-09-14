"""Sensor platform for Log Doctor."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ANOMALIES,
    ATTR_LAST_SCAN,
    ATTR_NEW_COUNT,
    ATTR_RECURRING_COUNT,
    DOMAIN,
)
from .coordinator import LogDoctorCoordinator
from .digest import ScanResult

_MAX_ATTR_ANOMALIES = 50


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: LogDoctorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LogDoctorAnomalySensor(coordinator, entry)])


class LogDoctorAnomalySensor(CoordinatorEntity[LogDoctorCoordinator], SensorEntity):
    """Reports the number of outstanding log anomalies found in the last scan."""

    _attr_has_entity_name = True
    _attr_name = "Anomalies"
    _attr_icon = "mdi:file-search-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: LogDoctorCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_anomalies"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Log Doctor",
            manufacturer="hass_logreview",
            model="Log Doctor",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int:
        result: ScanResult | None = self.coordinator.data
        return len(result.reports) if result else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result: ScanResult | None = self.coordinator.data
        if result is None:
            return {}
        anomalies = [r.as_attr_dict() for r in result.reports[:_MAX_ATTR_ANOMALIES]]
        return {
            ATTR_ANOMALIES: anomalies,
            ATTR_NEW_COUNT: len(result.new_reports),
            ATTR_RECURRING_COUNT: len(result.recurring_reports),
            ATTR_LAST_SCAN: result.scanned_at.isoformat(),
            "lines_scanned": result.lines_scanned,
        }
