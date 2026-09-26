"""A running list of automation failures, one table row per failure.

Kept as a Markdown file at `<config>/logdoctor/automation_failures.md` (the
scan reviews are in its reviews/ subfolder), so it survives after the
notifications are dismissed and reads as a table in any Markdown viewer.
Each row is:

    | Date | Time | Automation | Reason |

- A failed run is logged by the automation failure monitor
  (automation_monitor.py). Its time is when that run was triggered, which
  for a time-scheduled automation is its scheduled time.
- A run missed while Home Assistant was offline is logged by the missed
  schedule check (missed_schedules.py), one row per missed time, with the
  time it was scheduled for.

Rows are only ever appended at the end of the table, and rows older than
the report retention window are pruned along with old reports after each
daily scan (see report_files.py). Before 0.16.0 this was a plain-text
automation_failures.log; convert_legacy_failure_log_sync() turns that into
rows of this table once.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import FAILURE_LOG_FILENAME, LEGACY_FAILURE_LOG_FILENAME
from .paths import failure_log_path

_LOGGER = logging.getLogger(__name__)

_HEADER = """# Automation failures

Recorded by WP Log Doctor, one row per failure. **Time** is when the run was
triggered - for an automation on a time schedule, its scheduled time.
**Failed** rows are runs that raised an error; **Missed** rows are runs that
never happened because Home Assistant was offline.

| Date | Time | Automation | Reason |
| --- | --- | --- | --- |
"""
# Keep one row per failure even when an error message is huge.
_MAX_REASON_CHARS = 1000

# A table row as written by this module: "| YYYY-MM-DD | ..."
_ROW_DATE_RE = re.compile(r"^\| (\d{4}-\d{2}-\d{2}) \|")

# Appends (from the monitors) and pruning (after the daily scan) both run in
# executor threads.
_FILE_LOCK = threading.Lock()


@dataclass
class FailureEntry:
    when: datetime
    name: str
    entity_id: str
    reason: str


def _cell(text: str) -> str:
    """Make text safe for one Markdown table cell.

    Newlines (tracebacks, multi-line template errors) are folded into
    spaces so a failure stays one row; "|" would end the cell and "<" can
    start an HTML tag that a viewer silently hides (e.g. "<state ...>"), so
    both are escaped.
    """
    text = " ".join(text.split())
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("<", "\\<")


def format_row(entry: FailureEntry) -> str:
    local = dt_util.as_local(entry.when)
    reason = " ".join(entry.reason.split())
    if len(reason) > _MAX_REASON_CHARS:
        reason = reason[: _MAX_REASON_CHARS - 1] + "…"
    kind, sep, detail = reason.partition(": ")
    if sep and kind in ("Failed", "Missed"):
        # Bold the kind so failed and missed runs stand apart at a glance.
        reason_cell = f"**{kind}:** {_cell(detail)}"
    else:
        reason_cell = _cell(reason)
    return (
        f"| {local.strftime('%Y-%m-%d')} "
        f"| {local.strftime('%H:%M:%S')} "
        f"| {_cell(entry.name)} (`{entry.entity_id}`) "
        f"| {reason_cell} |"
    )


def _append_rows_sync(path: Path, rows: list[str]) -> None:
    with _FILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not path.exists()
        with path.open("a", encoding="utf-8") as handle:
            if new_file:
                handle.write(_HEADER)
            for row in rows:
                handle.write(row + "\n")


async def async_record_failures(hass: HomeAssistant, entries: list[FailureEntry]) -> None:
    """Append one row per entry, oldest first. Never raises."""
    if not entries:
        return
    rows = [format_row(entry) for entry in sorted(entries, key=lambda e: e.when)]
    path = failure_log_path(hass)
    try:
        await hass.async_add_executor_job(_append_rows_sync, path, rows)
    except Exception:  # noqa: BLE001 - never let the log break the monitors
        _LOGGER.exception("Could not write to the automation failure log %s", path)


def prune_failure_log_sync(path: Path, retention_days: int) -> None:
    """Drop rows dated before the retention window (0 = keep everything)."""
    if retention_days <= 0:
        return
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    with _FILE_LOCK:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        # ISO dates compare correctly as strings. The header, table header
        # and anything unrecognizable are kept.
        kept = [
            line
            for line in lines
            if not ((match := _ROW_DATE_RE.match(line)) and match.group(1) < cutoff)
        ]
        if len(kept) != len(lines):
            path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def convert_legacy_failure_log_sync(main_dir: Path) -> None:
    """Turn a pre-0.16.0 automation_failures.log into rows of the table.

    Its lines were "date | time | name (entity_id) | reason". They go
    before any rows already in the Markdown file (they're older), and the
    old file is removed once converted.
    """
    legacy = main_dir / LEGACY_FAILURE_LOG_FILENAME
    if not legacy.is_file():
        return
    path = main_dir / FAILURE_LOG_FILENAME
    with _FILE_LOCK:
        converted: list[str] = []
        for line in legacy.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split(" | ", 3)
            if len(parts) != 4:
                continue
            date, time, automation, reason = parts
            name, _, entity = automation.rpartition(" (")
            entity_id = entity.rstrip(")")
            if not name or not entity_id.startswith("automation."):
                name, entity_id = automation, ""
            entry_cell = f"{_cell(name)} (`{entity_id}`)" if entity_id else _cell(name)
            kind, sep, detail = reason.partition(": ")
            reason_cell = (
                f"**{kind}:** {_cell(detail)}"
                if sep and kind in ("Failed", "Missed")
                else _cell(reason)
            )
            converted.append(f"| {date} | {time} | {entry_cell} | {reason_cell} |")

        existing_rows: list[str] = []
        if path.exists():
            existing_rows = [
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if _ROW_DATE_RE.match(line)
            ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _HEADER + "".join(row + "\n" for row in converted + existing_rows),
            encoding="utf-8",
        )
        legacy.unlink()
    _LOGGER.info("Converted %s to %s (%d rows)", legacy, path, len(converted))
