# Log Doctor

A Home Assistant custom integration that periodically reads your Home
Assistant log, groups the warnings/errors it finds into anomalies, checks
them against a built-in knowledge base, and reports everything it finds
once a day - as plain data, not a guess at what it means. When you give it
an OpenAI API key, it then automatically runs an
[investigation stage](#investigation-stage) against that report, right
after every scan. A separate [companion app](#companion-app) offers the
same research on demand instead, against any report file, whenever you
want it.

**Log Doctor never modifies your configuration, restarts anything, or
applies any fix automatically.** It is strictly read-only / report-only,
in the same spirit as [Spook](https://github.com/frenck/spook) — it looks
inward at your Home Assistant instance, but every action it takes is a
report, never a change.

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
   deprecated config, SSL errors, MQTT/Zigbee/Z-Wave network issues, auth
   failures, etc.) for an instant explanation and suggested fix - this is
   fast, local, and offline, with no external requests involved.
5. **Every scan produces a full report, even when nothing is wrong** — it
   always states what log file was read, the time window covered, how many
   lines/entries were checked, and how many matched the knowledge base, so
   a clean run is evidence of a real check rather than a blank "no errors"
   message. It reaches you as:
   - A **persistent notification** in Home Assistant (Settings bell icon),
     rebuilt each scan - kept short on purpose: the scan summary, plus just
     the totals of new vs. still-occurring anomalies (e.g. "New anomalies:
     2", "Still occurring: 1"), not a write-up of every single one.
   - The **full** report - every anomaly's logger, level, count, first/last
     seen, and every one of its raw matching log lines (including
     tracebacks) - written to disk as a Markdown file each run, so it
     survives past the notification being dismissed or overwritten by the
     next scan (see [Retained reports](#retained-reports) below), and
     exposed in full on `sensor.log_doctor_anomalies`'s attributes for
     dashboards/automations.
   - Optionally, a short push notification via any `notify.*` mobile app
     service.
6. **If you've configured an OpenAI API key**, the scan's report then
   automatically goes through the
   [investigation stage](#investigation-stage): every anomaly gets
   researched by an OpenAI model, and a **second, separate persistent
   notification** appears once that finishes - independent of the scan's
   own notification, since investigating can take a while. Without a key,
   Log Doctor never guesses at what an anomaly means or how to fix it
   beyond the built-in knowledge base - run the
   [companion app](#companion-app) by hand instead whenever you want that
   diagnosis.

## Installation

### HACS (custom repository)

1. In HACS, go to the three-dot menu → **Custom repositories**.
2. Add `https://github.com/willkpalmer/hass_logdoctor` as category
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
   - **Mobile notify service** — e.g. `mobile_app_pixel_10_pro_xl`, to also
     get a push notification summary. Leave blank to skip.
   - **Report retention** — how many days of past report files to keep on
     disk before they're pruned.
   - **Check Supervisor/Host/add-on logs** — on by default; only has any
     effect on Home Assistant OS/Supervised installs (see
     [Supervisor-managed logs](#supervisor-managed-logs) below).
   - **OpenAI API key** — optional; set this to turn on the automatic
     [investigation stage](#investigation-stage) after every scan. Leave
     it blank to skip investigation entirely (the companion app remains
     available on demand either way).
   - **Max anomalies investigated per scan** — a per-scan cap on OpenAI
     calls, so one very noisy scan can't run away with your API bill. Only
     used when an OpenAI API key is set.

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
days) are pruned automatically; `latest.md` is never pruned. This is also
the file the [investigation stage](#investigation-stage) and the
[companion app](#companion-app) both read.

## Investigation stage

When an OpenAI API key is configured **and** the `switch.log_doctor_auto_
investigate` entity is on (on by default), Log Doctor automatically
researches every anomaly in each scan's report - right after the scan
finishes, against the report it just wrote - using the same approach as
the [companion app](#companion-app): an OpenAI model (`gpt-6-astra`) with
web search enabled, asked to explain what each error means, what's likely
causing it, and how to troubleshoot or resolve it.

Investigating isn't free - it's one OpenAI call per anomaly, every scan.
The **Auto-investigate** switch lets you pause that without clearing the
API key: flip it off to stop automatic runs (e.g. while iterating on
something noisy that's generating lots of anomalies), then back on when
you want them again. Its state persists across restarts. This is separate
from the OpenAI API key setting: the key is what makes investigation
*possible*, the switch is whether it *actually runs* right now.

This runs as its own background step, separate from the scan itself, so a
slow investigation (one OpenAI call per anomaly) never delays the scan's
own notification or the `scan_now` service call returning. When it
finishes, it posts its **own persistent notification** - distinct from the
scan's - whether it found something, had nothing to investigate, or
failed (e.g. a bad API key), so you always know the stage ran. Findings
are written to disk next to the report, the same way the report itself is:
`log_doctor_report_*.findings.md` per run, plus a `latest.findings.md` that
always mirrors the most recent one, pruned on the same retention window as
reports.

The **max anomalies investigated per scan** setting (default 15) caps how
many OpenAI calls one scan can trigger - anomalies beyond the cap are
simply skipped for that run (noted in the notification), not queued or
carried over.

This is entirely optional - leave the OpenAI API key blank and Log Doctor
behaves exactly as it does without it, reporting only raw data and its
built-in knowledge-base matches. Automatic investigation and the companion
app are independent of each other; use one, the other, or both.

## Companion app

`companion/log_doctor_companion.py` is a separate command-line script -
not part of the Home Assistant integration, and not installed by it. Run
it on your own machine, whenever you want, against a report Log Doctor
wrote. There's a command-line version and a desktop GUI version - both
share the same research logic.

```bash
cd companion
pip install -r requirements.txt
```

### GUI

```bash
python log_doctor_companion_gui.py
```

A small window (built with Tk, part of the Python standard library - no
extra install) with:

- **Input report** — **Browse...** opens a file picker for the markdown
  report (starts in `log_doctor_reports/` if that exists next to where
  you ran it from). Picking a report lists its anomalies below as
  checkboxes.
- **Output file** — defaults to the input file's own folder (e.g.
  `latest.md` → `latest.findings.md`), with its own **Browse...** to save
  somewhere else instead.
- **Anomalies** — every anomaly in the report, each with its own
  checkbox (checked by default), plus **Select all** / **Select none**.
  Uncheck anything you've already investigated or don't care about, so
  you only spend OpenAI credits on the ones you actually want researched.
- **Investigate selected** — researches only the checked anomalies,
  showing progress and a running log as it goes.
- **View output** — enabled once processing finishes; opens the findings
  file in your system's default app for it.

### Command line

```bash
python log_doctor_companion.py
```

With no argument it prompts for a report path (defaulting to
`log_doctor_reports/latest.md` if that exists), or pass one directly:

```bash
python log_doctor_companion.py /path/to/log_doctor_reports/latest.md
```

### What it does

For each anomaly in the report, it asks an OpenAI model (`gpt-6-astra`,
OpenAI's flagship reasoning model) - with web search enabled, so it can
check the Home Assistant docs, GitHub issues, the Community forum, and
anywhere else that's relevant - to explain what the error means, what's
likely causing it, and how to troubleshoot or resolve it. Results are
written to a findings file next to the report (e.g. `latest.findings.md`),
one section per anomaly.

It needs an OpenAI API key, set as the `OPENAI_API_KEY` environment
variable:

- **Get a key**: [platform.openai.com](https://platform.openai.com) →
  **Settings → API Keys** → Create new secret key.
- **Temporary (current PowerShell window only)**:
  ```powershell
  $env:OPENAI_API_KEY = "sk-your-key-here"
  ```
- **Permanent (persists across reboots/new terminals)**:
  ```powershell
  setx OPENAI_API_KEY "sk-your-key-here"
  ```
  `setx` doesn't affect terminals/apps already open - close and reopen
  them afterward. You can also set it via **Start menu → "environment
  variables" → Edit environment variables for your account → New...**
  under "User variables".

Each run calls the OpenAI API once per anomaly in the report (with web
search) - cost scales with how many distinct anomalies are in the report,
not with log size.

## Entities

| Entity | Description |
| --- | --- |
| `sensor.log_doctor_anomalies` | State = number of anomalies found in the last scan. Attributes include the full anomaly list (message, count, level, known fix if matched in the built-in knowledge base, first/last seen), scan stats (lines read, knowledge-base matches), which log sources were checked and how many lines each returned (`sources_checked`), the full report text (`last_report`), and the path to that run's retained report file (`report_file`). |
| `button.log_doctor_scan_now` | Triggers an immediate scan outside the daily schedule. |
| `switch.log_doctor_auto_investigate` | On by default. Turns the automatic [investigation stage](#investigation-stage) on or off after each scan; only has any effect when an OpenAI API key is configured. State persists across restarts. |

## Services

- `log_doctor.scan_now` — run a scan immediately.
- `log_doctor.clear_history` — forget which anomalies have already been
  reported, so the next scan reports everything as new.

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
designed to save you the time of *finding* a problem in a sea of log
lines, and the companion app to save you the time of *researching* it —
while leaving the judgment call of *whether and how* to act on every fix
entirely up to you.
