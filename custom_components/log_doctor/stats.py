"""Counts of warnings and errors over time, for the Insights page and the
weekly digest.

Kept in `.storage/log_doctor.stats` and fed by every scan with the log
lines it read that were logged since the previous scan, at warning level
or above (whatever the minimum severity setting, which only decides what's
reported), backup messages included:

    {"hours": {"2026-10-06T08": {"WARNING": 12, "ERROR": 3, "CRITICAL": 0}},
     "days": {"2026-10-06": {"<source>": {"WARNING": 4, "ERROR": 1, ...}}}}

- hours - lines per level for each hour (UTC), by the time each line says
  it was logged (the scan's, for the few that don't say), for the
  error-rate graph.
- days - lines per level for each source and day (UTC), for the "noisiest
  integrations" ranking. A source is the integration a logger belongs to
  (homeassistant.components.<domain>, custom_components.<domain>), a
  Supervisor source (an add-on, Host, ...), or else the logger's first part
  ("homeassistant" for Home Assistant's own core, "aiohttp", ...).

Both are pruned to the report retention window with every scan.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .log_parser import LogEntry, component_from_logger

STORAGE_VERSION = 1
STORAGE_KEY = "log_doctor.stats"
_SAVE_DELAY = 10

LEVELS = ("WARNING", "ERROR", "CRITICAL")

KIND_INTEGRATION = "integration"
KIND_SOURCE = "source"
KIND_OTHER = "other"


def noise_source(logger: str, sources: Iterable[str] = ()) -> tuple[str, str]:
    """(source, kind) a log line is counted against in the ranking.

    Lines from the Supervisor's sources (Host, add-ons, ...; their names in
    `sources`) have the source's name as their logger, or "<name>:<logger>"
    (see log_parser.parse_supervisor_log_text).
    """
    for name in sources:
        if logger == name or logger.startswith(f"{name}:"):
            return name, KIND_SOURCE
    _kind, component = component_from_logger(logger)
    if component:
        return component, KIND_INTEGRATION
    return (logger.split(".", 1)[0] or "unknown"), KIND_OTHER


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.astimezone()
    return dt_util.as_utc(value)


class StatsStore:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.hours: dict[str, dict[str, int]] = {}
        self.days: dict[str, dict[str, dict[str, int]]] = {}
        # Source kinds (integration / source / other), kept with the counts.
        self.kinds: dict[str, str] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.hours = data.get("hours", {})
        self.days = data.get("days", {})
        self.kinds = data.get("kinds", {})

    def _data(self) -> dict[str, Any]:
        return {"hours": self.hours, "days": self.days, "kinds": self.kinds}

    def record(
        self,
        entries: Iterable[LogEntry],
        since: datetime | None,
        sources: Iterable[str] = (),
    ) -> int:
        """Count the lines logged since `since` (naive local, like the log).

        sources: the names of the Supervisor sources read.
        """
        sources = sorted(sources, key=len, reverse=True)
        counted = 0
        for entry in entries:
            if entry.level not in LEVELS:
                continue
            if since is not None and entry.timestamp < since:
                continue
            when = _utc(entry.timestamp)
            hour = self.hours.setdefault(when.strftime("%Y-%m-%dT%H"), {})
            hour[entry.level] = hour.get(entry.level, 0) + 1
            source, kind = noise_source(entry.logger, sources)
            self.kinds[source] = kind
            day = self.days.setdefault(when.strftime("%Y-%m-%d"), {}).setdefault(source, {})
            day[entry.level] = day.get(entry.level, 0) + 1
            counted += 1
        if counted:
            self._store.async_delay_save(self._data, _SAVE_DELAY)
        return counted

    def prune(self, retention_days: int) -> None:
        if retention_days <= 0:
            return
        cutoff = dt_util.utcnow() - timedelta(days=retention_days)
        hour_cutoff = cutoff.strftime("%Y-%m-%dT%H")
        day_cutoff = cutoff.strftime("%Y-%m-%d")
        before = (len(self.hours), len(self.days))
        self.hours = {k: v for k, v in self.hours.items() if k >= hour_cutoff}
        self.days = {k: v for k, v in self.days.items() if k >= day_cutoff}
        sources = {source for day in self.days.values() for source in day}
        self.kinds = {k: v for k, v in self.kinds.items() if k in sources}
        if (len(self.hours), len(self.days)) != before:
            self._store.async_delay_save(self._data, _SAVE_DELAY)

    async def async_shutdown(self) -> None:
        await self._store.async_save(self._data())

    # -- reading ------------------------------------------------------------

    def hourly(self, hours: int, now: datetime | None = None) -> list[dict[str, Any]]:
        """One point per hour, oldest first, ending with the current hour."""
        now = dt_util.as_utc(now or dt_util.utcnow()).replace(minute=0, second=0, microsecond=0)
        points = []
        for back in range(hours - 1, -1, -1):
            start = now - timedelta(hours=back)
            counts = self.hours.get(start.strftime("%Y-%m-%dT%H"), {})
            points.append({"t": start.isoformat(), **{lvl: counts.get(lvl, 0) for lvl in LEVELS}})
        return points

    def daily(self, days: int, now: datetime | None = None) -> list[dict[str, Any]]:
        """One point per day (UTC), oldest first, ending with today."""
        now = dt_util.as_utc(now or dt_util.utcnow())
        points = []
        for back in range(days - 1, -1, -1):
            day = (now - timedelta(days=back)).strftime("%Y-%m-%d")
            counts = {lvl: 0 for lvl in LEVELS}
            for source in self.days.get(day, {}).values():
                for level, count in source.items():
                    counts[level] = counts.get(level, 0) + count
            points.append({"t": f"{day}T00:00:00+00:00", **counts})
        return points

    def ranking(self, days: int, now: datetime | None = None) -> list[dict[str, Any]]:
        """Sources by lines logged over the last `days` days, noisiest first."""
        now = dt_util.as_utc(now or dt_util.utcnow())
        first = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        last = now.strftime("%Y-%m-%d")
        totals: dict[str, dict[str, int]] = defaultdict(dict)
        for day, sources in self.days.items():
            if not first <= day <= last:
                continue
            for source, counts in sources.items():
                for level, count in counts.items():
                    totals[source][level] = totals[source].get(level, 0) + count
        rows = [
            {
                "source": source,
                "kind": self.kinds.get(source, KIND_OTHER),
                **{lvl: counts.get(lvl, 0) for lvl in LEVELS},
                "total": sum(counts.values()),
            }
            for source, counts in totals.items()
        ]
        rows.sort(key=lambda r: (-(r["ERROR"] + r["CRITICAL"]), -r["total"], r["source"]))
        return rows

    def totals(self, days: int, now: datetime | None = None) -> dict[str, int]:
        """Lines per level over the last `days` days."""
        result = {lvl: 0 for lvl in LEVELS}
        for row in self.ranking(days, now):
            for lvl in LEVELS:
                result[lvl] += row[lvl]
        return result
