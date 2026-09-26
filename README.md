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
   - The **Last scan** section of the [Settings](#settings) view in the
     sidebar's Log Doctor page: what was checked (log file and lines read,
     time window, other sources and their line counts) and what was found
     (matching lines, distinct anomalies, new vs. still occurring,
     knowledge-base matches, and the review file). Kept with the scan
     history, so it's still there after a restart.
   - A **persistent notification** in Home Assistant (Settings bell icon) -
     **only when the scan finds new anomalies** - with just the totals of
     new vs. still-occurring anomalies (e.g. "New anomalies: 2", "Still
     occurring: 1") and a link to the Log review. A scan that finds nothing
     new stays quiet.
   - The **full** report - every anomaly's logger, level, count, first/last
     seen, and every one of its raw matching log lines (including
     tracebacks) - written to disk as a Markdown file each run, so it
     survives past the notification being dismissed or overwritten by the
     next scan (see [Retained reports](#retained-reports) below), and
     exposed in full on `sensor.log_doctor_anomalies`'s attributes for
     dashboards/automations.
   - Optionally, a short push notification via any `notify.*` mobile app
     service - likewise only when there's something new.
6. **Separately from the daily scan, it watches every automation run in
   real time** and posts a persistent notification the moment one fails -
   see [Automation failure alerts](#automation-failure-alerts) below.
7. **After every restart, it checks for scheduled automations that were
   missed while Home Assistant was offline** - see
   [Missed schedule alerts](#missed-schedule-alerts) below.
8. **Everything it reports - log anomalies, automation failures, device
   and integration problems, and backups - is collected on a "Log Doctor"
   page in the sidebar**, where you can sort
   and filter them, mark them resolved (moving them to an archive) and
   clear the archive - see [Log Doctor panel](#log-doctor-panel) below.
9. **If you've configured an OpenAI API key**, the scan's report then
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

The brand icon (`custom_components/log_doctor/brand/`) shows up correctly on
the Settings → Devices & Services page (HA 2026.3+ reads it directly from
the installed integration), but HACS's own repository list/download panel
currently shows "icon not available" for all custom integrations that ship
icons this way - `home-assistant/brands` no longer accepts new custom
integration submissions, and HACS's dashboard hasn't yet switched to reading
the local icon. This is a known HACS bug
([hacs/integration#5223](https://github.com/hacs/integration/issues/5223)),
not something wrong with this repository; a fix is up as
[hacs/integration#5228](https://github.com/hacs/integration/pull/5228) and
[hacs/frontend#937](https://github.com/hacs/frontend/pull/937).

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
     get a push notification summary whenever a scan finds new anomalies.
     Leave blank to skip.
   - **Report retention** — how many days of past report files to keep on
     disk before they're pruned.
   - **Check Supervisor/Host/add-on logs** — on by default; only has any
     effect on Home Assistant OS/Supervised installs (see
     [Supervisor-managed logs](#supervisor-managed-logs) below).
   - **Notify me when any automation fails** — on by default; see
     [Automation failure alerts](#automation-failure-alerts) below.
   - **After a restart, tell me about missed schedules** — on by default;
     see [Missed schedule alerts](#missed-schedule-alerts) below.
   - **Skip time pattern triggers that repeat more often than every …
     minutes** — default 15; 0 checks every pattern. See
     [Missed schedule alerts](#missed-schedule-alerts).
   - **Also push automation failures and missed schedules to this phone** —
     optional; pick a device from the Mobile App integration to also get a
     push notification for each automation failure and missed schedule.
   - **OpenAI API key** — optional; set this to turn on the automatic
     [investigation stage](#investigation-stage) after every scan. Leave
     it blank to skip investigation entirely (the companion app remains
     available on demand either way).
   - **Max anomalies investigated per scan** — a per-scan cap on OpenAI
     calls, so one very noisy scan can't run away with your API bill. Only
     used when an OpenAI API key is set.

All of these can be changed later from the **Settings** view of the
[Log Doctor panel](#settings) in the sidebar, or from the integration's
**Configure** button.

## Automation failure alerts

With **Notify me when any automation or script fails** on (the default),
Log Doctor watches every automation and script run as it happens - not
just at the daily scan - and posts a persistent notification within a
couple of seconds of any run failing: an action that raised an error, a
service that doesn't exist, a template that couldn't be rendered, invalid
service data, and so on. Scripts get the same notifications, titled
"Script failed: <name>" and linking to the script's traces.

- There's **one notification per automation**
  (`log_doctor_automation_failure_<object_id>`), titled
  "Automation failed: <name>". If the same automation fails again, its
  notification is replaced with the latest failure (and a count of how many
  times it has failed since Home Assistant started) rather than stacking up
  a new one each time.
- Each notification lists the error(s) from that run and links straight to
  the automation's trace, when the automation has an `id` (every automation
  created in the UI does).
- **Optionally, a push notification to your phone too.** Choose a device
  under **Also push automation failures to this phone** (the list shows
  every phone/tablet registered with the Home Assistant Companion app, via
  the Mobile App integration). Each push carries the automation's name and
  its first error; tapping it opens the automation's trace. Repeat
  failures of the same automation replace the earlier push rather than
  stacking up. This is separate from the **Mobile notify service** setting,
  which only receives the daily scan summary. If the chosen device is later
  removed or can't receive notifications, the persistent notification is
  still posted and a warning is logged.
- Every failure is also added to the
  [Log Doctor panel](#automation-failures) and the
  [automation failure log](#automation-failure-log) file; each
  notification links to it.
- Like everything else here it's report-only: the automation itself is
  never touched.

How it works: Home Assistant doesn't fire an event when an automation
fails, but every automation logs its failures at `ERROR` through its own
logger (`homeassistant.components.automation.<object_id>`). Log Doctor
listens on that logger directly, so it sees failures immediately without
reading the log file. That also means:

- Runs that stop on purpose - conditions not met, a `stop` action (even
  with `error: true`), or a run skipped because the automation is already
  running in `single` mode - aren't reported, since none of those log an
  error.
- A step marked `continue_on_error: true` that fails *is* reported, even
  though the rest of the run carries on - Home Assistant still logs the
  step's error.
- If you've raised the log level of `homeassistant.components.automation`
  above `ERROR` in your `logger:` configuration, failures won't be seen.

## Missed schedule alerts

Home Assistant never catches up on a time trigger that passed while it was
offline: if an automation is set for 03:00 and Home Assistant is restarting,
updating, crashed, or without power from 02:55 to 03:10, that run is
silently skipped. With **After a restart, tell me about missed schedules**
on (the default), Log Doctor works out which runs were skipped and posts a
persistent notification ("Automations missed while Home Assistant was
offline") listing each automation, linked to its editor, and the times it
should have run. If a phone is chosen for pushes, it gets a short summary
too. Each missed time is also added to the
[Log Doctor panel](#automation-failures) and the
[automation failure log](#automation-failure-log).

How it works:

- While running, Log Doctor saves a heartbeat timestamp every **30
  seconds** (a tiny file under `.storage/`), plus once more on a clean
  shutdown. After a restart, the last heartbeat and the moment Home
  Assistant finished starting (when automations re-attach their triggers)
  give the offline window - exact for a clean restart, and to within 30
  seconds for a crash or power cut.
- Each enabled automation's triggers are checked against that window:
  - **Time triggers** - fixed times (`at: "03:00"`), several times, and
    times taken from an `input_datetime` helper (time-only or date+time) or
    a timestamp `sensor`, including offsets and weekday limits.
  - **Sun triggers** - sunrise/sunset, including offsets.
  - **Time pattern triggers** - `hours`/`minutes`/`seconds` patterns such
    as `minutes: "/15"` or `hours: 3`, matched exactly the way Home
    Assistant does. Patterns that repeat more often than the **Skip time
    pattern triggers that repeat more often than every … minutes** setting
    (default **15**) are left out: a restart usually takes a few minutes,
    so a pattern firing every minute or five would be reported after
    almost every restart. Quarter-hourly, hourly and less frequent patterns
    are still checked. The gap is measured between consecutive matches,
    including from the last match of one day to the first of the next, so
    e.g. `minutes: "/50"` (at :00 and :50) counts as every 10 minutes. Set
    it to 0 to check every pattern. Up to 10,000 missed times per trigger
    are counted; any more are shown as "N+ more".
- Any time at or before the automation's `last_triggered` is dropped: it
  actually ran (e.g. just before the shutdown).

Limits:

- It only reports; missed automations are never re-run.
- Conditions can't be checked after the fact, so "missed" means "was
  scheduled but never attempted" - some might not have done anything.
- Other trigger types - calendar events, state changes, and so on -
  aren't checked.
- Times from a helper or sensor use its current value, which is normally
  what it was during the outage.
- Nothing is checked after the first restart following installation (there
  was no heartbeat yet), or when only the integration is reloaded (Home
  Assistant itself never went down).

## Log Doctor panel

A **Log Doctor** page in Home Assistant's sidebar (admins only; it also
works in the Companion app) collects everything Log Doctor reports into
lists you can work through. Switch between them with the buttons at the top
(or go straight to `/log-doctor#logs`, `#failures`, `#health` or
`#backups`); each shows how many entries are still open. The scan's
notification links to the Log review (and to Backups when it found new
backup problems), and each automation failure notification to the failures
list.

The lists work the same way:

- **Open** tab: everything not yet dealt with. Click a column header to
  sort by it; click again to reverse. Filter by text, or with the drop-down.
  Tick one or more rows (or the header box for everything shown) and
  **Mark resolved** to move them to the archive.
- **Archived** tab: resolved entries, with when they were resolved.
  **Restore to open** moves selected ones back; **Clear archive** (after a
  confirmation) permanently deletes every archived entry.
- New entries appear live, without refreshing. On a phone, each entry shows
  as a card and the column names become sort buttons.

### Log review

One entry per anomaly the daily scans report - the same grouping the scan
reports use, so repeated occurrences of one problem are a single entry
whose **Count** keeps growing. Columns: **Level**, **Last seen**,
**Logger**, **Message** and **Count**; filter by level. Click the ▸ next to
a message to see when it was first and last seen, how many scans found it,
the built-in knowledge base's explanation and suggested fix when it
recognizes the message (marked **Known issue**), and the raw log lines
(with tracebacks) from the latest scan that found it.

If an anomaly you've marked resolved is logged again *after* you resolved
it, the next scan moves it back to **Open**, marked **Recurred**, so a fix
that didn't hold doesn't go unnoticed. Entries not seen within the report
retention window (default 30 days) are pruned after each scan; at most
5,000 are kept.

The per-scan Markdown reports in `logdoctor/reviews/` are unchanged -
they're a record of each scan, while this list is what's still open.

Backup warnings and errors aren't in this list - they're in
[Backups](#backups) instead, so a failing backup is only listed once.

### Automation failures

Failed automation and script runs, and automation runs missed while Home
Assistant was offline. Columns: **Date**, **Time** (sorts by time of day,
so everything that fails around 03:00 sorts together), **Automation /
script** (links to its traces; scripts are marked **Script**) and
**Reason**; filter to failed runs, missed runs or scripts only. A script
that fails when called from an automation appears twice - once for each,
since both runs failed.

### Devices & integrations

Things that have stopped working, checked every 5 minutes (and 5 minutes
after Home Assistant starts, once things have had time to come up):

- **Offline** - a device whose entities have been unavailable for at
  least the time set in Settings (default 1 hour), or an entity with no
  device. Shown as "Offline", or "2 of 5 entities unavailable" when only
  some of its entities are down. Diagnostic entities alone (e.g. a firmware
  update entity) don't count, and devices of an integration that failed to
  load are left to that integration's entry, so one broken integration
  isn't reported as dozens of devices.
- **Battery** - a battery below the level set in Settings (default 20%),
  one entry per device.
- **Integration** - an integration that failed to set up, is retrying
  setup, or failed to migrate, with the reason Home Assistant gives.
  Disabled integrations aren't checked.
- **Repair** - an issue from Home Assistant's own **Repairs** page that
  hasn't been ignored there, with its severity and, if it has one, the
  version it breaks in.

Columns: **Type**, **Name** (with its area and integration; links to the
device, integration or Repairs page), **Problem** and **Since**; filter by
type. Click ▸ to see which entities are affected, each linking to its
history.

These problems end by themselves, so this list keeps up with them:

- When a problem clears up - the device comes back, the battery is
  replaced, the integration loads, the repair is fixed - it moves to
  **Archived** automatically, marked **Cleared**.
- **Mark resolved** on a problem that's still there archives it as
  acknowledged; it stays archived for as long as it lasts.
- If an archived problem comes back after it had cleared, it returns to
  **Open**, marked **Recurred**.
- **Clear archive** deletes archived entries; one that's still a problem
  reappears on the next check.

Home Assistant resets every entity's "last changed" time when it restarts,
so a device that was already offline before a restart counts from the
restart - unless it was already on this list, which keeps its original
**Since**. Nothing here sends notifications; it's a list to check.

### Backups

Everything about backups, in one place, from two sources:

- **Home Assistant** - its built-in backup: the backup integration, the
  backup platforms of integrations that store backups (Home Assistant
  Cloud, Google Drive, OneDrive, the Supervisor's local storage, ...) and,
  on Home Assistant OS/Supervised, the Supervisor's backup manager.
- **GDrive Backup** - the
  [GDrive Backup Utility](https://github.com/willkpalmer/hass_gdrive_backup)
  add-on, recognized by its `hass_gdrive_backup` logger names, in both
  `home-assistant.log` and the add-on's own log (the add-on's own log is
  read through the Supervisor, so only on Home Assistant OS/Supervised
  with **Check Supervisor/Host/add-on logs** on). From the add-on's own
  log, only lines in Home Assistant's log format are read, so lines from
  add-on versions before 0.9.0 (which used another format) are ignored.

Two kinds of entry:

- **Problems** - every warning or error (at or above the minimum severity)
  from either source. Each scan moves them here **instead of** the Log
  review, and they get the same grouping, known-issue matching,
  **Recurred** handling and retention. They're still in the scan's report
  file (under "Backup problems", so the investigation stage looks at them
  too), and new ones are counted in the scan's notification with a link
  here. The add-on sends its warnings and errors to `home-assistant.log`
  as well as its own log; a copy logged within a minute of the original
  is only counted once. Backup problems the Log review listed before this
  view existed are moved here on startup.
- **Successes** - the add-on's "Backup finished" and "Uploaded ... to
  Google Drive" lines (from its own log, found by each scan), and every
  backup Home Assistant's backup manager completes, added the moment it
  finishes - manual, automatic, or asked for by the add-on. A backup the
  manager fails is added the same way as a problem ("Backup failed:
  upload failed"). Like anomalies, successes are grouped, so each kind is
  one entry: its **Last seen** is the latest successful backup, **Count**
  how many there have been. Marking one resolved archives it until the
  next success brings it back.

Columns: **Status** (Success or the problem's level), **Last seen**,
**Source** (with the logger), **Message** and **Count**; filter to
problems, successes or one source. Click ▸ for the details and latest log
lines.

### Settings

Every setting from the integration's **Configure** dialog, plus what its
entities do, on one page (`/log-doctor#settings`):

- **Daily scan** - scan time, minimum severity, first-scan lookback, log
  file path, Supervisor/Host/add-on logs, and how long reports and list
  entries are kept.
- **Automations & scripts** - failure alerts, missed-schedule alerts, and
  which time patterns to skip.
- **Devices & integrations** - turn the checks on or off, how long a
  device must be offline before it's reported, and the battery level to
  report below (0 turns battery checks off).
- **Notifications** - the phone to push automation failures and missed
  schedules to (picked from your Companion app devices), and the notify
  service for the daily scan summary (with suggestions).
- **Investigation (OpenAI)** - the API key, the per-scan cap, and the
  **Auto-investigate** switch. The key is never shown or sent to the
  browser: the page only says whether one is set. Type a new one to replace
  it, or tick **Remove key**.
- **Last scan** - what the last scan checked (log file and lines read,
  time window, each other source and its lines) and found (matching lines,
  distinct anomalies, new vs. still occurring, knowledge-base matches, the
  review file), where the files are, **Scan now** (the button entity), and **Clear history**
  (the `log_doctor.clear_history` service; asks you to click twice).

Changed fields are marked with a dot until you **Save** (or **Discard
changes**). Saving is checked against the same limits as the Configure
dialog - an out-of-range value is refused with a message and nothing is
saved - and, like saving that dialog, restarts WP Log Doctor for a moment.
The Auto-investigate switch, Scan now and Clear history take effect
straight away. The entities and the Configure dialog still work and stay in
step with this page.

## Automation failure log

The Automation failures list is also written to the Markdown file
`<config>/logdoctor/automation_failures.md` - Log Doctor's main folder,
whose `reviews/` subfolder holds the [retained reports](#retained-reports) -
so it can be read outside Home Assistant too. It's rewritten to match the
Log Doctor panel after every change (a few seconds later, so a burst of failures is
one write), with an **Open** table and an **Archived** table:

| Date | Time | Automation | Reason |
| --- | --- | --- | --- |
| 2026-09-26 | 03:00:00 | Nightly backup (`automation.nightly_backup`) | **Failed:** Error executing script. Service not found for call_service at pos 1: Service backup.create not found. |
| 2026-09-26 | 06:30:00 | Morning lights (`automation.morning_lights`) | **Missed:** Home Assistant was offline from 06:28:41 to 06:31:05 |

- **Failed runs** (see [Automation failure alerts](#automation-failure-alerts))
  are recorded with the time the run was *triggered* - for an automation on
  a time schedule, its scheduled time - even if the error came later in the
  run (e.g. after a delay). The reason is **Failed:** followed by the
  error(s) from that run.
- **Missed runs** (see [Missed schedule alerts](#missed-schedule-alerts))
  are recorded one row per missed time, with the time it was scheduled for
  and **Missed:** plus the offline window.
- Each failure stays one row: multi-line errors are folded onto it, very
  long reasons are cut at 1,000 characters, and characters that would break
  the table (`|`) or be hidden by a viewer (`<`) are escaped.
- The list itself lives in Home Assistant's storage
  (`.storage/log_doctor.failures`); editing the Markdown file by hand has
  no effect and is overwritten on the next change - use the Log Doctor
  panel instead.
- Failures (open and archived) older than the report retention window
  (default 30 days) are pruned after each daily scan, like old report
  files. At most 10,000 are kept; beyond that the oldest are dropped.
- Upgrading: failures already in the Markdown file from version 0.16.0, or
  in the plain-text `automation_failures.log` from 0.14.0-0.15.x, are
  imported into the list (as open) on the first start after updating.

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
  way to catch problems in logs with no fixed format. The exception is the
  [GDrive Backup Utility](#backups) add-on (slug ending `hass_gdrive_backup`,
  or named "GDrive Backup Utility"): it always logs in the structured format
  from v0.9.0 on, so only structured lines are read from it and anything
  else - such as lines from older versions - is ignored.
- Home Assistant Core's own log entry is deliberately skipped here, since
  Log Doctor already reads the complete `home-assistant.log` file directly
  (a fuller history than this endpoint's bounded tail).

The scan summary in every report lists exactly which sources were checked
and how many lines each returned, so you can always see what was covered.

## Retained reports

Every scan writes its full Markdown report to
`<config>/logdoctor/reviews/` — one timestamped file per run
(`log_doctor_report_2026-09-15_080000.md`), plus a `latest.md` that always
mirrors the most recent one. This is what survives after the persistent
notification is dismissed or gets overwritten by tomorrow's scan: open the
folder with the Studio Code Server / File editor add-on, Samba, or SSH to
see the full history, including every "nothing found" run and exactly what
was checked. Files older than the configured retention window (default 30
days) are pruned automatically; `latest.md` is never pruned. This is also
the file the [investigation stage](#investigation-stage) and the
[companion app](#companion-app) both read.

Log Doctor's files are laid out like this:

```
<config>/logdoctor/
├── automation_failures.md       (see Automation failure log)
└── reviews/
    ├── log_doctor_report_2026-09-15_080000.md
    ├── latest.md
    └── latest.findings.md       (from the investigation stage)
```

Before version 0.15.0 everything was kept flat in
`<config>/log_doctor_reports/`. On the first start after updating, those
files are moved into the layout above automatically and the old folder is
removed. A file is never overwritten: if one with the same name already
exists in the new place, the old copy is left where it was (and a warning
is logged).

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
  report (starts in `logdoctor/reviews/` if that exists next to where
  you ran it from, or the older `log_doctor_reports/`). Picking a report
  lists its anomalies below as checkboxes.
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
`logdoctor/reviews/latest.md` if that exists), or pass one directly:

```bash
python log_doctor_companion.py /path/to/logdoctor/reviews/latest.md
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
| `sensor.log_doctor_anomalies` | State = number of anomalies found in the last scan, not counting backup problems (those are in `backup_problems` and the panel's [Backups](#backups) view). Attributes include the full anomaly list (message, count, level, known fix if matched in the built-in knowledge base, first/last seen), scan stats (lines read, knowledge-base matches), which log sources were checked and how many lines each returned (`sources_checked`), the full report text (`last_report`), and the path to that run's retained report file (`report_file`). |
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
update. Releases are created automatically by the
[Release workflow](.github/workflows/release.yml): on every push to
`main`, it reads `"version"` from `manifest.json` and, if there's no
matching `v<version>` release yet, creates one (with auto-generated notes).
So each time a change should be installable as an update:

1. Bump `"version"` in `custom_components/log_doctor/manifest.json`
   (semantic versioning, e.g. `0.2.0` → `0.3.0`).
2. Push to `main`.

Pushes that don't change the version are a no-op for the workflow. It can
also be run by hand from the repository's **Actions** tab. If it fails
with a permissions error, allow "Read and write permissions" under
**Settings → Actions → General → Workflow permissions**.

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
