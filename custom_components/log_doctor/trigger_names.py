"""Which of an automation's triggers started a run, described from its config.

Home Assistant's automation_triggered event only says what kind of thing
triggered a run, in general terms ("sun event sunset", "time pattern",
"state of binary_sensor.door"). Which of the automation's triggers it was
is in the run's trace (the trace step is "trigger/<index>", with the
trigger's alias if it has one), and the trigger itself in the automation's
config. From those this gives the trigger's own name - its alias, as set in
the automation editor's "Rename" - or a short description of it like the
editor's: "Sunset +00:15:00", "At 07:30", "Every 15 minutes",
"Front door → on for 00:02:00".

Traces are Home Assistant's own, read as the trace pages read them, and
can be turned off per automation (stored_traces: 0); when there's no trace
for the run, the trigger is still found when the automation has only one
of that kind. Anything that can't be worked out gives None, and the run
keeps Home Assistant's description.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

# Home Assistant's descriptions start with these, by trigger platform.
_DESCRIPTION_PLATFORMS = (
    ("numeric state of", "numeric_state"),
    ("state of", "state"),
    ("sun event", "sun"),
    ("time pattern", "time_pattern"),
    ("time", "time"),
    ("event", "event"),
    ("home assistant", "homeassistant"),
    ("mqtt topic", "mqtt"),
    ("webhook", "webhook"),
    ("zone", "zone"),
    ("template", "template"),
    ("device", "device"),
    ("calendar", "calendar"),
    ("tag", "tag"),
)


def run_trigger_name(hass: HomeAssistant, event: Event) -> str | None:
    """The name of the trigger that started the run in an automation_triggered event."""
    try:
        return _run_trigger_name(hass, event)
    except Exception:  # noqa: BLE001 - only ever a nicer label
        _LOGGER.debug("Couldn't work out which trigger started %s", event.data, exc_info=True)
        return None


def _run_trigger_name(hass: HomeAssistant, event: Event) -> str | None:
    entity_id = event.data.get("entity_id")
    if not entity_id or not event.data.get("source"):
        return None  # run by hand: no trigger
    entity = _automation_entity(hass, entity_id)
    triggers = _triggers(entity) if entity is not None else []
    index, alias = _from_trace(hass, entity, event)
    if alias:
        return str(alias)
    if index is None:
        index = _guess_index(triggers, event.data.get("source") or "")
    if index is None or not 0 <= index < len(triggers):
        return None
    conf = triggers[index]
    if conf.get("alias"):
        return str(conf["alias"])
    return describe_trigger(hass, conf)


def _automation_entity(hass: HomeAssistant, entity_id: str) -> Any:
    component = hass.data.get("automation")
    get_entity = getattr(component, "get_entity", None)
    return get_entity(entity_id) if get_entity else None


def _triggers(entity: Any) -> list[dict[str, Any]]:
    """The automation's triggers, in the order the trace numbers them."""
    validated = getattr(entity, "_trigger_config", None)
    if isinstance(validated, list) and all(isinstance(t, dict) for t in validated):
        return validated
    raw = getattr(entity, "raw_config", None) or {}
    found = raw.get("triggers", raw.get("trigger", []))
    found = found if isinstance(found, list) else [found]
    flat: list[dict[str, Any]] = []
    for conf in found:
        # A trigger list can group triggers under "triggers".
        if isinstance(conf, dict) and "triggers" in conf and len(conf) == 1:
            nested = conf["triggers"]
            flat.extend(nested if isinstance(nested, list) else [nested])
        elif isinstance(conf, dict):
            flat.append(conf)
    return flat


def _from_trace(hass: HomeAssistant, entity: Any, event: Event) -> tuple[int | None, str | None]:
    """(trigger index, alias) from this run's trace, if it's kept."""
    unique_id = getattr(entity, "unique_id", None)
    traces = (hass.data.get("trace") or {}).get(f"automation.{unique_id}") if unique_id else None
    if not traces:
        return None, None
    for trace in reversed(list(traces.values())):
        context = getattr(trace, "context", None)
        if context is None or context.id != event.context.id:
            continue
        steps = trace.as_extended_dict().get("trace") or {}
        for path, elements in steps.items():
            if not path.startswith("trigger"):
                continue
            _, _, number = path.partition("/")
            variables = (elements[0] if elements else {}).get("changed_variables") or {}
            trigger = variables.get("trigger") or {}
            index = int(number) if number.isdigit() else trigger.get("idx")
            if isinstance(index, str) and index.isdigit():
                index = int(index)
            return (index if isinstance(index, int) else None), trigger.get("alias")
        return None, None
    return None, None


def _platform(conf: dict[str, Any]) -> str:
    return str(conf.get("trigger") or conf.get("platform") or "")


def _guess_index(triggers: list[dict[str, Any]], source: str) -> int | None:
    """Without a trace: the automation's only trigger, or only one of that kind."""
    if len(triggers) == 1:
        return 0
    lowered = source.lower()
    for prefix, platform in _DESCRIPTION_PLATFORMS:
        if lowered.startswith(prefix):
            matches = [i for i, conf in enumerate(triggers) if _platform(conf) == platform]
            return matches[0] if len(matches) == 1 else None
    return None


# -- describing a trigger ---------------------------------------------------


def _duration(value: Any) -> str | None:
    """"00:15:00" from a timedelta, "HH:MM:SS" text or {"minutes": 15}; signed."""
    if value in (None, "", 0):
        return None
    if isinstance(value, dict):
        try:
            value = timedelta(**{k: float(v) for k, v in value.items()})
        except (TypeError, ValueError):
            return None
    if isinstance(value, (int, float)):
        value = timedelta(seconds=value)
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
        if not seconds:
            return None
        sign = "-" if seconds < 0 else ""
        seconds = abs(seconds)
        return f"{sign}{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return str(value)


def _signed(value: Any) -> str | None:
    text = _duration(value)
    if text is None or text.strip("-0:") == "":
        return None
    return text if text.startswith("-") else f"+{text}"


def _names(hass: HomeAssistant, value: Any) -> str:
    """Entity ids as their friendly names, joined."""
    ids = value if isinstance(value, list) else [value]
    registry = er.async_get(hass)
    names = []
    for entity_id in ids:
        # Device triggers refer to entities by their registry id.
        if (entry := registry.async_get(str(entity_id))) is not None:
            entity_id = entry.entity_id
        state = hass.states.get(str(entity_id))
        names.append(state.name if state is not None else str(entity_id))
    return ", ".join(names)


def _list(value: Any) -> str:
    values = value if isinstance(value, list) else [value]
    return ", ".join(str(v) for v in values)


def _time(value: Any) -> str:
    """A time ("07:30:00" → "07:30") or a helper/sensor entity."""
    text = str(value)
    if len(text) == 8 and text[2] == ":" and text.endswith(":00"):
        return text[:5]
    return text


def _plain(value: Any) -> Any:
    """Validated config holds templates as Template objects: their text."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if hasattr(value, "template") and hasattr(value, "async_render"):
        return value.template
    return value


def describe_trigger(hass: HomeAssistant, conf: dict[str, Any]) -> str | None:
    """A short description of a trigger's config, or None if unknown."""
    conf = _plain(conf)
    platform = _platform(conf)
    if platform == "sun":
        event = str(conf.get("event") or "").capitalize()
        offset = _signed(conf.get("offset"))
        return f"{event} {offset}" if offset else event or None
    if platform == "time":
        at = conf.get("at")
        times = at if isinstance(at, list) else [at]
        shown = []
        for item in times:
            if isinstance(item, dict):  # {"entity_id": ..., "offset": ...}
                text = _names(hass, item.get("entity_id"))
                if offset := _signed(item.get("offset")):
                    text += f" {offset}"
                shown.append(text)
            elif isinstance(item, str) and "." in item and ":" not in item:
                shown.append(_names(hass, item))
            else:
                shown.append(_time(item))
        text = f"At {', '.join(shown)}"
        if weekday := conf.get("weekday"):
            text += f" ({_list(weekday)})"
        return text
    if platform == "time_pattern":
        parts = []
        for unit in ("hours", "minutes", "seconds"):
            value = conf.get(unit)
            if value is None or value == "":
                continue
            text = str(value)
            if text.startswith("/"):
                every = text[1:]
                parts.append(f"every {every} {unit if every != '1' else unit[:-1]}")
            elif text != "*":
                parts.append(f"{unit[:-1]} {text}")
        return ("Time pattern: " + ", ".join(parts)) if parts else "Time pattern"
    if platform in ("state", "numeric_state"):
        text = _names(hass, conf.get("entity_id"))
        if attribute := conf.get("attribute"):
            text += f" {attribute}"
        if platform == "state":
            if "from" in conf and conf["from"] is not None:
                text += f" from {_list(conf['from'])}"
            if "to" in conf and conf["to"] is not None:
                text += f" → {_list(conf['to'])}"
            elif "to" not in conf and "from" not in conf:
                text += " changed"
        else:
            if conf.get("above") is not None:
                text += f" above {_names(hass, conf['above']) if isinstance(conf['above'], str) and '.' in conf['above'] else conf['above']}"
            if conf.get("below") is not None:
                text += f" below {_names(hass, conf['below']) if isinstance(conf['below'], str) and '.' in conf['below'] else conf['below']}"
        if (held := _duration(conf.get("for"))) is not None:
            text += f" for {held}"
        return text
    if platform == "homeassistant":
        event = str(conf.get("event") or "")
        return {"start": "Home Assistant started", "shutdown": "Home Assistant stopping"}.get(event, f"Home Assistant {event}")
    if platform == "event":
        return f"Event {_list(conf.get('event_type'))}"
    if platform == "mqtt":
        text = f"MQTT {conf.get('topic')}"
        if conf.get("payload") is not None:
            text += f" = {conf['payload']}"
        return text
    if platform == "webhook":
        return f"Webhook {conf.get('webhook_id')}"
    if platform == "zone":
        return f"{_names(hass, conf.get('entity_id'))} {conf.get('event', 'enter')}s {_names(hass, conf.get('zone'))}"
    if platform == "template":
        text = "Template"
        if (held := _duration(conf.get("for"))) is not None:
            text += f" for {held}"
        return text
    if platform == "calendar":
        text = f"{_names(hass, conf.get('entity_id'))} event {conf.get('event', 'start')}"
        if offset := _signed(conf.get("offset")):
            text += f" {offset}"
        return text
    if platform == "tag":
        return f"Tag {_list(conf.get('tag_id'))}"
    if platform == "conversation":
        return f"Sentence {_list(conf.get('command'))}"
    if platform == "device":
        what = " ".join(
            str(conf[key]).replace("_", " ") for key in ("type", "subtype") if conf.get(key)
        ) or "trigger"
        if conf.get("entity_id"):
            return f"{_names(hass, conf['entity_id'])} {what}"
        device = dr.async_get(hass).async_get(str(conf.get("device_id") or ""))
        name = (device.name_by_user or device.name) if device is not None else "Device"
        return f"{name} {what}"
    return None
