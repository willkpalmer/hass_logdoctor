// WP Log Doctor - sidebar panel.
//
// A self-contained web component (no build step, no external libraries)
// with five views. Four are reviewable lists with Open and Archived tabs:
//
//   #logs      Log review - the anomalies the daily scans reported
//   #restarts  Startup & shutdown - the anomalies logged only while Home
//              Assistant was starting or shutting down (the same list as
//              the Log review, split by each entry's category)
//   #reboots   Restart history - each Home Assistant restart's shutdown and
//              startup times: the windows Startup & shutdown goes by
//   #failures  Automation failures - failed automation and script runs,
//              and scheduled runs missed while Home Assistant was offline
//   #health    Devices & integrations - offline devices, unavailable
//              entities, integrations
//              that failed to load, and Repairs issues
//   #backups   Backups - backup problems and successes, from Home
//              Assistant's own backup and the GDrive Backup Utility add-on
//              (left out of the Log review)
//
// and #settings holds all of WP Log Doctor's settings (see
// LogDoctorSettings at the end of this file).
//
// Each list is subscribed to over the WebSocket (log_doctor/review/*) and
// comes back in full after every change, so new entries appear live.
// Open entries can be sorted, filtered, selected and marked resolved,
// which moves them to Archived; archived ones can be restored, or the
// archive cleared, which deletes them for good. Log review and Backups
// entries can also be ignored, which moves them to a third tab, Ignored,
// where scans keep them up to date without bringing them back.
//
// The page itself doesn't scroll: the view buttons, tabs, toolbar and
// column headings stay put and only the list scrolls (unless the window is
// too short for that, e.g. a phone held sideways).

const WS = {
  SUBSCRIBE: "log_doctor/review/subscribe",
  RESOLVE: "log_doctor/review/resolve",
  RESTORE: "log_doctor/review/restore",
  CLEAR_ARCHIVED: "log_doctor/review/clear_archived",
  DELETE: "log_doctor/review/delete",
  IGNORE: "log_doctor/review/ignore",
  UNIGNORE: "log_doctor/review/unignore",
  SET_CATEGORY: "log_doctor/review/set_category",
  INVESTIGATION_PROMPT: "log_doctor/review/investigation_prompt",
};

// Rows rendered at once; "Show more" adds this many again.
const PAGE_SIZE = 500;

const LEVEL_RANK = { WARNING: 1, ERROR: 2, CRITICAL: 3 };

const STYLE = `
:host {
  /* Fills the window; only the list scrolls, so everything above it and
     the column headings stay in view. */
  display: flex; flex-direction: column;
  height: 100vh; height: 100dvh;
  background: var(--primary-background-color, #fafafa);
  color: var(--primary-text-color, #212121);
  font-family: var(--paper-font-body1_-_font-family, var(--ha-font-family-body, Roboto, sans-serif));
  font-size: 14px;
}
* { box-sizing: border-box; }
.header {
  display: flex; align-items: center; gap: 8px;
  height: var(--header-height, 56px); padding: 0 16px;
  background: var(--app-header-background-color, var(--primary-color, #03a9f4));
  color: var(--app-header-text-color, #fff);
  flex: none;
}
.header h1 { font-size: 20px; font-weight: 400; margin: 0; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.menu-btn { display: none; background: none; border: 0; color: inherit; font-size: 22px; cursor: pointer; padding: 4px 8px; }
:host([narrow]) .menu-btn { display: inline-block; }
.content {
  flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column;
  width: 100%; max-width: 1400px; margin: 0 auto; padding: 16px;
}
.views { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; flex: none; }
log-doctor-settings { flex: 1 1 auto; min-height: 0; overflow: auto; }
.view {
  font: inherit; font-weight: 500; padding: 8px 16px; border-radius: 18px; cursor: pointer;
  border: 1px solid var(--divider-color, #e0e0e0);
  background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121);
}
.view.active { background: var(--primary-color, #03a9f4); border-color: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
.view .count { opacity: 0.8; font-weight: 400; }
.card {
  background: var(--card-background-color, #fff);
  border-radius: var(--ha-card-border-radius, 12px);
  border: 1px solid var(--divider-color, #e0e0e0);
  overflow: hidden;
  flex: 0 1 auto; min-height: 0; display: flex; flex-direction: column;
}
.card[hidden] { display: none; }
.card > .tabs, .card > .toolbar, .card > .confirm, .card > .footer { flex: none; }
.tabs { display: flex; border-bottom: 1px solid var(--divider-color, #e0e0e0); }
.tab {
  flex: 0 0 auto; padding: 12px 20px; background: none; border: 0;
  border-bottom: 2px solid transparent; color: var(--secondary-text-color, #727272);
  font: inherit; font-weight: 500; cursor: pointer;
}
.tab.active { color: var(--primary-color, #03a9f4); border-bottom-color: var(--primary-color, #03a9f4); }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 12px 16px; }
.toolbar input[type=search], .toolbar select {
  font: inherit; padding: 8px 10px; border-radius: 6px;
  border: 1px solid var(--divider-color, #ccc);
  background: var(--secondary-background-color, #f5f5f5); color: inherit;
}
.toolbar input[type=search] { flex: 1 1 220px; min-width: 160px; }
.spacer { flex: 1 1 auto; }
button.action {
  font: inherit; font-weight: 500; padding: 8px 14px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--primary-color, #03a9f4); background: var(--primary-color, #03a9f4);
  color: var(--text-primary-color, #fff);
}
button.action.secondary { background: transparent; color: var(--primary-color, #03a9f4); }
button.action.danger { border-color: var(--error-color, #db4437); background: var(--error-color, #db4437); }
button.action.danger.secondary { background: transparent; color: var(--error-color, #db4437); }
button.action:disabled { opacity: 0.4; cursor: default; }
.confirm {
  display: none; align-items: center; flex-wrap: wrap; gap: 8px; padding: 10px 16px;
  background: rgba(219, 68, 55, 0.1); border-top: 1px solid var(--divider-color, #e0e0e0);
}
.confirm.open { display: flex; }
.confirm span { flex: 1 1 240px; }
.table-wrap { flex: 0 1 auto; min-height: 0; overflow: auto; }
thead th {
  position: sticky; top: 0; z-index: 1;
  background: var(--card-background-color, #fff);
  box-shadow: inset 0 -1px 0 var(--divider-color, #e0e0e0);
}
table { width: 100%; border-collapse: separate; border-spacing: 0; }
th, td { text-align: left; padding: 8px 12px; border-top: 1px solid var(--divider-color, #e0e0e0); vertical-align: top; }
th { font-weight: 500; color: var(--secondary-text-color, #727272); white-space: nowrap; user-select: none; }
th.sortable { cursor: pointer; }
th.sortable:hover { color: var(--primary-text-color, #212121); }
th .arrow { display: inline-block; width: 1em; }
td.check, th.check { width: 36px; padding-right: 0; }
td.when { white-space: nowrap; font-variant-numeric: tabular-nums; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
th.num { text-align: right; }
td.text { min-width: 260px; word-break: break-word; }
td.logger { word-break: break-all; min-width: 140px; }
tbody tr.row:hover { background: var(--secondary-background-color, rgba(0,0,0,0.03)); }
tbody tr.group td {
  background: var(--secondary-background-color, #f5f5f5); font-weight: 500; padding: 6px 12px;
}
tbody tr.group { cursor: pointer; user-select: none; }
tbody tr.group .caret { display: inline-block; width: 1.2em; color: var(--secondary-text-color, #727272); }
tbody tr.group .group-link {
  margin-left: 12px; font-size: 12px; font-weight: 500; white-space: nowrap;
  padding: 1px 8px; border: 1px solid var(--primary-color, #03a9f4); border-radius: 10px;
}
tbody tr.group .group-link:hover { text-decoration: none; background: rgba(3, 169, 244, 0.1); }
tbody tr.group .group-count { font-weight: 400; color: var(--secondary-text-color, #727272); }
tbody tr.row.selected { background: rgba(3, 169, 244, 0.1); }
tr.details td { border-top: 0; padding-top: 0; }
.detail-box {
  background: var(--secondary-background-color, #f5f5f5); border-radius: 8px;
  padding: 10px 12px; margin-left: 36px; display: grid; gap: 8px;
}
.detail-box h4 { margin: 0; font-size: 13px; font-weight: 600; }
.detail-box p { margin: 0; }
.detail-box pre {
  margin: 0; padding: 8px; overflow-x: auto; max-height: 280px;
  background: var(--card-background-color, #fff); border-radius: 6px;
  font-size: 12px; white-space: pre-wrap; word-break: break-word;
}
.detail-meta { color: var(--secondary-text-color, #727272); font-size: 12px; }
.expand { background: none; border: 0; cursor: pointer; color: var(--primary-color, #03a9f4); font: inherit; padding: 0 6px 0 0; text-align: left; }
input[type=checkbox] { width: 18px; height: 18px; cursor: pointer; accent-color: var(--primary-color, #03a9f4); }
a { color: var(--primary-color, #03a9f4); text-decoration: none; }
a:hover { text-decoration: underline; }
.sub { color: var(--secondary-text-color, #727272); font-size: 12px; }
.chip {
  display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: 0.3px;
  padding: 1px 7px; border-radius: 10px; margin-right: 6px; text-transform: uppercase; white-space: nowrap;
}
.chip.failed, .chip.error { background: rgba(219, 68, 55, 0.15); color: var(--error-color, #db4437); }
.chip.critical { background: var(--error-color, #db4437); color: #fff; }
.chip.missed, .chip.warning { background: rgba(255, 152, 0, 0.18); color: var(--warning-color, #e68a00); }
.chip.running { background: rgba(255, 152, 0, 0.18); color: var(--warning-color, #e68a00); }
.chip.phase { background: rgba(127, 127, 127, 0.15); color: var(--secondary-text-color, #727272); }
.chip.recurred { background: rgba(3, 169, 244, 0.15); color: var(--primary-color, #03a9f4); }
.chip.known, .chip.recovered, .chip.success { background: rgba(76, 175, 80, 0.15); color: var(--success-color, #43a047); }
.chip.offline, .chip.integration { background: rgba(219, 68, 55, 0.15); color: var(--error-color, #db4437); }
.chip.unavailable { background: rgba(255, 152, 0, 0.18); color: var(--warning-color, #e68a00); }
.chip.repair, .chip.script, .chip.source { background: rgba(3, 169, 244, 0.15); color: var(--primary-color, #03a9f4); }
.entity-list { margin: 0; padding-left: 18px; font-size: 13px; }
.empty, .status { padding: 32px 16px; text-align: center; color: var(--secondary-text-color, #727272); }
.more { padding: 12px; text-align: center; }
.footer { padding: 8px 16px 12px; color: var(--secondary-text-color, #727272); font-size: 12px; }
.label { display: none; }

/* Phones: one card per entry; the column headers become sort buttons. */
@media (max-width: 700px) {
  .content { padding: 8px; }
  table, thead, tbody { display: block; }
  thead tr {
    display: flex; flex-wrap: wrap; align-items: center; gap: 2px 14px;
    padding: 6px 12px; border-top: 1px solid var(--divider-color, #e0e0e0);
  }
  thead {
    position: sticky; top: 0; z-index: 1; background: var(--card-background-color, #fff);
    box-shadow: inset 0 -1px 0 var(--divider-color, #e0e0e0);
  }
  thead th { border: 0; padding: 6px 2px; position: static; box-shadow: none; }
  th.num { text-align: left; }
  tbody tr.row {
    display: grid; grid-template-columns: 30px 1fr; column-gap: 10px; row-gap: 3px;
    padding: 10px 12px; border-top: 1px solid var(--divider-color, #e0e0e0);
  }
  tbody tr.row td { border: 0; padding: 0; min-width: 0; grid-column: 2; text-align: left; }
  tbody tr.row td.check { grid-column: 1; grid-row: 1 / span 8; }
  tbody tr.row td.when, tbody tr.row td.num { font-size: 12px; color: var(--secondary-text-color, #727272); }
  tbody tr.group, tbody tr.group td { display: block; }
  tr.details { display: block; padding: 0 12px 10px; }
  tr.details td { display: block; padding: 0; }
  .detail-box { margin-left: 40px; }
  .label { display: inline; }
}

/* Too short for a fixed top part (e.g. a phone held sideways): the whole
   page scrolls instead. */
@media (max-height: 520px) {
  :host { height: auto; min-height: 100vh; display: block; }
  .content, .card { display: block; }
  .table-wrap { overflow: visible; overflow-x: auto; }
  thead, thead th { position: static; }
}
`;

const TEMPLATE = `
<div class="header">
  <button class="menu-btn" title="Menu" data-action="menu">&#9776;</button>
  <h1>Log Doctor</h1>
</div>
<div class="content">
  <div class="views">
    <button class="view" data-view="logs">Log review <span class="count" data-count="logs"></span></button>
    <button class="view" data-view="restarts">Startup &amp; shutdown <span class="count" data-count="restarts"></span></button>
    <button class="view" data-view="reboots">Restart history <span class="count" data-count="reboots"></span></button>
    <button class="view" data-view="failures">Automation failures <span class="count" data-count="failures"></span></button>
    <button class="view" data-view="health">Devices &amp; integrations <span class="count" data-count="health"></span></button>
    <button class="view" data-view="backups">Backups <span class="count" data-count="backups"></span></button>
    <button class="view" data-view="settings">Settings</button>
  </div>
  <log-doctor-settings data-el="settings" hidden></log-doctor-settings>
  <div class="card" data-el="list-card">
    <div class="tabs">
      <button class="tab" data-tab="open">Open</button>
      <button class="tab" data-tab="archived">Archived</button>
      <button class="tab" data-tab="ignored" data-ignorable>Ignored</button>
    </div>
    <div class="toolbar">
      <input type="search" data-el="filter">
      <select data-el="kind" title="Show"></select>
      <span class="spacer"></span>
      <button class="action secondary" data-action="copy-prompt" data-only-view="logs restarts" disabled
        title="Copy the prompt the investigation stage would send for the selected entries, to paste into any AI chat">Copy investigation prompt</button>
      <button class="action secondary" data-action="to-restarts" data-only-view="logs" disabled
        title="These only happen when Home Assistant starts or stops: move them to Startup &amp; shutdown">Move to Startup &amp; shutdown</button>
      <button class="action secondary" data-action="to-operational" data-only-view="restarts" disabled
        title="Move these to the Log review">Move to Log review</button>
      <button class="action secondary" data-action="toggle-groups" data-only-view="health"
        title="Collapse or expand every integration">Collapse all</button>
      <button class="action secondary" data-action="ignore" data-show="open archived" data-ignorable disabled
        title="Stop showing these here; they keep being tracked on the Ignored tab">Ignore</button>
      <button class="action secondary" data-action="unignore" data-show="ignored" disabled
        title="Move these back to the open list">Stop ignoring</button>
      <button class="action" data-action="resolve" data-show="open" disabled>Mark resolved</button>
      <button class="action secondary" data-action="restore" data-show="archived" disabled>Restore to open</button>
      <button class="action danger secondary" data-action="ask-delete" data-show="archived" data-only-view="reboots" disabled>Delete selected</button>
      <button class="action danger secondary" data-action="ask-clear" data-show="archived" disabled>Clear archive</button>
    </div>
    <div class="confirm" data-el="confirm">
      <span data-el="confirm-text"></span>
      <button class="action secondary" data-action="cancel-clear">Cancel</button>
      <button class="action danger" data-action="clear">Delete permanently</button>
    </div>
    <div class="table-wrap" data-el="scroll">
      <table>
        <thead><tr data-el="head"></tr></thead>
        <tbody data-el="body"></tbody>
      </table>
      <div class="status" data-el="status">Loading…</div>
      <div class="more" data-el="more" hidden><button class="action secondary" data-action="more">Show more</button></div>
    </div>
    <div class="footer" data-el="footer"></div>
  </div>
</div>
`;

// -- the list views -----------------------------------------------------

const BACKUP_SOURCES = { ha: "Home Assistant", gdrive: "GDrive Backup" };
// Heading for Devices & integrations rows that don't belong to an integration
const OTHER_GROUP = "Other";
// Where the collapsed groups of each view are remembered, per browser.
const COLLAPSED_KEY = "log_doctor.collapsed_groups";

// How long a restart took: from the shutdown (or the start, when no
// shutdown was recorded) until Home Assistant had finished starting.
function rebootSeconds(r) {
  const from = r.shutdown_start || r.starting;
  return from && r.started ? (new Date(r.started) - new Date(from)) / 1000 : -1;
}

// "Startup", "Shutdown" or "Startup & shutdown".
function phaseLabel(r) {
  const phases = r.phases || [];
  const names = [];
  if (phases.includes("startup")) names.push("Startup");
  if (phases.includes("shutdown")) names.push("Shutdown");
  return names.join(" & ");
}

// Successes sort below every problem level.
function backupRank(r) {
  return r.kind === "success" ? 0 : LEVEL_RANK[r.level] || 0;
}

const VIEWS = {
  logs: {
    list: "anomalies",
    noun: ["entry", "entries"],
    filterPlaceholder: "Filter by logger or message",
    kinds: [["", "All levels"], ["CRITICAL", "Critical"], ["ERROR", "Error"], ["WARNING", "Warning"]],
    kindOf: (r) => r.level,
    search: (r) => `${r.logger} ${r.message} ${r.level}`,
    defaultSort: { key: "logged", dir: -1 },
    empty: {
      open: "Nothing to review. Anomalies from each scan appear here. 🎉",
      archived: "Nothing archived. Entries you mark resolved appear here.",
      ignored: "Nothing ignored. Entries you ignore appear here, still updated by each scan.",
    },
    ignorable: true,
    columns: [
      { key: "level", label: "Level" },
      { key: "logged", label: "Last logged", firstDir: -1 },
      { key: "last", label: "Last found", firstDir: -1 },
      { key: "logger", label: "Logger" },
      { key: "message", label: "Message" },
      { key: "count", label: "Count", num: true, firstDir: -1 },
    ],
    compare: {
      level: (a, b) => (LEVEL_RANK[a.level] || 0) - (LEVEL_RANK[b.level] || 0),
      logged: (a, b) => (a.last_logged || "").localeCompare(b.last_logged || ""),
      last: (a, b) => (a.last_scan || a.last_seen || "").localeCompare(b.last_scan || b.last_seen || ""),
      logger: (a, b) => a.logger.localeCompare(b.logger, undefined, { sensitivity: "base" }),
      message: (a, b) => a.message.localeCompare(b.message, undefined, { sensitivity: "base" }),
      count: (a, b) => a.count - b.count,
    },
    tiebreak: (a, b) => (a.last_seen || "").localeCompare(b.last_seen || ""),
    expandable: true,
    where: "the Log review",
    // Shares the "anomalies" list with the Startup & shutdown view.
    include: (r) => r.category !== "restart",
  },
  restarts: {
    list: "anomalies",
    include: (r) => r.category === "restart",
    noun: ["entry", "entries"],
    filterPlaceholder: "Filter by logger or message",
    kinds: [
      ["", "Everything"], ["startup", "Startup"], ["shutdown", "Shutdown"],
      ["CRITICAL", "Critical"], ["ERROR", "Error"], ["WARNING", "Warning"],
    ],
    kindOf: (r) => r.level,
    matches: (r, kind) => (kind === "startup" || kind === "shutdown" ? (r.phases || []).includes(kind) : r.level === kind),
    search: (r) => `${r.logger} ${r.message} ${r.level} ${(r.phases || []).join(" ")}`,
    defaultSort: { key: "logged", dir: -1 },
    empty: {
      open: "No startup or shutdown messages. Anomalies logged only while Home Assistant starts or stops appear here.",
      archived: "Nothing archived. Entries you mark resolved appear here.",
      ignored: "Nothing ignored. Entries you ignore appear here, still updated by each scan.",
    },
    ignorable: true,
    columns: [
      { key: "level", label: "Level" },
      { key: "logged", label: "Last logged", firstDir: -1 },
      { key: "last", label: "Last found", firstDir: -1 },
      { key: "phase", label: "Phase" },
      { key: "logger", label: "Logger" },
      { key: "message", label: "Message" },
      { key: "restarts", label: "Restarts", num: true, firstDir: -1 },
      { key: "count", label: "Count", num: true, firstDir: -1 },
    ],
    compare: {
      level: (a, b) => (LEVEL_RANK[a.level] || 0) - (LEVEL_RANK[b.level] || 0),
      logged: (a, b) => (a.last_logged || "").localeCompare(b.last_logged || ""),
      last: (a, b) => (a.last_scan || a.last_seen || "").localeCompare(b.last_scan || b.last_seen || ""),
      phase: (a, b) => phaseLabel(a).localeCompare(phaseLabel(b)),
      logger: (a, b) => a.logger.localeCompare(b.logger, undefined, { sensitivity: "base" }),
      message: (a, b) => a.message.localeCompare(b.message, undefined, { sensitivity: "base" }),
      restarts: (a, b) => (a.restarts || 0) - (b.restarts || 0),
      count: (a, b) => a.count - b.count,
    },
    tiebreak: (a, b) => (a.last_seen || "").localeCompare(b.last_seen || ""),
    expandable: true,
    where: "Startup & shutdown",
  },
  reboots: {
    list: "restart_history",
    noun: ["restart", "restarts"],
    filterPlaceholder: "Filter by date or time",
    kinds: [["", "Everything"], ["clean", "Clean shutdowns"], ["unclean", "No clean shutdown recorded"]],
    kindOf: (r) => (r.shutdown_start ? "clean" : "unclean"),
    // Filled in with the times as shown (see _onMessage).
    search: (r) => r._text || "",
    decorate: (r, panel) => {
      r._text = [r.shutdown_start, r.starting, r.started, r.window_end].map((t) => panel._dateTime(t)).join(" ");
    },
    defaultSort: { key: "starting", dir: -1 },
    empty: {
      open: "No restarts recorded yet. Each Home Assistant restart since WP Log Doctor 0.29.0 appears here.",
      archived: "Nothing archived. Restarts you archive, and older ones beyond the number kept open (see Settings), appear here.",
    },
    columns: [
      { key: "shutdown", label: "Shutdown began", firstDir: -1 },
      { key: "starting", label: "Started", firstDir: -1 },
      { key: "started", label: "Finished starting", firstDir: -1 },
      { key: "window", label: "Startup messages until", firstDir: -1 },
      { key: "took", label: "Took", num: true, firstDir: -1 },
    ],
    compare: {
      shutdown: (a, b) => (a.shutdown_start || "").localeCompare(b.shutdown_start || ""),
      starting: (a, b) => (a.starting || "").localeCompare(b.starting || ""),
      started: (a, b) => (a.started || "").localeCompare(b.started || ""),
      window: (a, b) => (a.window_end || "").localeCompare(b.window_end || ""),
      took: (a, b) => rebootSeconds(a) - rebootSeconds(b),
    },
    tiebreak: (a, b) => (a.starting || "").localeCompare(b.starting || ""),
    expandable: false,
    resolveLabel: "Archive",
    archivedLabel: "Archived",
    where: "the Restart history",
  },
  failures: {
    list: "failures",
    noun: ["entry", "entries"],
    filterPlaceholder: "Filter by name or reason",
    kinds: [["", "Everything"], ["failed", "Failed runs"], ["missed", "Missed runs"], ["script", "Scripts only"]],
    kindOf: (r) => (r.reason.startsWith("Missed:") ? "missed" : r.reason.startsWith("Failed:") ? "failed" : ""),
    matches: (r, kind) => (kind === "script" ? r.entity_id.startsWith("script.") : VIEWS.failures.kindOf(r) === kind),
    search: (r) => `${r.name} ${r.entity_id} ${r.reason}`,
    defaultSort: { key: "date", dir: -1 },
    empty: {
      open: "No open automation failures. 🎉",
      archived: "Nothing archived. Failures you mark resolved appear here.",
    },
    columns: [
      { key: "date", label: "Date", firstDir: -1 },
      // Time of day, so e.g. everything failing around 03:00 sorts together.
      { key: "time", label: "Time" },
      { key: "name", label: "Automation / script" },
      { key: "reason", label: "Reason" },
    ],
    compare: {
      date: (a, b) => a.when.localeCompare(b.when),
      time: null, // needs formatting; see _compare()
      name: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
      reason: (a, b) => a.reason.localeCompare(b.reason),
    },
    tiebreak: (a, b) => a.when.localeCompare(b.when),
    expandable: false,
    where: "the automation failure log",
  },
  health: {
    list: "health",
    noun: ["entry", "entries"],
    filterPlaceholder: "Filter by name, area or problem",
    kinds: [["", "Everything"], ["offline", "Offline devices"], ["unavailable", "Unavailable entities"], ["integration", "Integrations"], ["repair", "Repairs"]],
    kindOf: (r) => r.kind,
    search: (r) => `${r.name} ${r.sub} ${r.detail} ${r.integration_name || ""} ${(r.entities || []).join(" ")}`,
    // Rows are shown under a heading for their integration
    groupBy: (r) => r.integration_name || r.integration || OTHER_GROUP,
    // Home Assistant's own parts (automations, scripts, helpers, ...) first.
    groupRank: (r) => (r.integration_core ? 0 : 1),
    // Links on each integration's heading to its unavailable entities on
    // Home Assistant's entities page (see _groupLinks).
    groupLinks: true,
    defaultSort: { key: "since", dir: -1 },
    empty: {
      open: "No device or integration problems. 🎉",
      archived: "Nothing archived. Problems that clear up by themselves, and ones you mark resolved, appear here.",
    },
    columns: [
      { key: "kind", label: "Type" },
      { key: "name", label: "Name" },
      { key: "detail", label: "Problem" },
      { key: "since", label: "Since", firstDir: -1 },
    ],
    compare: {
      kind: (a, b) => (HEALTH_KINDS[a.kind]?.order ?? 9) - (HEALTH_KINDS[b.kind]?.order ?? 9),
      name: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
      detail: (a, b) => a.detail.localeCompare(b.detail, undefined, { numeric: true }),
      since: (a, b) => (a.since || "").localeCompare(b.since || ""),
    },
    tiebreak: (a, b) => (a.since || "").localeCompare(b.since || ""),
    expandable: true,
    where: "Devices & integrations",
  },
  backups: {
    list: "backups",
    noun: ["entry", "entries"],
    filterPlaceholder: "Filter by source, logger or message",
    kinds: [
      ["", "Everything"], ["problem", "Problems"], ["success", "Successes"],
      ["ha", BACKUP_SOURCES.ha], ["gdrive", BACKUP_SOURCES.gdrive],
    ],
    kindOf: (r) => r.kind,
    matches: (r, kind) => (BACKUP_SOURCES[kind] ? r.source === kind : r.kind === kind),
    search: (r) => `${BACKUP_SOURCES[r.source] || ""} ${r.logger} ${r.message} ${r.kind === "success" ? "success" : r.level}`,
    defaultSort: { key: "logged", dir: -1 },
    empty: {
      open: "No backup messages yet. Backup problems and successful backups appear here.",
      archived: "Nothing archived. Entries you mark resolved appear here.",
      ignored: "Nothing ignored. Entries you ignore appear here, still updated as backups run.",
    },
    ignorable: true,
    columns: [
      { key: "status", label: "Status" },
      { key: "logged", label: "Last logged", firstDir: -1 },
      { key: "last", label: "Last found", firstDir: -1 },
      { key: "source", label: "Source" },
      { key: "message", label: "Message" },
      { key: "count", label: "Count", num: true, firstDir: -1 },
    ],
    compare: {
      status: (a, b) => backupRank(a) - backupRank(b),
      logged: (a, b) => (a.last_logged || "").localeCompare(b.last_logged || ""),
      last: (a, b) => (a.last_scan || a.last_seen || "").localeCompare(b.last_scan || b.last_seen || ""),
      source: (a, b) => (BACKUP_SOURCES[a.source] || "").localeCompare(BACKUP_SOURCES[b.source] || ""),
      message: (a, b) => a.message.localeCompare(b.message, undefined, { sensitivity: "base" }),
      count: (a, b) => a.count - b.count,
    },
    tiebreak: (a, b) => (a.last_seen || "").localeCompare(b.last_seen || ""),
    expandable: true,
    where: "Backups",
  },
};

const HEALTH_KINDS = {
  offline: { label: "Offline", order: 0 },
  unavailable: { label: "Unavailable", order: 1 },
  integration: { label: "Integration", order: 2 },
  repair: { label: "Repair", order: 3 },
};

const RESOLVED_COLUMN = { key: "resolved", label: "Resolved", firstDir: -1 };

// "3m 05s" between two ISO times, or "" if either is missing.
function duration(fromIso, toIso) {
  if (!fromIso || !toIso) return "";
  const seconds = Math.max(0, Math.round((new Date(toIso) - new Date(fromIso)) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const sec = String(seconds % 60).padStart(2, "0");
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m ${sec}s` : `${seconds}s`;
}
const IGNORED_COLUMNS = [
  { key: "ignored", label: "Ignored", firstDir: -1 },
  { key: "ignored_count", label: "Since ignored", num: true, firstDir: -1 },
];

// Which tab an entry is on.
function tabOf(r) {
  if (r.ignored) return "ignored";
  return r.resolved ? "archived" : "open";
}

class LogDoctorPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._narrow = false;
    this._panel = null;
    this._view = "logs";
    this._state = {};
    for (const [name, view] of Object.entries(VIEWS)) {
      this._state[name] = {
        records: [],
        loaded: false,
        unsub: null,
        subscribing: false,
        tab: "open",
        sort: { ...view.defaultSort },
        selected: new Set(),
        expanded: new Set(),
        collapsed: this._loadCollapsed(name),
        filter: "",
        kind: "",
        limit: PAGE_SIZE,
      };
    }
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>${TEMPLATE}`;
    this._el = (name) => this.shadowRoot.querySelector(`[data-el="${name}"]`);
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
    this._el("filter").addEventListener("input", (ev) => {
      const st = this._st();
      st.filter = ev.target.value;
      st.limit = PAGE_SIZE;
      this._render();
    });
    this._onHash = () => this._applyHash();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this._el("settings").hass = hass;
    if (first) this._formatters();
    if (this.isConnected) this._subscribeAll();
  }

  get hass() { return this._hass; }

  set narrow(value) {
    this._narrow = value;
    this.toggleAttribute("narrow", !!value);
  }

  get narrow() { return this._narrow; }

  set panel(value) {
    this._panel = value;
    this._applyHash();
  }

  get panel() { return this._panel; }

  connectedCallback() {
    window.addEventListener("hashchange", this._onHash);
    this._applyHash();
    if (this._hass) this._subscribeAll();
  }

  disconnectedCallback() {
    window.removeEventListener("hashchange", this._onHash);
    for (const name of Object.keys(VIEWS)) this._unsubscribe(name);
  }

  _st(name = this._view) { return this._state[name]; }

  _applyHash() {
    const hash = window.location.hash.replace("#", "");
    const fromConfig = this._panel?.config?.view;
    const isView = (v) => !!VIEWS[v] || v === "settings";
    const view = isView(hash) ? hash : isView(fromConfig) ? fromConfig : this._view;
    if (view !== this._view || !this._rendered) {
      this._view = view;
      this._syncControls();
      this._render();
    }
  }

  _setView(view) {
    if ((!VIEWS[view] && view !== "settings") || view === this._view) return;
    this._view = view;
    history.replaceState(history.state, "", `${window.location.pathname}${window.location.search}#${view}`);
    this._el("confirm").classList.remove("open");
    this._el("scroll").scrollTop = 0;
    this._syncControls();
    this._render();
  }

  _syncControls() {
    if (!VIEWS[this._view]) return;
    const view = VIEWS[this._view];
    const st = this._st();
    const filter = this._el("filter");
    filter.placeholder = view.filterPlaceholder;
    filter.value = st.filter;
    const kind = this._el("kind");
    kind.textContent = "";
    for (const [value, label] of view.kinds) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      kind.appendChild(opt);
    }
    kind.value = st.kind;
  }

  // -- data -----------------------------------------------------------

  _subscribeAll() {
    for (const name of Object.keys(VIEWS)) {
      const st = this._st(name);
      if (!st.unsub && !st.subscribing) this._subscribe(name);
    }
  }

  async _subscribe(name) {
    const st = this._st(name);
    if (st.subscribing || !this._hass) return;
    st.subscribing = true;
    try {
      st.unsub = await this._hass.connection.subscribeMessage(
        (msg) => this._onMessage(name, msg),
        { type: WS.SUBSCRIBE, list: VIEWS[name].list },
      );
    } catch (err) {
      st.error = `Couldn't load: ${err.message || err.code || err}`;
      this._render();
    } finally {
      st.subscribing = false;
    }
  }

  _unsubscribe(name) {
    const st = this._st(name);
    if (st.unsub) {
      try { st.unsub(); } catch (_err) { /* connection already gone */ }
      st.unsub = null;
    }
  }

  _onMessage(name, msg) {
    const st = this._st(name);
    if (msg.reload) {
      // WP Log Doctor is reloading; pick up the new list shortly.
      this._unsubscribe(name);
      setTimeout(() => this._subscribe(name), 2000);
      return;
    }
    const view = VIEWS[name];
    st.records = (msg.records || []).filter((r) => !view.include || view.include(r));
    if (view.decorate) for (const r of st.records) view.decorate(r, this);
    st.loaded = true;
    st.error = null;
    const ids = new Set(st.records.map((r) => r.id));
    for (const id of [...st.selected]) if (!ids.has(id)) st.selected.delete(id);
    this._render();
  }

  // Collapses a group of the current view; its entries are deselected, so
  // nothing hidden is acted on.
  _collapse(group) {
    const view = VIEWS[this._view];
    const st = this._st();
    st.collapsed.add(group);
    for (const r of st.records) if (view.groupBy(r) === group) st.selected.delete(r.id);
  }

  _inCollapsedGroup(r) {
    const view = VIEWS[this._view];
    return !!view.groupBy && this._st().collapsed.has(view.groupBy(r));
  }

  _loadCollapsed(name) {
    try {
      const saved = JSON.parse(localStorage.getItem(COLLAPSED_KEY) || "{}");
      return new Set(Array.isArray(saved[name]) ? saved[name] : []);
    } catch (_err) {
      return new Set();
    }
  }

  _saveCollapsed() {
    try {
      const saved = {};
      for (const [name, st] of Object.entries(this._state)) {
        if (st.collapsed.size) saved[name] = [...st.collapsed];
      }
      localStorage.setItem(COLLAPSED_KEY, JSON.stringify(saved));
    } catch (_err) {
      // Not remembered; it still works for this visit.
    }
  }

  async _call(type, extra = {}) {
    try {
      return await this._hass.callWS({ type, list: VIEWS[this._view].list, ...extra });
    } catch (err) {
      alert(`WP Log Doctor: ${err.message || err.code || err}`);
      return null;
    }
  }

  // -- formatting -----------------------------------------------------

  _formatters() {
    // Shown in Home Assistant's time zone, like the files Log Doctor writes.
    const timeZone = this._hass?.config?.time_zone || undefined;
    const make = (locale, opts) => {
      try { return new Intl.DateTimeFormat(locale, { ...opts, timeZone }); }
      catch (_err) { return new Intl.DateTimeFormat(locale, opts); }
    };
    this._fmtDate = make("en-CA", { year: "numeric", month: "2-digit", day: "2-digit" });
    this._fmtTime = make("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  }

  _date(iso) {
    const d = new Date(iso);
    return iso && !Number.isNaN(d.getTime()) ? this._fmtDate.format(d) : "";
  }

  _time(iso) {
    const d = new Date(iso);
    return iso && !Number.isNaN(d.getTime()) ? this._fmtTime.format(d) : "";
  }

  _dateTime(iso) {
    return iso ? `${this._date(iso)} ${this._time(iso)}` : "";
  }

  // -- rendering ------------------------------------------------------

  _columns() {
    const cols = VIEWS[this._view].columns;
    const tab = this._st().tab;
    if (tab === "archived") {
      const label = VIEWS[this._view].archivedLabel;
      return [...cols, label ? { ...RESOLVED_COLUMN, label } : RESOLVED_COLUMN];
    }
    if (tab === "ignored") return [...cols, ...IGNORED_COLUMNS];
    return cols;
  }

  _compare(key) {
    const view = VIEWS[this._view];
    if (key === "resolved") return (a, b) => (a.resolved || "").localeCompare(b.resolved || "");
    if (key === "ignored") return (a, b) => (a.ignored || "").localeCompare(b.ignored || "");
    if (key === "ignored_count") return (a, b) => (a.ignored_count || 0) - (b.ignored_count || 0);
    if (this._view === "failures" && key === "time") {
      const cache = new Map();
      const tod = (r) => {
        if (!cache.has(r.id)) cache.set(r.id, this._time(r.when));
        return cache.get(r.id);
      };
      return (a, b) => tod(a).localeCompare(tod(b));
    }
    return view.compare[key] || view.tiebreak;
  }

  _visible() {
    const view = VIEWS[this._view];
    const st = this._st();
    const needle = st.filter.trim().toLowerCase();
    let rows = st.records.filter((r) => tabOf(r) === st.tab);
    if (st.kind) rows = rows.filter((r) => (view.matches ? view.matches(r, st.kind) : view.kindOf(r) === st.kind));
    if (needle) rows = rows.filter((r) => view.search(r).toLowerCase().includes(needle));
    const primary = this._compare(st.sort.key);
    const dir = st.sort.dir;
    rows.sort((a, b) => dir * (primary(a, b) || view.tiebreak(a, b)));
    if (view.groupBy) {
      // Keep the chosen sort within each group. Groups go by rank (see
      // groupRank), then name, with "Other" last.
      const groups = new Map();
      for (const r of rows) {
        const group = view.groupBy(r);
        if (!groups.has(group)) groups.set(group, []);
        groups.get(group).push(r);
      }
      const rank = (name) => {
        if (name === OTHER_GROUP) return 9;
        return view.groupRank ? Math.min(...groups.get(name).map(view.groupRank)) : 0;
      };
      const names = [...groups.keys()].sort((a, b) =>
        rank(a) - rank(b) || a.localeCompare(b, undefined, { sensitivity: "base" }));
      rows = names.flatMap((name) => groups.get(name));
    }
    return rows;
  }

  _render() {
    this._rendered = true;
    for (const btn of this.shadowRoot.querySelectorAll(".view")) {
      btn.classList.toggle("active", btn.dataset.view === this._view);
    }
    for (const name of Object.keys(VIEWS)) {
      const s = this._st(name);
      const open = s.records.filter((r) => tabOf(r) === "open").length;
      this.shadowRoot.querySelector(`[data-count="${name}"]`).textContent = s.loaded ? `(${open})` : "";
    }
    const settings = this._el("settings");
    const showSettings = this._view === "settings";
    this._el("list-card").hidden = showSettings;
    if (showSettings && settings.hidden) {
      settings.hidden = false;
      settings.activate();
    } else if (!showSettings) {
      settings.hidden = true;
    }
    if (showSettings) return;

    const view = VIEWS[this._view];
    const st = this._st();
    const archived = st.tab === "archived";
    const ignoredTab = st.tab === "ignored";
    const tabCounts = { open: 0, archived: 0, ignored: 0 };
    for (const r of st.records) tabCounts[tabOf(r)] += 1;
    const archivedCount = tabCounts.archived;
    const tabNames = { open: "Open", archived: "Archived", ignored: "Ignored" };
    for (const tab of this.shadowRoot.querySelectorAll(".tab")) {
      tab.textContent = `${tabNames[tab.dataset.tab]} (${tabCounts[tab.dataset.tab]})`;
      tab.classList.toggle("active", tab.dataset.tab === st.tab);
    }
    for (const el of this.shadowRoot.querySelectorAll("[data-show], [data-ignorable]")) {
      const onTab = el.dataset.show === undefined || el.dataset.show.split(" ").includes(st.tab);
      el.hidden = !onTab || (el.dataset.ignorable !== undefined && !view.ignorable);
    }
    for (const el of this.shadowRoot.querySelectorAll("[data-only-view]")) {
      const shownByTab = !el.matches("[data-show], [data-ignorable]") || !el.hidden;
      el.hidden = !el.dataset.onlyView.split(" ").includes(this._view) || !shownByTab;
    }

    const rows = this._visible();
    // Rows in collapsed groups aren't shown, and don't count towards the page.
    const isCollapsed = (r) => !!view.groupBy && st.collapsed.has(view.groupBy(r));
    const shown = rows.filter((r) => !isCollapsed(r)).slice(0, st.limit);
    const shownIds = new Set(shown.map((r) => r.id));
    const visibleIds = new Set(rows.map((r) => r.id));
    const selectedVisible = [...st.selected].filter((id) => visibleIds.has(id));
    const columns = this._columns();

    // Header
    const head = this._el("head");
    head.textContent = "";
    const thCheck = document.createElement("th");
    thCheck.className = "check";
    const all = document.createElement("input");
    all.type = "checkbox";
    all.dataset.el = "select-all";
    all.title = "Select all shown";
    const selectable = rows.filter((r) => !isCollapsed(r)).length;
    all.checked = selectable > 0 && selectedVisible.length === selectable;
    all.indeterminate = selectedVisible.length > 0 && selectedVisible.length < selectable;
    thCheck.appendChild(all);
    head.appendChild(thCheck);
    for (const col of columns) {
      const th = document.createElement("th");
      th.className = "sortable" + (col.num ? " num" : "");
      th.dataset.sort = col.key;
      th.textContent = col.label + " ";
      const arrow = document.createElement("span");
      arrow.className = "arrow";
      arrow.textContent = st.sort.key === col.key ? (st.sort.dir > 0 ? "▲" : "▼") : "";
      th.appendChild(arrow);
      head.appendChild(th);
    }

    // Body
    const body = this._el("body");
    body.textContent = "";
    const frag = document.createDocumentFragment();
    const groupSizes = new Map();
    if (view.groupBy) {
      for (const r of rows) groupSizes.set(view.groupBy(r), (groupSizes.get(view.groupBy(r)) || 0) + 1);
    }
    let lastGroup = null;
    const lastShown = shown.length ? shown[shown.length - 1].id : null;
    let pastPage = shown.length === 0;
    for (const r of rows) {
      const collapsed = isCollapsed(r);
      // Stop after the page's last row; collapsed groups up to there still get a heading.
      if (pastPage && !collapsed) break;
      if (view.groupBy && view.groupBy(r) !== lastGroup) {
        lastGroup = view.groupBy(r);
        const trGroup = document.createElement("tr");
        trGroup.className = "group";
        trGroup.dataset.groupToggle = lastGroup;
        trGroup.title = collapsed ? "Show this integration's entries" : "Hide this integration's entries";
        const td = document.createElement("td");
        td.colSpan = columns.length + 1;
        const caret = document.createElement("span");
        caret.className = "caret";
        caret.textContent = collapsed ? "▸" : "▾";
        td.append(caret, lastGroup);
        const count = document.createElement("span");
        count.className = "group-count";
        count.textContent = ` (${groupSizes.get(lastGroup)})`;
        td.appendChild(count);
        if (view.groupLinks) td.append(...this._groupLinks(rows.filter((g) => view.groupBy(g) === lastGroup)));
        trGroup.appendChild(td);
        frag.appendChild(trGroup);
      }
      if (collapsed || !shownIds.has(r.id)) continue;
      if (r.id === lastShown) pastPage = true;
      const tr = document.createElement("tr");
      tr.className = "row";
      tr.dataset.id = r.id;
      if (st.selected.has(r.id)) tr.classList.add("selected");
      const tdCheck = document.createElement("td");
      tdCheck.className = "check";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.row = r.id;
      cb.checked = st.selected.has(r.id);
      tdCheck.appendChild(cb);
      tr.appendChild(tdCheck);
      if (this._view === "logs" || this._view === "restarts") this._logCells(tr, r);
      else if (this._view === "backups") this._backupCells(tr, r);
      else if (this._view === "health") this._healthCells(tr, r);
      else if (this._view === "reboots") this._rebootCells(tr, r);
      else this._failureCells(tr, r);
      if (archived) {
        const td = this._td("", "when");
        td.append(this._label(`${VIEWS[this._view].archivedLabel || "Resolved"} `));
        if (r.recovered) {
          const chip = this._chip("recovered", "Cleared");
          chip.title = "Cleared up by itself";
          td.appendChild(chip);
        }
        if (r.auto_archived) {
          const chip = this._chip("phase", "Auto");
          chip.title = "Archived automatically: more restarts than the number kept open (see Settings)";
          td.appendChild(chip);
        }
        td.append(this._dateTime(r.resolved));
        tr.appendChild(td);
      }
      if (ignoredTab) {
        const td = this._td("", "when");
        td.append(this._label("Ignored "), this._dateTime(r.ignored));
        tr.appendChild(td);
        const tdCount = this._td("", "num");
        tdCount.title = "Times logged since it was ignored";
        tdCount.append(this._label("Since ignored: "), String(r.ignored_count || 0));
        tr.appendChild(tdCount);
      }
      frag.appendChild(tr);
      if (view.expandable && st.expanded.has(r.id)) {
        frag.appendChild(this._view === "logs" || this._view === "backups" || this._view === "restarts"
          ? this._logDetails(r, columns.length + 1)
          : this._healthDetails(r, columns.length + 1));
      }
    }
    body.appendChild(frag);

    // Status / empty / more
    let status = "";
    if (st.error) status = st.error;
    else if (!st.loaded) status = "Loading…";
    else if (!rows.length) {
      status = st.filter.trim() || st.kind ? "Nothing matches the filter." : view.empty[st.tab];
    }
    const statusEl = this._el("status");
    statusEl.textContent = status;
    statusEl.hidden = !status;
    const expandedCount = rows.filter((r) => !isCollapsed(r)).length;
    this._el("more").hidden = expandedCount <= shown.length;
    this._el("footer").textContent = rows.length
      ? `Showing ${shown.length} of ${rows.length}` + (selectedVisible.length ? ` · ${selectedVisible.length} selected` : "")
      : "";

    // Buttons
    const n = selectedVisible.length;
    const resolveBtn = this.shadowRoot.querySelector('[data-action="resolve"]');
    resolveBtn.disabled = n === 0;
    const resolveLabel = view.resolveLabel;
    resolveBtn.textContent = resolveLabel
      ? (n ? `${resolveLabel} ${n}` : resolveLabel)
      : (n ? `Mark ${n} resolved` : "Mark resolved");
    const deleteBtn = this.shadowRoot.querySelector('[data-action="ask-delete"]');
    deleteBtn.disabled = n === 0;
    deleteBtn.textContent = n ? `Delete ${n}` : "Delete selected";
    const restoreBtn = this.shadowRoot.querySelector('[data-action="restore"]');
    restoreBtn.disabled = n === 0;
    restoreBtn.textContent = n ? `Restore ${n} to open` : "Restore to open";
    const groupsBtn = this.shadowRoot.querySelector('[data-action="toggle-groups"]');
    const groupNames = view.groupBy ? [...groupSizes.keys()] : [];
    const allCollapsed = groupNames.length > 0 && groupNames.every((g) => st.collapsed.has(g));
    groupsBtn.disabled = groupNames.length === 0;
    groupsBtn.textContent = allCollapsed ? "Expand all" : "Collapse all";
    for (const action of ["to-restarts", "to-operational"]) {
      this.shadowRoot.querySelector(`[data-action="${action}"]`).disabled = n === 0;
    }
    const ignoreBtn = this.shadowRoot.querySelector('[data-action="ignore"]');
    ignoreBtn.disabled = n === 0;
    ignoreBtn.textContent = n ? `Ignore ${n}` : "Ignore";
    const unignoreBtn = this.shadowRoot.querySelector('[data-action="unignore"]');
    unignoreBtn.disabled = n === 0;
    unignoreBtn.textContent = n ? `Stop ignoring ${n}` : "Stop ignoring";
    const copyBtn = this.shadowRoot.querySelector('[data-action="copy-prompt"]');
    copyBtn.disabled = n === 0;
    if (!copyBtn.dataset.busy) copyBtn.textContent = n ? `Copy investigation prompt (${n})` : "Copy investigation prompt";
    this.shadowRoot.querySelector('[data-action="ask-clear"]').disabled = archivedCount === 0;
    if (archivedCount === 0) this._el("confirm").classList.remove("open");
  }

  // Copies the investigation prompt for the given Log review entries. The
  // prompt comes from the integration (the same one the investigation stage
  // sends); the clipboard write is started straight from the click, with
  // the text still to come, so browsers that need a user gesture allow it.
  async _copyPrompt(btn, ids) {
    const fetched = this._hass.callWS({ type: WS.INVESTIGATION_PROMPT, ids });
    const label = btn.textContent;
    const done = (text) => {
      btn.textContent = text;
      btn.dataset.busy = "1";
      setTimeout(() => {
        delete btn.dataset.busy;
        btn.textContent = label;
        this._render();
      }, 2000);
    };
    let prompt;
    try {
      prompt = fetched.then((res) => res.prompt);
      if (navigator.clipboard && window.ClipboardItem) {
        try {
          const blob = prompt.then((text) => new Blob([text], { type: "text/plain" }));
          await navigator.clipboard.write([new ClipboardItem({ "text/plain": blob })]);
          done("Copied ✓");
          return;
        } catch (_err) {
          // Fall through to the other ways of copying.
        }
      }
      const text = await prompt;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
          await navigator.clipboard.writeText(text);
          done("Copied ✓");
          return;
        } catch (_err) {
          // Fall through.
        }
      }
      if (this._copyWithSelection(text)) {
        done("Copied ✓");
        return;
      }
      // Couldn't reach the clipboard (e.g. Home Assistant served over plain
      // http); let the user copy it by hand.
      window.prompt("Copy the investigation prompt (Ctrl+C / ⌘C):", text);
    } catch (err) {
      alert(`WP Log Doctor: ${err.message || err.code || err}`);
    }
  }

  _copyWithSelection(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_err) { ok = false; }
    ta.remove();
    return ok;
  }

  // Links from an integration's heading to Home Assistant's entities page,
  // filtered to that integration (its ?domain= parameter) with the status
  // typed into the search box: the page takes that from the history
  // state's "filter" when opened with a filter in the URL, and the Status
  // column is searchable. Entities no longer provided show as "Not
  // provided" there rather than "Unavailable", and the search box holds
  // one term, so they get a link of their own.
  _groupLinks(groupRows) {
    const domain = groupRows.find((r) => r.integration)?.integration;
    const entityRows = groupRows.filter((r) => (r.kind === "offline" || r.kind === "unavailable") && (r.entities || []).length);
    if (!domain || !entityRows.length) return [];
    const status = (key, fallback) =>
      this._hass?.localize?.(`ui.panel.config.entities.picker.status.${key}`) || fallback;
    const link = (label, search, title) => {
      const a = document.createElement("a");
      a.className = "group-link";
      a.href = `/config/entities?domain=${encodeURIComponent(domain)}`;
      a.dataset.nav = "1";
      a.dataset.search = search;
      a.title = title;
      a.textContent = label;
      return a;
    };
    const links = [link("Unavailable entities ↗", status("unavailable", "Unavailable"),
      "Open Settings → Entities for this integration, searching for unavailable entities")];
    if (entityRows.some((r) => (r.detail || "").includes("no longer provided"))) {
      links.push(link("Not provided ↗", status("not_provided", "Not provided"),
        "Open Settings → Entities for this integration, searching for entities it no longer provides"));
    }
    return links;
  }

  // Restart history rows: one restart's shutdown and startup windows.
  _rebootCells(tr, r) {
    const tdShutdown = this._td("", "when");
    tdShutdown.append(this._label("Shutdown began "));
    if (r.shutdown_start) {
      tdShutdown.append(this._dateTime(r.shutdown_start));
    } else {
      const chip = this._chip("unavailable", r.unclean ? "Not clean" : "Not recorded");
      chip.title = r.unclean
        ? "Home Assistant didn't shut down cleanly (a crash, power cut or forced stop), so no shutdown window"
        : "The shutdown before this start wasn't recorded (before Log Doctor recorded restarts)";
      tdShutdown.appendChild(chip);
    }
    tr.appendChild(tdShutdown);

    const tdStart = this._td("", "when");
    tdStart.append(this._label("Started "), this._dateTime(r.starting));
    if (r.current) {
      const chip = this._chip("recovered", "Current");
      chip.title = "Home Assistant has been running since this start";
      chip.style.marginLeft = "6px";
      tdStart.appendChild(chip);
    }
    tr.appendChild(tdStart);

    const tdStarted = this._td("", "when");
    tdStarted.append(this._label("Finished starting "),
      r.started ? this._dateTime(r.started) : r.current ? "Still starting" : "Didn't finish starting");
    tr.appendChild(tdStarted);

    const tdWindow = this._td("", "when");
    tdWindow.title = "Messages up to this time count as startup messages (the grace period after finishing starting, see Settings)";
    tdWindow.append(this._label("Startup messages until "), this._dateTime(r.window_end));
    tr.appendChild(tdWindow);

    const tdTook = this._td("", "num");
    tdTook.title = r.shutdown_start ? "From the shutdown until Home Assistant had finished starting" : "From the start until Home Assistant had finished starting";
    tdTook.append(this._label("Took "), duration(r.shutdown_start || r.starting, r.started));
    tr.appendChild(tdTook);
  }

  // Last logged - the time the newest log line itself gives - and Last
  // found - the scan that last found it (see anomaly_store.py).
  _lastCells(tr, r, loggedLabel) {
    const tdLogged = this._td("", "when");
    tdLogged.append(this._label(loggedLabel));
    if (r.last_logged) {
      tdLogged.append(this._dateTime(r.last_logged));
    } else {
      tdLogged.append("—");
      tdLogged.title = "Its log lines don't say when they were logged";
    }
    tr.appendChild(tdLogged);
    const tdFound = this._td("", "when");
    tdFound.append(this._label("Found "), this._dateTime(r.last_scan || r.last_seen));
    tdFound.title = "The scan that last found it";
    tr.appendChild(tdFound);
  }

  // Log review and Startup & shutdown rows (the latter with Phase and
  // Restarts too).
  _logCells(tr, r) {
    const tdLevel = this._td("", "");
    tdLevel.appendChild(this._chip(r.level.toLowerCase(), r.level));
    if (r.recurred) {
      const chip = this._chip("recurred", "Recurred");
      chip.title = "Logged again after it was marked resolved";
      tdLevel.appendChild(chip);
    }
    if (r.while_running) {
      const chip = this._chip("running", "Also while running");
      chip.title = `Was on Startup & shutdown until it was logged while Home Assistant was running normally (scan of ${this._dateTime(r.while_running)})`;
      tdLevel.appendChild(chip);
    }
    tr.appendChild(tdLevel);

    this._lastCells(tr, r, "Last logged ");

    if (this._view === "restarts") {
      const tdPhase = this._td("", "");
      for (const phase of r.phases || []) {
        tdPhase.appendChild(this._chip("phase", phase === "startup" ? "Startup" : "Shutdown"));
      }
      tr.appendChild(tdPhase);
    }

    tr.appendChild(this._td(r.logger, "logger"));

    const tdMsg = this._td("", "text");
    const expand = document.createElement("button");
    expand.className = "expand";
    expand.dataset.expand = r.id;
    expand.title = "Show log lines and details";
    expand.textContent = this._st().expanded.has(r.id) ? "▾" : "▸";
    tdMsg.appendChild(expand);
    if (r.known_issue) {
      const chip = this._chip("known", "Known issue");
      chip.title = r.known_issue.title;
      tdMsg.appendChild(chip);
    }
    tdMsg.appendChild(document.createTextNode(r.message));
    tr.appendChild(tdMsg);

    if (this._view === "restarts") {
      const tdRestarts = this._td("", "num");
      tdRestarts.title = "How many restarts it was logged during";
      tdRestarts.append(this._label("Restarts "), String(r.restarts || 0));
      tr.appendChild(tdRestarts);
    }

    const tdCount = this._td("", "num");
    tdCount.append(this._label("Count "), String(r.count));
    tr.appendChild(tdCount);
  }

  _backupCells(tr, r) {
    const tdStatus = this._td("", "");
    if (r.kind === "success") tdStatus.appendChild(this._chip("success", "Success"));
    else tdStatus.appendChild(this._chip(r.level.toLowerCase(), r.level));
    if (r.recurred) {
      const chip = this._chip("recurred", "Recurred");
      chip.title = "Logged again after it was marked resolved";
      tdStatus.appendChild(chip);
    }
    tr.appendChild(tdStatus);

    this._lastCells(tr, r, r.kind === "success" ? "Last success " : "Last logged ");

    const tdSource = this._td("", "logger");
    tdSource.appendChild(document.createTextNode(BACKUP_SOURCES[r.source] || r.source || ""));
    const sub = document.createElement("div");
    sub.className = "sub";
    sub.textContent = r.logger;
    tdSource.appendChild(sub);
    tr.appendChild(tdSource);

    const tdMsg = this._td("", "text");
    const expand = document.createElement("button");
    expand.className = "expand";
    expand.dataset.expand = r.id;
    expand.title = "Show log lines and details";
    expand.textContent = this._st().expanded.has(r.id) ? "▾" : "▸";
    tdMsg.appendChild(expand);
    if (r.known_issue) {
      const chip = this._chip("known", "Known issue");
      chip.title = r.known_issue.title;
      tdMsg.appendChild(chip);
    }
    tdMsg.appendChild(document.createTextNode(r.message));
    tr.appendChild(tdMsg);

    const tdCount = this._td("", "num");
    tdCount.append(this._label("Count "), String(r.count));
    tr.appendChild(tdCount);
  }

  _logDetails(r, span) {
    const tr = document.createElement("tr");
    tr.className = "details";
    const td = document.createElement("td");
    td.colSpan = span;
    const box = document.createElement("div");
    box.className = "detail-box";

    const meta = document.createElement("div");
    meta.className = "detail-meta";
    meta.textContent =
      `First seen ${this._dateTime(r.first_seen)} · last seen ${this._dateTime(r.last_seen)} · ` +
      (r.last_logged ? `last logged ${this._dateTime(r.last_logged)} · ` : "") +
      `${r.count} line${r.count === 1 ? "" : "s"} over ${r.scans} scan${r.scans === 1 ? "" : "s"}` +
      (r.restarts ? ` · logged during ${r.restarts} restart${r.restarts === 1 ? "" : "s"}` : "") +
      ` · signature ${r.id}`;
    box.appendChild(meta);

    if (r.known_issue) {
      const h = document.createElement("h4");
      h.textContent = `Known issue: ${r.known_issue.title}`;
      box.appendChild(h);
      if (r.known_issue.explanation) box.appendChild(this._p(r.known_issue.explanation));
      if (r.known_issue.fix) box.appendChild(this._p(`Suggested fix: ${r.known_issue.fix}`));
      if (r.known_issue.doc_url && /^https?:\/\//.test(r.known_issue.doc_url)) {
        const a = document.createElement("a");
        a.href = r.known_issue.doc_url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = "Documentation";
        box.appendChild(a);
      }
    }
    const samples = r.samples || [];
    if (samples.length) {
      const h = document.createElement("h4");
      h.textContent = this._view === "backups"
        ? `Latest log lines (${samples.length})`
        : `Log lines from the latest scan that found it (${samples.length})`;
      box.appendChild(h);
      const pre = document.createElement("pre");
      pre.textContent = samples.map((line) => this._localJournalTime(line)).join("\n");
      box.appendChild(pre);
    }
    td.appendChild(box);
    tr.appendChild(td);
    return tr;
  }

  _failureCells(tr, r) {
    const tdDate = this._td(this._date(r.when), "when");
    tr.appendChild(tdDate);
    tr.appendChild(this._td(this._time(r.when), "when"));

    const tdName = document.createElement("td");
    const domain = (r.entity_id || "automation.").split(".")[0];
    if (domain === "script") tdName.appendChild(this._chip("script", "Script"));
    if (r.config_id) {
      const a = document.createElement("a");
      a.href = `/config/${domain === "script" ? "script" : "automation"}/trace/${encodeURIComponent(r.config_id)}`;
      a.dataset.nav = "1";
      a.title = `Open this ${domain === "script" ? "script" : "automation"}'s traces`;
      a.textContent = r.name;
      tdName.appendChild(a);
    } else {
      tdName.appendChild(document.createTextNode(r.name));
    }
    if (r.entity_id) {
      const ent = document.createElement("div");
      ent.className = "sub";
      ent.textContent = r.entity_id;
      tdName.appendChild(ent);
    }
    tr.appendChild(tdName);

    const tdReason = this._td("", "text");
    const kind = VIEWS.failures.kindOf(r);
    let text = r.reason;
    if (kind) {
      tdReason.appendChild(this._chip(kind, kind));
      text = text.replace(/^(Failed|Missed): /, "");
    }
    tdReason.appendChild(document.createTextNode(text));
    tr.appendChild(tdReason);
  }

  _healthCells(tr, r) {
    const tdKind = this._td("", "");
    tdKind.appendChild(this._chip(r.kind, HEALTH_KINDS[r.kind]?.label || r.kind));
    if (r.recurred) {
      const chip = this._chip("recurred", "Recurred");
      chip.title = "Came back after it had cleared up";
      tdKind.appendChild(chip);
    }
    tr.appendChild(tdKind);

    const tdName = document.createElement("td");
    if (r.link) {
      const a = document.createElement("a");
      a.href = r.link;
      a.dataset.nav = "1";
      a.textContent = r.name;
      tdName.appendChild(a);
    } else {
      tdName.appendChild(document.createTextNode(r.name));
    }
    if (r.sub) {
      const sub = document.createElement("div");
      sub.className = "sub";
      sub.textContent = r.sub;
      tdName.appendChild(sub);
    }
    tr.appendChild(tdName);

    const tdDetail = this._td("", "text");
    if ((r.entities || []).length) {
      const expand = document.createElement("button");
      expand.className = "expand";
      expand.dataset.expand = r.id;
      expand.title = "Show the entities";
      expand.textContent = this._st().expanded.has(r.id) ? "▾" : "▸";
      tdDetail.appendChild(expand);
    }
    tdDetail.appendChild(document.createTextNode(r.detail));
    tr.appendChild(tdDetail);

    const tdSince = this._td("", "when");
    tdSince.append(this._label("Since "), this._dateTime(r.since));
    tr.appendChild(tdSince);
  }

  _healthDetails(r, span) {
    const tr = document.createElement("tr");
    tr.className = "details";
    const td = document.createElement("td");
    td.colSpan = span;
    const box = document.createElement("div");
    box.className = "detail-box";
    const h = document.createElement("h4");
    h.textContent = "Unavailable entities";
    box.appendChild(h);
    const ul = document.createElement("ul");
    ul.className = "entity-list";
    // Each entry is one device's (or one entity with no device), so its
    // entities open that device's page, where they can be removed; an
    // entity with no device opens its own dialog (settings to remove it).
    const deviceLink = (r.link || "").startsWith("/config/devices/device/") ? r.link : null;
    for (const entityId of r.entities || []) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      if (deviceLink) {
        a.href = deviceLink;
        a.dataset.nav = "1";
        a.title = `Open the device ${r.name}`;
      } else {
        a.href = "#";
        a.dataset.moreInfo = entityId;
        a.title = "Open this entity (its settings let you remove it)";
      }
      a.textContent = entityId;
      li.appendChild(a);
      ul.appendChild(li);
    }
    box.appendChild(ul);
    td.appendChild(box);
    tr.appendChild(td);
    return tr;
  }

  // The Supervisor's journal lines (Host, add-ons, plugins) start with the
  // time in UTC, without saying so: "2026-09-29 02:35:25.250 host proc[1]: ".
  // Shown in local time like every other time here. Home Assistant's own
  // "time LEVEL (thread)" lines are already local and left alone.
  _localJournalTime(line) {
    const match = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(\.\d+)?( \S+ [^\s:]+: )/.exec(line);
    if (!match) return line;
    const iso = `${match[1]}T${match[2]}${match[3] || ""}Z`;
    if (Number.isNaN(new Date(iso).getTime())) return line;
    return `${this._dateTime(iso)}${match[3] || ""}${match[4]}${line.slice(match[0].length)}`;
  }

  _td(text, cls) {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    if (text) td.textContent = text;
    return td;
  }

  _p(text) {
    const p = document.createElement("p");
    p.textContent = text;
    return p;
  }

  _chip(cls, text) {
    const chip = document.createElement("span");
    chip.className = `chip ${cls}`;
    chip.textContent = text;
    return chip;
  }

  _label(text) {
    // Only shown in the phone layout, where there are no column headers.
    const span = document.createElement("span");
    span.className = "label";
    span.textContent = text;
    return span;
  }

  // -- events ---------------------------------------------------------

  _onChange(ev) {
    if (!VIEWS[this._view]) return;
    const target = ev.target;
    const st = this._st();
    if (target.dataset.row) {
      if (target.checked) st.selected.add(target.dataset.row);
      else st.selected.delete(target.dataset.row);
      this._render();
    } else if (target.dataset.el === "select-all") {
      // Not the entries hidden in collapsed groups.
      for (const r of this._visible().filter((r) => !this._inCollapsedGroup(r))) {
        if (target.checked) st.selected.add(r.id);
        else st.selected.delete(r.id);
      }
      this._render();
    } else if (target.dataset.el === "kind") {
      st.kind = target.value;
      st.limit = PAGE_SIZE;
      this._render();
    }
  }

  async _onClick(ev) {
    const path = ev.composedPath();
    const find = (key) => path.find((el) => el.dataset && el.dataset[key] !== undefined);
    const st = this._st();

    const moreInfo = find("moreInfo");
    if (moreInfo) {
      ev.preventDefault();
      // Home Assistant's own entity dialog.
      this.dispatchEvent(new CustomEvent("hass-more-info", {
        detail: { entityId: moreInfo.dataset.moreInfo }, bubbles: true, composed: true,
      }));
      return;
    }
    const link = find("nav");
    if (link) {
      ev.preventDefault();
      // A search for the page opened (see _groupLinks).
      history.pushState(link.dataset.search ? { filter: link.dataset.search } : null, "", link.getAttribute("href"));
      window.dispatchEvent(new CustomEvent("location-changed"));
      if (link.dataset.search) {
        // Home Assistant keeps the entities page once opened and only
        // re-attaches it after this event, so a second visit would miss the
        // new URL and keep the first one's filters. Tell it again once it's
        // attached; it ignores the event if its filters already match.
        for (const delay of [100, 500]) {
          setTimeout(() => window.dispatchEvent(new CustomEvent("location-changed")), delay);
        }
      }
      return;
    }
    const viewBtn = find("view");
    if (viewBtn) {
      this._setView(viewBtn.dataset.view);
      return;
    }
    if (!VIEWS[this._view]) {
      // Settings view: it handles its own clicks; only the menu is ours.
      if (find("action")?.dataset.action === "menu") {
        this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
      }
      return;
    }
    const groupRow = find("groupToggle");
    if (groupRow) {
      const group = groupRow.dataset.groupToggle;
      if (st.collapsed.has(group)) st.collapsed.delete(group);
      else this._collapse(group);
      this._saveCollapsed();
      this._render();
      return;
    }
    const expand = find("expand");
    if (expand) {
      const id = expand.dataset.expand;
      if (st.expanded.has(id)) st.expanded.delete(id);
      else st.expanded.add(id);
      this._render();
      return;
    }
    const tab = find("tab");
    if (tab) {
      if (tab.dataset.tab !== st.tab) {
        st.tab = tab.dataset.tab;
        st.selected.clear();
        st.limit = PAGE_SIZE;
        // A column only this tab had (e.g. Resolved) can't stay the sort.
        if (!this._columns().some((c) => c.key === st.sort.key)) st.sort = { ...VIEWS[this._view].defaultSort };
        this._el("scroll").scrollTop = 0;
        this._el("confirm").classList.remove("open");
        this._render();
      }
      return;
    }
    const th = find("sort");
    if (th) {
      const key = th.dataset.sort;
      const col = this._columns().find((c) => c.key === key);
      st.sort = st.sort.key === key
        ? { key, dir: -st.sort.dir }
        // Dates and counts start newest/largest first; text A-Z.
        : { key, dir: col && col.firstDir ? col.firstDir : 1 };
      this._render();
      return;
    }
    const btn = find("action");
    if (!btn || btn.disabled) return;
    const selectedIds = () => {
      const visible = new Set(this._visible().map((r) => r.id));
      return [...st.selected].filter((id) => visible.has(id));
    };
    switch (btn.dataset.action) {
      case "menu":
        this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
        break;
      case "toggle-groups": {
        const view = VIEWS[this._view];
        const names = new Set(this._visible().map((r) => view.groupBy(r)));
        const allCollapsed = [...names].every((g) => st.collapsed.has(g));
        for (const g of names) {
          if (allCollapsed) st.collapsed.delete(g);
          else this._collapse(g);
        }
        this._saveCollapsed();
        this._render();
        break;
      }
      case "more":
        st.limit += PAGE_SIZE;
        this._render();
        break;
      case "resolve": {
        const ids = selectedIds();
        if (ids.length && (await this._call(WS.RESOLVE, { ids }))) {
          for (const id of ids) st.selected.delete(id);
          this._render();
        }
        break;
      }
      case "to-restarts":
      case "to-operational": {
        const ids = selectedIds();
        const category = btn.dataset.action === "to-restarts" ? "restart" : "operational";
        if (ids.length && (await this._call(WS.SET_CATEGORY, { ids, category }))) {
          for (const id of ids) st.selected.delete(id);
          this._render();
        }
        break;
      }
      case "ignore":
      case "unignore": {
        const ids = selectedIds();
        const type = btn.dataset.action === "ignore" ? WS.IGNORE : WS.UNIGNORE;
        if (ids.length && (await this._call(type, { ids }))) {
          for (const id of ids) st.selected.delete(id);
          this._render();
        }
        break;
      }
      case "restore": {
        const ids = selectedIds();
        if (ids.length && (await this._call(WS.RESTORE, { ids }))) {
          for (const id of ids) st.selected.delete(id);
          this._render();
        }
        break;
      }
      case "copy-prompt": {
        // In the order they're listed.
        const ids = this._visible().filter((r) => st.selected.has(r.id)).map((r) => r.id);
        if (ids.length) await this._copyPrompt(btn, ids);
        break;
      }
      case "ask-delete": {
        const ids = selectedIds();
        if (!ids.length) break;
        const [one, many] = VIEWS[this._view].noun;
        this._confirmIds = ids;
        this._el("confirm-text").textContent =
          `Permanently delete ${ids.length} archived ${ids.length === 1 ? one : many} from ${VIEWS[this._view].where}? This can't be undone.`;
        this._el("confirm").classList.add("open");
        break;
      }
      case "ask-clear": {
        this._confirmIds = null;
        const count = st.records.filter((r) => tabOf(r) === "archived").length;
        const [one, many] = VIEWS[this._view].noun;
        const where = VIEWS[this._view].where;
        this._el("confirm-text").textContent =
          `Permanently delete all ${count} archived ${count === 1 ? one : many} from ${where}? This can't be undone.`;
        this._el("confirm").classList.add("open");
        break;
      }
      case "cancel-clear":
        this._confirmIds = null;
        this._el("confirm").classList.remove("open");
        break;
      case "clear": {
        this._el("confirm").classList.remove("open");
        const ids = this._confirmIds;
        this._confirmIds = null;
        const ok = ids
          ? await this._call(WS.DELETE, { ids })
          // Only this view's entries: some views share a list (see include).
          : await this._call(WS.CLEAR_ARCHIVED, { ids: st.records.filter((r) => tabOf(r) === "archived").map((r) => r.id) });
        if (ok) {
          st.selected.clear();
          this._render();
        }
        break;
      }
      default:
        break;
    }
  }
}

if (!customElements.get("log-doctor-panel")) {
  customElements.define("log-doctor-panel", LogDoctorPanel);
}

// -- Settings view ------------------------------------------------------
//
// Everything from the integration's Configure dialog plus its entities
// (the Auto-investigate switch, the Scan now button, the clear_history
// service). Saving goes through log_doctor/settings/update, which
// validates like the Configure dialog and reloads WP Log Doctor.

const SWS = {
  GET: "log_doctor/settings/get",
  UPDATE: "log_doctor/settings/update",
  AUTO_INVESTIGATE: "log_doctor/settings/set_auto_investigate",
  SCAN_NOW: "log_doctor/settings/scan_now",
  CLEAR_HISTORY: "log_doctor/settings/clear_history",
};

const SETTINGS_SECTIONS = [
  {
    title: "Daily scan",
    fields: [
      { key: "scan_time", label: "Daily scan time", type: "time" },
      { key: "min_severity", label: "Minimum severity to report", type: "select", options: "severity_levels" },
      { key: "lookback_hours", label: "Lookback window on the first scan", type: "number", min: 1, max: 168, unit: "hours" },
      { key: "log_path", label: "Log file path", type: "text" },
      { key: "include_supervisor_logs", label: "Also check Supervisor, Host and add-on logs", help: "Home Assistant OS / Supervised only.", type: "bool" },
      { key: "restart_grace_minutes", label: "Count as startup messages until this long after starting", type: "number", min: 0, max: 60, unit: "minutes", help: "Messages logged from Home Assistant starting until this long after it has finished starting (and while it shuts down) go on Startup & shutdown." },
      { key: "restart_history_open_entries", label: "Restarts kept open on Restart history", type: "number", min: 1, max: 500, help: "Older ones are archived automatically." },
      { key: "report_retention_days", label: "Keep reports and list entries for", type: "number", min: 1, max: 365, unit: "days", help: "Also how long Log review, Automation failures and Backups entries are kept." },
    ],
  },
  {
    title: "Automations & scripts",
    fields: [
      { key: "monitor_automations", label: "Notify me when any automation or script fails", type: "bool" },
      { key: "monitor_missed_schedules", label: "After a restart, report scheduled runs missed while offline", type: "bool" },
      { key: "missed_schedule_min_pattern_minutes", label: "Skip time patterns repeating more often than", type: "number", min: 0, max: 1440, unit: "minutes", help: "0 checks every time pattern." },
    ],
  },
  {
    title: "Devices & integrations",
    fields: [
      { key: "monitor_health", label: "Watch devices, integrations and Repairs", type: "bool", help: "Checked every 5 minutes." },
      { key: "offline_hours", label: "Report devices offline for at least", type: "number", min: 1, max: 168, unit: "hours" },
    ],
  },
  {
    title: "Notifications",
    fields: [
      { key: "automation_failure_notify_device", label: "Also push automation failures and missed schedules to", type: "device" },
      { key: "mobile_notify_service", label: "Mobile notify service for the daily scan summary", type: "text", datalist: "notify_services", help: "e.g. mobile_app_pixel_10. Leave blank for none." },
    ],
  },
  {
    title: "Investigation (OpenAI)",
    fields: [
      { key: "openai_api_key", label: "OpenAI API key", type: "apikey", help: "Enables automatic investigation of each scan's anomalies." },
      { key: "max_investigated", label: "Max anomalies investigated per scan", type: "number", min: 0, max: 100 },
    ],
    autoInvestigate: true,
  },
];

const SETTINGS_STYLE = `
:host { display: block; }
:host([hidden]) { display: none; }
* { box-sizing: border-box; }
.card {
  background: var(--card-background-color, #fff);
  border-radius: var(--ha-card-border-radius, 12px);
  border: 1px solid var(--divider-color, #e0e0e0);
  margin-bottom: 12px; overflow: hidden;
}
h2 { font-size: 16px; font-weight: 500; margin: 0; padding: 14px 16px 6px; }
.field {
  display: grid; grid-template-columns: minmax(200px, 1fr) minmax(200px, 1.2fr);
  gap: 4px 16px; align-items: center; padding: 10px 16px;
  border-top: 1px solid var(--divider-color, #e0e0e0);
}
.field:first-of-type { border-top: 0; }
.field label { font-weight: 500; }
.help { grid-column: 1; color: var(--secondary-text-color, #727272); font-size: 12px; }
.control { display: flex; align-items: center; gap: 8px; grid-row: 1 / span 2; grid-column: 2; }
.control input[type=text], .control input[type=password], .control input[type=number],
.control input[type=time], .control select {
  font: inherit; padding: 8px 10px; border-radius: 6px; width: 100%; min-width: 0;
  border: 1px solid var(--divider-color, #ccc);
  background: var(--secondary-background-color, #f5f5f5); color: var(--primary-text-color, #212121);
}
.control input[type=number] { max-width: 120px; }
.unit { color: var(--secondary-text-color, #727272); white-space: nowrap; }
.changed > label::after { content: " •"; color: var(--primary-color, #03a9f4); }
input[type=checkbox] { width: 20px; height: 20px; accent-color: var(--primary-color, #03a9f4); cursor: pointer; }
button {
  font: inherit; font-weight: 500; padding: 8px 14px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--primary-color, #03a9f4); background: var(--primary-color, #03a9f4);
  color: var(--text-primary-color, #fff); white-space: nowrap;
}
button.secondary { background: transparent; color: var(--primary-color, #03a9f4); }
button.danger { border-color: var(--error-color, #db4437); background: transparent; color: var(--error-color, #db4437); }
button:disabled { opacity: 0.4; cursor: default; }
.savebar {
  position: sticky; bottom: 0; z-index: 1; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 12px 16px; margin-bottom: 12px;
  background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #e0e0e0);
  border-radius: var(--ha-card-border-radius, 12px);
}
.savebar .msg { flex: 1 1 240px; color: var(--secondary-text-color, #727272); }
.msg.error { color: var(--error-color, #db4437); }
.msg.ok { color: var(--success-color, #43a047); }
.status { padding: 4px 16px 12px; display: grid; gap: 4px; }
.status div { word-break: break-word; }
.status ul { margin: 2px 0 0; padding-left: 20px; }
.status .k { color: var(--secondary-text-color, #727272); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--divider-color, #e0e0e0); align-items: center; }
.actions .msg { flex: 1 1 200px; color: var(--secondary-text-color, #727272); }
.loading { padding: 32px 16px; text-align: center; color: var(--secondary-text-color, #727272); }
@media (max-width: 700px) {
  .field { grid-template-columns: 1fr; }
  .control { grid-row: auto; grid-column: 1; }
}
`;

class LogDoctorSettings extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._data = null;
    this._values = {};
    this._apiKey = { value: "", clear: false };
    this._busy = false;
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${SETTINGS_STYLE}</style><div class="loading">Loading settings…</div>`;
    this.shadowRoot.addEventListener("input", (ev) => this._onInput(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onInput(ev));
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
  }

  set hass(hass) { this._hass = hass; }

  // Called whenever the Settings view is shown.
  activate() {
    if (!this._dirty()) this._load();
  }

  async _load(message) {
    if (!this._hass) return;
    try {
      this._data = await this._hass.callWS({ type: SWS.GET });
    } catch (err) {
      this.shadowRoot.querySelector(".loading")?.replaceChildren(`Couldn't load settings: ${err.message || err.code || err}`);
      return;
    }
    this._values = { ...this._data.options };
    this._apiKey = { value: "", clear: false };
    this._build();
    if (message) this._message(message, "ok");
  }

  // -- values ---------------------------------------------------------

  _normalize(key, value) {
    const field = SETTINGS_SECTIONS.flatMap((s) => s.fields).find((f) => f.key === key);
    if (!field) return value;
    if (field.type === "number") return value === "" || value === null || value === undefined ? value : Number(value);
    if (field.type === "time" && typeof value === "string" && value.length === 5) return `${value}:00`;
    if (field.type === "device") return value || null;
    if (field.type === "text") return value ?? "";
    return value;
  }

  _changes() {
    const changes = {};
    for (const field of SETTINGS_SECTIONS.flatMap((s) => s.fields)) {
      if (field.type === "apikey") continue;
      const before = this._normalize(field.key, this._data.options[field.key]);
      const after = this._normalize(field.key, this._values[field.key]);
      if (before !== after && !(before == null && after == null)) changes[field.key] = after;
    }
    if (this._apiKey.value) changes.openai_api_key = this._apiKey.value;
    return changes;
  }

  _dirty() {
    return !!this._data && (Object.keys(this._changes()).length > 0 || this._apiKey.clear);
  }

  // -- rendering ------------------------------------------------------

  _build() {
    const d = this._data;
    const root = this.shadowRoot;
    root.replaceChildren();
    const style = document.createElement("style");
    style.textContent = SETTINGS_STYLE;
    root.appendChild(style);

    for (const section of SETTINGS_SECTIONS) {
      const card = document.createElement("div");
      card.className = "card";
      const h = document.createElement("h2");
      h.textContent = section.title;
      card.appendChild(h);
      for (const field of section.fields) card.appendChild(this._field(field));
      if (section.autoInvestigate) {
        card.appendChild(this._toggleRow(
          "auto_investigate",
          "Auto-investigate after each scan",
          d.status.auto_investigate,
          "Takes effect straight away (the Auto-investigate switch). Only does anything with an API key set.",
        ));
      }
      root.appendChild(card);
    }

    // Actions and status
    const card = document.createElement("div");
    card.className = "card";
    const h = document.createElement("h2");
    h.textContent = "Last scan";
    card.appendChild(h);
    const status = document.createElement("div");
    status.className = "status";
    status.dataset.el = "status";
    card.appendChild(status);
    const actions = document.createElement("div");
    actions.className = "actions";
    actions.append(
      this._button("Scan now", "scan"),
      this._button("Clear history", "ask-clear-history", "danger"),
    );
    const amsg = document.createElement("span");
    amsg.className = "msg";
    amsg.dataset.el = "action-msg";
    actions.appendChild(amsg);
    card.appendChild(actions);
    root.appendChild(card);
    this._renderStatus();

    // Save bar
    const bar = document.createElement("div");
    bar.className = "savebar";
    const msg = document.createElement("span");
    msg.className = "msg";
    msg.dataset.el = "msg";
    bar.append(msg, this._button("Discard changes", "discard", "secondary"), this._button("Save", "save"));
    root.appendChild(bar);
    this._refreshDirty();
  }

  _field(field) {
    const d = this._data;
    const row = document.createElement("div");
    row.className = "field";
    row.dataset.field = field.key;
    const label = document.createElement("label");
    label.textContent = field.label;
    const id = `f-${field.key}`;
    label.htmlFor = id;
    row.appendChild(label);
    const control = document.createElement("div");
    control.className = "control";
    let input;
    const value = this._values[field.key];

    if (field.type === "bool") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!value;
    } else if (field.type === "select") {
      input = document.createElement("select");
      for (const opt of d[field.options] || []) input.appendChild(new Option(opt, opt));
      input.value = value ?? "";
    } else if (field.type === "device") {
      input = document.createElement("select");
      input.appendChild(new Option("None", ""));
      const devices = d.mobile_devices || [];
      for (const dev of devices) input.appendChild(new Option(dev.name, dev.id));
      if (value && !devices.some((dev) => dev.id === value)) {
        input.appendChild(new Option("(device no longer available)", value));
      }
      input.value = value || "";
    } else if (field.type === "apikey") {
      input = document.createElement("input");
      input.type = "password";
      input.autocomplete = "off";
      input.placeholder = d.openai_api_key_set ? "Set - leave blank to keep it" : "Not set";
      if (d.openai_api_key_set) {
        const remove = document.createElement("label");
        remove.style.cssText = "display:flex;align-items:center;gap:6px;font-weight:400;white-space:nowrap";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.dataset.el = "clear-key";
        remove.append(cb, "Remove key");
        control.appendChild(remove);
      }
    } else {
      input = document.createElement("input");
      input.type = field.type === "number" ? "number" : field.type === "time" ? "time" : "text";
      if (field.type === "time") input.step = 1;
      if (field.min !== undefined) input.min = field.min;
      if (field.max !== undefined) input.max = field.max;
      if (field.type === "number") input.step = 1;
      input.value = value ?? (field.key === "log_path" ? d.default_log_path : "");
      if (field.datalist) {
        const list = document.createElement("datalist");
        list.id = `dl-${field.key}`;
        for (const name of d[field.datalist] || []) list.appendChild(new Option(name));
        input.setAttribute("list", list.id);
        control.appendChild(list);
      }
    }
    input.id = id;
    input.dataset.key = field.key;
    control.prepend(input);
    if (field.unit) {
      const unit = document.createElement("span");
      unit.className = "unit";
      unit.textContent = field.unit;
      control.appendChild(unit);
    }
    row.appendChild(control);
    if (field.help) {
      const help = document.createElement("div");
      help.className = "help";
      help.textContent = field.help;
      row.appendChild(help);
    }
    return row;
  }

  _toggleRow(key, labelText, checked, helpText) {
    const row = document.createElement("div");
    row.className = "field";
    const label = document.createElement("label");
    label.textContent = labelText;
    label.htmlFor = `t-${key}`;
    const control = document.createElement("div");
    control.className = "control";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = `t-${key}`;
    input.checked = !!checked;
    input.dataset.toggle = key;
    control.appendChild(input);
    const help = document.createElement("div");
    help.className = "help";
    help.textContent = helpText;
    row.append(label, control, help);
    return row;
  }

  _button(text, action, cls = "") {
    const b = document.createElement("button");
    b.textContent = text;
    b.dataset.sact = action;
    if (cls) b.className = cls;
    return b;
  }

  _renderStatus() {
    const el = this.shadowRoot.querySelector('[data-el="status"]');
    if (!el) return;
    const s = this._data.status || {};
    const sum = s.summary;
    const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "");
    const lines = (n) => `${n} line${n === 1 ? "" : "s"}`;
    const rows = [];
    if (!sum) {
      rows.push(["Last scan", s.last_scan
        // Scans before 0.20.0 didn't keep a summary.
        ? `${fmt(s.last_scan)} - full details (sources checked, lines read, what was found) appear after the next scan; use Scan now to see them straight away.`
        : "No scan yet - use Scan now, or wait for the daily scan."]);
    } else {
      rows.push(["Scanned", fmt(sum.scanned_at)]);
      rows.push(["Window checked (Core log)", `${sum.since ? fmt(sum.since) : "beginning of the retained log"} → ${fmt(sum.scanned_at)}`]);
      rows.push(["Home Assistant Core log", `${sum.log_path} (${lines(sum.lines_scanned)})`]);
      if (sum.previous_log_lines) {
        rows.push(["Previous Core log (before the last restart)", `${sum.log_path}.1 (${lines(sum.previous_log_lines)} since the last scan)`]);
      }
      if (sum.sources && sum.sources.length) {
        rows.push([`Other sources checked (${sum.sources.length})`,
          sum.sources.map((src) => `${src.name}: ${src.ok ? lines(src.lines_read) : `unavailable (${src.note || "no response"})`}`)]);
      } else {
        rows.push(["Other sources checked", "none (not a Home Assistant OS/Supervised install, or the check is off)"]);
      }
      const d = sum.anomalies;
      rows.push(["Matching log lines", `${sum.matching_lines} across ${d} distinct anomal${d === 1 ? "y" : "ies"}`]);
      rows.push(["Anomalies found", `${sum.new} new, ${sum.recurring} still occurring`]);
      rows.push(["Matched to the built-in knowledge base", String(sum.known_issue_matches)]);
      if (sum.restart_messages !== undefined) {
        rows.push(["Startup & shutdown messages (see that view)", `${sum.restart_messages} (${sum.new_restart_messages} new)`]);
      }
      if (sum.backup_problems !== undefined) {
        // Scans before the Backups view didn't count these.
        rows.push(["Backups (see the Backups view)",
          `${sum.backup_problems} problem${sum.backup_problems === 1 ? "" : "s"} (${sum.new_backup_problems} new), ` +
          `${sum.backup_successes} success${sum.backup_successes === 1 ? "" : "es"} logged`]);
      }
      rows.push(["Review file", sum.report_file || "-"]);
    }
    rows.push(["Reviews folder", s.reviews_dir]);
    rows.push(["Automation failure log", s.failure_log]);
    el.replaceChildren(...rows.map(([k, v]) => {
      const div = document.createElement("div");
      const key = document.createElement("span");
      key.className = "k";
      key.textContent = `${k}: `;
      div.appendChild(key);
      if (Array.isArray(v)) {
        const ul = document.createElement("ul");
        for (const item of v) {
          const li = document.createElement("li");
          li.textContent = item;
          ul.appendChild(li);
        }
        div.appendChild(ul);
      } else {
        div.append(v);
      }
      return div;
    }));
  }

  _refreshDirty() {
    const changes = this._changes();
    for (const row of this.shadowRoot.querySelectorAll(".field[data-field]")) {
      const key = row.dataset.field;
      const changed = key in changes || (key === "openai_api_key" && this._apiKey.clear);
      row.classList.toggle("changed", changed);
    }
    const dirty = this._dirty();
    const save = this.shadowRoot.querySelector('[data-sact="save"]');
    const discard = this.shadowRoot.querySelector('[data-sact="discard"]');
    if (save) save.disabled = !dirty || this._busy;
    if (discard) discard.disabled = !dirty || this._busy;
    if (!this._busy) {
      this._message(dirty ? "Unsaved changes. Saving restarts WP Log Doctor for a moment." : "");
    }
  }

  _message(text, kind = "", which = "msg") {
    const el = this.shadowRoot.querySelector(`[data-el="${which}"]`);
    if (!el) return;
    el.textContent = text;
    el.className = `msg ${kind}`;
  }

  // -- events ---------------------------------------------------------

  _onInput(ev) {
    const t = ev.target;
    if (t.dataset.key) {
      if (t.dataset.key === "openai_api_key") this._apiKey.value = t.value;
      else this._values[t.dataset.key] = t.type === "checkbox" ? t.checked : t.value;
      this._refreshDirty();
    } else if (t.dataset.el === "clear-key") {
      this._apiKey.clear = t.checked;
      this._refreshDirty();
    } else if (t.dataset.toggle === "auto_investigate" && ev.type === "change") {
      this._setAutoInvestigate(t);
    }
  }

  async _setAutoInvestigate(input) {
    input.disabled = true;
    try {
      await this._hass.callWS({ type: SWS.AUTO_INVESTIGATE, enabled: input.checked });
      this._message(`Auto-investigate turned ${input.checked ? "on" : "off"}.`, "ok", "action-msg");
    } catch (err) {
      input.checked = !input.checked;
      this._message(`Couldn't change Auto-investigate: ${err.message || err.code || err}`, "error", "action-msg");
    } finally {
      input.disabled = false;
    }
  }

  async _onClick(ev) {
    const btn = ev.composedPath().find((el) => el.dataset && el.dataset.sact);
    if (!btn || btn.disabled) return;
    switch (btn.dataset.sact) {
      case "discard":
        this._values = { ...this._data.options };
        this._apiKey = { value: "", clear: false };
        this._build();
        break;
      case "save":
        await this._save();
        break;
      case "scan":
        btn.disabled = true;
        this._message("Scanning…", "", "action-msg");
        try {
          const res = await this._hass.callWS({ type: SWS.SCAN_NOW });
          this._data.status = { ...this._data.status, ...res.status };
          this._renderStatus();
          const sum = res.status.summary;
          this._message(
            sum ? `Scan finished: ${sum.new} new, ${sum.recurring} still occurring. See the Log review.` : "Scan finished.",
            "ok", "action-msg",
          );
        } catch (err) {
          this._message(`Scan failed: ${err.message || err.code || err}`, "error", "action-msg");
        } finally {
          btn.disabled = false;
        }
        break;
      case "ask-clear-history":
        btn.textContent = "Click again to confirm";
        btn.dataset.sact = "clear-history";
        this._message(
          "Forgets which anomalies were already reported, so the next scan reports everything as new. The Log review list is not affected.",
          "", "action-msg",
        );
        break;
      case "clear-history":
        btn.disabled = true;
        try {
          await this._hass.callWS({ type: SWS.CLEAR_HISTORY });
          this._message("History cleared.", "ok", "action-msg");
        } catch (err) {
          this._message(`Couldn't clear history: ${err.message || err.code || err}`, "error", "action-msg");
        } finally {
          btn.textContent = "Clear history";
          btn.dataset.sact = "ask-clear-history";
          btn.disabled = false;
        }
        break;
      default:
        break;
    }
  }

  async _save() {
    const options = this._changes();
    this._busy = true;
    this._refreshDirty();
    this._message("Saving…");
    try {
      const res = await this._hass.callWS({
        type: SWS.UPDATE,
        options,
        clear_openai_api_key: this._apiKey.clear,
      });
      this._busy = false;
      if (res.changed) {
        this._message("Saved. WP Log Doctor is restarting…", "ok");
        // The reload takes a moment; read the settings back afterwards.
        setTimeout(() => this._load("Saved."), 2500);
      } else {
        await this._load("Nothing to change.");
      }
    } catch (err) {
      this._busy = false;
      this._refreshDirty();
      this._message(`Not saved: ${err.message || err.code || err}`, "error");
    }
  }
}

if (!customElements.get("log-doctor-settings")) {
  customElements.define("log-doctor-settings", LogDoctorSettings);
}
