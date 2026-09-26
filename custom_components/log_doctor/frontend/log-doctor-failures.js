// WP Log Doctor - "Automation failures" sidebar panel.
//
// A self-contained web component (no build step, no external libraries).
// It subscribes to log_doctor/failures/subscribe and gets the full list
// back on every change, so new failures appear live. Open failures can be
// sorted, filtered, selected and marked resolved, which moves them to the
// Archived tab; archived ones can be restored, or the archive cleared,
// which deletes them from the log for good.

const WS = {
  SUBSCRIBE: "log_doctor/failures/subscribe",
  RESOLVE: "log_doctor/failures/resolve",
  RESTORE: "log_doctor/failures/restore",
  CLEAR_ARCHIVED: "log_doctor/failures/clear_archived",
};

// Rows rendered at once; "Show more" adds this many again. Keeps the page
// responsive even with thousands of failures.
const PAGE_SIZE = 500;

const STYLE = `
:host {
  display: block;
  min-height: 100vh;
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
  position: sticky; top: 0; z-index: 2;
}
.header h1 { font-size: 20px; font-weight: 400; margin: 0; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.menu-btn { display: none; background: none; border: 0; color: inherit; font-size: 22px; cursor: pointer; padding: 4px 8px; }
:host([narrow]) .menu-btn { display: inline-block; }
.content { padding: 16px; max-width: 1400px; margin: 0 auto; }
.card {
  background: var(--card-background-color, #fff);
  border-radius: var(--ha-card-border-radius, 12px);
  border: 1px solid var(--divider-color, #e0e0e0);
  overflow: hidden;
}
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
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 12px; border-top: 1px solid var(--divider-color, #e0e0e0); vertical-align: top; }
th { font-weight: 500; color: var(--secondary-text-color, #727272); white-space: nowrap; user-select: none; }
th.sortable { cursor: pointer; }
th.sortable:hover { color: var(--primary-text-color, #212121); }
th .arrow { display: inline-block; width: 1em; }
td.check, th.check { width: 36px; padding-right: 0; }
td.when { white-space: nowrap; font-variant-numeric: tabular-nums; }
td.reason { min-width: 260px; word-break: break-word; }
tbody tr:hover { background: var(--secondary-background-color, rgba(0,0,0,0.03)); }
tbody tr.selected { background: rgba(3, 169, 244, 0.1); }
input[type=checkbox] { width: 18px; height: 18px; cursor: pointer; accent-color: var(--primary-color, #03a9f4); }
a { color: var(--primary-color, #03a9f4); text-decoration: none; }
a:hover { text-decoration: underline; }
.entity { color: var(--secondary-text-color, #727272); font-size: 12px; }
.chip {
  display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: 0.3px;
  padding: 1px 7px; border-radius: 10px; margin-right: 6px; text-transform: uppercase;
}
.chip.failed { background: rgba(219, 68, 55, 0.15); color: var(--error-color, #db4437); }
.chip.missed { background: rgba(255, 152, 0, 0.18); color: var(--warning-color, #e68a00); }
.empty, .status { padding: 32px 16px; text-align: center; color: var(--secondary-text-color, #727272); }
.more { padding: 12px; text-align: center; }
.footer { padding: 8px 16px 12px; color: var(--secondary-text-color, #727272); font-size: 12px; }
.resolved-label { display: none; }

/* Phones: one card per failure; the column headers become sort buttons. */
@media (max-width: 700px) {
  .content { padding: 8px; }
  .table-wrap { overflow: visible; }
  table, thead, tbody { display: block; }
  thead tr {
    display: flex; flex-wrap: wrap; align-items: center; gap: 4px 14px;
    padding: 6px 12px; border-top: 1px solid var(--divider-color, #e0e0e0);
  }
  thead th { border: 0; padding: 6px 2px; }
  tbody tr {
    display: grid; grid-template-columns: 30px auto 1fr; column-gap: 10px; row-gap: 4px;
    padding: 10px 12px; border-top: 1px solid var(--divider-color, #e0e0e0);
  }
  tbody td { border: 0; padding: 0; min-width: 0; }
  tbody td.check { grid-column: 1; grid-row: 1 / span 4; }
  tbody td:nth-child(2) { grid-column: 2; grid-row: 1; }
  tbody td:nth-child(3) { grid-column: 3; grid-row: 1; }
  tbody td.when { font-size: 12px; color: var(--secondary-text-color, #727272); }
  tbody td:nth-child(4) { grid-column: 2 / 4; }
  tbody td:nth-child(5) { grid-column: 2 / 4; min-width: 0; }
  tbody td:nth-child(6) { grid-column: 2 / 4; }
  .resolved-label { display: inline; }
}
`;

const TEMPLATE = `
<div class="header">
  <button class="menu-btn" title="Menu" data-action="menu">&#9776;</button>
  <h1>Automation failures</h1>
</div>
<div class="content">
  <div class="card">
    <div class="tabs">
      <button class="tab active" data-tab="open">Open</button>
      <button class="tab" data-tab="archived">Archived</button>
    </div>
    <div class="toolbar">
      <input type="search" placeholder="Filter by automation or reason" data-el="filter">
      <select data-el="kind" title="Show">
        <option value="">Failed and missed</option>
        <option value="failed">Failed only</option>
        <option value="missed">Missed only</option>
      </select>
      <span class="spacer"></span>
      <button class="action" data-action="resolve" data-show="open" disabled>Mark resolved</button>
      <button class="action secondary" data-action="restore" data-show="archived" disabled>Restore to open</button>
      <button class="action danger secondary" data-action="ask-clear" data-show="archived" disabled>Clear archive</button>
    </div>
    <div class="confirm" data-el="confirm">
      <span data-el="confirm-text"></span>
      <button class="action secondary" data-action="cancel-clear">Cancel</button>
      <button class="action danger" data-action="clear">Delete permanently</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr data-el="head"></tr></thead>
        <tbody data-el="body"></tbody>
      </table>
    </div>
    <div class="status" data-el="status">Loading…</div>
    <div class="more" data-el="more" hidden><button class="action secondary" data-action="more">Show more</button></div>
    <div class="footer" data-el="footer"></div>
  </div>
</div>
`;

const COLUMNS = {
  open: [
    { key: "date", label: "Date" },
    { key: "time", label: "Time" },
    { key: "name", label: "Automation" },
    { key: "reason", label: "Reason" },
  ],
  archived: [
    { key: "date", label: "Date" },
    { key: "time", label: "Time" },
    { key: "name", label: "Automation" },
    { key: "reason", label: "Reason" },
    { key: "resolved", label: "Resolved" },
  ],
};

class LogDoctorFailuresPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._narrow = false;
    this._failures = [];
    this._tab = "open";
    this._sort = { key: "date", dir: -1 }; // newest first
    this._selected = new Set();
    this._limit = PAGE_SIZE;
    this._unsub = null;
    this._subscribing = false;
    this._loaded = false;
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>${TEMPLATE}`;
    this._el = (name) => this.shadowRoot.querySelector(`[data-el="${name}"]`);
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
    this._el("filter").addEventListener("input", () => { this._limit = PAGE_SIZE; this._render(); });
    this._el("kind").addEventListener("change", () => { this._limit = PAGE_SIZE; this._render(); });
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._formatters();
    if (this.isConnected && !this._unsub) this._subscribe();
  }

  get hass() { return this._hass; }

  set narrow(value) {
    this._narrow = value;
    this.toggleAttribute("narrow", !!value);
  }

  get narrow() { return this._narrow; }

  set panel(_value) {}

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    this._unsubscribe();
  }

  // -- data -----------------------------------------------------------

  async _subscribe() {
    if (this._subscribing || !this._hass) return;
    this._subscribing = true;
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (msg) => this._onMessage(msg),
        { type: WS.SUBSCRIBE },
      );
    } catch (err) {
      this._showStatus(`Couldn't load automation failures: ${err.message || err.code || err}`);
    } finally {
      this._subscribing = false;
    }
  }

  _unsubscribe() {
    if (this._unsub) {
      try { this._unsub(); } catch (_err) { /* connection already gone */ }
      this._unsub = null;
    }
  }

  _onMessage(msg) {
    if (msg.reload) {
      // WP Log Doctor is reloading; pick up the new list shortly.
      this._unsubscribe();
      setTimeout(() => this._subscribe(), 2000);
      return;
    }
    this._failures = msg.failures || [];
    this._loaded = true;
    const ids = new Set(this._failures.map((f) => f.id));
    for (const id of [...this._selected]) if (!ids.has(id)) this._selected.delete(id);
    this._render();
  }

  async _call(type, extra = {}) {
    try {
      return await this._hass.callWS({ type, ...extra });
    } catch (err) {
      alert(`WP Log Doctor: ${err.message || err.code || err}`);
      return null;
    }
  }

  // -- formatting -----------------------------------------------------

  _formatters() {
    // Shown in Home Assistant's time zone, like the Markdown file.
    const timeZone = this._hass?.config?.time_zone || undefined;
    const make = (locale, opts) => {
      try { return new Intl.DateTimeFormat(locale, { ...opts, timeZone }); }
      catch (_err) { return new Intl.DateTimeFormat(locale, opts); }
    };
    this._fmtDate = make("en-CA", { year: "numeric", month: "2-digit", day: "2-digit" });
    this._fmtTime = make("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  }

  _parts(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return { date: "", time: "", ts: 0, tod: "" };
    const time = this._fmtTime.format(d);
    return { date: this._fmtDate.format(d), time, ts: d.getTime(), tod: time };
  }

  _kind(failure) {
    if (failure.reason.startsWith("Missed:")) return "missed";
    if (failure.reason.startsWith("Failed:")) return "failed";
    return "";
  }

  // -- rendering ------------------------------------------------------

  _visible() {
    const archived = this._tab === "archived";
    const needle = this._el("filter").value.trim().toLowerCase();
    const kind = this._el("kind").value;
    let rows = this._failures.filter((f) => !!f.resolved === archived);
    if (kind) rows = rows.filter((f) => this._kind(f) === kind);
    if (needle) {
      rows = rows.filter((f) =>
        `${f.name} ${f.entity_id} ${f.reason}`.toLowerCase().includes(needle));
    }
    const { key, dir } = this._sort;
    const cache = new Map();
    const parts = (f) => {
      if (!cache.has(f.id)) cache.set(f.id, this._parts(f.when));
      return cache.get(f.id);
    };
    const byWhen = (a, b) => parts(a).ts - parts(b).ts;
    const compare = {
      date: byWhen,
      // Time of day, so e.g. everything failing around 03:00 sorts together.
      time: (a, b) => parts(a).tod.localeCompare(parts(b).tod) || byWhen(a, b),
      name: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || byWhen(a, b),
      reason: (a, b) => a.reason.localeCompare(b.reason) || byWhen(a, b),
      resolved: (a, b) => (a.resolved || "").localeCompare(b.resolved || "") || byWhen(a, b),
    }[key] || byWhen;
    rows.sort((a, b) => dir * compare(a, b));
    return { rows, parts };
  }

  _render() {
    const archived = this._tab === "archived";
    const openCount = this._failures.filter((f) => !f.resolved).length;
    const archivedCount = this._failures.length - openCount;
    for (const tab of this.shadowRoot.querySelectorAll(".tab")) {
      const isOpen = tab.dataset.tab === "open";
      tab.textContent = isOpen ? `Open (${openCount})` : `Archived (${archivedCount})`;
      tab.classList.toggle("active", tab.dataset.tab === this._tab);
    }
    for (const el of this.shadowRoot.querySelectorAll("[data-show]")) {
      el.hidden = el.dataset.show !== this._tab;
    }

    const { rows, parts } = this._visible();
    const shown = rows.slice(0, this._limit);
    const visibleIds = new Set(rows.map((r) => r.id));
    const selectedVisible = [...this._selected].filter((id) => visibleIds.has(id));

    // Header
    const head = this._el("head");
    head.textContent = "";
    const thCheck = document.createElement("th");
    thCheck.className = "check";
    const all = document.createElement("input");
    all.type = "checkbox";
    all.dataset.el = "select-all";
    all.title = "Select all shown";
    all.checked = rows.length > 0 && selectedVisible.length === rows.length;
    all.indeterminate = selectedVisible.length > 0 && selectedVisible.length < rows.length;
    thCheck.appendChild(all);
    head.appendChild(thCheck);
    for (const col of COLUMNS[this._tab]) {
      const th = document.createElement("th");
      th.className = "sortable";
      th.dataset.sort = col.key;
      th.textContent = col.label + " ";
      const arrow = document.createElement("span");
      arrow.className = "arrow";
      arrow.textContent = this._sort.key === col.key ? (this._sort.dir > 0 ? "▲" : "▼") : "";
      th.appendChild(arrow);
      head.appendChild(th);
    }

    // Body
    const body = this._el("body");
    body.textContent = "";
    const frag = document.createDocumentFragment();
    for (const f of shown) {
      const p = parts(f);
      const tr = document.createElement("tr");
      tr.dataset.id = f.id;
      if (this._selected.has(f.id)) tr.classList.add("selected");

      const tdCheck = document.createElement("td");
      tdCheck.className = "check";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.row = f.id;
      cb.checked = this._selected.has(f.id);
      tdCheck.appendChild(cb);
      tr.appendChild(tdCheck);

      tr.appendChild(this._td(p.date, "when"));
      tr.appendChild(this._td(p.time, "when"));

      const tdName = document.createElement("td");
      if (f.config_id) {
        const a = document.createElement("a");
        a.href = `/config/automation/trace/${encodeURIComponent(f.config_id)}`;
        a.dataset.nav = "1";
        a.title = "Open this automation's traces";
        a.textContent = f.name;
        tdName.appendChild(a);
      } else {
        tdName.appendChild(document.createTextNode(f.name));
      }
      if (f.entity_id) {
        const ent = document.createElement("div");
        ent.className = "entity";
        ent.textContent = f.entity_id;
        tdName.appendChild(ent);
      }
      tr.appendChild(tdName);

      const tdReason = document.createElement("td");
      tdReason.className = "reason";
      const kind = this._kind(f);
      let text = f.reason;
      if (kind) {
        const chip = document.createElement("span");
        chip.className = `chip ${kind}`;
        chip.textContent = kind;
        tdReason.appendChild(chip);
        text = text.replace(/^(Failed|Missed): /, "");
      }
      tdReason.appendChild(document.createTextNode(text));
      tr.appendChild(tdReason);

      if (archived) {
        const r = this._parts(f.resolved);
        const td = this._td("", "when");
        const label = document.createElement("span");
        label.className = "resolved-label";
        label.textContent = "Resolved ";
        td.append(label, `${r.date} ${r.time}`);
        tr.appendChild(td);
      }
      frag.appendChild(tr);
    }
    body.appendChild(frag);

    // Status / empty / more
    let status = "";
    if (!this._loaded) status = "Loading…";
    else if (!rows.length) {
      const filtered = this._el("filter").value.trim() || this._el("kind").value;
      status = filtered ? "Nothing matches the filter."
        : archived ? "Nothing archived. Failures you mark resolved appear here."
          : "No open automation failures. 🎉";
    }
    this._showStatus(status);
    this._el("more").hidden = rows.length <= shown.length;
    this._el("footer").textContent = rows.length
      ? `Showing ${shown.length} of ${rows.length}` + (selectedVisible.length ? ` · ${selectedVisible.length} selected` : "")
      : "";

    // Buttons
    const n = selectedVisible.length;
    const resolveBtn = this.shadowRoot.querySelector('[data-action="resolve"]');
    resolveBtn.disabled = n === 0;
    resolveBtn.textContent = n ? `Mark ${n} resolved` : "Mark resolved";
    const restoreBtn = this.shadowRoot.querySelector('[data-action="restore"]');
    restoreBtn.disabled = n === 0;
    restoreBtn.textContent = n ? `Restore ${n} to open` : "Restore to open";
    this.shadowRoot.querySelector('[data-action="ask-clear"]').disabled = archivedCount === 0;
    if (archivedCount === 0) this._el("confirm").classList.remove("open");
  }

  _td(text, cls) {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    td.textContent = text;
    return td;
  }

  _showStatus(text) {
    const el = this._el("status");
    el.textContent = text;
    el.hidden = !text;
  }

  // -- events ---------------------------------------------------------

  _onChange(ev) {
    const target = ev.target;
    if (target.dataset.row) {
      if (target.checked) this._selected.add(target.dataset.row);
      else this._selected.delete(target.dataset.row);
      this._render();
    } else if (target.dataset.el === "select-all") {
      const { rows } = this._visible();
      for (const r of rows) {
        if (target.checked) this._selected.add(r.id);
        else this._selected.delete(r.id);
      }
      this._render();
    }
  }

  async _onClick(ev) {
    const path = ev.composedPath();
    const link = path.find((el) => el.dataset && el.dataset.nav);
    if (link) {
      ev.preventDefault();
      history.pushState(null, "", link.getAttribute("href"));
      window.dispatchEvent(new CustomEvent("location-changed"));
      return;
    }
    const tab = path.find((el) => el.dataset && el.dataset.tab);
    if (tab) {
      if (tab.dataset.tab !== this._tab) {
        this._tab = tab.dataset.tab;
        this._selected.clear();
        this._limit = PAGE_SIZE;
        if (this._tab === "open" && this._sort.key === "resolved") this._sort = { key: "date", dir: -1 };
        this._el("confirm").classList.remove("open");
        this._render();
      }
      return;
    }
    const th = path.find((el) => el.dataset && el.dataset.sort);
    if (th) {
      const key = th.dataset.sort;
      this._sort = this._sort.key === key
        ? { key, dir: -this._sort.dir }
        // Dates newest first; names and text A-Z.
        : { key, dir: key === "date" || key === "resolved" ? -1 : 1 };
      this._render();
      return;
    }
    const btn = path.find((el) => el.dataset && el.dataset.action);
    if (!btn || btn.disabled) return;
    const selectedIds = () => {
      const visible = new Set(this._visible().rows.map((r) => r.id));
      return [...this._selected].filter((id) => visible.has(id));
    };
    switch (btn.dataset.action) {
      case "menu":
        this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
        break;
      case "more":
        this._limit += PAGE_SIZE;
        this._render();
        break;
      case "resolve": {
        const ids = selectedIds();
        if (ids.length && (await this._call(WS.RESOLVE, { ids }))) {
          for (const id of ids) this._selected.delete(id);
        }
        break;
      }
      case "restore": {
        const ids = selectedIds();
        if (ids.length && (await this._call(WS.RESTORE, { ids }))) {
          for (const id of ids) this._selected.delete(id);
        }
        break;
      }
      case "ask-clear": {
        const count = this._failures.filter((f) => f.resolved).length;
        this._el("confirm-text").textContent =
          `Permanently delete all ${count} archived ${count === 1 ? "entry" : "entries"} from the automation failure log? This can't be undone.`;
        this._el("confirm").classList.add("open");
        break;
      }
      case "cancel-clear":
        this._el("confirm").classList.remove("open");
        break;
      case "clear":
        this._el("confirm").classList.remove("open");
        if (await this._call(WS.CLEAR_ARCHIVED)) this._selected.clear();
        break;
      default:
        break;
    }
  }
}

if (!customElements.get("log-doctor-failures-panel")) {
  customElements.define("log-doctor-failures-panel", LogDoctorFailuresPanel);
}
