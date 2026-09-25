"""Detects time-scheduled automation runs missed while Home Assistant was down.

Home Assistant never catches up on a time trigger that passed while it was
offline (restarting, updating, crashed, or without power) - the run is just
skipped, silently. This works out what was skipped:

1. Once Home Assistant has fully started, a heartbeat timestamp is saved
   every HEARTBEAT_INTERVAL, plus once more on a clean shutdown. After a restart, the last heartbeat
   and the moment Home Assistant finished starting (when automations attach
   their triggers again) bound the outage window, to within
   HEARTBEAT_INTERVAL for an unclean stop.
2. Every enabled automation's time, time pattern and sun triggers are
   expanded into the points in time they would have fired within that
   window.
3. Any of those at or before the automation's last_triggered time did run
   (e.g. just before the shutdown) and are dropped.

What's left is reported as a persistent notification (and optionally a push
to a Mobile App device). Like the rest of Log Doctor it only reports - it
never runs the missed automations. Conditions can't be evaluated after the
fact, so "missed" means "was scheduled but never attempted".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterator

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import template as template_helper
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.util import dt as dt_util

from .const import DOMAIN, NOTIFICATION_ID_MISSED_SCHEDULES
from .mobile_push import resolve_mobile_app_notify_service

_LOGGER = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = timedelta(seconds=30)
_HEARTBEAT_STORAGE_VERSION = 1

# Cap on missed times listed per automation; a long outage can span many
# runs of a daily automation.
_MAX_TIMES_PER_AUTOMATION = 5

# Cap on missed points collected per trigger. A time pattern firing every
# second over a multi-day outage would otherwise mean hundreds of thousands;
# past this the notification just says "N+ more".
_MAX_POINTS_PER_TRIGGER = 10_000

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class MissedAutomation:
    entity_id: str
    name: str
    config_id: str | None
    times: list[datetime] = field(default_factory=list)
    # True if more times were missed than were collected (see
    # _MAX_POINTS_PER_TRIGGER).
    truncated: bool = False


class MissedScheduleWatch:
    """Keeps the heartbeat and reports missed runs after a restart."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        notify_device_id: str | None = None,
    ) -> None:
        self.hass = hass
        self.notify_device_id = notify_device_id
        self._store: Store[dict[str, Any]] = Store(
            hass, _HEARTBEAT_STORAGE_VERSION, f"{DOMAIN}.{entry_id}.heartbeat"
        )
        self._unsub_interval: Any = None
        self._unsub_started: Any = None
        self._unsub_stop: Any = None
        self._stopping = False

    async def async_start(self) -> None:
        """Load the previous heartbeat and start beating once running.

        Beating only starts after Home Assistant has fully started, because
        automations can't run before then either: if Home Assistant goes
        down again mid-startup, the next check still covers the whole time
        since it was last really running. On an integration reload Home
        Assistant is already running and never went down, so there's
        nothing to check.
        """
        if self.hass.state is CoreState.running:
            await self._async_start_beating()
            return

        data = await self._store.async_load() or {}
        last_alive = dt_util.parse_datetime(data.get("last_alive") or "")

        async def _on_started(_event: Event) -> None:
            self._unsub_started = None
            # Automations attach their triggers when Home Assistant has
            # started, so anything scheduled before now was missed.
            started = dt_util.utcnow()
            await self._async_start_beating()
            if last_alive is not None:
                await self._async_check(last_alive, started)

        self._unsub_started = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _on_started
        )

    async def _async_start_beating(self) -> None:
        await self._async_beat()
        self._unsub_interval = async_track_time_interval(
            self.hass, self._async_beat, HEARTBEAT_INTERVAL
        )
        self._unsub_stop = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._async_on_stop
        )

    @callback
    def async_stop(self) -> None:
        """Stop beating (on unload). Listeners that already fired are skipped."""
        for name in ("_unsub_interval", "_unsub_started", "_unsub_stop"):
            if (unsub := getattr(self, name)) is not None:
                unsub()
                setattr(self, name, None)

    async def _async_beat(self, _now: datetime | None = None) -> None:
        if self._stopping:
            return
        await self._store.async_save({"last_alive": dt_util.utcnow().isoformat()})

    async def _async_on_stop(self, _event: Event) -> None:
        self._unsub_stop = None
        # A final beat as close to the shutdown as possible, then no more,
        # so nothing later in the shutdown can race it.
        await self._async_beat()
        self._stopping = True

    async def _async_check(self, window_start: datetime, window_end: datetime) -> None:
        try:
            missed = find_missed_runs(self.hass, window_start, window_end)
        except Exception:  # noqa: BLE001 - never let the check break startup
            _LOGGER.exception("Log Doctor couldn't check for missed scheduled automations")
            return

        if not missed:
            _LOGGER.debug(
                "No scheduled automation runs missed between %s and %s",
                window_start,
                window_end,
            )
            return

        await self._async_notify(missed, window_start, window_end)

    async def _async_notify(
        self,
        missed: list[MissedAutomation],
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        window = _format_window(window_start, window_end)
        lines = [f"Home Assistant was offline {window}, so these scheduled runs never happened:", ""]
        for item in missed:
            shown = ", ".join(_format_time(t, window_start, window_end) for t in item.times[:_MAX_TIMES_PER_AUTOMATION])
            hidden = len(item.times) - _MAX_TIMES_PER_AUTOMATION
            if hidden > 0 or item.truncated:
                plus = "+" if item.truncated else ""
                shown += f" and {max(hidden, 0):,}{plus} more"
            label = f"**{item.name}**"
            if item.config_id:
                label = f"[{item.name}](/config/automation/edit/{item.config_id})"
            lines.append(f"- {label} (`{item.entity_id}`) - scheduled {shown}")
        lines += [
            "",
            "_Log Doctor doesn't re-run them. Conditions can't be checked after "
            "the fact, so some of these may not have done anything anyway._",
        ]

        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": NOTIFICATION_ID_MISSED_SCHEDULES,
                    "title": "Automations missed while Home Assistant was offline",
                    "message": "\n".join(lines),
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notification failure escalate
            _LOGGER.exception("Failed to post missed schedule notification")

        if not self.notify_device_id:
            return
        service = resolve_mobile_app_notify_service(self.hass, self.notify_device_id)
        if service is None:
            _LOGGER.warning(
                "Can't send missed schedule push: the chosen Mobile App device "
                "(%s) no longer has a notify service",
                self.notify_device_id,
            )
            return
        names = ", ".join(item.name for item in missed)
        try:
            await self.hass.services.async_call(
                "notify",
                service,
                {
                    "title": f"{len(missed)} automation(s) missed while offline",
                    "message": f"Offline {window}: {names}",
                    "data": {"tag": NOTIFICATION_ID_MISSED_SCHEDULES},
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notification failure escalate
            _LOGGER.exception("Failed to send missed schedule push via notify.%s", service)


@callback
def find_missed_runs(
    hass: HomeAssistant, window_start: datetime, window_end: datetime
) -> list[MissedAutomation]:
    """Return every enabled automation with time/sun trigger points that fell
    inside (window_start, window_end) and after its last_triggered time.
    """
    component = hass.data.get("automation")
    if component is None:
        return []

    missed: list[MissedAutomation] = []
    for entity in component.entities:
        if not entity.is_on:
            continue
        # The validated trigger config (blueprints already substituted,
        # "trigger:" normalized to "platform:"). Not a public attribute,
        # so bail out quietly if a future Home Assistant renames it.
        triggers = getattr(entity, "_trigger_config", None)
        if not isinstance(triggers, list):
            continue

        state = hass.states.get(entity.entity_id)
        last_triggered = None
        if state is not None:
            last_triggered = state.attributes.get("last_triggered")
            if isinstance(last_triggered, str):
                last_triggered = dt_util.parse_datetime(last_triggered)

        times: set[datetime] = set()
        truncated = False
        for trigger in triggers:
            if trigger.get("enabled", True) is False:
                continue
            collected = 0
            for point in _trigger_points(hass, trigger, window_start, window_end):
                if window_start < point < window_end and (
                    last_triggered is None or point > last_triggered
                ):
                    if collected >= _MAX_POINTS_PER_TRIGGER:
                        truncated = True
                        break
                    times.add(point)
                    collected += 1

        if times:
            missed.append(
                MissedAutomation(
                    entity_id=entity.entity_id,
                    name=(state and state.name) or entity.entity_id,
                    config_id=(state.attributes.get("id") if state else None),
                    times=sorted(times),
                    truncated=truncated,
                )
            )
    missed.sort(key=lambda m: m.times[0])
    return missed


def _trigger_points(
    hass: HomeAssistant, trigger: dict[str, Any], start: datetime, end: datetime
) -> Iterator[datetime]:
    platform = trigger.get("platform") or trigger.get("trigger")
    if platform == "time":
        weekdays = trigger.get("weekday")
        if isinstance(weekdays, str):
            weekdays = [weekdays]
        for at in trigger.get("at", []):
            for point in _time_at_points(hass, at, start, end):
                if weekdays and _WEEKDAYS[dt_util.as_local(point).weekday()] not in weekdays:
                    continue
                yield point
    elif platform == "sun":
        yield from _sun_points(hass, trigger, start, end)
    elif platform == "time_pattern":
        yield from _time_pattern_points(hass, trigger, start, end)
    # Other trigger types (state, calendar, ...) aren't schedules that can
    # be expanded reliably, so they're not checked.


def _time_pattern_points(
    hass: HomeAssistant, trigger: dict[str, Any], start: datetime, end: datetime
) -> Iterator[datetime]:
    """Yield, in order, the local times in (start, end) a time pattern matches.

    Mirrors the time_pattern trigger: a unit that isn't given matches every
    value, except that when a larger unit is given the smaller ones default
    to 0 (so "hours: /2" fires on the hour, not every second of it). Hours
    and minutes wholly outside the window are skipped without visiting
    their seconds, so the cost is roughly the number of points yielded.
    """
    hours = trigger.get("hours")
    minutes = trigger.get("minutes")
    seconds = trigger.get("seconds")
    if minutes is None and hours is not None:
        minutes = 0
    if seconds is None and minutes is not None:
        seconds = 0
    try:
        hour_values = dt_util.parse_time_expression(hours, 0, 23)
        minute_values = dt_util.parse_time_expression(minutes, 0, 59)
        second_values = dt_util.parse_time_expression(seconds, 0, 59)
    except (ValueError, TypeError):
        return

    tz = _time_zone(hass)
    day = dt_util.as_local(start).date()
    last_day = dt_util.as_local(end).date()
    while day <= last_day:
        for hour in hour_values:
            hour_start = datetime(day.year, day.month, day.day, hour, tzinfo=tz)
            if hour_start >= end:
                return
            if hour_start + timedelta(hours=1) <= start:
                continue
            for minute in minute_values:
                minute_start = hour_start.replace(minute=minute)
                if minute_start >= end:
                    return
                if minute_start + timedelta(minutes=1) <= start:
                    continue
                for second in second_values:
                    point = minute_start.replace(second=second)
                    if point >= end:
                        return
                    if point > start:
                        yield point
        day += timedelta(days=1)


def _time_at_points(
    hass: HomeAssistant, at: Any, start: datetime, end: datetime
) -> Iterator[datetime]:
    offset = timedelta(0)
    if isinstance(at, template_helper.Template):
        # A "limited template" - render it the way the time trigger does.
        try:
            if getattr(at, "hass", None) is None:
                at.hass = hass
            at = template_helper.render_complex(at, {}, limited=True)
        except Exception:  # noqa: BLE001 - unrenderable now: skip it
            return
        if isinstance(at, str) and "." not in at:
            parsed = dt_util.parse_time(at)
            if parsed is None:
                return
            at = parsed
    if isinstance(at, dict):
        offset = at.get("offset") or timedelta(0)
        at = at.get("entity_id")

    if isinstance(at, time):
        yield from _daily_points(hass, at, start, end)
        return
    if not isinstance(at, str):
        return

    # Entity-based: uses the entity's current value, which is normally what
    # it was during the outage too.
    state = hass.states.get(at)
    if state is None:
        return
    tz = _time_zone(hass)
    if state.domain == "input_datetime":
        attrs = state.attributes
        has_time = attrs.get("has_time")
        at_time = time(
            attrs.get("hour", 0) if has_time else 0,
            attrs.get("minute", 0) if has_time else 0,
            attrs.get("second", 0) if has_time else 0,
        )
        if attrs.get("has_date"):
            yield datetime(attrs["year"], attrs["month"], attrs["day"], tzinfo=tz).replace(
                hour=at_time.hour, minute=at_time.minute, second=at_time.second
            ) + offset
        elif has_time:
            # Matches the time trigger: the offset wraps within the day.
            shifted = (datetime.combine(date(2000, 1, 1), at_time) + offset).time()
            yield from _daily_points(hass, shifted, start, end)
    elif state.domain == "sensor" and state.attributes.get("device_class") == "timestamp":
        point = dt_util.parse_datetime(state.state)
        if point is not None:
            yield point + offset


def _time_zone(hass: HomeAssistant):
    # Home Assistant's own time zone, which "at" times are in.
    return dt_util.get_time_zone(hass.config.time_zone) or dt_util.UTC


def _daily_points(
    hass: HomeAssistant, at: time, start: datetime, end: datetime
) -> Iterator[datetime]:
    tz = _time_zone(hass)
    day = dt_util.as_local(start).date()
    last_day = dt_util.as_local(end).date()
    while day <= last_day:
        yield datetime.combine(day, at, tzinfo=tz)
        day += timedelta(days=1)


def _sun_points(
    hass: HomeAssistant, trigger: dict[str, Any], start: datetime, end: datetime
) -> Iterator[datetime]:
    event = trigger.get("event")
    offset = trigger.get("offset") or timedelta(0)
    if not isinstance(offset, timedelta) or event not in ("sunrise", "sunset"):
        return
    cursor = start
    while True:
        try:
            point = get_astral_event_next(hass, event, cursor, offset)
        except ValueError:  # e.g. polar day/night with no event
            return
        if point >= end:
            return
        yield point
        cursor = point


def _format_time(point: datetime, start: datetime, end: datetime) -> str:
    local = dt_util.as_local(point)
    if dt_util.as_local(start).date() == dt_util.as_local(end).date():
        return local.strftime("%H:%M:%S")
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _format_window(start: datetime, end: datetime) -> str:
    local_start, local_end = dt_util.as_local(start), dt_util.as_local(end)
    if local_start.date() == local_end.date():
        return f"from {local_start.strftime('%H:%M:%S')} to {local_end.strftime('%H:%M:%S')}"
    return (
        f"from {local_start.strftime('%Y-%m-%d %H:%M:%S')} "
        f"to {local_end.strftime('%Y-%m-%d %H:%M:%S')}"
    )
