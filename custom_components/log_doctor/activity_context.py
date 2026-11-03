"""Who or what started something: a person, an automation, a script.

Home Assistant gives everything that happens a context: an id, the user
who started it (when a person did, in the app or a dashboard), and the
id of the context it came from (parent_id) - so a scene turned on by an
automation's action carries that automation run's context, and an
automation run started from the Run button has the button press's
context as its parent. This remembers the recent contexts it sees:

- every action call (call_service): the user, if any, and the action;
- every automation run (automation_triggered) and script run
  (script_started): which automation or script,

and describe() follows a context (and its parents) back to the person or
automation/script behind it: {"by": "Will", "by_kind": "user"},
{"by": "Evening lights", "by_kind": "automation", "by_entity":
"automation.evening_lights", "by_config_id": "1700…"}, or None when it
can't be told (e.g. a device, an integration, or Home Assistant itself).
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context, Event, HomeAssistant, callback

EVENT_AUTOMATION_TRIGGERED = "automation_triggered"
EVENT_SCRIPT_STARTED = "script_started"

# Contexts remembered; plenty for a busy few minutes.
_MAX_CONTEXTS = 2_000
# Parents followed at most (automation → script → scene ...).
_MAX_HOPS = 6


class ContextTracker:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        # context id -> {"parent", "user", "kind", "name", "entity_id", "config_id"}
        self._contexts: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._users: dict[str, str] = {}

    @callback
    def async_start(self) -> Callable[[], None]:
        unsubs = [
            self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._async_service_called),
            self.hass.bus.async_listen(EVENT_AUTOMATION_TRIGGERED, self._async_automation),
            self.hass.bus.async_listen(EVENT_SCRIPT_STARTED, self._async_script),
        ]
        self.hass.async_create_task(self._async_load_users())

        @callback
        def _stop() -> None:
            for unsub in unsubs:
                unsub()

        return _stop

    async def _async_load_users(self) -> None:
        try:
            users = await self.hass.auth.async_get_users()
        except Exception:  # noqa: BLE001 - names are only nicer labels
            return
        self._users = {user.id: user.name or "a user" for user in users}

    def _remember(self, context: Context, **info: Any) -> None:
        entry = self._contexts.get(context.id) or {"parent": context.parent_id, "user": context.user_id}
        # An automation or script run says more than the call that started it.
        if info.get("kind") or not entry.get("kind"):
            entry.update({k: v for k, v in info.items() if v is not None})
        self._contexts[context.id] = entry
        self._contexts.move_to_end(context.id)
        while len(self._contexts) > _MAX_CONTEXTS:
            self._contexts.popitem(last=False)

    @callback
    def _async_service_called(self, event: Event) -> None:
        self._remember(event.context)

    @callback
    def _async_automation(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        state = self.hass.states.get(entity_id) if entity_id else None
        self._remember(
            event.context,
            kind="automation",
            name=event.data.get("name") or entity_id,
            entity_id=entity_id,
            config_id=state.attributes.get("id") if state else None,
        )

    @callback
    def _async_script(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        state = self.hass.states.get(entity_id) if entity_id else None
        self._remember(
            event.context,
            kind="script",
            name=event.data.get("name") or entity_id,
            entity_id=entity_id,
            config_id=(entity_id or "").removeprefix("script.") or None,
        )

    def user_name(self, user_id: str) -> str:
        if user_id in self._users:
            return self._users[user_id]
        # A person linked to the user, while the user list loads.
        for state in self.hass.states.async_all("person"):
            if state.attributes.get("user_id") == user_id:
                return state.name
        self.hass.async_create_task(self._async_load_users())
        return "a user"

    def describe(self, context: Context | None, *, skip: str | None = None) -> dict[str, Any] | None:
        """Who or what is behind a context, or None if it can't be told.

        skip: an automation or script's own run, to look past it (an
        automation run by hand has its own run's context).
        """
        if context is None:
            return None
        if context.user_id:
            return {"by": self.user_name(context.user_id), "by_kind": "user"}
        context_id: str | None = context.id
        parent: str | None = context.parent_id
        for _hop in range(_MAX_HOPS):
            entry = self._contexts.get(context_id) if context_id else None
            if entry is not None:
                if entry.get("kind") and entry.get("entity_id") != skip:
                    return {
                        "by": entry.get("name"),
                        "by_kind": entry["kind"],
                        "by_entity": entry.get("entity_id"),
                        "by_config_id": entry.get("config_id"),
                    }
                if entry.get("user"):
                    return {"by": self.user_name(entry["user"]), "by_kind": "user"}
                parent = entry.get("parent")
            context_id, parent = parent, None
            if context_id is None:
                break
        return None
