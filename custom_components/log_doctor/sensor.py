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
    ATTR_LAST_REPORT,
    ATTR_LAST_SCAN,
    ATTR_NEW_COUNT,
    ATTR_RECURRING_COUNT,
    ATTR_REPORT_FILE,
    ATTR_REPORTS_DIR,
    DEVICE_NAME,
    DOMAIN,
    MAX_REPORT_ATTR_CHARS,
    REPORTS_DIR_NAME,
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
            name=DEVICE_NAME,
            manufacturer="hass_logdoctor",
            model=DEVICE_NAME,
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
        report_text = result.report_markdown
        truncated = len(report_text) > MAX_REPORT_ATTR_CHARS
        if truncated:
            report_text = report_text[:MAX_REPORT_ATTR_CHARS] + "\n\n… (truncated, see report_file for the full report)"
        return {
            ATTR_ANOMALIES: anomalies,
            ATTR_NEW_COUNT: len(result.new_reports),
            ATTR_RECURRING_COUNT: len(result.recurring_reports),
            ATTR_LAST_SCAN: result.scanned_at.isoformat(),
            "lines_scanned": result.lines_scanned,
            "known_issue_matches": result.known_issue_matches,
            ATTR_LAST_REPORT: report_text,
            ATTR_REPORT_FILE: result.report_file,
            ATTR_REPORTS_DIR: self.coordinator.hass.config.path(REPORTS_DIR_NAME),
            "sources_checked": [
                {"name": s.name, "lines_read": s.lines_read, "ok": s.ok, "note": s.note}
                for s in result.sources_checked
            ],
        }
