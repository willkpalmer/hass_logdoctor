"""Persist each scan's full report to disk so it survives past the
persistent notification (which is overwritten every run, and can be
dismissed by the user).

Reports are written under `<config>/logdoctor/reviews/` as one timestamped
Markdown file per run, plus a `latest.md` that always mirrors the most
recent one. Old dated files are pruned on a retention window; `latest.md`
is never pruned. (The same window also prunes old automation failures -
see failure_store.py - after each scan, in coordinator.py.)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import LATEST_REPORT_FILENAME
from .paths import reviews_dir

_LOGGER = logging.getLogger(__name__)


def _write_report_sync(
    reports_dir: Path,
    report_markdown: str,
    scanned_at: datetime,
    retention_days: int,
) -> str:
    reports_dir.mkdir(parents=True, exist_ok=True)

    filename = f"log_doctor_report_{scanned_at.strftime('%Y-%m-%d_%H%M%S')}.md"
    report_path = reports_dir / filename
    report_path.write_text(report_markdown, encoding="utf-8")

    latest_path = reports_dir / LATEST_REPORT_FILENAME
    latest_path.write_text(report_markdown, encoding="utf-8")

    if retention_days > 0:
        cutoff = datetime.now() - timedelta(days=retention_days)
        for existing in reports_dir.glob("log_doctor_report_*.md"):
            try:
                mtime = datetime.fromtimestamp(existing.stat().st_mtime)
            except OSError:
                continue
            if mtime < cutoff:
                try:
                    existing.unlink()
                except OSError:
                    _LOGGER.debug("Could not prune old report %s", existing)

    return str(report_path)


async def async_write_report(
    hass: HomeAssistant,
    report_markdown: str,
    scanned_at: datetime,
    retention_days: int,
) -> str:
    """Write the report to disk (via the executor) and return its path."""
    return await hass.async_add_executor_job(
        _write_report_sync,
        reviews_dir(hass),
        report_markdown,
        scanned_at,
        retention_days,
    )
