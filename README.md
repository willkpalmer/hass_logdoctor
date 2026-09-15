# Log Doctor

A Home Assistant custom integration that periodically reads your Home
Assistant log, groups the warnings/errors it finds into anomalies, checks
them against a built-in knowledge base, and (optionally) searches GitHub
for related issues and fixes — then reports everything to you once a day.

**Log Doctor never modifies your configuration, restarts anything, or
applies any fix automatically.** It is strictly read-only / report-only,
in the same spirit as [Spook](https://github.com/frenck/spook) — it looks
inward at your Home Assistant instance and outward at public sources for
context, but every action it takes is a report, never a change.

## What it does

1. On a schedule you choose (default: daily at 08:00), it reads your
   `home-assistant.log` file in full.
2. **On Home Assistant OS or Supervised installs**, it also checks every
   other log source shown in the dropdown on **Settings → System → Logs**
   - Supervisor, Host, DNS, Audio, CLI, Multicast, and every installed
   add-on - by talking to the Supervisor API directly (the same mechanism
   that page itself uses). Home Assistant Core can't read those as plain
   files; they only exist in separate containers/journald. This is
   automatic and needs no setup, and is silently skipped on a Core-only
   install (Docker/Container/venv) where there's no Supervisor to ask. It
   can be turned off in configuration if you'd rather it only checked
   `home-assistant.log`.
3. Warning/error/critical lines are grouped into "anomalies" by a
   normalized signature, so 50 occurrences of the same underlying problem
   show up as one entry with a count, not 50 separate reports.
4. Each anomaly is checked against a bundled knowledge base of common,
   well-known Home Assistant issues (database locks, blocking calls,
   deprecated config, SSL errors, MQTT/Zigbee/Z-Wave network issues,
   auth failures, etc.) for an instant explanation and suggested fix.
5. Anything not covered by the built-in knowledge base is (optionally)
   looked up live via the GitHub issue search API, scoped to
   `home-assistant/core` for built-in integrations or a best-effort search
   for custom components, so you get links to relevant existing issues and
   their resolution status.
6. **Every scan produces a full report, even when nothing is wrong** — it
   always states what log file was read, the time window covered, how many
   lines/entries were checked, and how many were matched against the
   knowledge base or GitHub, so a clean run is evidence of a real check
   rather than a blank "no errors" message. It reaches you as:
   - A **persistent notification** in Home Assistant (Settings bell icon),
     rebuilt each scan - kept short on purpose: the scan summary, plus just
     the totals of new vs. still-occurring anomalies (e.g. "New anomalies:
     2", "Still occurring: 1"), not a write-up of every single one.
   - The **full** report - every anomaly's message, known fix, and GitHub
     matches - written to disk as a Markdown file each run, so it survives
     past the notification being dismissed or overwritten by the next scan
     (see [Retained reports](#retained-reports) below), and exposed in full
     on `sensor.log_doctor_anomalies`'s attributes for dashboards/
     automations.
   - Optionally, a short push notification via any `notify.*` mobile app
     service.

## Installation

### HACS (custom repository)

1. In HACS, go to the three-dot menu → **Custom repositories**.
2. Add `https://github.com/willkpalmer/hass_logreview` as category
   **Integration**.
3. Install **Log Doctor**, then restart Home Assistant.

### Manual

1. Copy `custom_components/log_doctor` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

## Setup

1. Go to **Settings → Devices & Services → Add Integration** and search for
   **Log Doctor**.
2. Configure:
   - **Log file path** — defaults to your instance's
     `home-assistant.log`.
   - **Daily scan time** — when the automatic daily scan runs.
   - **Minimum severity to report** — `WARNING`, `ERROR`, or `CRITICAL`.
   - **Lookback window** — how far back to look on the very first scan.
   - **GitHub lookup** — enable/disable live searches for unmatched
     anomalies, plus an optional personal access token to raise GitHub's
     rate limit from ~10 requests/minute to ~30, and a cap on how many
     searches one scan can make.
   - **Mobile notify service** — e.g. `mobile_app_pixel_10_pro_xl`, to also
     get a push notification summary. Leave blank to skip.
   - **Report retention** — how many days of past report files to keep on
     disk before they're pruned.
   - **Check Supervisor/Host/add-on logs** — on by default; only has any
     effect on Home Assistant OS/Supervised installs (see
     [Supervisor-managed logs](#supervisor-managed-logs) below).

All of these can be changed later from the integration's **Configure**
button.

## Supervisor-managed logs

On Home Assistant OS or Supervised, the Settings → System → Logs page
covers more than just Home Assistant Core - Supervisor, Host, the DNS/
Audio/CLI/Multicast plugins, and each add-on all keep their own separate
logs, none of which are plain files Home Assistant Core can read. Log
Doctor reaches them the same way that Settings page does: through the
Supervisor's internal API (`SUPERVISOR`/`SUPERVISOR_TOKEN`, injected into
the Core container automatically - no token or extra setup needed on your
end).

A couple of things are different for these sources compared to
`home-assistant.log`:

- Each fetch only returns a bounded tail of recent log lines (up to the
  last 1000, via Supervisor's `lines` parameter - its own default without
  that is just 100), not a full history, so there's no separate "lookback
  window" for them - Log Doctor just checks the current tail every scan.
  Repeat entries are still deduped by the same "already reported" tracking
  as everything else, so you won't get renotified for the same ongoing
  issue every day.
- Home Assistant Core's own structured `LEVEL (thread) [logger] message`
  format is only guaranteed for Core and Supervisor (which uses the same
  logger). Host, plugin, and add-on logs can be formatted however that
  process chooses, so Log Doctor falls back to a best-effort scan for the
  words `ERROR`, `WARNING`, `CRITICAL`, or `FATAL` as whole words on those.
  It's less precise than the structured parsing - occasionally a line that
  merely mentions one of those words could be flagged - but it's the only
  way to catch problems in logs with no fixed format.
- Home Assistant Core's own log entry is deliberately skipped here, since
  Log Doctor already reads the complete `home-assistant.log` file directly
  (a fuller history than this endpoint's bounded tail).

The scan summary in every report lists exactly which sources were checked
and how many lines each returned, so you can always see what was covered.

## Retained reports

Every scan writes its full Markdown report to
`<config>/log_doctor_reports/` — one timestamped file per run
(`log_doctor_report_2026-09-15_080000.md`), plus a `latest.md` that always
mirrors the most recent one. This is what survives after the persistent
notification is dismissed or gets overwritten by tomorrow's scan: open the
folder with the Studio Code Server / File editor add-on, Samba, or SSH to
see the full history, including every "nothing found" run and exactly what
was checked. Files older than the configured retention window (default 30
days) are pruned automatically; `latest.md` is never pruned.

## Entities

| Entity | Description |
| --- | --- |
| `sensor.log_doctor_anomalies` | State = number of anomalies found in the last scan. Attributes include the full anomaly list (message, count, level, known fix or GitHub matches, first/last seen), scan stats (lines read, matches, GitHub checks), which log sources were checked and how many lines each returned (`sources_checked`), the full report text (`last_report`), and the path to that run's retained report file (`report_file`). |
| `button.log_doctor_scan_now` | Triggers an immediate scan outside the daily schedule. |

## Services

- `log_doctor.scan_now` — run a scan immediately.
- `log_doctor.clear_history` — forget which anomalies have already been
  reported (and cached GitHub results), so the next scan reports
  everything as new.

## Releasing updates (for maintainers)

HACS tracks updates for this integration via GitHub Releases, not just
commits to `main` — it compares the latest release tag against the
`version` in the installed `manifest.json` to decide whether to show an
update. Each time a change should be installable as an update:

1. Bump `"version"` in `custom_components/log_doctor/manifest.json`
   (semantic versioning, e.g. `0.2.0` → `0.3.0`).
2. Push to `main`.
3. Cut a release: `gh release create v0.3.0 --title "v0.3.0" --notes "..."`
   (tag must match the manifest version, with a `v` prefix).

Without a release, HACS still sees the repository but has nothing to
compare against, so it won't surface a clean "update available".

## Why "report only"

Automatically "fixing" a Home Assistant issue found in a log is risky:
the same error message can have different root causes, and the wrong
automated change could take your home automation offline. Log Doctor is
designed to save you the time of *diagnosing* a problem — reading logs,
searching GitHub — while leaving the judgment call of *whether and how* to
act on every fix entirely up to you.
