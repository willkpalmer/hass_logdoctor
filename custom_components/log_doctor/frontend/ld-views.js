// WP Log Doctor panel - the list views: what each one lists and how (see
// log-doctor-panel.js for how the modules fit together).

const V = new URL(import.meta.url).search;
const {
  BACKUP_SOURCES, DEVICE_KINDS, LEVEL_RANK, OTHER_GROUP, backupRank, duration,
  phaseLabel, rebootSeconds, runTrigger, startupSeconds,
} = await import(`./ld-util.js${V}`);

// What each tab holds, under the tabs; a view's own hints replace these.
export const TAB_HINTS = {
  open: "Needs a look. Archive what's dealt with, or Ignore what's harmless and can't be fixed.",
  archived: "Dealt with. If it's logged again it goes back to Open, marked Recurred.",
  ignored: "Still tracked, but never brought back to Open by itself. Stop ignoring to see it there again.",
  unmonitored: "Not checked at all until you monitor them again.",
};

export const VIEWS = {
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
      archived: "Nothing archived. Entries you archive appear here.",
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
    alert: (r) => r.level === "ERROR" || r.level === "CRITICAL",
    exportHeader: ["Level", "Last logged", "Last found", "Logger", "Message", "Count", "Scans", "First seen", "Known issue"],
    exportRow: (r, p) => [r.level, p._dateTime(r.last_logged), p._dateTime(r.last_scan || r.last_seen), r.logger, r.message, r.count, r.scans, p._dateTime(r.first_seen), r.known_issue?.title || ""],
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
      archived: "Nothing archived. Entries you archive appear here.",
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
    alert: (r) => r.level === "ERROR" || r.level === "CRITICAL",
    // Restart history's Messages link shows just one restart's (see runFilter).
    runFilter: true,
    hints: {
      open: "Messages logged only while Home Assistant was starting or shutting down. One also logged while running moves to the Log review.",
    },
    exportHeader: ["Level", "Last logged", "Last found", "Phase", "Logger", "Message", "Restarts", "Count"],
    exportRow: (r, p) => [r.level, p._dateTime(r.last_logged), p._dateTime(r.last_scan || r.last_seen), phaseLabel(r), r.logger, r.message, r.restarts || 0, r.count],
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
      { key: "startup", label: "Startup took", num: true, firstDir: -1 },
      { key: "took", label: "Down for", num: true, firstDir: -1 },
      { key: "messages", label: "Messages", num: true, firstDir: -1 },
    ],
    compare: {
      shutdown: (a, b) => (a.shutdown_start || "").localeCompare(b.shutdown_start || ""),
      starting: (a, b) => (a.starting || "").localeCompare(b.starting || ""),
      started: (a, b) => (a.started || "").localeCompare(b.started || ""),
      window: (a, b) => (a.window_end || "").localeCompare(b.window_end || ""),
      startup: (a, b) => startupSeconds(a) - startupSeconds(b),
      took: (a, b) => rebootSeconds(a) - rebootSeconds(b),
      messages: (a, b) => (a.messages || 0) - (b.messages || 0) || (a.errors || 0) - (b.errors || 0),
    },
    tiebreak: (a, b) => (a.starting || "").localeCompare(b.starting || ""),
    expandable: false,
    where: "the Restart history",
    // Every restart is open until archived automatically: no count on the button.
    navCount: false,
    hints: {
      open: "Each restart's shutdown and startup windows, how long it took and what it logged. Older ones are archived automatically (see Settings).",
      archived: "Archived by you, or automatically beyond the number kept open. Archiving doesn't change how messages are classified.",
    },
    exportHeader: ["Shutdown began", "Started", "Finished starting", "Startup messages until", "Startup took", "Down for", "Messages", "Errors", "Clean shutdown"],
    exportRow: (r, p) => [p._dateTime(r.shutdown_start), p._dateTime(r.starting), p._dateTime(r.started), p._dateTime(r.window_end), duration(r.starting, r.started), duration(r.shutdown_start || r.starting, r.started), r.messages || 0, r.errors || 0, r.shutdown_start ? "yes" : "no"],
  },
  failures: {
    list: "failures",
    noun: ["entry", "entries"],
    filterPlaceholder: "Filter by name or reason",
    kinds: [["", "Everything"], ["failed", "Failed runs"], ["missed", "Missed runs"], ["stopped", "Stopped running"], ["script", "Scripts only"]],
    kindOf: (r) => {
      const prefix = (r.reason.match(/^(Failed|Missed|Stopped):/) || [])[1];
      return prefix ? prefix.toLowerCase() : "";
    },
    matches: (r, kind) => (kind === "script" ? r.entity_id.startsWith("script.") : VIEWS.failures.kindOf(r) === kind),
    search: (r) => `${r.name} ${r.entity_id} ${r.reason}`,
    defaultSort: { key: "date", dir: -1 },
    empty: {
      open: "No open automation failures. 🎉",
      archived: "Nothing archived. Failures you archive appear here.",
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
    alert: () => true,
    hints: {
      open: "Failed runs, scheduled runs missed while Home Assistant was offline, and automations that stopped running. Archive them once dealt with.",
    },
    exportHeader: ["Date", "Time", "Automation / script", "Entity", "Reason"],
    exportRow: (r, p) => [p._date(r.when), p._time(r.when), r.name, r.entity_id, r.reason],
  },
  runs: {
    list: "automation_runs",
    noun: ["run", "runs"],
    filterPlaceholder: "Filter by automation or trigger",
    kinds: [["", "Everything"], ["triggered", "Triggered"], ["manual", "Manual"]],
    kindOf: (r) => (r.manual ? "manual" : "triggered"),
    search: (r) => `${r.name} ${r.entity_id} ${r.manual ? "Manual" : `${r.trigger_name || ""} ${r.trigger || ""}`}`,
    defaultSort: { key: "when", dir: -1 },
    // Grouped by day (in Home Assistant's time zone), newest first, each
    // collapsible; the day is worked out once per update (see _onMessage).
    decorate: (r, panel) => { r._day = panel._date(r.when); },
    groupBy: (r) => r._day || OTHER_GROUP,
    groupSort: (a, b) => b.localeCompare(a),
    groupLabel: (day, panel) => panel._dayLabel(day),
    groupNoun: "day",
    // The Last 1 / 6 / 12 / 24 hours drop-down (runs, not the Not monitored tab).
    timeWindow: true,
    empty: {
      open: "No automation runs recorded yet. Every automation run appears here as it happens.",
      unmonitored: "Every automation is monitored. Automations you stop monitoring appear here; their runs aren't recorded until you monitor them again.",
    },
    columns: [
      { key: "when", label: "Ran", firstDir: -1 },
      { key: "name", label: "Automation" },
      { key: "trigger", label: "Trigger" },
    ],
    compare: {
      when: (a, b) => (a.when || "").localeCompare(b.when || ""),
      name: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
      trigger: (a, b) => runTrigger(a).localeCompare(runTrigger(b), undefined, { sensitivity: "base" }),
    },
    tiebreak: (a, b) => (a.when || "").localeCompare(b.when || ""),
    expandable: false,
    // A log, not a to-do list: no Archived tab, nothing to resolve.
    archivable: false,
    // Not monitoring an automation, like a device: its runs aren't recorded.
    unmonitorable: true,
    unmonitorKinds: ["run"],
    unmonitorTitles: [
      "Remove these automations' runs and stop recording them; they're listed on the Not monitored tab",
      "Record these automations' runs again",
    ],
    tabNames: { open: "Runs" },
    // The automation drop-down.
    automationFilter: true,
    navCount: false,
    where: "the automation runs",
    hints: {
      open: "Every automation run as it happens, and what triggered it. Automations stopped by their conditions aren't runs.",
      unmonitored: "Automations whose runs aren't recorded. Their runs already recorded were removed.",
    },
    exportHeader: ["Ran", "Automation", "Entity", "Trigger", "Home Assistant's description"],
    exportRow: (r, p) => [p._dateTime(r.when), r.name, r.entity_id, runTrigger(r), r.manual ? "" : r.trigger || ""],
  },
  health: {
    list: "health",
    noun: ["entry", "entries"],
    filterPlaceholder: "Filter by name, area or problem",
    kinds: [
      ["", "Everything"], ["offline", "Offline devices"], ["unavailable", "Unavailable entities"],
      ["not_provided", "Not provided"], ["flapping", "Flapping devices"], ["integration", "Integrations"], ["repair", "Repairs"],
    ],
    kindOf: (r) => r.kind,
    // Not provided: entries with entities their integration no longer
    // provides (an offline or unavailable one's "N no longer provided").
    matches: (r, kind) => (kind === "not_provided"
      ? (r.detail || "").includes("no longer provided")
      : r.kind === kind),
    search: (r) => `${r.name} ${r.sub} ${r.detail} ${r.integration_name || ""} ${(r.entities || []).join(" ")}`,
    // Rows are shown under a heading for their integration
    groupBy: (r) => r.integration_name || r.integration || OTHER_GROUP,
    // Home Assistant's own parts (automations, scripts, helpers, ...) first.
    groupRank: (r) => (r.integration_core ? 0 : 1),
    // Links on each integration's heading to its page (or Home Assistant's
    // page for its own parts) and its unavailable entities on the entities
    // page (see _groupLinks).
    groupLinks: true,
    defaultSort: { key: "since", dir: -1 },
    empty: {
      open: "No device or integration problems. 🎉",
      archived: "Nothing archived. Problems that clear up by themselves, and ones you archive, appear here.",
      ignored: "Nothing ignored. Problems you ignore - entities that are unavailable on purpose - appear here, still checked.",
      unmonitored: "Every device is monitored. Devices you stop monitoring appear here, and nothing about them is reported until you monitor them again.",
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
    ignorable: true,
    unmonitorable: true,
    unmonitorKinds: DEVICE_KINDS,
    // Its Ignored tab shows whether each problem is still there.
    ignoredColumns: [
      { key: "ignored", label: "Ignored", firstDir: -1 },
      { key: "active", label: "Now" },
    ],
    where: "Devices & integrations",
    alert: (r) => r.kind === "offline" || r.kind === "integration",
    hints: {
      open: "Problems found by the check every 5 minutes. They're archived by themselves when they clear up, and come back marked Recurred if they return.",
      archived: "Cleared up by themselves, or archived by you while still there (they stay archived as long as they last).",
      ignored: "Still checked, and back on Open if another of the device's entities becomes unavailable.",
    },
    exportHeader: ["Type", "Integration", "Name", "Details", "Problem", "Since", "Entities"],
    exportRow: (r, p) => [HEALTH_KINDS[r.kind]?.label || r.kind, r.integration_name || r.integration || "", r.name, r.sub, r.detail, p._dateTime(r.since), (r.entities || []).join(" ")],
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
      archived: "Nothing archived. Entries you archive appear here.",
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
    alert: (r) => r.kind !== "success",
    exportHeader: ["Status", "Last logged", "Last found", "Source", "Logger", "Message", "Count"],
    exportRow: (r, p) => [r.kind === "success" ? "Success" : r.level, p._dateTime(r.last_logged), p._dateTime(r.last_scan || r.last_seen), BACKUP_SOURCES[r.source] || r.source || "", r.logger, r.message, r.count],
  },
};


export const HEALTH_KINDS = {
  offline: { label: "Offline", order: 0 },
  unavailable: { label: "Unavailable", order: 1 },
  flapping: { label: "Flapping", order: 1.5 },
  integration: { label: "Integration", order: 2 },
  repair: { label: "Repair", order: 3 },
};

export const RESOLVED_COLUMN = { key: "resolved", label: "Archived", firstDir: -1 };

export const IGNORED_COLUMNS = [
  { key: "ignored", label: "Ignored", firstDir: -1 },
  { key: "ignored_count", label: "Since ignored", num: true, firstDir: -1 },
];

