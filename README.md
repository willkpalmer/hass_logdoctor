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
   `home-assistant.log` file.
2. Warning/error/critical lines are grouped into "anomalies" by a
   normalized signature, so 50 occurrences of the same underlying problem
   show up as one entry with a count, not 50 separate reports.
3. Each anomaly is checked against a bundled knowledge base of common,
   well-known Home Assistant issues (database locks, blocking calls,
   deprecated config, SSL errors, MQTT/Zigbee/Z-Wave network issues,
   auth failures, etc.) for an instant explanation and suggested fix.
4. Anything not covered by the built-in knowledge base is (optionally)
   looked up live via the GitHub issue search API, scoped to
   `home-assistant/core` for built-in integrations or a best-effort search
   for custom components, so you get links to relevant existing issues and
   their resolution status.
5. The results are reported to you via:
   - A persistent notification in Home Assistant (Settings bell icon),
     rebuilt each scan.
   - A `sensor.log_doctor_anomalies` entity with the anomaly count and full
     details as attributes, for your own dashboards/automations.
   - Optionally, a push notification via any `notify.*` mobile app service.

## Installation

### HACS (custom repository)

1. In HACS, go to the three-dot menu → **Custom repositories**.
2. Add `https://github.com/willkpalmer/hass_logreview` as category
   **Integration**. (This repo is private — HACS needs a GitHub token with
   access configured in its own settings to install from it.)
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

All of these can be changed later from the integration's **Configure**
button.

## Entities

| Entity | Description |
| --- | --- |
| `sensor.log_doctor_anomalies` | State = number of anomalies found in the last scan. Attributes include the full list (message, count, level, known fix or GitHub matches, first/last seen). |
| `button.log_doctor_scan_now` | Triggers an immediate scan outside the daily schedule. |

## Services

- `log_doctor.scan_now` — run a scan immediately.
- `log_doctor.clear_history` — forget which anomalies have already been
  reported (and cached GitHub results), so the next scan reports
  everything as new.

## Why "report only"

Automatically "fixing" a Home Assistant issue found in a log is risky:
the same error message can have different root causes, and the wrong
automated change could take your home automation offline. Log Doctor is
designed to save you the time of *diagnosing* a problem — reading logs,
searching GitHub — while leaving the judgment call of *whether and how* to
act on every fix entirely up to you.
