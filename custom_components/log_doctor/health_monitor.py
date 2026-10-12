"""Checks devices, integrations and Repairs every few minutes.

Feeds the "Devices & integrations" view of the Log Doctor panel (see
health_store.py for how each problem is tracked). Like the rest of Log
Doctor it only reports; it never reloads, restarts or changes anything.

What counts as a problem:

- offline - a device (or an entity with no device) whose main entities
  have all been unavailable for at least the configured time. Diagnostic
  and config entities don't decide this.
- unavailable - a device (or an entity with no device) with some
  unavailable entities, diagnostic and config ones included, that isn't
  offline as a whole, so there's a row for every device with entities to
  tidy up. Entities the integration no longer provides (restored by Home
  Assistant as unavailable) are counted straight away and called out.
- integration - a config entry that failed to set up, is retrying setup,
  failed to migrate or failed to unload (disabled ones aren't checked);
  one that hasn't been loaded at all (its integration failed to set up,
  so its entries were never tried), two checks running; and one of whose
  platforms (sensor, light, ...) failed to set up while the rest loaded.
  Each lists the devices affected and the log messages about it from the
  Log review (see setup_failures.py), the setup failure first.
- repair - an active issue in Home Assistant's Repairs that hasn't been
  ignored there.
- flapping - a device (or an entity with no device) that keeps going
  unavailable and coming back: at least the configured number of times
  within the configured window (see flapping.py), however briefly.

Entities of integrations that failed to load are left to the integration
check, so one broken integration isn't also reported as dozens of devices.
Entities of a platform that failed to load are still counted on their
device, but as "not loaded" rather than "no longer provided": they're
still there, Home Assistant just couldn't set them up.

Home Assistant resets every entity's "last changed" time on restart, so
right after a restart a device that was already offline only counts from
the restart; its record keeps the original "since" time if it was already
being tracked.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_UNAVAILABLE
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity_platform import async_get_platforms
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.translation import async_get_translations
from homeassistant.loader import async_get_integrations
from homeassistant.util import dt as dt_util

from .anomaly_store import AnomalyStore
from .flapping import FlapTracker
from .health_store import HealthStore

_LOGGER = logging.getLogger(__name__)

CHECK_INTERVAL = timedelta(minutes=5)
# First check after Home Assistant has started, giving integrations and
# devices time to come up.
FIRST_CHECK_DELAY = 300

# Most entity IDs listed per problem.
_MAX_ENTITIES = 25
# Most devices and log messages listed per integration problem.
_MAX_DEVICES = 25
_MAX_MESSAGES = 5

_BAD_ENTRY_STATES = {
    ConfigEntryState.SETUP_ERROR: "Failed to set up",
    ConfigEntryState.SETUP_RETRY: "Retrying setup",
    ConfigEntryState.MIGRATION_ERROR: "Migration failed",
    ConfigEntryState.FAILED_UNLOAD: "Failed to unload",
}


# Integration types that are part of Home Assistant itself rather than a
# connection to a device or service: system (automation, script, person,
# zone, ...), helper (input_boolean, template, group, timer, ...) and
# entity (scene, light, ...). Quality scale "internal" isn't used: it also
# covers integrations like Mobile App.
_CORE_TYPES = {"system", "helper", "entity"}


def _is_core(integration: Any) -> bool:
    """Whether an integration is one of Home Assistant's own parts."""
    return (
        bool(getattr(integration, "is_built_in", False))
        and getattr(integration, "integration_type", None) in _CORE_TYPES
    )


class HealthMonitor:
    def __init__(
        self,
        hass: HomeAssistant,
        store: HealthStore,
        *,
        offline_after: timedelta,
        flaps: FlapTracker | None = None,
        anomalies: AnomalyStore | None = None,
    ) -> None:
        self.hass = hass
        self.store = store
        self.offline_after = offline_after
        self.flaps = flaps
        # The Log review's anomalies, for each integration problem's messages.
        self.anomalies = anomalies
        # Config entries found not loaded by the last check (see
        # _integration_issues).
        self._not_loaded: set[str] = set()
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
            current.update(self._flap_issues())
            self._add_log_messages(current)
            await self._name_integrations(current)
            await self.store.async_update(current)
        except Exception:  # noqa: BLE001 - never let a check break anything
            _LOGGER.exception("Log Doctor's device and integration check failed")

    # -- integrations -----------------------------------------------------

    def _integration_issues(self) -> dict[str, dict[str, Any]]:
        issues = {}
        dev_reg = dr.async_get(self.hass)
        ent_reg = er.async_get(self.hass)
        not_loaded: set[str] = set()
        for entry in self.hass.config_entries.async_entries():
            if entry.disabled_by or entry.source == SOURCE_IGNORE:
                continue
            if entry.state is ConfigEntryState.NOT_LOADED:
                # Never set up - its integration failed to - or being
                # reloaded right now: only reported if it still isn't at the
                # next check.
                not_loaded.add(entry.entry_id)
                if entry.entry_id not in self._not_loaded or self.hass.state is not CoreState.running:
                    continue
                detail = "Not loaded"
            elif entry.state in _BAD_ENTRY_STATES:
                detail = _BAD_ENTRY_STATES[entry.state]
                if entry.reason:
                    detail += f": {entry.reason}"
            else:
                continue
            devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
            entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
            issues[f"integration:{entry.entry_id}"] = {
                "kind": "integration",
                "name": entry.title or entry.domain,
                "sub": entry.domain,
                "integration": entry.domain,
                "detail": detail + _affected(devices),
                "link": f"/config/integrations/integration/{entry.domain}",
                "entities": sorted(e.entity_id for e in entities if not e.disabled_by)[:_MAX_ENTITIES],
                "devices": _device_names(devices),
            }
        self._not_loaded = not_loaded
        issues.update(self._platform_issues())
        return issues

    def _failed_platforms(self) -> dict[str, set[str]]:
        """{config entry id: entity domains whose platform didn't set up}.

        Home Assistant keeps an entry's platforms (sensor, light, ...) even
        when their setup failed or is still being retried; only loaded
        entries are looked at.
        """
        failed: dict[str, set[str]] = {}
        for entry in self.hass.config_entries.async_entries():
            if entry.state is not ConfigEntryState.LOADED or entry.disabled_by:
                continue
            for platform in async_get_platforms(self.hass, entry.domain):
                if platform.config_entry is not entry:
                    continue
                if not getattr(platform, "_setup_complete", True):
                    failed.setdefault(entry.entry_id, set()).add(platform.domain)
        return failed

    def _platform_issues(self) -> dict[str, dict[str, Any]]:
        issues = {}
        dev_reg = dr.async_get(self.hass)
        ent_reg = er.async_get(self.hass)
        for entry_id, domains in self._failed_platforms().items():
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                continue
            entities = [
                e for e in er.async_entries_for_config_entry(ent_reg, entry_id)
                if e.domain in domains and not e.disabled_by
            ]
            devices = [
                device for device_id in sorted({e.device_id for e in entities if e.device_id})
                if (device := dev_reg.async_get(device_id)) is not None
            ]
            names = ", ".join(sorted(domains))
            issues[f"platform:{entry_id}"] = {
                "kind": "integration",
                "name": entry.title or entry.domain,
                "sub": entry.domain,
                "integration": entry.domain,
                "detail": f"{names} platform{'s' if len(domains) > 1 else ''} not loaded" + _affected(devices),
                "link": f"/config/integrations/integration/{entry.domain}",
                "entities": sorted(e.entity_id for e in entities)[:_MAX_ENTITIES],
                "devices": _device_names(devices),
            }
        return issues

    def _add_log_messages(self, issues: dict[str, dict[str, Any]]) -> None:
        """Each integration problem's messages on the Log review.

        Setup failures about the integration (see setup_failures.py) first,
        then its own warnings and errors, newest first.
        """
        if self.anomalies is None:
            return
        records = self.anomalies.records
        for issue in issues.values():
            domain = issue.get("integration")
            if issue.get("kind") != "integration" or not domain:
                continue
            own = (f"homeassistant.components.{domain}", f"custom_components.{domain}")
            found = [
                r for r in records
                if r.get("setup_domain") == domain
                or any(r.get("logger", "") == p or r.get("logger", "").startswith(p + ".") for p in own)
            ]
            found.sort(key=lambda r: r.get("last_seen") or "", reverse=True)
            found.sort(key=lambda r: not r.get("setup_domain"))
            issue["log_messages"] = [
                {
                    "id": r["id"],
                    "level": r.get("level"),
                    "logger": r.get("logger"),
                    "message": (r.get("message") or "")[:300],
                    "category": r.get("category") or "operational",
                    "last_logged": r.get("last_logged") or r.get("last_seen"),
                    "setup": bool(r.get("setup_domain")),
                }
                for r in found[:_MAX_MESSAGES]
            ]

    # -- devices ----------------------------------------------------------

    def _device_issues(self) -> dict[str, dict[str, Any]]:
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        now = dt_util.utcnow()

        failed_platforms = self._failed_platforms()
        # group -> [(entity_id, last_changed, primary, restored, not_loaded)]
        unavailable: dict[str, list[tuple[str, datetime, bool, bool, bool]]] = {}

        for state in self.hass.states.async_all():
            if state.state != STATE_UNAVAILABLE:
                continue
            entry = ent_reg.async_get(state.entity_id)
            if entry is not None and entry.config_entry_id:
                config_entry = self.hass.config_entries.async_get_entry(entry.config_entry_id)
                if config_entry is not None and config_entry.state is not ConfigEntryState.LOADED:
                    continue  # reported as an integration problem instead
            group = entry.device_id if entry is not None and entry.device_id else state.entity_id
            primary = entry is None or entry.entity_category is None
            # Home Assistant restores a registered entity its integration
            # no longer provides as unavailable, with "restored": true.
            restored = bool(state.attributes.get("restored"))
            # Its platform failed to set up: still there, just not loaded.
            not_loaded = (
                entry is not None
                and entry.config_entry_id is not None
                and entry.domain in failed_platforms.get(entry.config_entry_id, ())
            )
            unavailable.setdefault(group, []).append(
                (state.entity_id, state.last_changed, primary, restored and not not_loaded, not_loaded)
            )

        issues: dict[str, dict[str, Any]] = {}

        for group, entities in unavailable.items():
            # Entities no longer provided are reported straight away; others
            # once they've been unavailable for the configured time.
            counted = [
                e for e in entities if e[3] or e[4] or now - e[1] >= self.offline_after
            ]
            if not counted:
                continue
            since = min(e[1] for e in counted)
            gone = sum(1 for e in counted if e[3])
            not_loaded = sum(1 for e in counted if e[4])
            name, sub, link, device = self._describe(group, dev_reg, area_reg)
            integration = self._device_integration(device, group, ent_reg)
            if device is not None:
                present = [
                    e for e in er.async_entries_for_device(ent_reg, device.id)
                    if not e.disabled_by and self.hass.states.get(e.entity_id) is not None
                ]
                primary = [e for e in present if e.entity_category is None]
                primary_down = sum(1 for e in counted if e[2])
                offline = bool(primary) and primary_down >= len(primary)
                if offline:
                    detail = "Offline"
                else:
                    detail = f"{len(counted)} of {len(present)} entities unavailable"
            else:
                offline = counted[0][2] and not gone and not not_loaded
                detail = "Offline" if offline else "Unavailable"
            if gone:
                detail += (
                    " · no longer provided" if device is None
                    else f" · {gone} no longer provided"
                )
            if not_loaded:
                # See the integration's "platform not loaded" problem.
                detail += (
                    " · not loaded (integration problem)" if device is None
                    else f" · {not_loaded} not loaded (integration problem)"
                )
            issues[f"offline:{group}"] = {
                "kind": "offline" if offline else "unavailable",
                "name": name,
                "sub": sub,
                "integration": integration,
                "detail": detail,
                "since": since.isoformat(),
                "link": link,
                "entities": sorted(e[0] for e in counted)[:_MAX_ENTITIES],
            }

        return issues

    def _flap_issues(self) -> dict[str, dict[str, Any]]:
        if self.flaps is None:
            return {}
        flapping = self.flaps.flapping()
        if not flapping:
            return {}
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        hours = self.flaps.window.total_seconds() / 3600
        window = f"{hours:g} hour{'' if hours == 1 else 's'}"
        issues: dict[str, dict[str, Any]] = {}
        for group, (times, entities) in flapping.items():
            if dev_reg.async_get(group) is None and self.hass.states.get(group) is None:
                continue  # removed since
            name, sub, link, device = self._describe(group, dev_reg, area_reg)
            last = max(times).astimezone(dt_util.get_default_time_zone()) if times else None
            detail = f"Unavailable {len(times)} times in the last {window}"
            if last is not None:
                detail += f" · last {last.strftime('%H:%M')}"
            issues[f"flapping:{group}"] = {
                "kind": "flapping",
                "name": name,
                "sub": sub,
                "integration": self._device_integration(device, group, ent_reg),
                "detail": detail,
                "since": min(times).isoformat() if times else None,
                "link": link,
                "entities": sorted(entities)[:_MAX_ENTITIES],
                "flaps": len(times),
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

    def _device_integration(
        self, device: dr.DeviceEntry | None, group: str, ent_reg: er.EntityRegistry
    ) -> str | None:
        """The integration (domain) a device or stand-alone entity belongs to."""
        if device is not None:
            primary = getattr(device, "primary_config_entry", None)
            entry_ids = [primary] if primary else sorted(device.config_entries)
            for entry_id in entry_ids:
                if entry_id and (entry := self.hass.config_entries.async_get_entry(entry_id)):
                    return entry.domain
            return None
        entity = ent_reg.async_get(group)
        return entity.platform if entity is not None else None

    async def _name_integrations(self, issues: dict[str, dict[str, Any]]) -> None:
        """Adds each issue's integration display name (e.g. "Philips Hue"), used to group the list.

        Also marks Home Assistant's own parts - automations, scripts,
        helpers, templates and the like - as integration_core, so the panel
        can list them before the integrations of actual devices and services.
        """
        domains = {issue["integration"] for issue in issues.values() if issue.get("integration")}
        names: dict[str, str] = {}
        core: set[str] = set()
        if domains:
            try:
                found = await async_get_integrations(self.hass, domains)
            except Exception:  # noqa: BLE001 - fall back to domains
                found = {}
            for domain in domains:
                integration = found.get(domain)
                if integration is None or isinstance(integration, Exception):
                    names[domain] = domain
                    continue
                names[domain] = integration.name
                if _is_core(integration):
                    core.add(domain)
        for issue in issues.values():
            domain = issue.get("integration")
            issue["integration_name"] = names.get(domain) if domain else None
            issue["integration_core"] = domain in core

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
                "integration": issue.domain,
                "detail": detail,
                "since": issue.created.isoformat() if issue.created else None,
                "link": "/config/repairs",
                "entities": [],
            }
        return issues



def _affected(devices: list[dr.DeviceEntry]) -> str:
    if not devices:
        return ""
    return f" · {len(devices)} device{'' if len(devices) == 1 else 's'} affected"


def _device_names(devices: list[dr.DeviceEntry]) -> list[str]:
    return sorted(d.name_by_user or d.name or d.id for d in devices)[:_MAX_DEVICES]
