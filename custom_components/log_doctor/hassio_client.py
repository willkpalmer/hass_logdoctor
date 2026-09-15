"""Optional access to Supervisor/Host/add-on logs on HAOS and Supervised installs.

Home Assistant Core cannot read Supervisor, Host, or add-on logs as plain
files the way it can read its own `home-assistant.log` - those only exist
inside separate containers/journald and are reachable only through the
Supervisor's internal API. This is the same set of sources shown in the
dropdown on Settings -> System -> Logs.

This talks to that API directly using the `SUPERVISOR` and
`SUPERVISOR_TOKEN` environment variables Supervisor injects into the Core
container - the same mechanism Home Assistant's own built-in `hassio`
integration uses internally. On a Core-only install (Home Assistant
Container/Core, venv) those variables don't exist, `supervisor_available()`
returns False, and every other function here is a no-op.
"""
from __future__ import annotations

import asyncio
import logging
import os

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# Fixed Supervisor-managed log sources, matching the dropdown on
# Settings -> System -> Logs. "core" is deliberately excluded - Log Doctor
# already reads the full home-assistant.log file directly, which is a more
# complete history than the bounded tail this endpoint returns.
_SYSTEM_SOURCES = [
    ("supervisor/logs", "Supervisor"),
    ("host/logs", "Host"),
    ("dns/logs", "DNS"),
    ("audio/logs", "Audio"),
    ("cli/logs", "CLI"),
    ("multicast/logs", "Multicast"),
]


def supervisor_available() -> bool:
    """True on HAOS/Supervised installs where the Supervisor API is reachable."""
    return bool(os.environ.get("SUPERVISOR")) and bool(os.environ.get("SUPERVISOR_TOKEN"))


def _base_url() -> str:
    return f"http://{os.environ.get('SUPERVISOR', 'supervisor')}"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ.get('SUPERVISOR_TOKEN', '')}"}


async def async_fetch_log_text(hass: HomeAssistant, log_path: str) -> str | None:
    """Fetch plain-text logs for one Supervisor-managed source, e.g. 'host/logs'."""
    if not supervisor_available():
        return None
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{_base_url()}/{log_path}",
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                _LOGGER.debug("Log fetch for %s returned HTTP %s", log_path, resp.status)
                return None
            return await resp.text(errors="replace")
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("Could not fetch logs for %s: %s", log_path, err)
        return None


async def async_list_addon_sources(hass: HomeAssistant) -> list[tuple[str, str]]:
    """Return (log_path, display_name) for every installed add-on."""
    if not supervisor_available():
        return []
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{_base_url()}/addons",
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return []
            payload = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("Could not list add-ons: %s", err)
        return []

    addons = payload.get("data", {}).get("addons", [])
    return [
        (f"addons/{addon['slug']}/logs", addon.get("name") or addon["slug"])
        for addon in addons
        if addon.get("slug")
    ]


async def async_list_all_sources(hass: HomeAssistant) -> list[tuple[str, str]]:
    """Every Supervisor-managed log source Log Doctor should check: system + add-ons."""
    if not supervisor_available():
        return []
    addon_sources = await async_list_addon_sources(hass)
    return _SYSTEM_SOURCES + addon_sources


async def async_fetch_all_logs(
    hass: HomeAssistant, sources: list[tuple[str, str]]
) -> dict[str, tuple[str, str | None]]:
    """Fetch all given sources concurrently.

    Returns {log_path: (display_name, text_or_None)}.
    """
    if not sources:
        return {}
    texts = await asyncio.gather(
        *(async_fetch_log_text(hass, path) for path, _name in sources)
    )
    return {
        path: (name, text) for (path, name), text in zip(sources, texts, strict=True)
    }
