"""The automation failure log's Markdown file.

The failures themselves are kept in Home Assistant's storage by
failure_store.py - the list the "Automation failures" sidebar panel shows
and edits. After every change, the whole list is written out as a Markdown
file at `<config>/logdoctor/automation_failures.md` (the scan reviews are in
its reviews/ subfolder), so it can still be read outside Home Assistant.
It has two tables:

- **Open** - failures that haven't been resolved yet.
- **Archived** - failures marked resolved in the panel, until the archive
  is cleared there, which deletes them from the log for good.

Each row is `| Date | Time | Automation | Reason |` (plus when it was
resolved, for archived ones):

- A failed run is recorded by the automation failure monitor
  (automation_monitor.py). Its time is when that run was triggered, which
  for a time-scheduled automation is its scheduled time.
- A run missed while Home Assistant was offline is recorded by the missed
  schedule check (missed_schedules.py), one row per missed time, with the
  time it was scheduled for.

Older versions wrote this file (0.16.0) or a plain-text
automation_failures.log (0.14.0-0.15.x) directly, one row/line per failure;
convert_legacy_failure_log_sync() and parse_markdown_rows() bring those
into the store once.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.util import dt as dt_util

from .const import FAILURE_LOG_FILENAME, LEGACY_FAILURE_LOG_FILENAME

_LOGGER = logging.getLogger(__name__)

_TITLE = """# Automation failures

Recorded by WP Log Doctor, one row per failure. **Time** is when the run was
triggered - for an automation on a time schedule, its scheduled time.
**Failed** rows are runs that raised an error; **Missed** rows are runs that
never happened because Home Assistant was offline. Resolve failures, and
clear resolved ones, from the **Automation failures** page in Home
Assistant's sidebar; this file is rewritten to match after every change.
"""
_OPEN_TABLE_HEADER = "| Date | Time | Automation | Reason |\n| --- | --- | --- | --- |\n"
_ARCHIVED_TABLE_HEADER = (
    "| Date | Time | Automation | Reason | Resolved |\n| --- | --- | --- | --- | --- |\n"
)
# Keep one row per failure even when an error message is huge.
MAX_REASON_CHARS = 1000

# A table row as written by this module: "| YYYY-MM-DD | HH:MM:SS | ..."
_ROW_RE = re.compile(r"^\| (\d{4}-\d{2}-\d{2}) \| (\d{2}:\d{2}:\d{2}) \| (.*) \|$")
# Splits a row's remaining cells on unescaped pipes.
_CELL_SPLIT_RE = re.compile(r"(?<!\\) \| ")
_AUTOMATION_CELL_RE = re.compile(r"^(.*) \(`(automation\.[^`]+)`\)$")

_FILE_LOCK = threading.Lock()


@dataclass
class FailureEntry:
    """A failure as reported by the monitors, before it's stored."""

    when: datetime
    name: str
    entity_id: str
    reason: str
    config_id: str | None = None


def clean_reason(reason: str) -> str:
    """One line, bounded length."""
    reason = " ".join(reason.split())
    if len(reason) > MAX_REASON_CHARS:
        reason = reason[: MAX_REASON_CHARS - 1] + "…"
    return reason


def _cell(text: str) -> str:
    """Make text safe for one Markdown table cell.

    Newlines (tracebacks, multi-line template errors) are folded into
    spaces so a failure stays one row; "|" would end the cell and "<" can
    start an HTML tag that a viewer silently hides (e.g. "<state ...>"), so
    both are escaped.
    """
    text = " ".join(text.split())
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("<", "\\<")


def _uncell(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def _reason_cell(reason: str) -> str:
    kind, sep, detail = reason.partition(": ")
    if sep and kind in ("Failed", "Missed"):
        # Bold the kind so failed and missed runs stand apart at a glance.
        return f"**{kind}:** {_cell(detail)}"
    return _cell(reason)


def _local(iso: str) -> datetime:
    parsed = dt_util.parse_datetime(iso)
    return dt_util.as_local(parsed) if parsed else dt_util.now()


def format_row(record: dict[str, Any]) -> str:
    local = _local(record["when"])
    automation = _cell(record["name"])
    if record.get("entity_id"):
        automation += f" (`{record['entity_id']}`)"
    cells = [
        local.strftime("%Y-%m-%d"),
        local.strftime("%H:%M:%S"),
        automation,
        _reason_cell(record["reason"]),
    ]
    if record.get("resolved"):
        cells.append(_local(record["resolved"]).strftime("%Y-%m-%d %H:%M:%S"))
    return "| " + " | ".join(cells) + " |"


def render_markdown(records: list[dict[str, Any]]) -> str:
    """The whole file: open failures, then archived ones, oldest first."""
    ordered = sorted(records, key=lambda r: r["when"])
    open_rows = [format_row(r) for r in ordered if not r.get("resolved")]
    archived_rows = [format_row(r) for r in ordered if r.get("resolved")]
    parts = [_TITLE, f"\n## Open ({len(open_rows)})\n\n"]
    parts.append(
        _OPEN_TABLE_HEADER + "".join(row + "\n" for row in open_rows)
        if open_rows
        else "_Nothing open._\n"
    )
    parts.append(f"\n## Archived ({len(archived_rows)})\n\n")
    parts.append(
        _ARCHIVED_TABLE_HEADER + "".join(row + "\n" for row in archived_rows)
        if archived_rows
        else "_Nothing archived._\n"
    )
    return "".join(parts)


def write_markdown_sync(path: Path, text: str) -> None:
    with _FILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)


def parse_markdown_rows(text: str) -> list[FailureEntry]:
    """Read the rows of a failure log written by 0.16.0 (one open table)."""
    entries: list[FailureEntry] = []
    tz = dt_util.DEFAULT_TIME_ZONE
    for line in text.splitlines():
        match = _ROW_RE.match(line)
        if not match:
            continue
        date, time, rest = match.groups()
        cells = _CELL_SPLIT_RE.split(rest)
        if len(cells) < 2:
            continue
        automation, reason = cells[0], cells[1]
        entity_id = ""
        if auto_match := _AUTOMATION_CELL_RE.match(automation):
            automation, entity_id = auto_match.groups()
        reason = re.sub(r"^\*\*(Failed|Missed):\*\* ", r"\1: ", reason)
        try:
            when = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        except ValueError:
            continue
        entries.append(
            FailureEntry(
                when=dt_util.as_utc(when),
                name=_uncell(automation),
                entity_id=entity_id,
                reason=_uncell(reason),
            )
        )
    return entries


def convert_legacy_failure_log_sync(main_dir: Path) -> None:
    """Turn a 0.14.0-0.15.x automation_failures.log into 0.16.0-style rows.

    Its lines were "date | time | name (entity_id) | reason". They're put
    before any rows already in the Markdown file (they're older), for the
    store to import (see failure_store.py). The old file is removed.
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
            converted.append(f"| {date} | {time} | {entry_cell} | {_reason_cell(reason)} |")

        existing_rows: list[str] = []
        if path.exists():
            existing_rows = [
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if _ROW_RE.match(line)
            ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _TITLE + "\n" + _OPEN_TABLE_HEADER
            + "".join(row + "\n" for row in converted + existing_rows),
            encoding="utf-8",
        )
        legacy.unlink()
    _LOGGER.info("Converted %s to %s (%d rows)", legacy, path, len(converted))
