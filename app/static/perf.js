/**
 * Perf tier detection (phase 6) — runs as a BLOCKING script at the top of
 * <head> so html[data-perf] is set before the first paint and the low-tier
 * CSS pause rules (app.css) apply from frame one. Inline scripts are banned
 * by the CSP, hence an external file loaded via asset().
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
