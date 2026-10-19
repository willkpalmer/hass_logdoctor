"""Scan schedules: several times a day, or every so often."""
from __future__ import annotations

from datetime import time, timedelta

import pytest

from custom_components.log_doctor.config_flow import _build_schema, validate_schedule
from custom_components.log_doctor.schedule import describe, parse_scan_times, scan_interval


def test_parse_scan_times():
    assert parse_scan_times("20:00, 08:00,8:00; 13.30") == [time(8), time(13, 30), time(20)]
    assert parse_scan_times("08:00:00") == [time(8)]  # stored before 0.45.0
    for bad in ("", "25:00", "8", "noon", "08:00, 7pm"):
        with pytest.raises(ValueError):
            parse_scan_times(bad)


def test_scan_interval():
    assert scan_interval(15, "minutes") == timedelta(minutes=15)
    assert scan_interval(6, "hours") == timedelta(hours=6)
    for amount, unit in ((4, "minutes"), (0, "hours"), (200, "hours")):
        with pytest.raises(ValueError):
            scan_interval(amount, unit)
    assert describe("interval", None, 1, "hours") == "Every hour"
    assert describe("times", "20:00, 08:00", None, None) == "At 08:00 and 20:00"


async def test_settings_validation(hass):
    options = _build_schema(hass, {})({"scan_time": "20:00,08:00"})
    assert options["scan_mode"] == "times"
    assert validate_schedule(options) == {}
    assert options["scan_time"] == "08:00, 20:00"
    assert validate_schedule({"scan_mode": "times", "scan_time": "later"}) == {"scan_time": "invalid_scan_time"}
    assert validate_schedule({"scan_mode": "interval", "scan_interval": 2, "scan_interval_unit": "minutes", "scan_time": "08:00"}) == {"scan_interval": "invalid_scan_interval"}
    # Times aren't needed when scanning every so often.
    assert validate_schedule({"scan_mode": "interval", "scan_interval": 30, "scan_interval_unit": "minutes", "scan_time": ""}) == {}
