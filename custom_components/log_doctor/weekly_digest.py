"""The weekly digest: a summary of the last seven days.

Sent after the daily scan on the chosen day of the week (and on demand,
from Insights or the log_doctor.send_weekly_digest action) as a persistent
notification, a push to the daily summary's notify service if one is set,
and a Markdown file in <config>/logdoctor/reviews/ (weekly_digest.md, plus
a dated copy pruned with the scan reports). It covers:

- the log - new anomalies, still open, startup and shutdown messages, and
  warnings and errors logged compared with the week before;
- the noisiest integrations - which integrations (and add-ons, Host, ...)
  logged the most errors and warnings, with the change on the week before
  (from stats.py);
- automations - runs, failures, missed and stopped runs, the ones failing
  most;
- devices and integrations - open problems, ones that cleared by
  themselves, flapping devices;
- restarts - how many, clean or not, how long startup took;
- backups - the last successful backup and any problems.

Everything comes from the lists Log Doctor keeps anyway; nothing is read
from the log again.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integrations
from homeassistant.util import dt as dt_util

from .const import (
    DATA_ANOMALY_STORE,
    DATA_BACKUP_STORE,
    DATA_FAILURE_STORE,
    DATA_HEALTH_STORE,
    DATA_RESTART_HISTORY,
    DATA_RUN_STORE,
    DATA_STATS,
    NOTIFICATION_ID_WEEKLY_DIGEST,
    PANEL_INSIGHTS_URL,
)
from .paths import reviews_dir
from .stats import KIND_INTEGRATION, LEVELS

_LOGGER = logging.getLogger(__name__)

DAYS = 7
# Rows in the noisiest integrations ranking, and items in other lists.
TOP_SOURCES = 10
TOP_ITEMS = 5
LATEST_FILENAME = "weekly_digest.md"


@dataclass
class WeeklyDigest:
    title: str
    markdown: str
    push_title: str
    push_message: str
    data: dict[str, Any] = field(default_factory=dict)


def _records(hass: HomeAssistant, key: str) -> list[dict[str, Any]]:
    store = hass.data.get(key)
    return list(store.records) if store is not None else []


def _plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count:,} {one if count == 1 else (many or one + 's')}"


def _change(now: int, before: int) -> str:
    if before == 0:
        return "new" if now else "-"
    pct = round((now - before) * 100 / before)
    return f"{'+' if pct > 0 else ''}{pct}%"


def _versus(now: int, before: int) -> str:
    """"+53% on the week before", "none the week before", ..."""
    if before == 0:
        return "none the week before" if now else "none the week before either"
    if now == before:
        return "the same as the week before"
    return f"{_change(now, before)} on the week before"


async def _source_names(hass: HomeAssistant, rows: list[dict[str, Any]]) -> dict[str, str]:
    domains = {row["source"] for row in rows if row["kind"] == KIND_INTEGRATION}
    names: dict[str, str] = {}
    if domains:
        try:
            found = await async_get_integrations(hass, domains)
        except Exception:  # noqa: BLE001 - fall back to domains
            found = {}
        for domain in domains:
            integration = found.get(domain)
            if integration is not None and not isinstance(integration, Exception):
                names[domain] = integration.name
    return names


async def async_build_digest(hass: HomeAssistant, now: datetime | None = None) -> WeeklyDigest:
    now = dt_util.as_utc(now or dt_util.utcnow())
    start = now - timedelta(days=DAYS)
    since = start.isoformat()
    data: dict[str, Any] = {"start": since, "end": now.isoformat()}

    # -- the log ------------------------------------------------------------
    anomalies = _records(hass, DATA_ANOMALY_STORE)
    fresh = [
        r for r in anomalies
        if (r.get("first_seen") or "") >= since and not r.get("ignored")
    ]
    rank = {"CRITICAL": 3, "ERROR": 2, "WARNING": 1}
    fresh.sort(key=lambda r: (rank.get(r.get("level"), 0), r.get("count", 0)), reverse=True)
    operational = [r for r in fresh if r.get("category") != "restart"]
    data["logs"] = {
        "new": len(operational),
        "new_restart": len(fresh) - len(operational),
        "open": sum(
            1 for r in anomalies
            if not r.get("resolved") and not r.get("ignored") and r.get("category") != "restart"
        ),
        "top": [
            {k: r.get(k) for k in ("id", "level", "logger", "message", "count")}
            for r in operational[:TOP_ITEMS]
        ],
    }

    stats = hass.data.get(DATA_STATS)
    if stats is not None:
        this_week = stats.ranking(DAYS, now)
        last_week = {row["source"]: row for row in stats.ranking(DAYS, now - timedelta(days=DAYS))}
        names = await _source_names(hass, this_week[:TOP_SOURCES])
        data["levels"] = {
            "this": stats.totals(DAYS, now),
            "previous": stats.totals(DAYS, now - timedelta(days=DAYS)),
        }
        data["noise"] = [
            {
                **row,
                "name": names.get(row["source"], row["source"]),
                "previous_total": last_week.get(row["source"], {}).get("total", 0),
            }
            for row in this_week[:TOP_SOURCES]
        ]
    else:
        data["levels"] = {"this": {}, "previous": {}}
        data["noise"] = []

    # -- automations --------------------------------------------------------
    failures = [r for r in _records(hass, DATA_FAILURE_STORE) if (r.get("when") or "") >= since]
    kinds = Counter((r.get("reason") or "").split(":", 1)[0] for r in failures)
    failing = Counter(
        (r.get("name"), r.get("entity_id"))
        for r in failures if (r.get("reason") or "").startswith("Failed:")
    )
    runs = [
        r for r in _records(hass, DATA_RUN_STORE)
        if r.get("kind") == "run" and (r.get("when") or "") >= since
    ]
    busiest = Counter((r.get("name"), r.get("entity_id")) for r in runs)
    data["automations"] = {
        "runs": len(runs),
        "failed": kinds.get("Failed", 0),
        "missed": kinds.get("Missed", 0),
        "stopped": kinds.get("Stopped", 0),
        "top_failing": [
            {"name": name, "entity_id": entity_id, "count": count}
            for (name, entity_id), count in failing.most_common(TOP_ITEMS)
        ],
        "busiest": [
            {"name": name, "entity_id": entity_id, "count": count}
            for (name, entity_id), count in busiest.most_common(TOP_ITEMS)
        ],
        "stopped_names": [
            r.get("name") for r in failures if (r.get("reason") or "").startswith("Stopped:")
        ][:TOP_ITEMS],
    }

    # -- devices & integrations ---------------------------------------------
    health = _records(hass, DATA_HEALTH_STORE)
    open_health = [
        r for r in health
        if not r.get("resolved") and not r.get("ignored") and not r.get("unmonitored")
    ]
    data["health"] = {
        "open": dict(Counter(r.get("kind") for r in open_health)),
        "cleared": sum(
            1 for r in health if r.get("recovered") and (r.get("resolved") or "") >= since
        ),
        "flapping": [
            {"name": r.get("name"), "detail": r.get("detail")}
            for r in health if r.get("kind") == "flapping" and r.get("active") and not r.get("unmonitored")
        ][:TOP_ITEMS],
    }

    # -- restarts -------------------------------------------------------------
    restarts = [r for r in _records(hass, DATA_RESTART_HISTORY) if (r.get("starting") or "") >= since]
    startup = []
    for r in restarts:
        begun, done = dt_util.parse_datetime(r.get("starting") or ""), dt_util.parse_datetime(r.get("started") or "")
        if begun and done:
            startup.append(((done - begun).total_seconds(), r.get("starting")))
    slowest = max(startup) if startup else None
    data["restarts"] = {
        "count": len(restarts),
        "unclean": sum(1 for r in restarts if r.get("unclean")),
        "average_startup": round(mean(s for s, _ in startup)) if startup else None,
        "slowest_startup": round(slowest[0]) if slowest else None,
        "slowest_at": slowest[1] if slowest else None,
        "messages": sum(r.get("messages", 0) for r in restarts),
    }

    # -- backups --------------------------------------------------------------
    backups = _records(hass, DATA_BACKUP_STORE)
    successes = [r.get("last_logged") or r.get("last_seen") for r in backups if r.get("kind") == "success"]
    data["backups"] = {
        "last_success": max((s for s in successes if s), default=None),
        "problems": sum(
            1 for r in backups
            if r.get("kind") != "success" and (r.get("last_seen") or "") >= since and not r.get("ignored")
        ),
    }

    return _render(data, now)


def _local(iso: str | None, fmt: str = "%a %d %b %H:%M") -> str:
    when = dt_util.parse_datetime(iso or "")
    return dt_util.as_local(when).strftime(fmt) if when else "-"


def _seconds(value: float | None) -> str:
    if value is None:
        return "-"
    minutes, seconds = divmod(int(value), 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def _render(data: dict[str, Any], now: datetime) -> WeeklyDigest:
    period = f"{_local(data['start'], '%d %b')} - {_local(data['end'], '%d %b %Y')}"
    title = f"Log Doctor weekly digest · {period}"
    logs, autos, health = data["logs"], data["automations"], data["health"]
    restarts, backups = data["restarts"], data["backups"]
    this, previous = data["levels"]["this"], data["levels"]["previous"]
    errors = this.get("ERROR", 0) + this.get("CRITICAL", 0)
    errors_before = previous.get("ERROR", 0) + previous.get("CRITICAL", 0)
    open_health = sum(health["open"].values())

    md = [f"# {title}", ""]
    md += [
        "## At a glance",
        "",
        f"- **Log:** {_plural(logs['new'], 'new anomaly', 'new anomalies')}, "
        f"{logs['open']:,} open on the Log review",
        f"- **Errors logged:** {errors:,} ({_versus(errors, errors_before)}), "
        f"**warnings:** {this.get('WARNING', 0):,} "
        f"({_versus(this.get('WARNING', 0), previous.get('WARNING', 0))})",
        f"- **Automations:** {_plural(autos['runs'], 'run')}, {autos['failed']:,} failed, "
        f"{autos['missed']:,} missed, {autos['stopped']:,} stopped",
        f"- **Devices & integrations:** {_plural(open_health, 'open problem')}, "
        f"{health['cleared']:,} cleared by themselves",
        f"- **Restarts:** {restarts['count']:,} ({restarts['unclean']:,} not clean)",
        f"- **Backups:** last success {_local(backups['last_success']) if backups['last_success'] else 'not seen in the log'}, "
        f"{_plural(backups['problems'], 'problem')}",
        "",
    ]

    md += ["## Noisiest integrations", ""]
    if data["noise"]:
        md += ["| | Source | Errors | Warnings | Total | Week before |", "|---|---|---:|---:|---:|---:|"]
        for number, row in enumerate(data["noise"], 1):
            row_errors = row.get("ERROR", 0) + row.get("CRITICAL", 0)
            md.append(
                f"| {number} | {row['name']} | {row_errors:,} | {row.get('WARNING', 0):,} | "
                f"{row['total']:,} | {row['previous_total']:,} ({_change(row['total'], row['previous_total'])}) |"
            )
    else:
        md.append("No warnings or errors logged this week. 🎉")
    md.append("")

    md += ["## New in the log", ""]
    if logs["top"]:
        for r in logs["top"]:
            md.append(f"- **{r['level']}** × {r['count']} `{r['logger']}` - {(r['message'] or '')[:160]}")
        if logs["new"] > len(logs["top"]):
            md.append(f"- … and {logs['new'] - len(logs['top']):,} more")
    else:
        md.append("Nothing new.")
    if logs["new_restart"]:
        md.append(f"- Plus {_plural(logs['new_restart'], 'new startup or shutdown message')}")
    md.append("")

    md += ["## Automations", ""]
    if autos["top_failing"]:
        md.append("Failing most:")
        md += [f"- {a['name']} (`{a['entity_id']}`) × {a['count']}" for a in autos["top_failing"]]
    if autos["stopped_names"]:
        md.append("Stopped running: " + ", ".join(str(n) for n in autos["stopped_names"]))
    if autos["busiest"]:
        md.append("Ran most: " + ", ".join(f"{a['name']} × {a['count']:,}" for a in autos["busiest"][:3]))
    if not (autos["top_failing"] or autos["stopped_names"] or autos["busiest"]):
        md.append("No runs or failures recorded.")
    md.append("")

    md += ["## Devices & integrations", ""]
    if open_health:
        md.append("Open: " + ", ".join(f"{count} {kind}" for kind, count in sorted(health["open"].items())))
    if health["flapping"]:
        md.append("Flapping: " + ", ".join(f"{f['name']} ({f['detail']})" for f in health["flapping"]))
    if not open_health and not health["flapping"]:
        md.append("No open problems. 🎉")
    md.append("")

    md += ["## Restarts", ""]
    if restarts["count"]:
        line = f"{_plural(restarts['count'], 'restart')}"
        if restarts["average_startup"] is not None:
            line += (
                f"; startup took {_seconds(restarts['average_startup'])} on average, the slowest "
                f"{_seconds(restarts['slowest_startup'])} ({_local(restarts['slowest_at'])})"
            )
        md.append(f"{line}. {_plural(restarts['messages'], 'message')} logged while starting or stopping.")
    else:
        md.append("No restarts.")
    md += ["", f"[Open Insights in Log Doctor]({PANEL_INSIGHTS_URL})", ""]

    push_title = f"Log Doctor week: {_plural(logs['new'], 'new anomaly', 'new anomalies')}"
    noisiest = data["noise"][0]["name"] if data["noise"] else None
    change = _change(errors, errors_before)
    push_message = (
        f"{errors:,} errors" + (f" ({change})" if errors_before else "") + f", {autos['failed']:,} automation failures, "
        f"{open_health:,} device/integration problems, {restarts['count']:,} restarts."
        + (f" Noisiest: {noisiest}." if noisiest else "")
    )
    return WeeklyDigest(
        title=title,
        markdown="\n".join(md),
        push_title=push_title,
        push_message=push_message,
        data=data,
    )


def _write_sync(directory: Path, markdown: str, now: datetime, retention_days: int) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    dated = directory / f"weekly_digest_{dt_util.as_local(now).strftime('%Y-%m-%d')}.md"
    dated.write_text(markdown, encoding="utf-8")
    (directory / LATEST_FILENAME).write_text(markdown, encoding="utf-8")
    if retention_days > 0:
        cutoff = datetime.now().timestamp() - retention_days * 86400
        for existing in directory.glob("weekly_digest_*.md"):
            try:
                if existing.stat().st_mtime < cutoff:
                    existing.unlink()
            except OSError:
                continue
    return str(dated)


async def async_send_digest(
    hass: HomeAssistant,
    *,
    mobile_notify_service: str | None,
    retention_days: int,
) -> WeeklyDigest:
    """Build the digest and send it: notification, push, file."""
    digest = await async_build_digest(hass)
    try:
        await hass.async_add_executor_job(
            _write_sync, reviews_dir(hass), digest.markdown, dt_util.utcnow(), retention_days
        )
    except OSError:
        _LOGGER.exception("Could not write the weekly digest file")
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "notification_id": NOTIFICATION_ID_WEEKLY_DIGEST,
            "title": digest.title,
            # The notification has its own title.
            "message": digest.markdown.split("\n", 2)[2],
        },
        blocking=True,
    )
    if mobile_notify_service:
        try:
            await hass.services.async_call(
                "notify",
                mobile_notify_service,
                {
                    "title": digest.push_title,
                    "message": digest.push_message,
                    "data": {"tag": NOTIFICATION_ID_WEEKLY_DIGEST, "url": PANEL_INSIGHTS_URL},
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - never let a bad notify target break the digest
            _LOGGER.exception("Failed to send the weekly digest via notify.%s", mobile_notify_service)
    return digest
