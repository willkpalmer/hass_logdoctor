"""WebSocket commands for the Log Doctor sidebar panel.

The panel shows four reviewable lists (see review_list.py), each picked by
a "list" field:

- "anomalies" - the Log review view (anomaly_store.py)
- "failures" - the Automation failures view (failure_store.py)
- "health" - the Devices & integrations view (health_store.py)
- "backups" - the Backups view (backup_store.py)

log_doctor/review/ignore and log_doctor/review/unignore move entries of the
lists that support it ("anomalies" and "backups") to and from their
Ignored tab.

log_doctor/review/set_category moves Log review entries between the Log
review ("operational") and Startup & shutdown ("restart") views.

log_doctor/review/investigation_prompt builds, for selected Log review
entries, the prompt the investigation stage would send (see
investigation.py), for the panel to copy to the clipboard.

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

from . import settings_api
from .anomaly_store import CATEGORY_OPERATIONAL, CATEGORY_RESTART, AnomalyStore
from .investigation import anomaly_from_record, build_copy_prompt
from .const import (
    DATA_ANOMALY_STORE,
    DATA_BACKUP_STORE,
    DATA_FAILURE_STORE,
    DATA_HEALTH_STORE,
)
from .review_list import ReviewList

WS_SUBSCRIBE = "log_doctor/review/subscribe"
WS_RESOLVE = "log_doctor/review/resolve"
WS_RESTORE = "log_doctor/review/restore"
WS_CLEAR_ARCHIVED = "log_doctor/review/clear_archived"
WS_INVESTIGATION_PROMPT = "log_doctor/review/investigation_prompt"
WS_IGNORE = "log_doctor/review/ignore"
WS_UNIGNORE = "log_doctor/review/unignore"
WS_SET_CATEGORY = "log_doctor/review/set_category"

_LISTS = {
    "anomalies": DATA_ANOMALY_STORE,
    "failures": DATA_FAILURE_STORE,
    "health": DATA_HEALTH_STORE,
    "backups": DATA_BACKUP_STORE,
}
_LIST = vol.In(list(_LISTS))
_IDS = vol.All([str], vol.Length(max=100_000))


@callback
def async_setup(hass: HomeAssistant) -> None:
    settings_api.async_setup(hass)
    websocket_api.async_register_command(hass, websocket_subscribe)
    websocket_api.async_register_command(hass, websocket_resolve)
    websocket_api.async_register_command(hass, websocket_restore)
    websocket_api.async_register_command(hass, websocket_clear_archived)
    websocket_api.async_register_command(hass, websocket_investigation_prompt)
    websocket_api.async_register_command(hass, websocket_ignore)
    websocket_api.async_register_command(hass, websocket_unignore)
    websocket_api.async_register_command(hass, websocket_set_category)


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


async def _async_ignore(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], method: str
) -> None:
    if (review_list := _get_list(hass, connection, msg)) is None:
        return
    handler = getattr(review_list, method, None)
    if handler is None:
        connection.send_error(msg["id"], "not_supported", "Entries of this list can't be ignored")
        return
    connection.send_result(msg["id"], {"count": await handler(msg["ids"])})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): WS_IGNORE, vol.Required("list"): _LIST, vol.Required("ids"): _IDS}
)
@websocket_api.async_response
async def websocket_ignore(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    await _async_ignore(hass, connection, msg, "async_ignore")


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): WS_UNIGNORE, vol.Required("list"): _LIST, vol.Required("ids"): _IDS}
)
@websocket_api.async_response
async def websocket_unignore(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    await _async_ignore(hass, connection, msg, "async_unignore")


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CLEAR_ARCHIVED,
        vol.Required("list"): _LIST,
        # Only these (views sharing a list clear just their own entries).
        vol.Optional("ids"): _IDS,
    }
)
@websocket_api.async_response
async def websocket_clear_archived(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (review_list := _get_list(hass, connection, msg)) is None:
        return
    connection.send_result(
        msg["id"], {"count": await review_list.async_clear_archived(msg.get("ids"))}
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): WS_INVESTIGATION_PROMPT, vol.Required("ids"): vol.All([str], vol.Length(min=1, max=1_000))}
)
@callback
def websocket_investigation_prompt(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    store: ReviewList | None = hass.data.get(DATA_ANOMALY_STORE)
    if store is None:
        connection.send_error(msg["id"], "not_loaded", "WP Log Doctor isn't loaded")
        return
    by_id = {record["id"]: record for record in store.records}
    # In the order the panel lists them.
    anomalies = [anomaly_from_record(by_id[i]) for i in msg["ids"] if i in by_id]
    if not anomalies:
        connection.send_error(msg["id"], "not_found", "None of those log entries exist any more")
        return
    connection.send_result(
        msg["id"], {"prompt": build_copy_prompt(anomalies), "count": len(anomalies)}
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_SET_CATEGORY,
        # Sent like every list action; only the Log review's list has categories.
        vol.Optional("list"): vol.In(["anomalies"]),
        vol.Required("ids"): _IDS,
        vol.Required("category"): vol.In([CATEGORY_OPERATIONAL, CATEGORY_RESTART]),
    }
)
@websocket_api.async_response
async def websocket_set_category(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    store: AnomalyStore | None = hass.data.get(DATA_ANOMALY_STORE)
    if store is None:
        connection.send_error(msg["id"], "not_loaded", "WP Log Doctor isn't loaded")
        return
    connection.send_result(
        msg["id"], {"count": await store.async_set_category(msg["ids"], msg["category"])}
    )
