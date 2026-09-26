"""Registers the Log Doctor sidebar panel.

The panel is a single self-contained web component (frontend/), served as
a static file and added to the sidebar for admins only, with "Log
review", "Automation failures", "Devices & integrations" and "Backups"
views. It talks to Home Assistant through the WebSocket commands in
websocket_api.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.core import HomeAssistant

from . import websocket_api
from .const import (
    DATA_PANEL_STATIC_REGISTERED,
    LEGACY_FAILURES_PANEL_URL_PATH,
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_MODULE_FILE,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_URL_PATH,
)

_FRONTEND_DIR = Path(__file__).parent / "frontend"


def _version() -> str:
    # Cache-busts the panel's JS on every release.
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    return manifest.get("version", "0")


async def async_register_panel(hass: HomeAssistant) -> None:
    # Static paths and WebSocket commands can't be unregistered, so they're
    # added once per Home Assistant run; the panel itself is re-added on
    # every (re)load and removed on unload.
    if not hass.data.get(DATA_PANEL_STATIC_REGISTERED):
        await _async_register_static(hass)
        websocket_api.async_setup(hass)
        hass.data[DATA_PANEL_STATIC_REGISTERED] = True

    version = await hass.async_add_executor_job(_version)
    module_url = f"{PANEL_STATIC_URL}/{PANEL_MODULE_FILE}?v={version}"
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=module_url,
        embed_iframe=False,
        require_admin=True,
    )
    # No sidebar title/icon: reachable by URL only, for old links.
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=LEGACY_FAILURES_PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        module_url=module_url,
        embed_iframe=False,
        require_admin=True,
        config={"view": "failures"},
    )


async def _async_register_static(hass: HomeAssistant) -> None:
    try:
        from homeassistant.components.http import StaticPathConfig
    except ImportError:  # Home Assistant before 2024.7
        hass.http.register_static_path(PANEL_STATIC_URL, str(_FRONTEND_DIR), False)
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_STATIC_URL, str(_FRONTEND_DIR), False)]
    )


def async_remove_panel(hass: HomeAssistant) -> None:
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
    frontend.async_remove_panel(hass, LEGACY_FAILURES_PANEL_URL_PATH)
