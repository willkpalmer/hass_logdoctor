"""Checks devices, integrations and Repairs every few minutes.

Feeds the "Devices & integrations" view of the Log Doctor panel (see
health_store.py for how each problem is tracked). Like the rest of Log
Doctor it only reports; it never reloads, restarts or changes anything.

What counts as a problem:

- offline - a device (or an entity with no device) whose entities have
  been unavailable for at least the configured time. Diagnostic and config
  entities alone don't count, so a device whose main entities work isn't
  reported because, say, its firmware-update entity is unavailable. Entities
  of integrations that failed to load are left to the integration check,
  so one broken integration isn't also reported as dozens of devices.
- integration - a config entry that failed to set up, is retrying setup,
  failed to migrate or failed to unload (disabled ones aren't checked).
- repair - an active issue in Home Assistant's Repairs that hasn't been
  ignored there.

Home Assistant resets every entity's "last changed" time on restart, so
right after a restart a device that was already offline only counts from
the restart; its record keeps the original "since" time if it was already
being tracked.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_UNAVAILABLE
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .health_store import HealthStore

_LOGGER = logging.getLogger(__name__)

CHECK_INTERVAL = timedelta(minutes=5)
# First check after Home Assistant has started, giving integrations and
# devices time to come up.
FIRST_CHECK_DELAY = 300

# Most entity IDs listed per problem.
_MAX_ENTITIES = 25

_BAD_ENTRY_STATES = {
    ConfigEntryState.SETUP_ERROR: "Failed to set up",
    ConfigEntryState.SETUP_RETRY: "Retrying setup",
    ConfigEntryState.MIGRATION_ERROR: "Migration failed",
    ConfigEntryState.FAILED_UNLOAD: "Failed to unload",
}


class HealthMonitor:
    def __init__(
        self,
        hass: HomeAssistant,
        store: HealthStore,
        *,
        offline_after: timedelta,
    ) -> None:
        self.hass = hass
        self.store = store
        self.offline_after = offline_after
        self._unsubs: list[Callable[[], None]] = []

    @callback
    def async_start(self) -> Callable[[], None]:
        @callback
        def _schedule_first(_event: Any = None) -> None:
            self._unsubs.append(
                async_call_later(self.hass, FIRST_CHECK_DELAY, self._async_check_later)
            )

        if self.hass.state is CoreState.running:
            _schedule_first()
        else:
            self._unsubs.append(
                self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule_first)
            )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_check_later, CHECK_INTERVAL)
        )
        return self._async_stop

    @callback
    def _async_stop(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except ValueError:
                pass  # a listen_once that already fired
        self._unsubs = []

    async def _async_check_later(self, _now: Any = None) -> None:
        await self.async_check()

    async def async_check(self) -> None:
        try:
            current: dict[str, dict[str, Any]] = {}
            current.update(self._integration_issues())
            current.update(self._device_issues())
            current.update(await self._repair_issues())
            await self.store.async_update(current)
        except Exception:  # noqa: BLE001 - never let a check break anything
            _LOGGER.exception("Log Doctor's device and integration check failed")

    # -- integrations -----------------------------------------------------

    def _integration_issues(self) -> dict[str, dict[str, Any]]:
        issues = {}
        for entry in self.hass.config_entries.async_entries():
            if entry.disabled_by or entry.state not in _BAD_ENTRY_STATES:
                continue
            detail = _BAD_ENTRY_STATES[entry.state]
            if entry.reason:
                detail += f": {entry.reason}"
            issues[f"integration:{entry.entry_id}"] = {
                "kind": "integration",
                "name": entry.title or entry.domain,
                "sub": entry.domain,
                "detail": detail,
                "link": f"/config/integrations/integration/{entry.domain}",
                "entities": [],
            }
        return issues

    # -- devices ----------------------------------------------------------

    def _device_issues(self) -> dict[str, dict[str, Any]]:
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        now = dt_util.utcnow()

        unavailable: dict[str, list[tuple[str, datetime]]] = {}

        for state in self.hass.states.async_all():
            entry = ent_reg.async_get(state.entity_id)
            if entry is not None and entry.config_entry_id:
                config_entry = self.hass.config_entries.async_get_entry(entry.config_entry_id)
                if config_entry is not None and config_entry.state is not ConfigEntryState.LOADED:
                    continue  # reported as an integration problem instead
            group = entry.device_id if entry is not None and entry.device_id else state.entity_id

            if state.state == STATE_UNAVAILABLE:
                if entry is not None and entry.entity_category is not None:
                    continue  # diagnostic/config entities alone don't count
                unavailable.setdefault(group, []).append((state.entity_id, state.last_changed))

        issues: dict[str, dict[str, Any]] = {}

        for group, entities in unavailable.items():
            since = min(changed for _, changed in entities)
            if now - since < self.offline_after:
                continue
            name, sub, link, device = self._describe(group, dev_reg, area_reg)
            detail = "Offline"
            if device is not None:
                primary = [
                    e for e in er.async_entries_for_device(ent_reg, device.id)
                    if e.entity_category is None and not e.disabled_by
                    and self.hass.states.get(e.entity_id) is not None
                ]
                if len(entities) < len(primary):
                    detail = f"{len(entities)} of {len(primary)} entities unavailable"
            issues[f"offline:{group}"] = {
                "kind": "offline",
                "name": name,
                "sub": sub,
                "detail": detail,
                "since": since.isoformat(),
                "link": link,
                "entities": sorted(e for e, _ in entities)[:_MAX_ENTITIES],
            }

        return issues

    def _describe(
        self, group: str, dev_reg: dr.DeviceRegistry, area_reg: ar.AreaRegistry
    ) -> tuple[str, str, str, dr.DeviceEntry | None]:
        """Name, area/integration line and link for a device or entity."""
        device = dev_reg.async_get(group)
        if device is not None:
            name = device.name_by_user or device.name or group
            parts = []
            if device.area_id and (area := area_reg.async_get_area(device.area_id)):
                parts.append(area.name)
            domains = sorted(
                {
                    ce.domain
                    for entry_id in device.config_entries
                    if (ce := self.hass.config_entries.async_get_entry(entry_id))
                }
            )
            parts.extend(domains)
            return name, " · ".join(parts), f"/config/devices/device/{device.id}", device
        state = self.hass.states.get(group)
        name = (state and state.attributes.get("friendly_name")) or group
        return name, group, f"/history?entity_id={group}", None

    # -- repairs ----------------------------------------------------------

    async def _repair_issues(self) -> dict[str, dict[str, Any]]:
        registry = ir.async_get(self.hass)
        found = [
            issue
            for issue in registry.issues.values()
            if issue.active and not issue.dismissed_version
        ]
        if not found:
            return {}
        language = self.hass.config.language or "en"
        try:
            translations = await async_get_translations(
                self.hass, language, "issues", {issue.domain for issue in found}
            )
        except Exception:  # noqa: BLE001 - fall back to raw keys
            translations = {}
        issues = {}
        for issue in found:
            title = issue.translation_key or issue.issue_id
            if issue.translation_key:
                template = translations.get(
                    f"component.{issue.domain}.issues.{issue.translation_key}.title"
                )
                if template:
                    try:
                        title = template.format(**(issue.translation_placeholders or {}))
                    except (KeyError, IndexError, ValueError):
                        title = template
            severity = issue.severity.value.capitalize() if issue.severity else "Issue"
            detail = severity
            if issue.breaks_in_ha_version:
                detail += f" · breaks in {issue.breaks_in_ha_version}"
            issues[f"repair:{issue.domain}:{issue.issue_id}"] = {
                "kind": "repair",
                "name": title,
                "sub": issue.domain,
                "detail": detail,
                "since": issue.created.isoformat() if issue.created else None,
                "link": "/config/repairs",
                "entities": [],
            }
        return issues

