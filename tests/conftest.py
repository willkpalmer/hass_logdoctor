"""Shared fixtures: a bare Home Assistant instance in a temporary config dir.

These tests use Home Assistant itself (pip install homeassistant) but not
pytest-homeassistant-custom-component: the parts tested only need a hass
object for storage, the event bus and the state machine.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homeassistant import config_entries, loader  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import area_registry as ar  # noqa: E402
from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.helpers import frame  # noqa: E402


@pytest_asyncio.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    instance.config.config_dir = str(tmp_path)
    frame.async_setup(instance)
    # For the tests that set up Home Assistant's own integrations.
    loader.async_setup(instance)
    instance.config_entries = config_entries.ConfigEntries(instance, {})
    await instance.config_entries.async_initialize()
    await ar.async_load(instance)
    await dr.async_load(instance)
    await er.async_load(instance)
    yield instance
    await instance.async_stop(force=True)


@pytest.fixture
def anyio_backend():
    return "asyncio"
