// WP Log Doctor - sidebar panel.
//
// Web components with no build step and no external libraries, in a few
// modules loaded by this one (each with this file's ?v= version, so a new
// release is never mixed with a cached old module):
//
//   ld-util.js      shared constants and helpers
//   ld-views.js     the list views: what each lists and how
//   ld-style.js     the main page's styles and markup
//   ld-panel.js     <log-doctor-panel>: view buttons, lists, actions
//   ld-insights.js  <log-doctor-insights>: the Insights page
//   ld-settings.js  <log-doctor-settings>: the Settings page
//
// The pages, in this order. Seven are reviewable lists with Open and
// Archived tabs:
//
//   #logs      Log review - the anomalies the daily scans reported
//   #restarts  Startup & shutdown - the anomalies logged only while Home
//              Assistant was starting or shutting down (the same list as
//              the Log review, split by each entry's category)
//   #failures  Automations: Failures - failed automation and script runs,
//              and scheduled runs missed while Home Assistant was offline
//   #runs      Automations: Runs - every automation run, when and what
//              triggered it (the Automations button covers both, with a
//              switch between them at the top of the page)
//   #health    Devices & integrations - offline devices, unavailable
//              entities, integrations that failed to load, and Repairs
//              issues
//   #backups   Backups - backup problems and successes, from Home
//              Assistant's own backup and the GDrive Backup Utility add-on
//              (left out of the Log review)
//   #reboots   Restart history - each Home Assistant restart's shutdown and
//              startup times: the windows Startup & shutdown goes by
//
// then #insights - warnings and errors over time, and a preview of the
// weekly digest with the noisiest integrations - and #settings, all of WP
// Log Doctor's settings.
//
// Each list is subscribed to once over the WebSocket (log_doctor/review/*)
// and comes back in full after every change (or, for automation runs, just
// the runs added and removed), so new entries appear live. Entries can be
// sorted, filtered, selected (with the keyboard too), exported and
// archived, which moves them to Archived; archived ones can be restored or
// deleted for good. Log review, Startup & shutdown, Devices & integrations
// and Backups entries can also be ignored, which moves them to Ignored,
// where they're kept up to date without coming back by themselves; devices
// and automations can be left unmonitored. Each action can be undone for a
// few seconds. Each view's search, filters, tab and sort are remembered in
// the browser.
//
// The page itself doesn't scroll: the view buttons, tabs, toolbar and
// column headings stay put and only the list scrolls (unless the window is
// too short for that, e.g. a phone held sideways).

const V = new URL(import.meta.url).search;
const [{ LogDoctorPanel }, { LogDoctorInsights }, { LogDoctorSettings }] = await Promise.all([
  import(`./ld-panel.js${V}`),
  import(`./ld-insights.js${V}`),
  import(`./ld-settings.js${V}`),
]);

for (const [name, element] of [
  ["log-doctor-settings", LogDoctorSettings],
  ["log-doctor-insights", LogDoctorInsights],
  ["log-doctor-panel", LogDoctorPanel],
]) {
  if (!customElements.get(name)) customElements.define(name, element);
}
