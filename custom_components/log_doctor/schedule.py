"""When the scheduled scans run.

Either at set times of day (scan_mode "times": scan_time holds one or more
times, separated by commas, e.g. "08:00, 20:00") or every so often
(scan_mode "interval": scan_interval minutes or hours, by
scan_interval_unit), counted from when Log Doctor starts.
"""
from __future__ import annotations

import re
from datetime import time, timedelta

MODE_TIMES = "times"
MODE_INTERVAL = "interval"
UNIT_MINUTES = "minutes"
UNIT_HOURS = "hours"

# Scans any closer together than this aren't allowed.
MIN_INTERVAL = timedelta(minutes=5)
MAX_INTERVAL = timedelta(days=7)

_TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?$")


def parse_scan_times(value: str | None) -> list[time]:
    """The times in "08:00, 20:00" (or "8:00;20:30:15"), sorted, no repeats.

    Raises ValueError with a message for the user when one isn't a time.
    """
    found: set[time] = set()
    for part in re.split(r"[,;\s]+", (value or "").strip()):
        if not part:
            continue
        match = _TIME_RE.match(part)
        if not match:
            raise ValueError(f"{part!r} isn't a time - use HH:MM, e.g. 08:00")
        hour, minute, second = int(match[1]), int(match[2]), int(match[3] or 0)
        if hour > 23 or minute > 59 or second > 59:
            raise ValueError(f"{part!r} isn't a time of day")
        found.add(time(hour, minute, second))
    if not found:
        raise ValueError("Enter at least one scan time, e.g. 08:00")
    return sorted(found)


def format_scan_times(times: list[time]) -> str:
    """"08:00, 20:00:30" - seconds only where set."""
    return ", ".join(t.strftime("%H:%M:%S" if t.second else "%H:%M") for t in times)


def scan_interval(amount: float | int | None, unit: str | None) -> timedelta:
    """The interval for "every <amount> <unit>"; ValueError if out of range."""
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError) as err:
        raise ValueError("The scan interval must be a number") from err
    interval = timedelta(hours=amount) if unit == UNIT_HOURS else timedelta(minutes=amount)
    if interval < MIN_INTERVAL:
        raise ValueError("Scans can't be closer together than every 5 minutes")
    if interval > MAX_INTERVAL:
        raise ValueError("Scan at least once a week (use set times for less often)")
    return interval


def describe(mode: str | None, times: str | None, amount: float | None, unit: str | None) -> str:
    """"At 08:00 and 20:00" / "Every 15 minutes", for the panel."""
    try:
        if mode == MODE_INTERVAL:
            interval = scan_interval(amount, unit)
            minutes = round(interval.total_seconds() / 60)
            if minutes % 60 == 0:
                hours = minutes // 60
                return "Every hour" if hours == 1 else f"Every {hours} hours"
            return f"Every {minutes} minutes"
        parsed = format_scan_times(parse_scan_times(times)).split(", ")
    except ValueError:
        return ""
    return "At " + (parsed[0] if len(parsed) == 1 else ", ".join(parsed[:-1]) + " and " + parsed[-1])
