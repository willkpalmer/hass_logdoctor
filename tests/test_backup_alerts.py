"""Backups watched by Uptime Kuma, and backup failure notifications."""
from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.log_doctor.backup_notify import BackupFailureNotifier, async_watch_gdrive_log
from custom_components.log_doctor.backup_store import BackupStore
from custom_components.log_doctor.uptime_kuma_backups import UptimeKumaBackupWatch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_setup_failures import _entry  # noqa: E402


def _calls(hass):
    calls = []

    async def _record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("persistent_notification", "create", _record)
    return calls


def _monitor(hass, kuma, name, key):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=kuma.entry_id, identifiers={("uptime_kuma", key)}, name=name
    )
    return er.async_get(hass).async_get_or_create(
        "sensor", "uptime_kuma", f"{kuma.entry_id}_{key}_status", config_entry=kuma, device_id=device.id
    ).entity_id


async def test_uptime_kuma_backup_monitor(hass):
    hass.set_state(CoreState.running)
    calls = _calls(hass)
    kuma = _entry(hass, "uptime_kuma", ConfigEntryState.LOADED)
    nvme = _monitor(hass, kuma, "utils.camelot NVMe Backup", "7")
    website = _monitor(hass, kuma, "Website", "8")
    store = BackupStore(hass)
    watch = UptimeKumaBackupWatch(hass, store, BackupFailureNotifier(hass))
    stop = watch.async_start()
    await hass.async_block_till_done()

    hass.states.async_set(nvme, "up")
    hass.states.async_set(website, "down")  # not a backup
    await hass.async_block_till_done()
    assert [(r["kind"], r["source"]) for r in store.records] == [("success", "kuma")]
    assert "utils.camelot NVMe Backup" in store.records[0]["message"]

    # Unavailable and back (a restart, a reload): nothing new.
    hass.states.async_set(nvme, "unavailable")
    hass.states.async_set(nvme, "up")
    hass.states.async_set(nvme, "pending")
    await hass.async_block_till_done()
    assert len(store.records) == 1 and store.records[0]["count"] == 1
    assert calls == []

    hass.states.async_set(nvme, "down")
    await hass.async_block_till_done()
    problem = next(r for r in store.records if r["kind"] == "problem")
    assert "didn't run in time" in problem["message"]
    assert len(calls) == 1 and calls[0][2]["title"] == "Backup failed: utils.camelot NVMe Backup"
    assert watch.monitors == {nvme: "utils.camelot NVMe Backup"}
    stop()
    await store.async_shutdown()


async def test_notifier_leaves_out_the_same_failure_twice(hass):
    calls = _calls(hass)
    notifier = BackupFailureNotifier(hass)
    now = dt_util.utcnow()
    notifier.async_failed("ha", ["Backup failed: upload failed"], now)
    await hass.async_block_till_done()
    # The next scan finds its log lines: the same failure.
    report = SimpleNamespace(group=SimpleNamespace(level="ERROR", last_seen=now + timedelta(seconds=5), example_message="Upload failed\ntraceback"))
    warning = SimpleNamespace(group=SimpleNamespace(level="WARNING", last_seen=now + timedelta(hours=1), example_message="Slow"))
    notifier.async_scan_problems([("ha", report), ("gdrive", warning)])
    await hass.async_block_till_done()
    assert len(calls) == 1
    # A later error, and another source's: notified.
    later = SimpleNamespace(group=SimpleNamespace(level="ERROR", last_seen=now + timedelta(hours=1), example_message="Upload failed"))
    notifier.async_scan_problems([("ha", later), ("gdrive", later)])
    await hass.async_block_till_done()
    assert [c[2]["notification_id"] for c in calls[1:]] == ["log_doctor_backup_failed_ha", "log_doctor_backup_failed_gdrive"]
    # Too old to be news (a first scan looking back).
    old = SimpleNamespace(group=SimpleNamespace(level="ERROR", last_seen=now - timedelta(days=3), example_message="Old"))
    notifier.async_scan_problems([("gdrive", old)])
    await hass.async_block_till_done()
    assert len(calls) == 3


async def test_gdrive_errors_as_logged(hass):
    calls = _calls(hass)
    stop = async_watch_gdrive_log(hass, BackupFailureNotifier(hass))
    logging.getLogger("hass_gdrive_backup.drive").error("Upload to Google Drive failed")
    logging.getLogger("hass_gdrive_backup").warning("Just a warning")
    await hass.async_block_till_done()
    stop()
    assert len(calls) == 1
    assert "Upload to Google Drive failed" in calls[0][2]["message"]
    assert calls[0][2]["title"] == "GDrive backup failed"
