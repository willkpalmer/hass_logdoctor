// WP Log Doctor panel - the main element, <log-doctor-panel>: the view
// buttons, the list views and their actions (see log-doctor-panel.js for
// how the modules fit together).

const V = new URL(import.meta.url).search;
// The version loaded, from the ?v= every module is loaded with (panel.py).
const VERSION = new URLSearchParams(V).get("v") || "";
const {
  BACKUP_SOURCES, COLLAPSED_KEY, OTHER_GROUP, PAGE_SIZE, SWS, VIEW_STATE_KEY, WS,
  duration, downloadFile, integrationPage, loadJSON, num, saveJSON, startupSeconds,
  tabOf, toCSV, toMarkdown, upgradeProperties,
} = await import(`./ld-util.js${V}`);
const {
  HEALTH_KINDS, IGNORED_COLUMNS, RESOLVED_COLUMN, TAB_HINTS, VIEWS,
} = await import(`./ld-views.js${V}`);
const { STYLE, TEMPLATE } = await import(`./ld-style.js${V}`);

// The pages that aren't lists.
const OTHER_PAGES = ["insights", "settings"];
// How long Undo is offered after an action.
const UNDO_MS = 8000;
// How often the header's last-scan status is refreshed.
const STATUS_INTERVAL = 5 * 60 * 1000;

export class LogDoctorPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._narrow = false;
    this._panel = null;
    this._view = "logs";
    this._state = {};
    // Each view's search, filters, tab and sort, as left last time.
    const saved = loadJSON(VIEW_STATE_KEY, {});
    for (const [name, view] of Object.entries(VIEWS)) {
      const was = saved[name] || {};
      const tabs = ["open", "archived", "ignored", "unmonitored"];
      this._state[name] = {
        records: [],
        loaded: false,
        error: null,
        tab: tabs.includes(was.tab) ? was.tab : "open",
        sort: was.sort?.key && (view.compare[was.sort.key] !== undefined || ["resolved", "ignored", "unmonitored", "active", "ignored_count"].includes(was.sort.key))
          ? { key: was.sort.key, dir: was.sort.dir === 1 ? 1 : -1 }
          : { ...view.defaultSort },
        selected: new Set(),
        expanded: new Set(),
        collapsed: this._loadCollapsed(name),
        filter: typeof was.filter === "string" ? was.filter : "",
        kind: typeof was.kind === "string" ? was.kind : "",
        hours: Number(was.hours) || 0,
        automation: typeof was.automation === "string" ? was.automation : "",
        // Startup & shutdown: only one restart's messages (see Restart history).
        run: null,
        limit: PAGE_SIZE,
      };
    }
    // One subscription per list, shared by the views showing it (the Log
    // review and Startup & shutdown both show "anomalies"), with the list
    // as last received.
    this._lists = {};
    for (const view of Object.values(VIEWS)) {
      this._lists[view.list] = { unsub: null, subscribing: false, records: [] };
    }
    this._status = null;
    this._undo = null;
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>${TEMPLATE}`;
    this.shadowRoot.querySelector('[data-el="version"]').textContent = VERSION ? `v${VERSION}` : "";
    this._el = (name) => this.shadowRoot.querySelector(`[data-el="${name}"]`);
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
    this.shadowRoot.addEventListener("keydown", (ev) => this._onKeyDown(ev));
    this._el("filter").addEventListener("input", (ev) => {
      const st = this._st();
      st.filter = ev.target.value;
      st.limit = PAGE_SIZE;
      this._saveViewState();
      this._render();
    });
    this._onHash = () => this._applyHash();
    // "/" jumps to the filter, Escape clears the selection, from anywhere
    // on the page (not while typing).
    this._onWindowKey = (ev) => {
      if (!this.isConnected || this.hidden || ev.defaultPrevented) return;
      const typing = ev.composedPath().some((el) => el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      if (typing || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (!VIEWS[this._view]) return;
      if (ev.key === "/") {
        ev.preventDefault();
        this._el("filter").focus();
      } else if (ev.key === "Escape") {
        this._clearSelection();
      }
    };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this._el("settings").hass = hass;
    this._el("insights").hass = hass;
    if (first) this._formatters();
    if (this.isConnected) {
      this._subscribeAll();
      if (first) this._refreshStatus();
    }
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
    upgradeProperties(this, ["hass", "narrow", "panel", "route"]);
    window.addEventListener("hashchange", this._onHash);
    window.addEventListener("keydown", this._onWindowKey);
    this._applyHash();
    if (this._hass) {
      this._subscribeAll();
      this._refreshStatus();
    }
    this._statusTimer = setInterval(() => this._refreshStatus(), STATUS_INTERVAL);
  }

  disconnectedCallback() {
    window.removeEventListener("hashchange", this._onHash);
    window.removeEventListener("keydown", this._onWindowKey);
    clearInterval(this._statusTimer);
    for (const list of Object.keys(this._lists)) this._unsubscribe(list);
  }

  _st(name = this._view) { return this._state[name]; }

  _applyHash() {
    const hash = window.location.hash.replace("#", "");
    const fromConfig = this._panel?.config?.view;
    const isView = (v) => !!VIEWS[v] || OTHER_PAGES.includes(v);
    const view = isView(hash) ? hash : isView(fromConfig) ? fromConfig : this._view;
    if (view !== this._view || !this._rendered) {
      this._view = view;
      this._syncControls();
      this._render();
    }
  }

  _setView(view) {
    if ((!VIEWS[view] && !OTHER_PAGES.includes(view)) || view === this._view) return;
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
    this._el("hours").value = String(st.hours || 0);
    this._fillAutomations();
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
    for (const list of Object.keys(this._lists)) {
      const ls = this._lists[list];
      if (!ls.unsub && !ls.subscribing) this._subscribe(list);
    }
  }

  // The views showing a list.
  _viewsOf(list) {
    return Object.keys(VIEWS).filter((name) => VIEWS[name].list === list);
  }

  async _subscribe(list) {
    const ls = this._lists[list];
    if (ls.subscribing || !this._hass) return;
    ls.subscribing = true;
    try {
      ls.unsub = await this._hass.connection.subscribeMessage(
        (msg) => this._onMessage(list, msg),
        { type: WS.SUBSCRIBE, list },
      );
    } catch (err) {
      for (const name of this._viewsOf(list)) {
        this._st(name).error = `Couldn't load: ${err.message || err.code || err}`;
      }
      this._render();
    } finally {
      ls.subscribing = false;
    }
  }

  _unsubscribe(list) {
    const ls = this._lists[list];
    if (ls.unsub) {
      try { ls.unsub(); } catch (_err) { /* connection already gone */ }
      ls.unsub = null;
    }
  }

  // The whole list ({records}), or just what changed ({added, removed}:
  // new automation runs, and the oldest dropped to make room).
  _onMessage(list, msg) {
    const ls = this._lists[list];
    if (msg.reload) {
      // WP Log Doctor is reloading; pick up the new list shortly.
      this._unsubscribe(list);
      setTimeout(() => this._subscribe(list), 2000);
      return;
    }
    let added;
    if (msg.records) {
      ls.records = msg.records;
      added = ls.records;
    } else {
      const removed = new Set(msg.removed || []);
      added = msg.added || [];
      ls.records = (removed.size ? ls.records.filter((r) => !removed.has(r.id)) : ls.records).concat(added);
    }
    for (const name of this._viewsOf(list)) {
      const view = VIEWS[name];
      const st = this._st(name);
      // Only new records need decorating; the others keep theirs.
      if (view.decorate) for (const r of added) view.decorate(r, this);
      st.records = view.include ? ls.records.filter(view.include) : ls.records;
      st.loaded = true;
      st.error = null;
      const ids = new Set(st.records.map((r) => r.id));
      for (const id of [...st.selected]) if (!ids.has(id)) st.selected.delete(id);
      if (view.groupNoun === "day") this._forgetOldDays(name);
    }
    if (this._viewsOf(list).includes(this._view) && VIEWS[this._view].automationFilter) this._fillAutomations();
    this._render();
  }

  // Collapsed days older than the oldest run kept aren't remembered.
  _forgetOldDays(name) {
    const st = this._st(name);
    if (!st.collapsed.size || !st.records.length) return;
    const oldest = st.records.reduce((min, r) => (r._day && r._day < min ? r._day : min), "9999");
    let changed = false;
    for (const day of [...st.collapsed]) {
      if (/^\d{4}-\d{2}-\d{2}$/.test(day) && day < oldest) {
        st.collapsed.delete(day);
        changed = true;
      }
    }
    if (changed) this._saveCollapsed();
  }

  _saveViewState() {
    const saved = {};
    for (const [name, st] of Object.entries(this._state)) {
      saved[name] = { tab: st.tab, sort: st.sort, filter: st.filter, kind: st.kind, hours: st.hours, automation: st.automation };
    }
    saveJSON(VIEW_STATE_KEY, saved);
  }

  // The Runs automation drop-down: every automation with runs listed.
  _fillAutomations() {
    const view = VIEWS[this._view];
    const select = this._el("automation");
    if (!view?.automationFilter) return;
    const st = this._st();
    const names = new Map();
    for (const r of st.records) if (r.kind === "run" && !names.has(r.entity_id)) names.set(r.entity_id, r.name);
    if (st.automation && !names.has(st.automation)) names.set(st.automation, st.automation);
    const options = [["", "All automations"], ...[...names].sort((a, b) => a[1].localeCompare(b[1], undefined, { sensitivity: "base" }))];
    const key = options.map((o) => o[0]).join("|");
    if (select.dataset.key !== key) {
      select.replaceChildren(...options.map(([value, label]) => new Option(label, value)));
      select.dataset.key = key;
    }
    select.value = st.automation;
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
    const saved = loadJSON(COLLAPSED_KEY, {});
    return new Set(Array.isArray(saved[name]) ? saved[name] : []);
  }

  _saveCollapsed() {
    const saved = {};
    for (const [name, st] of Object.entries(this._state || {})) {
      if (st.collapsed.size) saved[name] = [...st.collapsed];
    }
    saveJSON(COLLAPSED_KEY, saved);
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
    if (tab === "archived") return [...cols, RESOLVED_COLUMN];
    if (tab === "ignored") return [...cols, ...(VIEWS[this._view].ignoredColumns || IGNORED_COLUMNS)];
    if (tab === "unmonitored") return [...cols, { key: "unmonitored", label: "Not monitored since", firstDir: -1 }];
    return cols;
  }

  _compare(key) {
    const view = VIEWS[this._view];
    if (key === "resolved") return (a, b) => (a.resolved || "").localeCompare(b.resolved || "");
    if (key === "ignored") return (a, b) => (a.ignored || "").localeCompare(b.ignored || "");
    if (key === "unmonitored") return (a, b) => (a.unmonitored || "").localeCompare(b.unmonitored || "");
    if (key === "active") return (a, b) => Number(!!a.active) - Number(!!b.active);
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
    if (view.timeWindow && st.hours && st.tab === "open") {
      const since = new Date(Date.now() - st.hours * 3600 * 1000).toISOString();
      rows = rows.filter((r) => new Date(r.when).toISOString() >= since);
    }
    if (st.kind) rows = rows.filter((r) => (view.matches ? view.matches(r, st.kind) : view.kindOf(r) === st.kind));
    if (view.automationFilter && st.automation) rows = rows.filter((r) => r.entity_id === st.automation);
    if (view.runFilter && st.run) rows = rows.filter((r) => (r.restart_runs || []).includes(st.run));
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
      const names = [...groups.keys()].sort(view.groupSort || ((a, b) =>
        rank(a) - rank(b) || a.localeCompare(b, undefined, { sensitivity: "base" })));
      rows = names.flatMap((name) => groups.get(name));
    }
    return rows;
  }

  _render() {
    this._rendered = true;
    for (const btn of this.shadowRoot.querySelectorAll(".view")) {
      // A button covering several views (Automations) is active on each.
      const views = (btn.dataset.page || btn.dataset.view || "").split(" ");
      btn.classList.toggle("active", views.includes(this._view));
    }
    // Open entries on each view's button, red when any is an error.
    for (const [name, view] of Object.entries(VIEWS)) {
      if (view.navCount === false) continue;
      const s = this._st(name);
      const open = s.records.filter((r) => tabOf(r) === "open");
      const alert = !!view.alert && open.some(view.alert);
      for (const el of this.shadowRoot.querySelectorAll(`[data-count="${name}"], [data-section-count="${name}"]`)) {
        el.textContent = s.loaded && open.length ? num(open.length) : "";
        el.classList.toggle("alert", alert);
        el.title = `${open.length} open` + (alert ? ", including errors" : "");
      }
    }
    // The Failures | Runs switch, on the Automations page.
    const sections = this._el("sections");
    const page = this.shadowRoot.querySelector(`.view[data-page~="${this._view}"]`);
    sections.hidden = !page;
    for (const btn of sections.querySelectorAll(".section")) {
      btn.classList.toggle("active", btn.dataset.view === this._view);
    }
    this._renderStatus();
    // The pages that aren't lists: shown (and refreshed) when opened.
    for (const page of OTHER_PAGES) {
      const el = this._el(page);
      const show = this._view === page;
      if (show && el.hidden) {
        el.hidden = false;
        el.activate();
      } else if (!show) {
        el.hidden = true;
      }
    }
    this._el("list-card").hidden = !VIEWS[this._view];
    if (!VIEWS[this._view]) return;

    const view = VIEWS[this._view];
    const st = this._st();
    const archived = st.tab === "archived";
    const ignoredTab = st.tab === "ignored";
    const tabCounts = { open: 0, archived: 0, ignored: 0, unmonitored: 0 };
    for (const r of st.records) tabCounts[tabOf(r)] += 1;
    const archivedCount = tabCounts.archived;
    const tabNames = { open: "Open", archived: "Archived", ignored: "Ignored", unmonitored: "Not monitored", ...view.tabNames };
    for (const tab of this.shadowRoot.querySelectorAll(".tab")) {
      tab.textContent = `${tabNames[tab.dataset.tab]} (${num(tabCounts[tab.dataset.tab])})`;
      tab.classList.toggle("active", tab.dataset.tab === st.tab);
      tab.setAttribute("aria-selected", String(tab.dataset.tab === st.tab));
    }
    this._el("hint").textContent = (view.hints || {})[st.tab] ?? TAB_HINTS[st.tab] ?? "";
    const runFilter = this._el("run-filter");
    runFilter.hidden = !(view.runFilter && st.run);
    if (view.runFilter && st.run) {
      const restart = this._st("reboots").records.find((r) => r.id === st.run);
      runFilter.textContent = `Only the restart of ${this._dateTime(restart?.starting || st.run)} ✕`;
    }
    for (const el of this.shadowRoot.querySelectorAll("[data-show], [data-ignorable], [data-unmonitorable], [data-archivable]")) {
      const onTab = el.dataset.show === undefined || el.dataset.show.split(" ").includes(st.tab);
      el.hidden = !onTab
        || (el.dataset.ignorable !== undefined && !view.ignorable)
        || (el.dataset.unmonitorable !== undefined && !view.unmonitorable)
        || (el.dataset.archivable !== undefined && view.archivable === false);
    }
    for (const el of this.shadowRoot.querySelectorAll("[data-only-view]")) {
      const shownByTab = !el.matches("[data-show], [data-ignorable], [data-unmonitorable], [data-archivable]") || !el.hidden;
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
    all.setAttribute("aria-label", "Select all shown");
    const selectable = rows.filter((r) => !isCollapsed(r)).length;
    all.checked = selectable > 0 && selectedVisible.length === selectable;
    all.indeterminate = selectedVisible.length > 0 && selectedVisible.length < selectable;
    thCheck.appendChild(all);
    head.appendChild(thCheck);
    for (const col of columns) {
      const th = document.createElement("th");
      th.className = "sortable" + (col.num ? " num" : "");
      th.dataset.sort = col.key;
      th.tabIndex = 0;
      if (st.sort.key === col.key) th.setAttribute("aria-sort", st.sort.dir > 0 ? "ascending" : "descending");
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
        trGroup.tabIndex = 0;
        trGroup.setAttribute("aria-expanded", String(!collapsed));
        const noun = view.groupNoun || "integration";
        trGroup.title = collapsed ? `Show this ${noun}'s entries (Enter)` : `Hide this ${noun}'s entries (Enter)`;
        // A checkbox selecting every entry under the heading (not while
        // collapsed: nothing hidden is selected - see _collapse).
        const groupRows = rows.filter((g) => view.groupBy(g) === lastGroup);
        const tdCheck = document.createElement("td");
        tdCheck.className = "check";
        const groupCb = document.createElement("input");
        groupCb.type = "checkbox";
        groupCb.dataset.groupSelect = lastGroup;
        const groupSelected = groupRows.filter((g) => st.selected.has(g.id)).length;
        groupCb.checked = groupSelected > 0 && groupSelected === groupRows.length;
        groupCb.indeterminate = groupSelected > 0 && groupSelected < groupRows.length;
        groupCb.disabled = collapsed;
        groupCb.title = collapsed ? `Expand this ${noun} to select its entries` : `Select all of this ${noun}'s entries`;
        groupCb.setAttribute("aria-label", groupCb.title);
        tdCheck.appendChild(groupCb);
        trGroup.appendChild(tdCheck);
        const td = document.createElement("td");
        td.colSpan = columns.length;
        const caret = document.createElement("span");
        caret.className = "caret";
        caret.textContent = collapsed ? "▸" : "▾";
        td.append(caret, view.groupLabel ? view.groupLabel(lastGroup, this) : lastGroup);
        const count = document.createElement("span");
        count.className = "group-count";
        count.textContent = ` (${groupSizes.get(lastGroup)})`;
        td.appendChild(count);
        if (view.groupLinks) td.append(...this._groupLinks(groupRows));
        trGroup.appendChild(td);
        frag.appendChild(trGroup);
      }
      if (collapsed || !shownIds.has(r.id)) continue;
      if (r.id === lastShown) pastPage = true;
      const tr = document.createElement("tr");
      tr.className = "row";
      tr.dataset.id = r.id;
      // Keyboard: Space selects, Enter shows the details, arrows move.
      tr.tabIndex = 0;
      if (st.selected.has(r.id)) tr.classList.add("selected");
      tr.setAttribute("aria-selected", String(st.selected.has(r.id)));
      const tdCheck = document.createElement("td");
      tdCheck.className = "check";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.row = r.id;
      cb.checked = st.selected.has(r.id);
      cb.tabIndex = -1;
      cb.setAttribute("aria-label", `Select ${r.name || r.message || r.logger || this._dateTime(r.starting || r.when) || "entry"}`);
      tdCheck.appendChild(cb);
      tr.appendChild(tdCheck);
      if (this._view === "logs" || this._view === "restarts") this._logCells(tr, r);
      else if (this._view === "backups") this._backupCells(tr, r);
      else if (this._view === "health") this._healthCells(tr, r);
      else if (this._view === "reboots") this._rebootCells(tr, r);
      else if (this._view === "runs") this._runCells(tr, r);
      else this._failureCells(tr, r);
      if (archived) {
        const td = this._td("", "when");
        td.append(this._label("Archived "));
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
      if (st.tab === "unmonitored") {
        const td = this._td("", "when");
        td.title = "Nothing about it has been reported since";
        td.append(this._label("Not monitored since "), this._dateTime(r.unmonitored));
        tr.appendChild(td);
      }
      if (ignoredTab) {
        const td = this._td("", "when");
        td.append(this._label("Ignored "), this._dateTime(r.ignored));
        tr.appendChild(td);
        if (this._view === "health") {
          const tdNow = this._td("", "");
          tdNow.appendChild(r.active
            ? this._chip("unavailable", "Still there")
            : this._chip("recovered", "Cleared"));
          tdNow.title = "It stays ignored either way, unless another of its entities becomes unavailable";
          tr.appendChild(tdNow);
        } else {
          const tdCount = this._td("", "num");
          tdCount.title = "Times logged since it was ignored";
          tdCount.append(this._label("Since ignored: "), String(r.ignored_count || 0));
          tr.appendChild(tdCount);
        }
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

    // Buttons: the same verbs on every view, with how many they'd act on.
    const n = selectedVisible.length;
    const label = (action, text) => {
      const btn = this.shadowRoot.querySelector(`[data-action="${action}"]`);
      btn.disabled = n === 0;
      btn.textContent = n ? `${text} (${n})` : text;
      return btn;
    };
    label("resolve", "Archive");
    label("restore", "Restore");
    label("ask-delete", "Delete");
    label("ignore", "Ignore");
    label("unignore", "Stop ignoring");
    label("monitor", "Monitor again");
    label("to-restarts", "Move to Startup & shutdown");
    label("to-operational", "Move to Log review");
    const groupsBtn = this.shadowRoot.querySelector('[data-action="toggle-groups"]');
    const groupNames = view.groupBy ? [...groupSizes.keys()] : [];
    const allCollapsed = groupNames.length > 0 && groupNames.every((g) => st.collapsed.has(g));
    groupsBtn.disabled = groupNames.length === 0;
    groupsBtn.textContent = allCollapsed ? "Expand all" : "Collapse all";
    // Only devices (and entities with no device), or automations, can be
    // left unmonitored.
    const devices = rows.filter((r) => st.selected.has(r.id) && (view.unmonitorKinds || []).includes(r.kind)).length;
    const unmonitorBtn = this.shadowRoot.querySelector('[data-action="unmonitor"]');
    const monitorBtn = this.shadowRoot.querySelector('[data-action="monitor"]');
    unmonitorBtn.disabled = devices === 0;
    unmonitorBtn.textContent = devices ? `Stop monitoring (${devices})` : "Stop monitoring";
    [unmonitorBtn.title, monitorBtn.title] = view.unmonitorTitles || [
      "Stop reporting these devices altogether, whatever becomes unavailable or isn't provided any more; they're listed on the Not monitored tab",
      "Report these devices again; they're checked straight away",
    ];
    const copyBtn = this.shadowRoot.querySelector('[data-action="copy-prompt"]');
    copyBtn.disabled = n === 0;
    if (!copyBtn.dataset.busy) copyBtn.textContent = n ? `Copy investigation prompt (${n})` : "Copy investigation prompt";
    this.shadowRoot.querySelector('[data-action="ask-clear"]').disabled = archivedCount === 0;
    if (archivedCount === 0) this._el("confirm").classList.remove("open");
    const [one, many] = view.noun;
    const exportCount = n || rows.length;
    this._el("export-what").textContent = n
      ? `The ${n} selected ${n === 1 ? one : many}`
      : `The ${num(rows.length)} ${rows.length === 1 ? one : many} shown on this tab`;
    for (const b of this._el("export").querySelectorAll("button")) b.disabled = exportCount === 0;
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
    if (!domain) return [];
    const [pageLabel, pageHref] = integrationPage(domain);
    const page = document.createElement("a");
    page.className = "group-link";
    page.href = pageHref;
    page.dataset.nav = "1";
    page.title = `Open ${pageLabel === "Integration ↗" ? "this integration's page" : `the ${pageLabel.replace(" ↗", "")} page`}`;
    page.textContent = pageLabel;
    const entityRows = groupRows.filter((r) => (r.kind === "offline" || r.kind === "unavailable") && (r.entities || []).length);
    if (!entityRows.length) return [page];
    const status = (key, fallback) =>
      this._hass?.localize?.(`ui.panel.config.entities.picker.status.${key}`) || fallback;
    const link = (label, search, title, kind) => {
      const a = document.createElement("a");
      a.className = `group-link ${kind}`;
      a.href = `/config/entities?domain=${encodeURIComponent(domain)}`;
      a.dataset.nav = "1";
      a.dataset.search = search;
      a.title = title;
      a.textContent = label;
      return a;
    };
    const links = [link("Unavailable entities ↗", status("unavailable", "Unavailable"),
      "Open Settings → Entities for this integration, searching for unavailable entities", "unavailable")];
    if (entityRows.some((r) => (r.detail || "").includes("no longer provided"))) {
      links.push(link("Not provided ↗", status("not_provided", "Not provided"),
        "Open Settings → Entities for this integration, searching for entities it no longer provides", "not-provided"));
    }
    return [page, ...links];
  }

  // Runs a scan (the Scan now button entity / log_doctor.scan_now). The
  // lists update by themselves; the button says how it went for a moment.
  async _scanNow(btn) {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.textContent = "Scanning…";
    let result = "Scan now";
    try {
      const res = await this._hass.callWS({ type: SWS.SCAN_NOW });
      const sum = res?.status?.summary;
      result = sum ? `Scanned ✓ ${sum.new} new` : "Scanned ✓";
      btn.title = sum
        ? `Last scan: ${sum.new} new, ${sum.recurring} still occurring`
        : "Scan finished";
      // The Settings view shows the last scan's details.
      if (this._view === "settings") this._el("settings").activate();
      if (res?.status) this._setStatus(res.status);
    } catch (err) {
      result = "Scan failed";
      btn.title = `Scan failed: ${err.message || err.code || err}`;
      this._refreshStatus();
    }
    btn.disabled = false;
    btn.textContent = result;
    setTimeout(() => {
      if (!btn.disabled) btn.textContent = "Scan now";
    }, 4000);
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

    // How long starting took, flagged when it's much slower than usual.
    const tdStartup = this._td("", "num");
    tdStartup.title = "From Home Assistant starting until it had finished starting";
    tdStartup.append(this._label("Startup took "), duration(r.starting, r.started));
    const usual = this._usualStartup();
    const took = startupSeconds(r);
    if (usual && took > 30 && took > usual * 1.5) {
      const chip = this._chip("slow", "Slow");
      chip.title = `Much slower than usual (${duration(new Date(0).toISOString(), new Date(usual * 1000).toISOString())})`;
      chip.style.marginLeft = "6px";
      tdStartup.appendChild(chip);
    }
    tr.appendChild(tdStartup);

    const tdTook = this._td("", "num");
    tdTook.title = r.shutdown_start ? "From the shutdown until Home Assistant had finished starting" : "From the start until Home Assistant had finished starting";
    tdTook.append(this._label("Down for "), duration(r.shutdown_start || r.starting, r.started));
    tr.appendChild(tdTook);

    // What it logged: a link to those messages on Startup & shutdown.
    const tdMessages = this._td("", "num");
    tdMessages.append(this._label("Messages "));
    if (r.messages) {
      const a = document.createElement("a");
      a.href = "#restarts";
      a.dataset.run = r.id;
      a.title = "Show the messages logged during this restart's shutdown and startup on Startup & shutdown";
      a.textContent = num(r.messages);
      tdMessages.appendChild(a);
      if (r.errors) {
        const errors = document.createElement("div");
        errors.className = "sub errors";
        errors.textContent = `${num(r.errors)} error${r.errors === 1 ? "" : "s"}`;
        tdMessages.appendChild(errors);
      }
    } else {
      tdMessages.append(r.messages === undefined ? "—" : "0");
      if (r.messages === undefined) tdMessages.title = "Not counted: restarts are counted from WP Log Doctor 0.40.0, by the scans after them";
    }
    tr.appendChild(tdMessages);
  }

  // The median time Home Assistant takes to start, over the restarts kept.
  _usualStartup() {
    const records = this._st("reboots").records;
    if (this._usualFor === records) return this._usual;
    const times = records.map(startupSeconds).filter((t) => t > 0).sort((a, b) => a - b);
    this._usualFor = records;
    this._usual = times.length >= 3 ? times[Math.floor(times.length / 2)] : null;
    return this._usual;
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

  // Automations: Runs rows - when it ran, which automation, what triggered it.
  // "Today", "Yesterday" or e.g. "Saturday", then the date - a day heading.
  _dayLabel(day) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return day;
    const today = this._date(new Date().toISOString());
    const yesterday = this._date(new Date(Date.now() - 86400000).toISOString());
    if (day === today) return `Today · ${day}`;
    if (day === yesterday) return `Yesterday · ${day}`;
    const weekday = new Date(`${day}T12:00:00Z`).toLocaleDateString("en-GB", { weekday: "long", timeZone: "UTC" });
    return `${weekday} · ${day}`;
  }

  _runCells(tr, r) {
    // The day is the group's heading, so runs show the time; the Excluded
    // tab's "last run" keeps its date.
    const tdWhen = this._td("", "when");
    tdWhen.append(this._label(r.kind === "excluded" ? "Last run " : "Ran "),
      r.kind === "excluded" ? this._dateTime(r.when) : this._time(r.when));
    tdWhen.title = this._dateTime(r.when);
    tr.appendChild(tdWhen);

    const tdName = document.createElement("td");
    if (r.config_id) {
      const a = document.createElement("a");
      a.href = `/config/automation/trace/${encodeURIComponent(r.config_id)}`;
      a.dataset.nav = "1";
      a.title = "Open this automation's traces";
      a.textContent = r.name;
      tdName.appendChild(a);
    } else {
      tdName.appendChild(document.createTextNode(r.name));
    }
    const ent = document.createElement("div");
    ent.className = "sub";
    ent.textContent = r.entity_id;
    tdName.appendChild(ent);
    tr.appendChild(tdName);

    const tdTrigger = this._td("", "text");
    tdTrigger.append(this._label("Trigger "));
    if (r.kind === "excluded") {
      tdTrigger.append("—");
    } else if (r.manual) {
      const chip = this._chip("script", "Manual");
      chip.title = "Run by hand: the Run button or the automation.trigger action";
      tdTrigger.appendChild(chip);
    } else {
      // Which of its triggers (its name or a description of it), with Home
      // Assistant's own description under it when that says something else.
      tdTrigger.append(r.trigger_name || r.trigger || "");
      if (r.trigger_name && r.trigger && r.trigger_name.toLowerCase() !== r.trigger.toLowerCase()) {
        const sub = document.createElement("div");
        sub.className = "sub";
        sub.textContent = r.trigger;
        sub.title = "Home Assistant's description of what triggered it";
        tdTrigger.appendChild(sub);
      }
    }
    tr.appendChild(tdTrigger);
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
      chip.title = "Came back after it had cleared up, or another of its entities became unavailable while it was ignored";
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
    h.textContent = r.kind === "flapping" ? "Entities that went unavailable" : "Unavailable entities";
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
    } else if (target.dataset.groupSelect !== undefined) {
      const view = VIEWS[this._view];
      for (const r of this._visible()) {
        if (view.groupBy(r) !== target.dataset.groupSelect) continue;
        if (target.checked) st.selected.add(r.id);
        else st.selected.delete(r.id);
      }
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
      this._saveViewState();
      this._render();
    } else if (target.dataset.el === "hours") {
      st.hours = Number(target.value) || 0;
      st.limit = PAGE_SIZE;
      this._saveViewState();
      this._render();
    } else if (target.dataset.el === "automation") {
      st.automation = target.value;
      st.limit = PAGE_SIZE;
      this._saveViewState();
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
      this._navigate(link.getAttribute("href"), link.dataset.search);
      return;
    }
    // Restart history's Messages: that restart's on Startup & shutdown.
    const runLink = find("run");
    if (runLink) {
      ev.preventDefault();
      const restarts = this._st("restarts");
      restarts.run = runLink.dataset.run;
      restarts.tab = "open";
      restarts.limit = PAGE_SIZE;
      restarts.selected.clear();
      this._setView("restarts");
      this._render();
      return;
    }
    const viewBtn = find("view");
    if (viewBtn) {
      ev.preventDefault();
      this._setView(viewBtn.dataset.view);
      return;
    }
    const action = find("action")?.dataset.action;
    // On every page: Scan now, the menu (narrow windows), Undo.
    if (action === "scan-now") {
      await this._scanNow(find("action"));
      return;
    }
    if (action === "menu") {
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
      return;
    }
    if (action === "undo") {
      await this._runUndo();
      return;
    }
    if (!VIEWS[this._view]) return; // Settings and Insights handle their own.
    // Clicking anywhere else closes the Export menu.
    const exportMenu = this._el("export");
    if (exportMenu.open && !path.includes(exportMenu)) exportMenu.open = false;
    // A heading's checkbox selects (see _onChange), it doesn't collapse.
    if (find("groupSelect")) return;
    const groupRow = find("groupToggle");
    if (groupRow) {
      this._toggleGroup(groupRow.dataset.groupToggle);
      return;
    }
    const expand = find("expand");
    if (expand) {
      this._toggleExpanded(expand.dataset.expand);
      return;
    }
    const tab = find("tab");
    if (tab) {
      this._setTab(tab.dataset.tab);
      return;
    }
    const th = find("sort");
    if (th) {
      this._sortBy(th.dataset.sort);
      return;
    }
    const btn = find("action");
    if (!btn || btn.disabled) return;
    const view = VIEWS[this._view];
    const selectedIds = () => {
      const visible = new Set(this._visible().map((r) => r.id));
      return [...st.selected].filter((id) => visible.has(id));
    };
    const [one, many] = view.noun;
    const nouns = (n) => `${n} ${n === 1 ? one : many}`;
    switch (btn.dataset.action) {
      case "toggle-groups": {
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
      case "clear-run":
        st.run = null;
        st.limit = PAGE_SIZE;
        this._render();
        break;
      case "export-csv":
      case "export-md":
        this._export(btn.dataset.action === "export-csv" ? "csv" : "md");
        this._el("export").open = false;
        break;
      case "resolve": {
        const ids = selectedIds();
        await this._act(WS.RESOLVE, ids, `Archived ${nouns(ids.length)}`, { type: WS.RESTORE });
        break;
      }
      case "restore": {
        const ids = selectedIds();
        await this._act(WS.RESTORE, ids, `Restored ${nouns(ids.length)} to Open`, { type: WS.RESOLVE });
        break;
      }
      case "to-restarts":
      case "to-operational": {
        const ids = selectedIds();
        const toRestarts = btn.dataset.action === "to-restarts";
        await this._act(
          WS.SET_CATEGORY, ids,
          `Moved ${nouns(ids.length)} to ${toRestarts ? "Startup & shutdown" : "the Log review"}`,
          { type: WS.SET_CATEGORY, category: toRestarts ? "operational" : "restart" },
          { category: toRestarts ? "restart" : "operational" },
        );
        break;
      }
      case "unmonitor": {
        const ids = this._visible()
          .filter((r) => st.selected.has(r.id) && (view.unmonitorKinds || []).includes(r.kind))
          .map((r) => r.id);
        // Monitoring an automation again doesn't bring back the runs removed.
        await this._act(WS.UNMONITOR, ids, `Stopped monitoring ${ids.length}`, null);
        break;
      }
      case "monitor": {
        const ids = selectedIds();
        await this._act(WS.MONITOR, ids, `Monitoring ${ids.length} again`, null);
        break;
      }
      case "ignore": {
        const ids = selectedIds();
        await this._act(WS.IGNORE, ids, `Ignored ${nouns(ids.length)}`, { type: WS.UNIGNORE });
        break;
      }
      case "unignore": {
        const ids = selectedIds();
        await this._act(WS.UNIGNORE, ids, `Stopped ignoring ${nouns(ids.length)}`, { type: WS.IGNORE });
        break;
      }
      case "copy-prompt": {
        // In the order they're listed.
        const ids = this._visible().filter((r) => st.selected.has(r.id)).map((r) => r.id);
        if (ids.length) await this._copyPrompt(btn, ids);
        break;
      }
      case "ask-delete": {
        const ids = selectedIds().filter((id) => tabOf(st.records.find((r) => r.id === id) || {}) === "archived");
        if (!ids.length) break;
        this._confirmIds = ids;
        this._el("confirm-text").textContent =
          `Permanently delete ${nouns(ids.length)} from ${view.where}? This can't be undone.`;
        this._el("confirm").classList.add("open");
        break;
      }
      case "ask-clear": {
        this._confirmIds = null;
        const count = st.records.filter((r) => tabOf(r) === "archived").length;
        this._el("confirm-text").textContent =
          `Permanently delete all ${count} archived ${count === 1 ? one : many} from ${view.where}? This can't be undone.`;
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

  // -- actions ----------------------------------------------------------

  // Runs a list action on the selected entries, then offers Undo (the
  // opposite action on the same entries) for a few seconds.
  async _act(type, ids, message, undo, extra = {}) {
    if (!ids.length) return;
    const list = VIEWS[this._view].list;
    const st = this._st();
    if (!(await this._call(type, { ids, ...extra }))) return;
    for (const id of ids) st.selected.delete(id);
    this._render();
    this._showUndo(message, undo ? { list, ids, ...undo } : null);
  }

  _showUndo(message, undo) {
    clearTimeout(this._undoTimer);
    this._undo = undo;
    this._el("snack-text").textContent = message;
    this.shadowRoot.querySelector('[data-action="undo"]').hidden = !undo;
    this._el("snackbar").classList.add("open");
    this._undoTimer = setTimeout(() => this._hideUndo(), UNDO_MS);
  }

  _hideUndo() {
    clearTimeout(this._undoTimer);
    this._undo = null;
    this._el("snackbar").classList.remove("open");
  }

  async _runUndo() {
    const undo = this._undo;
    this._hideUndo();
    if (!undo) return;
    try {
      await this._hass.callWS(undo);
    } catch (err) {
      alert(`WP Log Doctor: ${err.message || err.code || err}`);
    }
  }

  _clearSelection() {
    const st = this._st();
    this._el("confirm").classList.remove("open");
    this._el("export").open = false;
    if (!st.selected.size) return;
    st.selected.clear();
    this._render();
  }

  _toggleGroup(group) {
    const st = this._st();
    if (st.collapsed.has(group)) st.collapsed.delete(group);
    else this._collapse(group);
    this._saveCollapsed();
    this._render();
  }

  _toggleExpanded(id) {
    const st = this._st();
    if (st.expanded.has(id)) st.expanded.delete(id);
    else st.expanded.add(id);
    this._render();
  }

  _setTab(tab) {
    const st = this._st();
    if (tab === st.tab) return;
    st.tab = tab;
    st.selected.clear();
    st.limit = PAGE_SIZE;
    // A column only this tab had (e.g. Archived) can't stay the sort.
    if (!this._columns().some((c) => c.key === st.sort.key)) st.sort = { ...VIEWS[this._view].defaultSort };
    this._el("scroll").scrollTop = 0;
    this._el("confirm").classList.remove("open");
    this._saveViewState();
    this._render();
  }

  _sortBy(key) {
    const st = this._st();
    const col = this._columns().find((c) => c.key === key);
    st.sort = st.sort.key === key
      ? { key, dir: -st.sort.dir }
      // Dates and counts start newest/largest first; text A-Z.
      : { key, dir: col && col.firstDir ? col.firstDir : 1 };
    this._saveViewState();
    this._render();
  }

  // Saves the selected entries, or all those shown on the tab (collapsed
  // groups and pages not shown yet included), as CSV or Markdown.
  _export(format) {
    const view = VIEWS[this._view];
    const st = this._st();
    let rows = this._visible();
    if (rows.some((r) => st.selected.has(r.id))) rows = rows.filter((r) => st.selected.has(r.id));
    if (!rows.length) return;
    const header = [...view.exportHeader];
    if (st.tab === "archived") header.push("Archived");
    if (st.tab === "ignored") header.push("Ignored");
    if (st.tab === "unmonitored") header.push("Not monitored since");
    const body = rows.map((r) => {
      const row = view.exportRow(r, this);
      if (st.tab === "archived") row.push(this._dateTime(r.resolved));
      if (st.tab === "ignored") row.push(this._dateTime(r.ignored));
      if (st.tab === "unmonitored") row.push(this._dateTime(r.unmonitored));
      return row;
    });
    const page = this.shadowRoot.querySelector(`.view[data-view="${this._view}"], .section[data-view="${this._view}"]`);
    const title = `WP Log Doctor - ${(page?.firstChild?.textContent || this._view).trim()}`;
    const stamp = this._date(new Date().toISOString());
    const name = `log-doctor-${this._view}-${st.tab}-${stamp}`;
    if (format === "csv") downloadFile(`${name}.csv`, toCSV(header, body), "text/csv;charset=utf-8");
    else downloadFile(`${name}.md`, toMarkdown(`${title} (${st.tab}, ${stamp})`, header, body), "text/markdown;charset=utf-8");
  }

  // Opens a page of Home Assistant's, as its own links do.
  _navigate(href, search) {
    // A search for the page opened (see _groupLinks).
    history.pushState(search ? { filter: search } : null, "", href);
    window.dispatchEvent(new CustomEvent("location-changed"));
    if (!search) return;
    // Home Assistant keeps the entities page once opened and only
    // re-attaches it after this event, so a second visit would miss the
    // new URL and keep the first one's filters. Tell it again once it's
    // attached; it ignores the event if its filters already match.
    for (const delay of [100, 500]) {
      setTimeout(() => window.dispatchEvent(new CustomEvent("location-changed")), delay);
    }
    // The search box is filled from the history state by the entities
    // page itself, which is Home Assistant's own business and could change:
    // if it hasn't been filled once the page is up, fill it in directly.
    // Best effort - at worst the page opens filtered to the integration
    // without the search.
    for (const delay of [900, 2000]) setTimeout(() => this._fillEntitiesSearch(search), delay);
  }

  _fillEntitiesSearch(term) {
    try {
      if (!window.location.pathname.startsWith("/config/entities")) return;
      const page = deepFind(document.querySelector("home-assistant"), (el) => el.localName === "ha-config-entities");
      if (!page) return;
      const search = deepFind(page, (el) => /^search-input/.test(el.localName));
      if (!search || (search.filter || "").includes(term)) return;
      search.filter = term;
      search.dispatchEvent(new CustomEvent("value-changed", { detail: { value: term } }));
    } catch (_err) {
      // Left as it is.
    }
  }

  // -- keyboard ---------------------------------------------------------

  // On a row: Space selects it, Enter shows its details, arrows move. On a
  // heading: Enter or Space collapses or expands it. On a column heading:
  // Enter sorts.
  _onKeyDown(ev) {
    if (!VIEWS[this._view]) return;
    const target = ev.composedPath()[0];
    if (!(target instanceof HTMLElement)) return;
    if (target.matches("th[data-sort]") && (ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault();
      this._sortBy(target.dataset.sort);
      this.shadowRoot.querySelector(`th[data-sort="${target.dataset.sort}"]`)?.focus();
      return;
    }
    if (!target.matches("tr.row, tr.group")) return;
    const focusAgain = (selector) => this.shadowRoot.querySelector(selector)?.focus();
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const rows = [...this.shadowRoot.querySelectorAll("tbody tr.row, tbody tr.group")];
      const next = rows[rows.indexOf(target) + (ev.key === "ArrowDown" ? 1 : -1)];
      next?.focus();
      return;
    }
    if (target.matches("tr.group") && (ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault();
      const group = target.dataset.groupToggle;
      this._toggleGroup(group);
      focusAgain(`tr.group[data-group-toggle="${CSS.escape(group)}"]`);
      return;
    }
    const id = target.dataset.id;
    if (ev.key === " ") {
      ev.preventDefault();
      const st = this._st();
      if (st.selected.has(id)) st.selected.delete(id);
      else st.selected.add(id);
      this._render();
      focusAgain(`tr.row[data-id="${CSS.escape(id)}"]`);
    } else if (ev.key === "Enter" && VIEWS[this._view].expandable && target.querySelector("[data-expand]")) {
      ev.preventDefault();
      this._toggleExpanded(id);
      focusAgain(`tr.row[data-id="${CSS.escape(id)}"]`);
    }
  }

  // -- the last scan, in the header -------------------------------------

  async _refreshStatus() {
    if (!this._hass) return;
    try {
      const res = await this._hass.callWS({ type: SWS.STATUS });
      this._setStatus(res.status);
    } catch (_err) {
      // Not loaded (yet): nothing to show.
    }
  }

  _setStatus(status) {
    this._status = status;
    this._renderStatus();
  }

  _renderStatus() {
    const el = this._el("scan-status");
    const s = this._status;
    if (!s || !s.last_scan) {
      el.textContent = s ? "No scan yet" : "";
      return;
    }
    const sum = s.summary || {};
    const failed = (sum.sources || []).filter((src) => !src.ok);
    const parts = [`Last scan ${this._dayLabel(this._date(s.last_scan)).split(" · ")[0]} ${this._time(s.last_scan).slice(0, 5)}`];
    if (sum.new !== undefined) parts.push(`${sum.new} new`);
    if (sum.lines_scanned !== undefined) parts.push(`${num(sum.lines_scanned + (sum.previous_log_lines || 0))} lines`);
    el.textContent = parts.join(" · ");
    if (s.last_scan_ok === false || failed.length) {
      const warn = document.createElement("span");
      warn.className = "warn";
      warn.textContent = s.last_scan_ok === false
        ? " · ⚠ last scan failed"
        : ` · ⚠ ${failed.length} source${failed.length === 1 ? "" : "s"} unavailable`;
      el.appendChild(warn);
    }
    el.title = [
      `Last scan: ${this._dateTime(s.last_scan)}`,
      s.last_error ? `Failed: ${s.last_error}` : "",
      ...failed.map((src) => `${src.name}: unavailable${src.note ? ` (${src.note})` : ""}`),
      "Open Settings for the details",
    ].filter(Boolean).join("\n");
  }
}

// The first element under root, through shadow roots, matching test; at
// most a few thousand elements are looked at.
function deepFind(root, test, budget = { left: 5000 }) {
  if (!root) return null;
  const stack = [root];
  while (stack.length && budget.left-- > 0) {
    const el = stack.pop();
    if (el !== root && el.nodeType === 1 && test(el)) return el;
    if (el.shadowRoot) stack.push(el.shadowRoot);
    for (let child = el.lastElementChild; child; child = child.previousElementSibling) stack.push(child);
  }
  return null;
}
