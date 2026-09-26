"""WebSocket commands for the "Automation failures" sidebar panel.

All admin-only, like the panel itself. The panel subscribes once and gets
the full list back straight away and again after every change, so new
failures appear live and several open browser tabs stay in sync.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DATA_FAILURE_STORE
from .failure_store import FailureStore

WS_SUBSCRIBE = "log_doctor/failures/subscribe"
WS_RESOLVE = "log_doctor/failures/resolve"
WS_RESTORE = "log_doctor/failures/restore"
WS_CLEAR_ARCHIVED = "log_doctor/failures/clear_archived"

_IDS = vol.All([str], vol.Length(max=100_000))


@callback
def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_subscribe)
    websocket_api.async_register_command(hass, websocket_resolve)
    websocket_api.async_register_command(hass, websocket_restore)
    websocket_api.async_register_command(hass, websocket_clear_archived)


def _get_store(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int
) -> FailureStore | None:
    store: FailureStore | None = hass.data.get(DATA_FAILURE_STORE)
    if store is None:
        connection.send_error(msg_id, "not_loaded", "WP Log Doctor isn't loaded")
    return store


def _payload(store: FailureStore) -> dict[str, Any]:
    return {"failures": store.records}


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_SUBSCRIBE})
@callback
def websocket_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (store := _get_store(hass, connection, msg["id"])) is None:
        return

    @callback
    def _forward() -> None:
        if store.closed:
            # The integration is reloading; the panel re-subscribes.
            connection.send_message(websocket_api.event_message(msg["id"], {"reload": True}))
            return
        connection.send_message(websocket_api.event_message(msg["id"], _payload(store)))

    connection.subscriptions[msg["id"]] = store.async_subscribe(_forward)
    connection.send_result(msg["id"])
    connection.send_message(websocket_api.event_message(msg["id"], _payload(store)))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_RESOLVE, vol.Required("ids"): _IDS})
@websocket_api.async_response
async def websocket_resolve(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (store := _get_store(hass, connection, msg["id"])) is None:
        return
    count = await store.async_resolve(msg["ids"])
    connection.send_result(msg["id"], {"count": count})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_RESTORE, vol.Required("ids"): _IDS})
@websocket_api.async_response
async def websocket_restore(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (store := _get_store(hass, connection, msg["id"])) is None:
        return
    count = await store.async_restore(msg["ids"])
    connection.send_result(msg["id"], {"count": count})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_CLEAR_ARCHIVED})
@websocket_api.async_response
async def websocket_clear_archived(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (store := _get_store(hass, connection, msg["id"])) is None:
        return
    count = await store.async_clear_archived()
    connection.send_result(msg["id"], {"count": count})
