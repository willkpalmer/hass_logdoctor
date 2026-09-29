"""Home Assistant's restarts, to tell startup and shutdown messages apart.

Keeps a short history of Home Assistant's runs in
`.storage/log_doctor.restarts`, one record per run:

    {"starting", "started", "stopping"}

- starting - when this run began: the first line of the new log (Home
  Assistant starts a fresh log file on every start), or when Log Doctor was
  set up if that's earlier or the log has nothing yet;
- started - when Home Assistant reported it had finished starting;
- stopping - when a clean shutdown began (None after a crash, or while
  running).

Times are naive local times, like the timestamps in the log.

A log line is a startup message if it was logged from a run's start until
the grace period after it finished starting, and a shutdown message if it
was logged after a shutdown began and before the next run started. Anything
else is operational. Runs are only recorded from Home Assistant starts
while Log Doctor is set up (not integration reloads), so classifying starts
with the first restart after installing it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .restart_history import RestartHistoryStore

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_STORAGE_KEY = f"{DOMAIN}.restarts"
# Runs kept; plenty to cover the retention window's scans.
_MAX_RUNS = 60
# A first log line older than this at setup isn't from this start (e.g.
# the log isn't rolled over on start when log_rotate_days is set).
_MAX_STARTUP = timedelta(minutes=30)
# Only this much of the new log is read for its first timestamp.
_FIRST_LINES = 500

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) ")

STARTUP = "startup"
SHUTDOWN = "shutdown"


@dataclass
class Run:
    starting: datetime
    started: datetime | None = None
    stopping: datetime | None = None

    @property
    def id(self) -> str:
        return self.starting.isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _first_log_timestamp(path: str) -> datetime | None:
    """The timestamp of the first line in the log file, if it has one."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle):
                if number >= _FIRST_LINES:
                    break
                if match := _TS_RE.match(line):
                    return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f")
    except OSError:
        return None
    return None


class RestartTracker:
    """Records Home Assistant's runs and classifies log timestamps by them."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        log_path: str,
        grace: timedelta,
        history: RestartHistoryStore | None = None,
        history_open_limit: int = 20,
    ) -> None:
        self.hass = hass
        self.log_path = log_path
        self.grace = grace
        # The panel's Restart history view, kept in step with the runs.
        self.history = history
        self.history_open_limit = history_open_limit
        self._store: Store[dict[str, Any]] = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self.runs: list[Run] = []
        # Cleared when they fire: removing a fired listener is an error.
        self._unsub_started: Any = None
        self._unsub_stop: Any = None

    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        for raw in data.get("runs", []):
            if (starting := _parse(raw.get("starting"))) is None:
                continue
            self.runs.append(
                Run(starting, _parse(raw.get("started")), _parse(raw.get("stopping")))
            )

        if self.hass.state is not CoreState.running:
            # Home Assistant is starting: a new run. (On an integration
            # reload it's already running and nothing restarted.)
            now = datetime.now()
            starting = now
            first = await self.hass.async_add_executor_job(_first_log_timestamp, self.log_path)
            earliest = now - _MAX_STARTUP
            if self.runs:
                previous = self.runs[-1]
                earliest = max(earliest, previous.stopping or previous.started or previous.starting)
            if first is not None and earliest <= first < now:
                starting = first
            self.runs.append(Run(starting))
            del self.runs[:-_MAX_RUNS]
            await self._async_save()
            self._unsub_started = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._async_on_started
            )

        self._unsub_stop = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._async_on_stop
        )
        await self._async_sync_history()

    @callback
    def async_stop(self) -> None:
        """On unload. Listeners that already fired are skipped."""
        for name in ("_unsub_started", "_unsub_stop"):
            if (unsub := getattr(self, name)) is not None:
                unsub()
                setattr(self, name, None)

    async def _async_on_started(self, _event: Event) -> None:
        self._unsub_started = None
        if self.runs and self.runs[-1].started is None:
            self.runs[-1].started = datetime.now()
            await self._async_save()
            await self._async_sync_history()

    async def _async_on_stop(self, _event: Event) -> None:
        # Saved straight away: nothing later in the shutdown can be relied on.
        self._unsub_stop = None
        if self.runs and self.runs[-1].stopping is None:
            self.runs[-1].stopping = datetime.now()
            await self._async_save()
            await self._async_sync_history()

    async def _async_sync_history(self) -> None:
        if self.history is None:
            return
        try:
            await self.history.async_sync(self.runs, self.grace, self.history_open_limit)
        except Exception:  # noqa: BLE001 - the history is only for display
            _LOGGER.exception("Could not update the restart history")

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "runs": [
                    {
                        "starting": run.starting.isoformat(),
                        "started": run.started.isoformat() if run.started else None,
                        "stopping": run.stopping.isoformat() if run.stopping else None,
                    }
                    for run in self.runs
                ]
            }
        )

    def phase_of(self, when: datetime) -> tuple[str, str] | None:
        """(STARTUP or SHUTDOWN, the run's id) for a log timestamp, or None.

        None means it was logged while Home Assistant was running normally
        (or before the runs recorded).
        """
        for index, run in enumerate(self.runs):
            following = self.runs[index + 1] if index + 1 < len(self.runs) else None
            if run.stopping is not None and when >= run.stopping:
                if following is None or when < following.starting:
                    return SHUTDOWN, run.id
                continue
            if when < run.starting:
                continue
            if run.started is not None:
                end: datetime | None = run.started + self.grace
            else:
                # Never finished starting (or is still starting).
                end = following.starting if following else None
            if end is None or when <= end:
                return STARTUP, run.id
        return None
