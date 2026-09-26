"""Where Log Doctor keeps its files under the Home Assistant config folder.

    <config>/logdoctor/
        automation_failures.log   - one line per automation failure
        reviews/                  - the scheduled scan reviews: one report
                                    per run, latest.md, and investigation
                                    findings

Before 0.15.0 everything lived flat in <config>/log_doctor_reports/;
migrate_legacy_folder_sync() moves it into this layout once.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import (
    FAILURE_LOG_FILENAME,
    LEGACY_REPORTS_DIR_NAME,
    LOGDOCTOR_DIR_NAME,
    REVIEWS_DIR_NAME,
)

_LOGGER = logging.getLogger(__name__)


def logdoctor_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(LOGDOCTOR_DIR_NAME))


def reviews_dir(hass: HomeAssistant) -> Path:
    return logdoctor_dir(hass) / REVIEWS_DIR_NAME


def failure_log_path(hass: HomeAssistant) -> Path:
    return logdoctor_dir(hass) / FAILURE_LOG_FILENAME


def migrate_legacy_folder_sync(config_dir: Path) -> None:
    """Move files from the old flat log_doctor_reports/ folder.

    The failure log goes to logdoctor/, everything else to
    logdoctor/reviews/. A file is left where it is if something with the
    same name already exists at its destination, so nothing is ever
    overwritten; the old folder is removed only once it's empty.
    """
    legacy = config_dir / LEGACY_REPORTS_DIR_NAME
    if not legacy.is_dir():
        return
    main = config_dir / LOGDOCTOR_DIR_NAME
    reviews = main / REVIEWS_DIR_NAME
    reviews.mkdir(parents=True, exist_ok=True)

    for item in legacy.iterdir():
        target = (main if item.name == FAILURE_LOG_FILENAME else reviews) / item.name
        if target.exists():
            _LOGGER.warning(
                "Not moving %s: %s already exists; the old copy was left in place",
                item,
                target,
            )
            continue
        try:
            shutil.move(str(item), str(target))
        except OSError:
            _LOGGER.warning("Could not move %s to %s", item, target, exc_info=True)

    try:
        legacy.rmdir()
        _LOGGER.info("Moved Log Doctor's files from %s to %s", legacy, main)
    except OSError:
        pass  # not empty: something was left behind (see warnings above)
