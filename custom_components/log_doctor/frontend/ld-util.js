// WP Log Doctor panel - shared constants and helpers (see
// log-doctor-panel.js for how the modules fit together).

export const WS = {
  SUBSCRIBE: "log_doctor/review/subscribe",
  RESOLVE: "log_doctor/review/resolve",
  RESTORE: "log_doctor/review/restore",
  CLEAR_ARCHIVED: "log_doctor/review/clear_archived",
  DELETE: "log_doctor/review/delete",
  IGNORE: "log_doctor/review/ignore",
  UNIGNORE: "log_doctor/review/unignore",
  UNMONITOR: "log_doctor/review/unmonitor",
  MONITOR: "log_doctor/review/monitor",
  SET_CATEGORY: "log_doctor/review/set_category",
  INVESTIGATION_PROMPT: "log_doctor/review/investigation_prompt",
};

// The Settings and Insights pages' commands (settings_api.py).
export const SWS = {
  GET: "log_doctor/settings/get",
  UPDATE: "log_doctor/settings/update",
  AUTO_INVESTIGATE: "log_doctor/settings/set_auto_investigate",
  SCAN_NOW: "log_doctor/settings/scan_now",
  CLEAR_HISTORY: "log_doctor/settings/clear_history",
  STATUS: "log_doctor/settings/status",
  INSIGHTS: "log_doctor/insights/get",
  SEND_DIGEST: "log_doctor/insights/send_digest",
};

// Rows rendered at once; "Show more" adds this many again.
export const PAGE_SIZE = 500;

export const LEVEL_RANK = { WARNING: 1, ERROR: 2, CRITICAL: 3 };

export const BACKUP_SOURCES = { ha: "Home Assistant", gdrive: "GDrive Backup" };
// Heading for Devices & integrations rows that don't belong to an integration
export const OTHER_GROUP = "Other";
// Where the collapsed groups of each view are remembered, per browser.
export const COLLAPSED_KEY = "log_doctor.collapsed_groups";
// Where each view's search, filters, tab and sort are remembered.
export const VIEW_STATE_KEY = "log_doctor.view_state";

// Where an integration heading's first link goes: Home Assistant's own
// pages for its own parts (automations, scripts, scenes, helpers, people,
// zones), the integration's page for everything else.
export const INTEGRATION_PAGES = {
  automation: ["Automations ↗", "/config/automation/dashboard"],
  script: ["Scripts ↗", "/config/script/dashboard"],
  scene: ["Scenes ↗", "/config/scene/dashboard"],
  person: ["People ↗", "/config/person"],
  zone: ["Zones ↗", "/config/zone"],
};
export const HELPER_DOMAINS = [
  "input_boolean", "input_button", "input_datetime", "input_number", "input_select",
  "input_text", "counter", "timer", "schedule",
];
export function integrationPage(domain) {
  if (INTEGRATION_PAGES[domain]) return INTEGRATION_PAGES[domain];
  if (HELPER_DOMAINS.includes(domain)) return ["Helpers ↗", "/config/helpers"];
  return ["Integration ↗", `/config/integrations/integration/${encodeURIComponent(domain)}`];
}

// How long a restart took: from the shutdown (or the start, when no
// shutdown was recorded) until Home Assistant had finished starting.
export function rebootSeconds(r) {
  const from = r.shutdown_start || r.starting;
  return from && r.started ? (new Date(r.started) - new Date(from)) / 1000 : -1;
}

// How long Home Assistant took to start: from starting until started.
export function startupSeconds(r) {
  return r.starting && r.started ? (new Date(r.started) - new Date(r.starting)) / 1000 : -1;
}

// "Startup", "Shutdown" or "Startup & shutdown".
export function phaseLabel(r) {
  const phases = r.phases || [];
  const names = [];
  if (phases.includes("startup")) names.push("Startup");
  if (phases.includes("shutdown")) names.push("Shutdown");
  return names.join(" & ");
}

// Successes sort below every problem level.
export function backupRank(r) {
  return r.kind === "success" ? 0 : LEVEL_RANK[r.level] || 0;
}

// Devices & integrations kinds that are a device (or an entity with no
// device), which can be left unmonitored.
export const DEVICE_KINDS = ["offline", "unavailable", "flapping"];

// "3m 05s" between two ISO times, or "" if either is missing.
export function duration(fromIso, toIso) {
  if (!fromIso || !toIso) return "";
  const seconds = Math.max(0, Math.round((new Date(toIso) - new Date(fromIso)) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const sec = String(seconds % 60).padStart(2, "0");
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m ${sec}s` : `${seconds}s`;
}
// What started an automation run: which of its triggers (its name, see
// trigger_names.py), Home Assistant's description of it, or Manual.
export function runTrigger(r) {
  return r.manual ? "Manual" : r.trigger_name || r.trigger || "";
}


// Which tab an entry is on.
export function tabOf(r) {
  if (r.unmonitored) return "unmonitored";
  if (r.ignored) return "ignored";
  return r.resolved ? "archived" : "open";
}

// localStorage, which can be unavailable (private windows, blocked
// storage): reads fall back, writes are skipped.
export function loadJSON(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    return value ?? fallback;
  } catch (_err) {
    return fallback;
  }
}

export function saveJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (_err) {
    // Not remembered; it still works for this visit.
  }
}

// Offers text as a file to save.
export function downloadFile(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// CSV with a header row; every cell quoted.
export function toCSV(header, rows) {
  const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return [header, ...rows].map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

// A Markdown table; "|" and line breaks in cells are escaped.
export function toMarkdown(title, header, rows) {
  const cell = (v) => String(v ?? "").replace(/\|/g, "\\|").replace(/\s*\n\s*/g, " ");
  const lines = [`# ${title}`, "", `| ${header.map(cell).join(" | ")} |`, `|${header.map(() => "---").join("|")}|`];
  for (const row of rows) lines.push(`| ${row.map(cell).join(" | ")} |`);
  return lines.join("\n") + "\n";
}

// "1,234" with the browser's grouping.
export function num(n) {
  return Number(n || 0).toLocaleString();
}
