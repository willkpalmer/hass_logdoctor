"""A running list of automation failures, one line per failure.

Kept at `<config>/logdoctor/automation_failures.log` (the scan reviews are
in its reviews/ subfolder), so it survives after the notifications are
dismissed. Each
line is:

    date | time | automation | reason

- A failed run is logged by the automation failure monitor
  (automation_monitor.py). Its time is when that run was triggered, which
  for a time-scheduled automation is its scheduled time.
- A run missed while Home Assistant was offline is logged by the missed
  schedule check (missed_schedules.py), one line per missed time, with the
  time it was scheduled for.

Lines older than the report retention window are pruned along with old
reports, after each daily scan (see report_files.py).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .paths import failure_log_path

_LOGGER = logging.getLogger(__name__)

_HEADER = (
    "# Automation failures recorded by WP Log Doctor, one per line:\n"
    "# date | time (when the run was triggered or scheduled) | automation | reason\n"
)
_SEPARATOR = " | "
# Keep one line per failure even when an error message is huge.
_MAX_REASON_CHARS = 1000

# Appends (from the monitors) and pruning (after the daily scan) both run in
# executor threads.
_FILE_LOCK = threading.Lock()


@dataclass
class FailureEntry:
    when: datetime
    name: str
    entity_id: str
    reason: str


def _clean(text: str) -> str:
    # One line per failure: fold any newlines (tracebacks, multi-line
    # template errors) into spaces, and keep the separator unambiguous.
    text = " ".join(text.split())
    return text.replace(_SEPARATOR, " / ")


def format_line(entry: FailureEntry) -> str:
    local = dt_util.as_local(entry.when)
    reason = _clean(entry.reason)
    if len(reason) > _MAX_REASON_CHARS:
        reason = reason[: _MAX_REASON_CHARS - 1] + "…"
    return _SEPARATOR.join(
        (
            local.strftime("%Y-%m-%d"),
            local.strftime("%H:%M:%S"),
            f"{_clean(entry.name)} ({entry.entity_id})",
            reason,
        )
    )


def _append_sync(path: Path, lines: list[str]) -> None:
    with _FILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not path.exists()
        with path.open("a", encoding="utf-8") as handle:
            if new_file:
                handle.write(_HEADER)
            for line in lines:
                handle.write(line + "\n")


async def async_record_failures(hass: HomeAssistant, entries: list[FailureEntry]) -> None:
    """Append one line per entry, oldest first. Never raises."""
    if not entries:
        return
    lines = [format_line(entry) for entry in sorted(entries, key=lambda e: e.when)]
    path = failure_log_path(hass)
    try:
        await hass.async_add_executor_job(_append_sync, path, lines)
    except Exception:  # noqa: BLE001 - never let the log break the monitors
        _LOGGER.exception("Could not write to the automation failure log %s", path)


def prune_failure_log_sync(path: Path, retention_days: int) -> None:
    """Drop lines dated before the retention window (0 = keep everything)."""
    if retention_days <= 0:
        return
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    with _FILE_LOCK:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        # ISO dates compare correctly as strings. Comment/header lines and
        # anything unrecognizable are kept.
        kept = [
            line
            for line in lines
            if line.startswith("#") or not (line[:10] < cutoff and line[4:5] == "-")
        ]
        if len(kept) != len(lines):
            path.write_text("\n".join(kept) + "\n", encoding="utf-8")
