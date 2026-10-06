"""Diagnostics for WP Log Doctor (Settings → Devices & services → WP Log
Doctor → ⋮ → Download diagnostics).

What it's set to and the state of what it keeps, for troubleshooting Log
Doctor itself. The OpenAI API key is redacted; log messages, entity ids
and names aren't included, only counts, times and the last scan's summary.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_OPENAI_API_KEY,
    DATA_ANOMALY_STORE,
    DATA_BACKUP_STORE,
    DATA_FAILURE_STORE,
    DATA_FLAPS,
    DATA_HEALTH_STORE,
    DATA_RESTART_HISTORY,
    DATA_RUN_STORE,
    DATA_STATS,
    DOMAIN,
)
from .review_list import ReviewList

TO_REDACT = {CONF_OPENAI_API_KEY}

_LISTS = {
    "anomalies": DATA_ANOMALY_STORE,
    "failures": DATA_FAILURE_STORE,
    "health": DATA_HEALTH_STORE,
    "backups": DATA_BACKUP_STORE,
    "restart_history": DATA_RESTART_HISTORY,
    "automation_runs": DATA_RUN_STORE,
}


def _tab(record: dict[str, Any]) -> str:
    if record.get("unmonitored"):
        return "not_monitored"
    if record.get("ignored"):
        return "ignored"
    return "archived" if record.get("resolved") else "open"


def _list_summary(review_list: ReviewList) -> dict[str, Any]:
    records = review_list.records
    summary: dict[str, Any] = {
        "records": len(records),
        "max_records": review_list.max_records,
        "tabs": dict(Counter(_tab(r) for r in records)),
    }
    kinds = Counter(r.get("kind") or r.get("category") for r in records)
    kinds.pop(None, None)
    if kinds:
        summary["kinds"] = dict(kinds)
    return summary


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    result: dict[str, Any] = {
        "entry": {
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "loaded": coordinator is not None,
        "lists": {
            name: _list_summary(review_list)
            for name, key in _LISTS.items()
            if (review_list := hass.data.get(key)) is not None
        },
    }
    if coordinator is not None:
        data = coordinator.store.data
        result["scan"] = {
            "log_path": coordinator.log_path,
            "last_scan": data.last_scan.isoformat() if data.last_scan else None,
            "last_summary": data.last_summary,
            "signatures_remembered": len(data.seen_signatures),
            "untimed_lines_remembered": {
                source: sum(seen.values()) for source, seen in data.untimed_seen.items()
            },
            "auto_investigate": data.auto_investigate,
            "openai_api_key_set": bool(coordinator.openai_api_key),
            "investigation_model": coordinator.investigation_model,
            "last_weekly_digest": data.last_digest,
        }
        if coordinator.restarts is not None:
            result["restarts"] = {
                "grace_minutes": coordinator.restarts.grace.total_seconds() / 60,
                "runs": [
                    {
                        "starting": run.starting.isoformat(),
                        "started": run.started.isoformat() if run.started else None,
                        "stopping": run.stopping.isoformat() if run.stopping else None,
                    }
                    for run in coordinator.restarts.runs[-10:]
                ],
            }
    if (stats := hass.data.get(DATA_STATS)) is not None:
        result["stats"] = {
            "hours_kept": len(stats.hours),
            "days_kept": len(stats.days),
            "last_7_days": stats.totals(7),
        }
    if (flaps := hass.data.get(DATA_FLAPS)) is not None:
        result["flapping"] = {
            "threshold": flaps.count,
            "window_hours": flaps.window.total_seconds() / 3600,
            "devices_flapping": len(flaps.flapping()),
        }
    return result
