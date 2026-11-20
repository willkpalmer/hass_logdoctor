"""Notifications when a backup fails.

Like the other notifications, a persistent notification - one per backup
source, so a later failure replaces the earlier one - and, when a phone is
chosen in Settings (the automation failure push device), a push to it.
Failures come from:

- Home Assistant's own backup, as it fails (backup_monitor.py), and its
  backup errors found by a scan (e.g. an upload to a backup location);
- the GDrive Backup Utility add-on: its errors as Home Assistant logs them
  (the add-on forwards its warnings and errors to Home Assistant's log; a
  logging handler picks them up straight away) and those found by a scan
  in either log;
- a backup watched by Uptime Kuma going down (uptime_kuma_backups.py):
  the backup failed, or didn't run in time.

The same failure can be seen twice - as it happens and again by the next
scan - so a source's failures within a few minutes of one already notified
are left out.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .backups import GDRIVE_LOGGER, SOURCE_GDRIVE, SOURCE_NAMES
from .const import NOTIFICATION_ID_BACKUP_FAILURE_PREFIX, PANEL_BACKUPS_URL
from .mobile_push import resolve_mobile_app_notify_service

_LOGGER = logging.getLogger(__name__)

# Failures of one source this close to one already notified are taken to
# be the same failure.
SAME_FAILURE = timedelta(minutes=10)
# Scans can look back further than the last scan (the first one does):
# failures older than this aren't news.
_TOO_OLD = timedelta(hours=24)
# Problems at these levels are failures; warnings aren't.
FAILURE_LEVELS = ("ERROR", "CRITICAL", "FATAL")

_TITLES = {
    "ha": "Home Assistant backup failed",
    "gdrive": "GDrive backup failed",
    "kuma": "Backup failed",
}


class BackupFailureNotifier:
    def __init__(self, hass: HomeAssistant, *, notify_device_id: str | None = None) -> None:
        self.hass = hass
        self.notify_device_id = notify_device_id
        # source -> times of the failures notified (recent ones only).
        self._notified: dict[str, list[datetime]] = {}

    def _seen(self, source: str, when: datetime) -> bool:
        return any(abs(when - seen) <= SAME_FAILURE for seen in self._notified.get(source, ()))

    @callback
    def async_failed(
        self,
        source: str,
        messages: list[str],
        when: datetime | None = None,
        *,
        title: str | None = None,
        key: str | None = None,
    ) -> None:
        """Notify a failure (or several, from one source), unless already notified.

        key: what's notified separately (default: the source), e.g. each
        Uptime Kuma monitor.
        """
        key = key or source
        when = when or dt_util.utcnow()
        if not messages or self._seen(key, when) or dt_util.utcnow() - when > _TOO_OLD:
            return
        recent = [t for t in self._notified.get(key, []) if dt_util.utcnow() - t <= _TOO_OLD]
        self._notified[key] = [*recent, when]
        self.hass.async_create_task(
            self._async_send(source, key, title or _TITLES.get(source, "Backup failed"), messages, when)
        )

    @callback
    def async_scan_problems(self, problems: list[tuple[str, Any]]) -> None:
        """A scan's backup problems ((source, AnomalyReport)): its errors, by source."""
        by_source: dict[str, list[Any]] = {}
        for source, report in problems:
            group = report.group
            if group.level in FAILURE_LEVELS and not self._seen(source, group.last_seen):
                by_source.setdefault(source, []).append(group)
        for source, groups in by_source.items():
            latest = max(group.last_seen for group in groups)
            messages = [group.example_message.split("\n", 1)[0] for group in groups]
            self.async_failed(source, messages, dt_util.as_utc(latest))

    async def _async_send(
        self, source: str, key: str, title: str, messages: list[str], when: datetime
    ) -> None:
        notification_id = f"{NOTIFICATION_ID_BACKUP_FAILURE_PREFIX}{key}"
        at = dt_util.as_local(when).strftime("%Y-%m-%d %H:%M")
        lines = [f"{SOURCE_NAMES.get(source, source)}, at {at}:", ""]
        lines += [f"- {message}" for message in messages[:10]]
        if len(messages) > 10:
            lines.append(f"- …and {len(messages) - 10} more")
        lines += ["", f"[See your backups in Log Doctor]({PANEL_BACKUPS_URL})"]
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {"notification_id": notification_id, "title": title, "message": "\n".join(lines)},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notification failure escalate
            _LOGGER.exception("Failed to post the backup failure notification")

        if not self.notify_device_id:
            return
        service = resolve_mobile_app_notify_service(self.hass, self.notify_device_id)
        if service is None:
            _LOGGER.warning(
                "Can't send the backup failure push: the chosen Mobile App device (%s) "
                "no longer has a notify service",
                self.notify_device_id,
            )
            return
        try:
            await self.hass.services.async_call(
                "notify",
                service,
                {
                    "title": title,
                    "message": messages[0] + (f" (+{len(messages) - 1} more)" if len(messages) > 1 else ""),
                    "data": {"tag": notification_id, "url": PANEL_BACKUPS_URL, "clickAction": PANEL_BACKUPS_URL},
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a notification failure escalate
            _LOGGER.exception("Failed to send the backup failure push via notify.%s", service)


class _GDriveErrorHandler(logging.Handler):
    """The GDrive Backup Utility's errors, as Home Assistant logs them."""

    def __init__(self, hass: HomeAssistant, notifier: BackupFailureNotifier) -> None:
        super().__init__(logging.ERROR)
        self.hass = hass
        self.notifier = notifier

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage().split("\n", 1)[0]
            when = dt_util.utc_from_timestamp(record.created)
            self.hass.loop.call_soon_threadsafe(self.notifier.async_failed, SOURCE_GDRIVE, [message], when)
        except Exception:  # noqa: BLE001 - a logging handler must never raise
            pass


@callback
def async_watch_gdrive_log(hass: HomeAssistant, notifier: BackupFailureNotifier) -> Callable[[], None]:
    """Notify the add-on's errors as they reach Home Assistant's log."""
    handler = _GDriveErrorHandler(hass, notifier)
    logger = logging.getLogger(GDRIVE_LOGGER)
    logger.addHandler(handler)

    @callback
    def _stop() -> None:
        logger.removeHandler(handler)

    return _stop
