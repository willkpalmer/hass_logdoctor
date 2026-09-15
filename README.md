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
5. **Every scan produces a full report, even when nothing is wrong** — it
   always states what log file was read, the time window covered, how many
   lines/entries were checked, and how many were matched against the
   knowledge base or GitHub, so a clean run is evidence of a real check
   rather than a blank "no errors" message. The report is:
   - Posted as a persistent notification in Home Assistant (Settings bell
     icon), rebuilt each scan.
   - Written to disk as a Markdown file, one per run, so it survives past
     the notification being dismissed or overwritten by the next scan (see
     [Retained reports](#retained-reports) below).
   - Exposed on `sensor.log_doctor_anomalies` as attributes, for your own
     dashboards/automations.
   - Optionally, sent as a push notification via any `notify.*` mobile app
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

All of these can be changed later from the integration's **Configure**
button.

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
| `sensor.log_doctor_anomalies` | State = number of anomalies found in the last scan. Attributes include the full anomaly list (message, count, level, known fix or GitHub matches, first/last seen), scan stats (lines read, matches, GitHub checks), the full report text (`last_report`), and the path to that run's retained report file (`report_file`). |
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
