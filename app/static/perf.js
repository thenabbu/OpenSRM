/**
 * Perf tier detection (phase 6) — runs as a BLOCKING script in <head> so
 * html[data-perf] is set before the first paint. Inline scripts are banned by
 * the CSP, hence an external file loaded via asset().
 *
 * What the tier actually drives, as of W5.4 (this list used to name app.css and
 * dash.js; both claims had drifted):
 *  - `html[data-perf="low"] .mo-root *` in src.css pauses every avatar loop
 *    (authored in src.css, shipped inside the built app.css);
 *  - `web/src/data/background.ts` toggles `.is-offscreen` on the same subtree,
 *    which pauses it too — no longer dash.js, which is deleted;
 *  - `app/static/gaze.js` returns early on the low tier, so no pointer driver
 *    is installed at all.
 * Override for testing: ?perf=low or ?perf=high (persisted in localStorage).
 */
(function () {
  var d = document.documentElement, n = navigator, forced = null;
  try { forced = new URLSearchParams(location.search).get('perf') || localStorage.getItem('perf'); } catch (e) {}
  var low = (n.deviceMemory && n.deviceMemory <= 3) ||
            (n.hardwareConcurrency && n.hardwareConcurrency <= 4) ||
            (n.connection && n.connection.saveData);
  d.dataset.perf = forced === 'low' || forced === 'high' ? forced : (low ? 'low' : 'high');
})();
