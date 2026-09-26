"""WebSocket commands for the Log Doctor sidebar panel.

The panel shows two reviewable lists (see review_list.py), each picked by
a "list" field:

- "anomalies" - the Log review view (anomaly_store.py)
- "failures" - the Automation failures view (failure_store.py)

All commands are admin-only, like the panel itself. The panel subscribes
once per list and gets the full list back straight away and again after
every change, so new entries appear live and open browser tabs stay in
sync.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DATA_ANOMALY_STORE, DATA_FAILURE_STORE
from .review_list import ReviewList

WS_SUBSCRIBE = "log_doctor/review/subscribe"
WS_RESOLVE = "log_doctor/review/resolve"
WS_RESTORE = "log_doctor/review/restore"
WS_CLEAR_ARCHIVED = "log_doctor/review/clear_archived"

_LISTS = {"anomalies": DATA_ANOMALY_STORE, "failures": DATA_FAILURE_STORE}
_LIST = vol.In(list(_LISTS))
_IDS = vol.All([str], vol.Length(max=100_000))


@callback
def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_subscribe)
    websocket_api.async_register_command(hass, websocket_resolve)
    websocket_api.async_register_command(hass, websocket_restore)
    websocket_api.async_register_command(hass, websocket_clear_archived)


def _get_list(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> ReviewList | None:
    review_list: ReviewList | None = hass.data.get(_LISTS[msg["list"]])
    if review_list is None:
        connection.send_error(msg["id"], "not_loaded", "WP Log Doctor isn't loaded")
    return review_list


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_SUBSCRIBE, vol.Required("list"): _LIST})
@callback
def websocket_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (review_list := _get_list(hass, connection, msg)) is None:
        return

    @callback
    def _forward() -> None:
        if review_list.closed:
            # The integration is reloading; the panel re-subscribes.
            connection.send_message(websocket_api.event_message(msg["id"], {"reload": True}))
            return
        connection.send_message(
            websocket_api.event_message(msg["id"], {"records": review_list.records})
        )

    connection.subscriptions[msg["id"]] = review_list.async_subscribe(_forward)
    connection.send_result(msg["id"])
    connection.send_message(
        websocket_api.event_message(msg["id"], {"records": review_list.records})
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): WS_RESOLVE, vol.Required("list"): _LIST, vol.Required("ids"): _IDS}
)
@websocket_api.async_response
async def websocket_resolve(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (review_list := _get_list(hass, connection, msg)) is None:
        return
    connection.send_result(msg["id"], {"count": await review_list.async_resolve(msg["ids"])})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): WS_RESTORE, vol.Required("list"): _LIST, vol.Required("ids"): _IDS}
)
@websocket_api.async_response
async def websocket_restore(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (review_list := _get_list(hass, connection, msg)) is None:
        return
    connection.send_result(msg["id"], {"count": await review_list.async_restore(msg["ids"])})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_CLEAR_ARCHIVED, vol.Required("list"): _LIST})
@websocket_api.async_response
async def websocket_clear_archived(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (review_list := _get_list(hass, connection, msg)) is None:
        return
    connection.send_result(msg["id"], {"count": await review_list.async_clear_archived()})
