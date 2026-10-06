// WP Log Doctor panel - the Settings page, <log-doctor-settings> (see
// log-doctor-panel.js for how the modules fit together).

const V = new URL(import.meta.url).search;
const { SWS } = await import(`./ld-util.js${V}`);

//
// Everything from the integration's Configure dialog plus its entities
// (the Auto-investigate switch, the Scan now button, the clear_history
// service). Saving goes through log_doctor/settings/update, which
// validates like the Configure dialog and reloads WP Log Doctor.

const WEEKDAY_NAMES = {
  mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday",
};

const SETTINGS_SECTIONS = [
  {
    id: "scan",
    title: "Daily scan",
    description: "When the log is scanned and what counts as a problem.",
    fields: [
      { key: "scan_time", label: "Daily scan time", type: "time" },
      { key: "min_severity", label: "Minimum severity to report", type: "select", options: "severity_levels" },
      { key: "lookback_hours", label: "Lookback window on the first scan", type: "number", min: 1, max: 168, unit: "hours" },
      { key: "log_path", label: "Log file path", type: "text" },
      { key: "include_supervisor_logs", label: "Also check Supervisor, Host and add-on logs", help: "Home Assistant OS / Supervised only.", type: "bool" },
    ],
  },
  {
    id: "restarts",
    title: "Startup & shutdown",
    description: "Which messages count as startup and shutdown messages, and the Restart history.",
    fields: [
      { key: "restart_grace_minutes", label: "Count as startup messages until this long after starting", type: "number", min: 0, max: 60, unit: "minutes", help: "Messages logged from Home Assistant starting until this long after it has finished starting (and while it shuts down) go on Startup & shutdown." },
      { key: "restart_history_open_entries", label: "Restarts kept open on Restart history", type: "number", min: 1, max: 500, help: "Older ones are archived automatically." },
    ],
  },
  {
    id: "retention",
    title: "Keeping history",
    description: "How long reports, list entries, automation runs and the Insights counts are kept.",
    fields: [
      { key: "report_retention_days", label: "Keep reports and list entries for", type: "number", min: 1, max: 365, unit: "days", help: "Log review, Startup & shutdown, automation failures and runs, Backups and the Insights counts. Ignored and not monitored entries are kept regardless." },
    ],
  },
  {
    id: "automations",
    title: "Automations & scripts",
    description: "Watching automation and script runs as they happen.",
    fields: [
      { key: "monitor_automations", label: "Notify me when any automation or script fails", type: "bool" },
      { key: "monitor_missed_schedules", label: "After a restart, report scheduled runs missed while offline", type: "bool" },
      { key: "missed_schedule_min_pattern_minutes", label: "Skip time patterns repeating more often than", type: "number", min: 0, max: 1440, unit: "minutes", help: "0 checks every time pattern." },
      { key: "monitor_stopped_automations", label: "Tell me when an automation that runs regularly stops running", type: "bool", help: "Once it has gone quiet for much longer than it ever has (from its recorded runs; it needs 8 or more). Checked every 30 minutes." },
    ],
  },
  {
    id: "health",
    title: "Devices & integrations",
    description: "The check every 5 minutes for offline devices, unavailable entities, failed integrations and Repairs.",
    fields: [
      { key: "monitor_health", label: "Watch devices, integrations and Repairs", type: "bool", help: "Checked every 5 minutes." },
      { key: "offline_hours", label: "Report devices offline for at least", type: "number", min: 1, max: 168, unit: "hours" },
      { key: "flap_count", label: "Report devices that go unavailable at least", type: "number", min: 0, max: 100, unit: "times", help: "However briefly: a weak Zigbee or Wi-Fi link. 0 turns this off." },
      { key: "flap_hours", label: "… within", type: "number", min: 1, max: 168, unit: "hours" },
    ],
  },
  {
    id: "notifications",
    title: "Notifications & weekly digest",
    description: "Where reports go, and the weekly summary (see Insights for a preview).",
    fields: [
      { key: "automation_failure_notify_device", label: "Also push automation failures, missed and stopped runs to", type: "device" },
      { key: "mobile_notify_service", label: "Mobile notify service for the daily scan summary and weekly digest", type: "text", datalist: "notify_services", help: "e.g. mobile_app_pixel_10. Leave blank for none." },
      { key: "weekly_digest", label: "Send a weekly digest", type: "bool", help: "The week's new problems, noisiest integrations, automations, devices, restarts and backups." },
      { key: "weekly_digest_day", label: "Send it after the daily scan on", type: "select", options: "weekdays", names: WEEKDAY_NAMES },
    ],
  },
  {
    id: "investigation",
    title: "Investigation (OpenAI)",
    description: "Researching each scan's anomalies with an OpenAI model. Optional.",
    fields: [
      { key: "openai_api_key", label: "OpenAI API key", type: "apikey", help: "Enables automatic investigation of each scan's anomalies." },
      { key: "investigation_model", label: "Model", type: "text", help: "The OpenAI model to use, e.g. gpt-6-astra. If OpenAI retires it, choose another here." },
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
h2 { font-size: 16px; font-weight: 500; margin: 0; padding: 14px 16px 2px; }
.description { padding: 0 16px 10px; color: var(--secondary-text-color, #727272); font-size: 13px; }
/* Links to each section, at the top. */
.jump { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.jump a {
  font-size: 13px; padding: 4px 10px; border-radius: 14px; text-decoration: none;
  border: 1px solid var(--divider-color, #e0e0e0); color: var(--primary-text-color, #212121);
  background: var(--card-background-color, #fff);
}
.jump a:hover, .jump a:focus-visible { border-color: var(--primary-color, #03a9f4); color: var(--primary-color, #03a9f4); }
.field {
  display: grid; grid-template-columns: minmax(200px, 1fr) minmax(200px, 1.2fr);
  gap: 4px 16px; align-items: center; padding: 10px 16px;
  border-top: 1px solid var(--divider-color, #e0e0e0);
}
.description + .field { border-top: 0; }
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

export class LogDoctorSettings extends HTMLElement {
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

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    // Opened on this page before Home Assistant was connected.
    if (first && hass && !this.hidden) this.activate();
  }

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

    // Links to each section.
    const jump = document.createElement("nav");
    jump.className = "jump";
    jump.setAttribute("aria-label", "Sections");
    for (const section of [...SETTINGS_SECTIONS, { id: "status", title: "Last scan" }]) {
      const a = document.createElement("a");
      a.href = `#settings-${section.id}`;
      a.dataset.jump = section.id;
      a.textContent = section.title;
      jump.appendChild(a);
    }
    root.appendChild(jump);

    for (const section of SETTINGS_SECTIONS) {
      const card = document.createElement("section");
      card.className = "card";
      card.id = `s-${section.id}`;
      const h = document.createElement("h2");
      h.textContent = section.title;
      card.appendChild(h);
      if (section.description) {
        const p = document.createElement("div");
        p.className = "description";
        p.textContent = section.description;
        card.appendChild(p);
      }
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
    const card = document.createElement("section");
    card.className = "card";
    card.id = "s-status";
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
      for (const opt of d[field.options] || []) input.appendChild(new Option(field.names?.[opt] || opt, opt));
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
    const jump = ev.composedPath().find((el) => el.dataset && el.dataset.jump);
    if (jump) {
      ev.preventDefault();
      this.shadowRoot.getElementById(`s-${jump.dataset.jump}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
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
