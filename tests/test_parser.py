"""Log parsing and restart classification."""
from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.log_doctor.log_parser import (
    filter_and_group,
    parse_log_lines,
    parse_supervisor_log_text,
)
from custom_components.log_doctor.restarts import SHUTDOWN, STARTUP, RestartTracker, Run

NOW = datetime(2026, 10, 6, 12, 0, 0)


def test_core_log_with_traceback():
    lines = [
        "2026-10-06 11:00:00.123 ERROR (MainThread) [homeassistant.components.zha] Boom\n",
        "Traceback (most recent call last):\n",
        '  File "x.py", line 1\n',
        "2026-10-06 11:00:01.000 INFO (MainThread) [homeassistant.core] fine\n",
    ]
    entries = parse_log_lines(lines)
    assert [e.level for e in entries] == ["ERROR", "INFO"]
    assert "Traceback" in entries[0].message
    groups = filter_and_group(entries, "WARNING", None)
    assert len(groups) == 1


def test_supervisor_levels_and_times():
    text = "\n".join(
        [
            "level=info msg=\"loading plugin\"",
            "[12:00:00] WARNING: Retrying",
            "everything is fine, no error here",
            "time=1 level=error msg=boom",
        ]
    )
    entries = parse_supervisor_log_text(text, "Add-on", fallback_timestamp=NOW)
    # "info" isn't an anomaly however its words read; "no error here" isn't
    # a stated level, but the keyword fallback finds the standalone word.
    assert [(e.level, e.timed) for e in entries] == [
        ("WARNING", False),
        ("ERROR", False),
        ("ERROR", False),
    ]


def test_journal_lines_are_utc():
    text = "2026-10-06 10:00:00.000 host proc[1]: ERROR something"
    entries = parse_supervisor_log_text(text, "Host", fallback_timestamp=NOW)
    assert entries and entries[0].timed
    # Shown in local time: the same instant as 10:00 UTC.
    expected = datetime(2026, 10, 6, 10, 0).replace(tzinfo=__import__("datetime").timezone.utc)
    assert entries[0].timestamp.astimezone().replace(tzinfo=None) == expected.astimezone().replace(tzinfo=None)


async def test_phase_of(hass, tmp_path):
    tracker = RestartTracker(hass, log_path=str(tmp_path / "x.log"), grace=timedelta(minutes=3))
    first = Run(NOW - timedelta(hours=5), NOW - timedelta(hours=5) + timedelta(minutes=1), NOW - timedelta(minutes=10))
    second = Run(NOW - timedelta(minutes=8), NOW - timedelta(minutes=6))
    tracker.runs = [first, second]
    assert tracker.phase_of(NOW - timedelta(hours=5) + timedelta(minutes=2)) == (STARTUP, first.id)
    assert tracker.phase_of(NOW - timedelta(hours=2)) is None
    assert tracker.phase_of(NOW - timedelta(minutes=9)) == (SHUTDOWN, first.id)
    assert tracker.phase_of(NOW - timedelta(minutes=4)) == (STARTUP, second.id)
    assert tracker.phase_of(NOW) is None
