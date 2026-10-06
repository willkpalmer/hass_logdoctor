// WP Log Doctor panel - the Insights page, <log-doctor-insights> (see
// log-doctor-panel.js for how the modules fit together):
//
// - warnings and errors logged per hour (24 hours, 7 days) or per day (30
//   days), as stacked columns, from the counts each scan keeps (stats.py),
//   with a table view;
// - a preview of the weekly digest (weekly_digest.py): the week at a
//   glance, the noisiest integrations against the week before, and what's
//   new - with buttons to send it now or save it as Markdown.

const V = new URL(import.meta.url).search;
const { SWS, downloadFile, num } = await import(`./ld-util.js${V}`);

const RANGES = [["24h", "24 hours"], ["7d", "7 days"], ["30d", "30 days"]];
const RANGE_KEY = "log_doctor.insights_range";
const WEEKDAY_NAMES = {
  mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday",
};
const HEALTH_NAMES = {
  offline: "offline", unavailable: "with unavailable entities", flapping: "flapping",
  integration: "integrations failing", repair: "Repairs",
};

const STYLE = `
:host {
  display: block;
  /* Status colours for the chart, checked for colour-blind separation and
     contrast on light and dark surfaces. */
  --ld-errors: #c5221f; --ld-warnings: #d99a00;
}
:host([dark]) { --ld-errors: #c8403a; --ld-warnings: #b88400; }
:host([hidden]) { display: none; }
* { box-sizing: border-box; }
.card {
  background: var(--card-background-color, #fff);
  border-radius: var(--ha-card-border-radius, 12px);
  border: 1px solid var(--divider-color, #e0e0e0);
  margin-bottom: 12px; padding: 14px 16px 16px;
}
.card-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; margin-bottom: 8px; }
h2 { font-size: 16px; font-weight: 500; margin: 0; flex: 1 1 auto; }
h3 { font-size: 14px; font-weight: 500; margin: 16px 0 6px; }
.sub { color: var(--secondary-text-color, #727272); font-size: 13px; }
.segmented { display: inline-flex; border: 1px solid var(--divider-color, #ccc); border-radius: 8px; overflow: hidden; }
.segmented button {
  font: inherit; font-size: 13px; padding: 6px 12px; border: 0; cursor: pointer;
  background: transparent; color: var(--primary-text-color, #212121);
}
.segmented button + button { border-left: 1px solid var(--divider-color, #ccc); }
.segmented button[aria-pressed="true"] { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
button.link {
  font: inherit; font-size: 13px; border: 0; background: none; padding: 4px 0; cursor: pointer; color: var(--primary-color, #03a9f4);
}
button.action {
  font: inherit; font-weight: 500; padding: 8px 14px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--primary-color, #03a9f4); background: var(--primary-color, #03a9f4);
  color: var(--text-primary-color, #fff);
}
button.action.secondary { background: transparent; color: var(--primary-color, #03a9f4); }
button.action:disabled { opacity: 0.5; cursor: default; }
.legend { display: flex; gap: 16px; font-size: 13px; color: var(--secondary-text-color, #727272); margin: 4px 0 8px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.chart { position: relative; width: 100%; }
.chart svg { display: block; width: 100%; overflow: visible; }
.chart svg:focus { outline: none; }
.chart svg:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 4px; border-radius: 4px; }
.grid line { stroke: var(--divider-color, #e0e0e0); stroke-width: 1; }
.axis text { fill: var(--secondary-text-color, #727272); font-size: 11px; font-variant-numeric: tabular-nums; }
.hover-band { fill: var(--primary-text-color, #000); opacity: 0.06; }
.tooltip {
  position: absolute; pointer-events: none; z-index: 2; min-width: 150px;
  background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121);
  border: 1px solid var(--divider-color, #e0e0e0); border-radius: 8px; padding: 8px 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15); font-size: 13px;
}
.tooltip[hidden] { display: none; }
.tooltip .t { font-weight: 500; margin-bottom: 4px; }
.tooltip .r { display: flex; align-items: center; gap: 6px; justify-content: space-between; }
.tooltip .r span:first-child { display: inline-flex; align-items: center; gap: 6px; }
.empty { padding: 32px 8px; text-align: center; color: var(--secondary-text-color, #727272); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 6px 8px; border-top: 1px solid var(--divider-color, #e0e0e0); vertical-align: middle; }
th { font-weight: 500; color: var(--secondary-text-color, #727272); white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.table-scroll { max-height: 320px; overflow: auto; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; margin: 8px 0 4px; }
.tile { border: 1px solid var(--divider-color, #e0e0e0); border-radius: 10px; padding: 10px 12px; }
.tile .label { font-size: 12px; color: var(--secondary-text-color, #727272); }
.tile .value { font-size: 22px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
.tile .delta { font-size: 12px; margin-top: 2px; color: var(--secondary-text-color, #727272); }
.delta.worse { color: var(--error-color, #db4437); }
.delta.better { color: var(--success-color, #43a047); }
.bar-cell { width: 30%; min-width: 80px; }
.bar { height: 8px; border-radius: 0 4px 4px 0; background: var(--primary-color, #03a9f4); opacity: 0.7; }
.kind { font-size: 11px; color: var(--secondary-text-color, #727272); margin-left: 6px; }
ul { margin: 4px 0; padding-left: 20px; }
li { margin: 2px 0; }
.level { font-size: 11px; font-weight: 600; letter-spacing: 0.3px; margin-right: 4px; }
.level.ERROR, .level.CRITICAL { color: var(--error-color, #db4437); }
.level.WARNING { color: var(--warning-color, #e68a00); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 16px; }
.actions .msg { flex: 1 1 200px; color: var(--secondary-text-color, #727272); font-size: 13px; }
.msg.ok { color: var(--success-color, #43a047); }
.msg.error { color: var(--error-color, #db4437); }
.columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 0 24px; }
@media (max-width: 700px) {
  .card { padding: 12px; }
  .bar-cell { display: none; }
}
`;

export class LogDoctorInsights extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._data = null;
    this._range = "7d";
    try { this._range = localStorage.getItem(RANGE_KEY) || "7d"; } catch (_err) { /* default */ }
    if (!RANGES.some(([key]) => key === this._range)) this._range = "7d";
    this._table = false;
    this._hover = null;
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><div class="empty">Loading…</div>`;
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this._resize = new ResizeObserver(() => this._drawChart());
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this.toggleAttribute("dark", !!hass?.themes?.darkMode);
    // Opened on this page before Home Assistant was connected.
    if (first && hass && !this.hidden) this.activate();
  }

  connectedCallback() {
    this._resize.observe(this);
  }

  disconnectedCallback() {
    this._resize.disconnect();
  }

  // Called whenever the page is shown.
  activate() {
    this._load();
  }

  async _load() {
    if (!this._hass) return;
    try {
      this._data = await this._hass.callWS({ type: SWS.INSIGHTS, range: this._range });
      this._error = null;
    } catch (err) {
      this._error = `Couldn't load Insights: ${err.message || err.code || err}`;
    }
    this._build();
  }

  // -- formatting -------------------------------------------------------

  _fmt(iso, opts) {
    const d = new Date(iso);
    if (!iso || Number.isNaN(d.getTime())) return "";
    try {
      return new Intl.DateTimeFormat(undefined, { ...opts, timeZone: this._hass?.config?.time_zone }).format(d);
    } catch (_err) {
      return new Intl.DateTimeFormat(undefined, opts).format(d);
    }
  }

  _when(iso) {
    return this._fmt(iso, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  }

  // -- building -----------------------------------------------------------

  _build() {
    const root = this.shadowRoot;
    root.replaceChildren();
    const style = document.createElement("style");
    style.textContent = STYLE;
    root.appendChild(style);
    if (this._error || !this._data) {
      root.appendChild(this._div("empty", this._error || "Loading…"));
      return;
    }
    root.append(this._chartCard(), this._digestCard());
    this._drawChart();
  }

  _div(cls, text) {
    const div = document.createElement("div");
    if (cls) div.className = cls;
    if (text !== undefined) div.textContent = text;
    return div;
  }

  _el(tag, text, cls) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }

  _chartCard() {
    const card = this._div("card");
    const head = this._div("card-head");
    head.appendChild(this._el("h2", "Warnings and errors logged"));
    const seg = this._div("segmented");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "Time range");
    for (const [key, label] of RANGES) {
      const b = this._el("button", label);
      b.dataset.range = key;
      b.setAttribute("aria-pressed", String(key === this._range));
      seg.appendChild(b);
    }
    const tableBtn = this._el("button", this._table ? "Show as chart" : "Show as table", "link");
    tableBtn.dataset.act = "table";
    head.append(seg, tableBtn);
    card.appendChild(head);
    const series = this._data.series || [];
    const total = series.reduce((sum, p) => sum + p.WARNING + p.ERROR + p.CRITICAL, 0);
    const errors = series.reduce((sum, p) => sum + p.ERROR + p.CRITICAL, 0);
    card.appendChild(this._div("sub",
      `${num(errors)} error${errors === 1 ? "" : "s"} and ${num(total - errors)} warning${total - errors === 1 ? "" : "s"} ` +
      `over the last ${RANGES.find(([k]) => k === this._range)[1]}, by when they were logged. Counted by each scan from WP Log Doctor 0.40.0, whatever the minimum severity setting.`));
    if (!total) {
      card.appendChild(this._div("empty", "Nothing logged in this time. Counts appear after the next scan."));
      return card;
    }
    if (this._table) {
      card.appendChild(this._seriesTable(series));
      return card;
    }
    const legend = this._div("legend");
    for (const [label, color] of [["Errors (incl. critical)", "var(--ld-errors)"], ["Warnings", "var(--ld-warnings)"]]) {
      const item = document.createElement("span");
      const sw = this._el("span", undefined, "swatch");
      sw.style.background = color;
      item.append(sw, label);
      legend.appendChild(item);
    }
    card.appendChild(legend);
    const chart = this._div("chart");
    chart.dataset.el = "chart";
    const tip = this._div("tooltip");
    tip.hidden = true;
    tip.dataset.el = "tip";
    chart.appendChild(tip);
    card.appendChild(chart);
    return card;
  }

  _label(point, long = false) {
    const hourly = this._data.bucket === "hour";
    if (!hourly) return this._fmt(point.t, { weekday: long ? "long" : "short", day: "numeric", month: "short" });
    const start = this._fmt(point.t, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
    const end = this._fmt(new Date(new Date(point.t).getTime() + 3600000).toISOString(), { hour: "2-digit", minute: "2-digit", hour12: false });
    return `${start}–${end}`;
  }

  _seriesTable(series) {
    const wrap = this._div("table-scroll");
    const table = document.createElement("table");
    const head = document.createElement("tr");
    for (const [label, cls] of [[this._data.bucket === "hour" ? "Hour" : "Day", ""], ["Errors", "num"], ["Warnings", "num"]]) {
      head.appendChild(this._el("th", label, cls));
    }
    table.appendChild(head);
    for (const p of [...series].reverse()) {
      if (!(p.WARNING + p.ERROR + p.CRITICAL)) continue;
      const tr = document.createElement("tr");
      tr.append(this._el("td", this._label(p)), this._el("td", num(p.ERROR + p.CRITICAL), "num"), this._el("td", num(p.WARNING), "num"));
      table.appendChild(tr);
    }
    wrap.appendChild(table);
    return wrap;
  }

  // Stacked columns: errors from the baseline, warnings on top, a 2px gap
  // between them in the surface colour, rounded only at the data end.
  _drawChart() {
    const chart = this.shadowRoot.querySelector('[data-el="chart"]');
    if (!chart || !this._data) return;
    const series = this._data.series || [];
    const width = chart.clientWidth;
    if (!width) return;
    const height = 220;
    const pad = { top: 8, right: 4, bottom: 24, left: 40 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const max = Math.max(1, ...series.map((p) => p.WARNING + p.ERROR + p.CRITICAL));
    const step = niceStep(max / 4);
    const top = Math.ceil(max / step) * step;
    const y = (v) => pad.top + plotH - (v / top) * plotH;
    const band = plotW / series.length;
    const gap = band >= 6 ? 2 : 1;
    const barW = Math.max(1, Math.min(24, band - gap));
    const radius = barW >= 8 ? 4 : barW >= 4 ? 1.5 : 0;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("height", String(height));
    svg.setAttribute("tabindex", "0");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Warnings and errors logged over time; use the arrow keys to read each column, or Show as table");
    const add = (parent, tag, attrs) => {
      const el = document.createElementNS(ns, tag);
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
      parent.appendChild(el);
      return el;
    };
    // Grid and y axis.
    const grid = add(svg, "g", { class: "grid" });
    const axis = add(svg, "g", { class: "axis" });
    for (let v = 0; v <= top; v += step) {
      add(grid, "line", { x1: pad.left, x2: width - pad.right, y1: y(v), y2: y(v) });
      const t = add(axis, "text", { x: pad.left - 6, y: y(v) + 4, "text-anchor": "end" });
      t.textContent = num(v);
    }
    // X labels: at day boundaries for hours, every few days for days.
    const hourly = this._data.bucket === "hour";
    let lastLabelX = -Infinity;
    series.forEach((p, i) => {
      const x = pad.left + band * i + band / 2;
      let text = null;
      if (hourly) {
        const hour = Number(this._fmt(p.t, { hour: "2-digit", hour12: false }));
        if (series.length <= 24 ? hour % 6 === 0 : hour === 0) {
          text = series.length <= 24
            ? this._fmt(p.t, { hour: "2-digit", minute: "2-digit", hour12: false })
            : this._fmt(p.t, { weekday: "short", day: "numeric" });
        }
      } else if ((series.length - 1 - i) % 5 === 0) {
        text = this._fmt(p.t, { day: "numeric", month: "short" });
      }
      if (text && x - lastLabelX > 48) {
        const t = add(axis, "text", { x, y: height - 6, "text-anchor": "middle" });
        t.textContent = text;
        lastLabelX = x;
      }
    });
    const hover = add(svg, "rect", { class: "hover-band", x: 0, y: pad.top, width: band, height: plotH, visibility: "hidden" });
    // Columns.
    const bars = add(svg, "g", {});
    series.forEach((p, i) => {
      const errors = p.ERROR + p.CRITICAL;
      const warnings = p.WARNING;
      if (!errors && !warnings) return;
      const x = pad.left + band * i + (band - barW) / 2;
      const base = y(0);
      const errTop = y(errors);
      const segGap = errors && warnings ? Math.min(2, (base - y(warnings + errors)) / 4) : 0;
      if (errors) {
        add(bars, "path", { d: column(x, errTop, barW, base - errTop, warnings ? 0 : radius), fill: "var(--ld-errors)" });
      }
      if (warnings) {
        const wTop = y(errors + warnings);
        const wBottom = errors ? errTop - segGap : base;
        add(bars, "path", { d: column(x, wTop, barW, Math.max(0.5, wBottom - wTop), radius), fill: "var(--ld-warnings)" });
      }
    });
    // Hover and keyboard: one column at a time, with a tooltip.
    const tip = chart.querySelector('[data-el="tip"]');
    const show = (i) => {
      if (i === null || i < 0 || i >= series.length) {
        hover.setAttribute("visibility", "hidden");
        tip.hidden = true;
        this._hover = null;
        return;
      }
      this._hover = i;
      const p = series[i];
      hover.setAttribute("x", String(pad.left + band * i));
      hover.setAttribute("visibility", "visible");
      tip.replaceChildren(this._div("t", this._label(p, true)));
      for (const [label, value, color] of [["Errors", p.ERROR + p.CRITICAL, "var(--ld-errors)"], ["Warnings", p.WARNING, "var(--ld-warnings)"]]) {
        const row = this._div("r");
        const name = document.createElement("span");
        const sw = this._el("span", undefined, "swatch");
        sw.style.background = color;
        name.append(sw, label);
        row.append(name, this._el("span", num(value)));
        tip.appendChild(row);
      }
      tip.hidden = false;
      const x = pad.left + band * i + band / 2;
      const left = Math.min(Math.max(0, x + 12), width - tip.offsetWidth);
      tip.style.left = `${x + 12 + tip.offsetWidth > width ? Math.max(0, x - 12 - tip.offsetWidth) : left}px`;
      tip.style.top = `${pad.top}px`;
    };
    const indexAt = (ev) => {
      const rect = svg.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * width;
      return Math.floor((x - pad.left) / band);
    };
    svg.addEventListener("pointermove", (ev) => show(indexAt(ev)));
    svg.addEventListener("pointerleave", () => show(null));
    svg.addEventListener("blur", () => show(null));
    svg.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      ev.preventDefault();
      const from = this._hover ?? (ev.key === "ArrowLeft" ? series.length : -1);
      show(Math.min(series.length - 1, Math.max(0, from + (ev.key === "ArrowRight" ? 1 : -1))));
    });
    chart.querySelector("svg")?.remove();
    chart.insertBefore(svg, tip);
  }

  _digestCard() {
    const { digest, weekly } = this._data;
    const data = digest.data;
    const card = this._div("card");
    const head = this._div("card-head");
    head.appendChild(this._el("h2", "Weekly digest"));
    card.appendChild(head);
    card.appendChild(this._div("sub",
      `The last 7 days (${this._fmt(data.start, { day: "numeric", month: "short" })} – ${this._fmt(data.end, { day: "numeric", month: "short" })}). ` +
      (weekly.enabled
        ? `Sent every ${WEEKDAY_NAMES[weekly.day] || weekly.day} after the daily scan.`
        : "Not sent automatically - turn it on in Settings.") +
      (weekly.last_sent ? ` Last sent ${this._when(weekly.last_sent)}.` : "")));

    // At a glance.
    const levels = data.levels || { this: {}, previous: {} };
    const errors = (levels.this.ERROR || 0) + (levels.this.CRITICAL || 0);
    const errorsBefore = (levels.previous.ERROR || 0) + (levels.previous.CRITICAL || 0);
    const openHealth = Object.values(data.health.open || {}).reduce((a, b) => a + b, 0);
    const autos = data.automations;
    const tiles = this._div("tiles");
    const tile = (label, value, delta) => {
      const t = this._div("tile");
      t.append(this._div("label", label), this._div("value", value));
      if (delta) t.appendChild(delta);
      tiles.appendChild(t);
    };
    tile("New anomalies", num(data.logs.new), this._div("delta", `${num(data.logs.open)} open on the Log review`));
    tile("Errors logged", num(errors), this._delta(errors, errorsBefore));
    tile("Warnings logged", num(levels.this.WARNING || 0), this._delta(levels.this.WARNING || 0, levels.previous.WARNING || 0));
    tile("Automation failures", num(autos.failed), this._div("delta", `${num(autos.missed)} missed · ${num(autos.stopped)} stopped`));
    tile("Device & integration problems", num(openHealth), this._div("delta", `${num(data.health.cleared)} cleared by themselves`));
    tile("Restarts", num(data.restarts.count), this._div("delta", data.restarts.unclean ? `${num(data.restarts.unclean)} not clean` : "all clean"));
    tile("Last successful backup", data.backups.last_success ? this._fmt(data.backups.last_success, { day: "numeric", month: "short" }) : "—",
      this._div("delta", data.backups.problems ? `${num(data.backups.problems)} problem${data.backups.problems === 1 ? "" : "s"} this week` : "no problems this week"));
    card.appendChild(tiles);

    // The noisiest integrations.
    card.appendChild(this._el("h3", "Noisiest integrations"));
    card.appendChild(this._div("sub", "What logged the most errors and warnings this week: integrations, add-ons and other sources, with the week before."));
    if (data.noise.length) {
      const wrap = this._div("table-scroll");
      const table = document.createElement("table");
      const head2 = document.createElement("tr");
      for (const [label, cls] of [["#", "num"], ["Source", ""], ["Errors", "num"], ["Warnings", "num"], ["Total", "num"], ["", "bar-cell"], ["Week before", "num"]]) {
        head2.appendChild(this._el("th", label, cls));
      }
      table.appendChild(head2);
      const most = Math.max(...data.noise.map((r) => r.total));
      data.noise.forEach((row, i) => {
        const tr = document.createElement("tr");
        const name = document.createElement("td");
        if (row.kind === "integration") {
          const a = document.createElement("a");
          a.href = `/config/integrations/integration/${encodeURIComponent(row.source)}`;
          a.dataset.nav = "1";
          a.textContent = row.name;
          a.style.color = "var(--primary-color, #03a9f4)";
          a.style.textDecoration = "none";
          name.appendChild(a);
        } else {
          name.append(row.name, this._el("span", row.kind === "source" ? "Supervisor source" : "logger", "kind"));
        }
        const barCell = this._el("td", undefined, "bar-cell");
        const bar = this._div("bar");
        bar.style.width = `${Math.max(2, (row.total / most) * 100)}%`;
        barCell.appendChild(bar);
        const before = this._el("td", num(row.previous_total), "num");
        const change = this._delta(row.total, row.previous_total, true);
        if (change) before.append(" ", change);
        tr.append(
          this._el("td", String(i + 1), "num"), name,
          this._el("td", num(row.ERROR + row.CRITICAL), "num"), this._el("td", num(row.WARNING), "num"),
          this._el("td", num(row.total), "num"), barCell, before,
        );
        table.appendChild(tr);
      });
      wrap.appendChild(table);
      card.appendChild(wrap);
    } else {
      card.appendChild(this._div("sub", "No warnings or errors logged this week. 🎉"));
    }

    const columns = this._div("columns");
    // New in the log.
    const logCol = this._div();
    logCol.appendChild(this._el("h3", "New in the log"));
    if (data.logs.top.length) {
      const ul = document.createElement("ul");
      for (const r of data.logs.top) {
        const li = document.createElement("li");
        li.append(this._el("span", r.level, `level ${r.level}`), `× ${num(r.count)} `, this._el("code", r.logger), ` - ${(r.message || "").slice(0, 140)}`);
        ul.appendChild(li);
      }
      if (data.logs.new > data.logs.top.length) ul.appendChild(this._el("li", `… and ${num(data.logs.new - data.logs.top.length)} more on the Log review`));
      logCol.appendChild(ul);
    } else {
      logCol.appendChild(this._div("sub", "Nothing new."));
    }
    if (data.logs.new_restart) logCol.appendChild(this._div("sub", `Plus ${num(data.logs.new_restart)} new startup or shutdown message${data.logs.new_restart === 1 ? "" : "s"}.`));
    columns.appendChild(logCol);

    // Automations.
    const autoCol = this._div();
    autoCol.appendChild(this._el("h3", "Automations"));
    autoCol.appendChild(this._div("sub", `${num(autos.runs)} run${autos.runs === 1 ? "" : "s"} recorded.`));
    const list = (title, items) => {
      if (!items.length) return;
      autoCol.appendChild(this._div("sub", title));
      const ul = document.createElement("ul");
      for (const text of items) ul.appendChild(this._el("li", text));
      autoCol.appendChild(ul);
    };
    list("Failing most:", autos.top_failing.map((a) => `${a.name} × ${num(a.count)}`));
    list("Stopped running:", autos.stopped_names.map(String));
    list("Ran most:", autos.busiest.slice(0, 3).map((a) => `${a.name} × ${num(a.count)}`));
    columns.appendChild(autoCol);

    // Devices and restarts.
    const devCol = this._div();
    devCol.appendChild(this._el("h3", "Devices & restarts"));
    const open = Object.entries(data.health.open || {});
    devCol.appendChild(this._div("sub", open.length
      ? `Open: ${open.map(([kind, count]) => `${num(count)} ${HEALTH_NAMES[kind] || kind}`).join(", ")}.`
      : "No open device or integration problems."));
    if (data.health.flapping.length) {
      const ul = document.createElement("ul");
      for (const f of data.health.flapping) ul.appendChild(this._el("li", `${f.name} - ${f.detail}`));
      devCol.appendChild(this._div("sub", "Flapping:"));
      devCol.appendChild(ul);
    }
    const r = data.restarts;
    devCol.appendChild(this._div("sub", r.count
      ? `${num(r.count)} restart${r.count === 1 ? "" : "s"}: startup took ${seconds(r.average_startup)} on average, the slowest ${seconds(r.slowest_startup)}. ${num(r.messages)} message${r.messages === 1 ? "" : "s"} logged while starting or stopping.`
      : "No restarts."));
    columns.appendChild(devCol);
    card.appendChild(columns);

    // Send it, or keep it.
    const actions = this._div("actions");
    const send = this._el("button", "Send digest now", "action");
    send.dataset.act = "send";
    const copy = this._el("button", "Copy as Markdown", "action secondary");
    copy.dataset.act = "copy";
    const save = this._el("button", "Download .md", "action secondary");
    save.dataset.act = "download";
    const msg = this._el("span", "", "msg");
    msg.dataset.el = "msg";
    actions.append(send, copy, save, msg);
    card.appendChild(actions);
    return card;
  }

  // "+12% on the week before", coloured: more errors is worse.
  _delta(now, before, short = false) {
    const el = this._el("span", undefined, "delta");
    if (!before) {
      if (!now || short) return short ? null : el;
      el.textContent = "none the week before";
      el.classList.add("worse");
      return el;
    }
    const pct = Math.round(((now - before) * 100) / before);
    el.textContent = short ? `(${pct > 0 ? "+" : ""}${pct}%)` : `${pct > 0 ? "+" : ""}${pct}% on the week before`;
    if (pct > 0) el.classList.add("worse");
    if (pct < 0) el.classList.add("better");
    return el;
  }

  _message(text, kind = "") {
    const el = this.shadowRoot.querySelector('[data-el="msg"]');
    if (!el) return;
    el.textContent = text;
    el.className = `msg ${kind}`;
  }

  async _onClick(ev) {
    const path = ev.composedPath();
    const find = (key) => path.find((el) => el.dataset && el.dataset[key] !== undefined);
    const range = find("range");
    if (range) {
      this._range = range.dataset.range;
      try { localStorage.setItem(RANGE_KEY, this._range); } catch (_err) { /* not remembered */ }
      this._load();
      return;
    }
    const nav = find("nav");
    if (nav) {
      ev.preventDefault();
      history.pushState(null, "", nav.getAttribute("href"));
      window.dispatchEvent(new CustomEvent("location-changed"));
      return;
    }
    const act = find("act");
    if (!act || act.disabled) return;
    const markdown = this._data?.digest?.markdown || "";
    switch (act.dataset.act) {
      case "table":
        this._table = !this._table;
        this._build();
        break;
      case "send":
        act.disabled = true;
        this._message("Sending…");
        try {
          const res = await this._hass.callWS({ type: SWS.SEND_DIGEST });
          this._data.weekly.last_sent = res.last_sent;
          this._message("Sent - see your notifications.", "ok");
        } catch (err) {
          this._message(`Couldn't send it: ${err.message || err.code || err}`, "error");
        } finally {
          act.disabled = false;
        }
        break;
      case "copy":
        try {
          await navigator.clipboard.writeText(markdown);
          this._message("Copied.", "ok");
        } catch (_err) {
          window.prompt("Copy the digest (Ctrl+C / ⌘C):", markdown);
        }
        break;
      case "download":
        downloadFile(`log-doctor-weekly-digest-${this._fmt(new Date().toISOString(), { year: "numeric", month: "2-digit", day: "2-digit" }).replace(/\//g, "-")}.md`, markdown, "text/markdown;charset=utf-8");
        break;
      default:
        break;
    }
  }
}

// A rounded-top column (square at the baseline).
function column(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  if (r <= 0) return `M${x},${y}h${w}v${h}h${-w}Z`;
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

// 1, 2, 5, 10, 20, 50, ... at least `raw`.
function niceStep(raw) {
  if (raw <= 1) return 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 5, 10]) if (m * power >= raw) return m * power;
  return 10 * power;
}

function seconds(value) {
  if (value === null || value === undefined) return "—";
  const m = Math.floor(value / 60);
  const s = Math.round(value % 60);
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}
