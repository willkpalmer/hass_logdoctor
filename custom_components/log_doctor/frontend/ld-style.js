// WP Log Doctor panel - the main page's styles and markup (see
// log-doctor-panel.js for how the modules fit together).

export const STYLE = `
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
.header .version { font-size: 13px; opacity: 0.8; margin-left: 4px; }
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
/* Open entries, on the view buttons: shown when there are any, red when
   any of them is an error (see each view's alert). */
.view .count, .section .count {
  display: inline-block; min-width: 20px; margin-left: 4px; padding: 0 6px; border-radius: 10px;
  font-size: 12px; font-weight: 600; line-height: 18px; text-align: center;
  background: rgba(127, 127, 127, 0.18); color: inherit;
}
.view .count:empty, .section .count:empty { display: none; }
.view .count.alert, .section .count.alert { background: var(--error-color, #db4437); color: #fff; }
.view.active .count:not(.alert) { background: rgba(255, 255, 255, 0.3); }
.header .scan-status {
  font-size: 13px; color: inherit; opacity: 0.9; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 55%; text-decoration: none; cursor: pointer;
}
.header .scan-status:hover { text-decoration: underline; }
.header .scan-status .warn { font-weight: 600; }
.view.scan { border-color: var(--primary-color, #03a9f4); color: var(--primary-color, #03a9f4); }
.view.scan:disabled { opacity: 0.6; cursor: default; }
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
/* Sections of one page (Automations: Failures | Runs). */
.sections { display: flex; gap: 8px; padding: 12px 16px 0; flex: none; }
.sections[hidden] { display: none; }
.section {
  font: inherit; font-weight: 500; padding: 6px 14px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--divider-color, #e0e0e0); background: transparent; color: var(--primary-text-color, #212121);
}
.section.active { border-color: var(--primary-color, #03a9f4); color: var(--primary-color, #03a9f4); background: rgba(3, 169, 244, 0.08); }
.tab {
  flex: 0 0 auto; padding: 12px 20px; background: none; border: 0;
  border-bottom: 2px solid transparent; color: var(--secondary-text-color, #727272);
  font: inherit; font-weight: 500; cursor: pointer;
}
.tab.active { color: var(--primary-color, #03a9f4); border-bottom-color: var(--primary-color, #03a9f4); }
.tab:focus-visible, .view:focus-visible, .section:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: -2px; }
/* What the current tab holds. */
.hint { padding: 8px 16px 0; color: var(--secondary-text-color, #727272); font-size: 12px; flex: none; }
.hint:empty { display: none; }
/* Restart history's "show this restart's messages", on Startup & shutdown. */
.run-filter {
  font: inherit; font-size: 13px; padding: 6px 10px; border-radius: 16px; cursor: pointer;
  border: 1px solid var(--primary-color, #03a9f4); background: rgba(3, 169, 244, 0.08); color: var(--primary-color, #03a9f4);
}
.run-filter[hidden] { display: none; }
/* Export: a small menu. */
.export { position: relative; }
.export summary { list-style: none; }
.export summary::-webkit-details-marker { display: none; }
.export .menu {
  position: absolute; right: 0; top: calc(100% + 4px); z-index: 3; display: grid; min-width: 220px;
  background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #e0e0e0);
  border-radius: 8px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15); overflow: hidden;
}
.export .menu button {
  font: inherit; text-align: left; padding: 10px 14px; border: 0; background: none; cursor: pointer; color: var(--primary-text-color, #212121);
}
.export .menu button:hover, .export .menu button:focus-visible { background: var(--secondary-background-color, #f5f5f5); }
.export .menu .sub { padding: 6px 14px 8px; }
/* Undo, after an action. */
.snackbar {
  position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 5;
  display: none; align-items: center; gap: 16px; max-width: calc(100vw - 32px);
  padding: 10px 12px 10px 16px; border-radius: 8px;
  background: var(--primary-text-color, #323232); color: var(--primary-background-color, #fff);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}
.snackbar.open { display: flex; }
.snackbar button {
  font: inherit; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; cursor: pointer;
  border: 0; background: none; color: var(--primary-color, #03a9f4); padding: 6px 8px;
}
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 12px 16px; }
.toolbar input[type=search], .toolbar select {
  font: inherit; padding: 8px 10px; border-radius: 6px;
  border: 1px solid var(--divider-color, #ccc);
  background: var(--secondary-background-color, #f5f5f5); color: inherit;
}
.toolbar input[type=search] { flex: 1 1 220px; min-width: 160px; }
.spacer { flex: 1 1 auto; }
.action {
  font: inherit; font-weight: 500; padding: 8px 14px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--primary-color, #03a9f4); background: var(--primary-color, #03a9f4);
  color: var(--text-primary-color, #fff);
}
.action.secondary { background: transparent; color: var(--primary-color, #03a9f4); }
.action.danger { border-color: var(--error-color, #db4437); background: var(--error-color, #db4437); }
.action.danger.secondary { background: transparent; color: var(--error-color, #db4437); }
.action:disabled { opacity: 0.4; cursor: default; }
.export summary.action { display: inline-block; user-select: none; }
.export[open] summary.action { background: rgba(3, 169, 244, 0.08); }
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
tbody tr.row:focus, tbody tr.group:focus { outline: none; }
tbody tr.row:focus-visible, tbody tr.group:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: -2px; }
tbody tr.group td {
  background: var(--secondary-background-color, #f5f5f5); font-weight: 500; padding: 6px 12px;
}
tbody tr.group { cursor: pointer; user-select: none; }
tbody tr.group .caret { display: inline-block; width: 1.2em; color: var(--secondary-text-color, #727272); }
tbody tr.group .group-link {
  display: inline-block; line-height: 1.5;
  margin-left: 12px; font-size: 12px; font-weight: 500; white-space: nowrap;
  padding: 1px 8px; border: 1px solid var(--primary-color, #03a9f4); border-radius: 10px;
}
tbody tr.group .group-link:hover { text-decoration: none; background: rgba(3, 169, 244, 0.1); }
/* Unavailable entities: the theme's accent colour; Not provided: the same
   red as the Offline label. */
tbody tr.group .group-link.unavailable {
  color: var(--accent-color, #ff9800); border-color: var(--accent-color, #ff9800);
}
tbody tr.group .group-link.unavailable:hover { background: rgba(255, 152, 0, 0.12); }
tbody tr.group .group-link.not-provided {
  color: var(--error-color, #db4437); border-color: var(--error-color, #db4437);
}
tbody tr.group .group-link.not-provided:hover { background: rgba(219, 68, 55, 0.12); }
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
.chip.missed, .chip.warning, .chip.stopped, .chip.slow { background: rgba(255, 152, 0, 0.18); color: var(--warning-color, #e68a00); }
.chip.flapping { background: rgba(255, 152, 0, 0.18); color: var(--warning-color, #e68a00); }
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
td.num a { font-variant-numeric: tabular-nums; }
.errors { color: var(--error-color, #db4437); }
log-doctor-insights { flex: 1 1 auto; min-height: 0; overflow: auto; }

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
  tbody tr.group { display: flex; align-items: center; }
  tbody tr.group td { display: block; }
  tbody tr.group td.check { width: auto; padding: 6px 0 6px 12px; }
  tbody tr.group td:not(.check) { flex: 1 1 auto; min-width: 0; line-height: 2; }
  tbody tr.group .group-link { margin-left: 0; margin-right: 6px; }
  tbody tr.group .group-count { margin-right: 8px; }
  /* The tabs scroll sideways rather than run off the card. */
  .tabs { overflow-x: auto; scrollbar-width: none; }
  .tab { white-space: nowrap; padding: 12px 14px; }
  tr.details { display: block; padding: 0 12px 10px; }
  tr.details td { display: block; padding: 0; }
  .detail-box { margin-left: 40px; }
  .label { display: inline; }
  .header .scan-status { max-width: 45%; font-size: 12px; }
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

export const TEMPLATE = `
<div class="header">
  <button class="menu-btn" title="Menu" aria-label="Menu" data-action="menu">&#9776;</button>
  <h1>Log Doctor <span class="version" data-el="version"></span></h1>
  <a class="scan-status" data-el="scan-status" data-view="settings" href="#settings" title="The last scan - open Settings for the details"></a>
</div>
<div class="content">
  <nav class="views" aria-label="Pages">
    <button class="view" data-view="logs">Log review<span class="count" data-count="logs"></span></button>
    <button class="view" data-view="restarts">Startup &amp; shutdown<span class="count" data-count="restarts"></span></button>
    <button class="view" data-view="failures" data-page="failures runs">Automations<span class="count" data-count="failures"></span></button>
    <button class="view" data-view="health">Devices &amp; integrations<span class="count" data-count="health"></span></button>
    <button class="view" data-view="backups">Backups<span class="count" data-count="backups"></span></button>
    <button class="view" data-view="reboots">Restart history</button>
    <button class="view" data-view="insights">Insights</button>
    <button class="view" data-view="settings">Settings</button>
    <button class="view scan" data-action="scan-now" title="Scan the logs now, as the daily scan does; the lists update as soon as it's done">Scan now</button>
  </nav>
  <log-doctor-settings data-el="settings" hidden></log-doctor-settings>
  <log-doctor-insights data-el="insights" hidden></log-doctor-insights>
  <div class="card" data-el="list-card">
    <div class="sections" data-el="sections" hidden>
      <button class="section" data-view="failures">Failures<span class="count" data-section-count="failures"></span></button>
      <button class="section" data-view="runs">Runs</button>
    </div>
    <div class="tabs" role="tablist">
      <button class="tab" role="tab" data-tab="open">Open</button>
      <button class="tab" role="tab" data-tab="archived" data-archivable>Archived</button>
      <button class="tab" role="tab" data-tab="ignored" data-ignorable>Ignored</button>
      <button class="tab" role="tab" data-tab="unmonitored" data-unmonitorable>Not monitored</button>
    </div>
    <div class="hint" data-el="hint"></div>
    <div class="toolbar">
      <input type="search" data-el="filter" aria-label="Filter" title="Filter (press / to jump here)">
      <select data-el="kind" title="Show" aria-label="Show"></select>
      <select data-el="automation" data-only-view="runs" title="Only this automation's runs" aria-label="Automation"></select>
      <button class="run-filter" data-action="clear-run" data-el="run-filter" hidden title="Show every restart's messages again"></button>
      <select data-el="hours" data-only-view="runs" data-show="open" title="Show runs from" aria-label="Show runs from">
        <option value="0">All recorded runs</option>
        <option value="1">Last hour</option>
        <option value="6">Last 6 hours</option>
        <option value="12">Last 12 hours</option>
        <option value="24">Last 24 hours</option>
      </select>
      <span class="spacer"></span>
      <button class="action secondary" data-action="copy-prompt" data-only-view="logs restarts" disabled
        title="Copy the prompt the investigation stage would send for the selected entries, to paste into any AI chat">Copy investigation prompt</button>
      <button class="action secondary" data-action="to-restarts" data-only-view="logs" disabled
        title="These only happen when Home Assistant starts or stops: move them to Startup &amp; shutdown">Move to Startup &amp; shutdown</button>
      <button class="action secondary" data-action="to-operational" data-only-view="restarts" disabled
        title="Move these to the Log review">Move to Log review</button>
      <button class="action secondary" data-action="toggle-groups" data-only-view="health runs"
        title="Collapse or expand every group">Collapse all</button>
      <details class="export" data-el="export">
        <summary class="action secondary" role="button" title="Save the entries shown (or just the selected ones) as a file">Export</summary>
        <div class="menu">
          <div class="sub" data-el="export-what"></div>
          <button data-action="export-csv">CSV (spreadsheet)</button>
          <button data-action="export-md">Markdown (GitHub, forums)</button>
        </div>
      </details>
      <button class="action secondary" data-action="ignore" data-show="open archived" data-ignorable disabled
        title="Harmless or can't be fixed: move to Ignored, where it's still tracked but never comes back to Open by itself">Ignore</button>
      <button class="action secondary" data-action="unignore" data-show="ignored" disabled
        title="Move these back to Open">Stop ignoring</button>
      <button class="action secondary" data-action="unmonitor" data-show="open archived ignored" data-unmonitorable disabled
        title="Stop reporting these devices altogether, whatever becomes unavailable or isn't provided any more; they're listed on the Not monitored tab">Stop monitoring</button>
      <button class="action secondary" data-action="monitor" data-show="unmonitored" data-unmonitorable disabled
        title="Report these devices again; they're checked straight away">Monitor again</button>
      <button class="action" data-action="resolve" data-show="open" data-archivable disabled
        title="Dealt with: move to Archived. If it happens again it comes back to Open, marked Recurred">Archive</button>
      <button class="action secondary" data-action="restore" data-show="archived" data-archivable disabled
        title="Move these back to Open">Restore</button>
      <button class="action danger secondary" data-action="ask-delete" data-show="archived" data-archivable disabled
        title="Delete the selected archived entries for good">Delete</button>
      <button class="action danger secondary" data-action="ask-clear" data-show="archived" data-archivable disabled
        title="Delete every archived entry here for good">Delete all archived</button>
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
<div class="snackbar" data-el="snackbar" role="status" aria-live="polite">
  <span data-el="snack-text"></span>
  <button data-action="undo">Undo</button>
</div>
`;
