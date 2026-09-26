"""Telling backup log messages apart from everything else.

Backup messages go to the Log Doctor panel's "Backups" view (see
backup_store.py) instead of the general Log review, so a failing backup
shows up in one place only. Two sources are recognised:

- "ha": Home Assistant's built-in backup - the backup integration
  (homeassistant.components.backup.*), the backup platforms of other
  integrations that store backups (homeassistant.components.<x>.backup,
  e.g. hassio, cloud, google_drive, onedrive), and Supervisor's backup
  manager (supervisor.backups.*, from the Supervisor log).
- "gdrive": the GDrive Backup Utility add-on
  (https://github.com/willkpalmer/hass_gdrive_backup), whose logger names
  all start with "hass_gdrive_backup" (see its LOGGING.md). Its warnings
  and errors are forwarded to home-assistant.log, and everything from INFO
  up is in the add-on's own log, read through the Supervisor.

Warnings and worse from either source are backup problems. The add-on's
INFO lines saying a backup finished or was uploaded are backup successes;
Home Assistant's own backup doesn't log its successes, so those come from
its backup manager instead (see backup_monitor.py).
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta

from .log_parser import LogEntry

SOURCE_HA = "ha"
SOURCE_GDRIVE = "gdrive"

# The add-on's slug and the prefix of all of its logger names. Installed
# from a repository, the slug gets a prefix: "<hash>_hass_gdrive_backup".
GDRIVE_LOGGER = "hass_gdrive_backup"
GDRIVE_SLUG = "hass_gdrive_backup"
GDRIVE_NAME = "GDrive Backup Utility"

_HA_LOGGER_RE = re.compile(
    r"^(?:homeassistant\.components\.(?:backup(?:\..+)?|[^.]+\.backup)"
    r"|supervisor\.backups(?:\..+)?)$"
)

# Longest expected gap between the add-on logging a message and it
# appearing in home-assistant.log.
_FORWARD_DELAY = timedelta(minutes=1)

# The add-on's INFO messages for a finished backup (ha/hasource.py) and a
# finished upload (drive/drivesource.py), matched on the first line.
_SUCCESS_RES = {
    SOURCE_GDRIVE: [
        re.compile(r"^Backup finished\b"),
        re.compile(r"^Uploaded '.*' to Google Drive\b"),
    ],
}


def is_gdrive_addon(slug: str, name: str) -> bool:
    """Whether a Supervisor add-on log source is the GDrive Backup Utility's.

    Only its lines in Home Assistant's log format are read (see
    log_parser.parse_supervisor_log_text's structured_only): versions
    before 0.9.0 logged in another format, so their lines are dropped,
    and every version since uses this one.
    """
    return slug == GDRIVE_SLUG or slug.endswith(f"_{GDRIVE_SLUG}") or name == GDRIVE_NAME


def _split_logger(logger: str) -> str:
    """The logger name without a Supervisor source prefix.

    Lines from Supervisor-managed logs have a "<source name>:" prefix (see
    log_parser.parse_supervisor_log_text); logger names never contain ":".
    """
    return logger.rpartition(":")[2]


def backup_source(logger: str) -> str | None:
    """SOURCE_HA or SOURCE_GDRIVE for a backup message's logger, else None."""
    name = _split_logger(logger)
    if name == GDRIVE_LOGGER or name.startswith(f"{GDRIVE_LOGGER}."):
        return SOURCE_GDRIVE
    if _HA_LOGGER_RE.match(name):
        return SOURCE_HA
    return None


def canonical_logger(logger: str) -> str:
    """The add-on's messages under the same logger in either log.

    Its warnings and errors appear both in its own log (with a source
    prefix) and in home-assistant.log (without); dropping the prefix groups
    the two copies of a message together.
    """
    name = _split_logger(logger)
    if name == GDRIVE_LOGGER or name.startswith(f"{GDRIVE_LOGGER}."):
        return name
    return logger


def _first_line(entry: LogEntry) -> str:
    return entry.message.split("\n", 1)[0]


def is_backup_success(source: str, entry: LogEntry) -> bool:
    if entry.level != "INFO":
        return False
    return any(pattern.search(_first_line(entry)) for pattern in _SUCCESS_RES.get(source, ()))


def split_backup_entries(
    entries: list[LogEntry],
) -> tuple[list[LogEntry], dict[str, list[LogEntry]]]:
    """Split parsed log entries into (everything else, backup entries by source).

    Backup entries get their canonical logger (see canonical_logger). The
    add-on's warnings and errors forwarded to home-assistant.log are
    dropped when its own log has the same message shortly before, so one
    problem isn't counted twice.
    """
    other: list[LogEntry] = []
    backups: dict[str, list[LogEntry]] = {}
    forwarded: list[LogEntry] = []
    in_addon_log: dict[tuple[str, str], list[datetime]] = {}
    for entry in entries:
        source = backup_source(entry.logger)
        if source is None:
            other.append(entry)
            continue
        logger = canonical_logger(entry.logger)
        if source == SOURCE_GDRIVE and logger == entry.logger:
            forwarded.append(entry)
            continue
        if logger != entry.logger:
            in_addon_log.setdefault((logger, _first_line(entry)), []).append(entry.timestamp)
            entry = replace(entry, logger=logger)
        backups.setdefault(source, []).append(entry)

    for entry in forwarded:
        if not any(
            timedelta(0) <= entry.timestamp - seen <= _FORWARD_DELAY
            for seen in in_addon_log.get((entry.logger, _first_line(entry)), ())
        ):
            backups.setdefault(SOURCE_GDRIVE, []).append(entry)
    return other, backups
