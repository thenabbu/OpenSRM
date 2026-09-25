// Error toast helper (global — used by timetable.js too)
function showError(msg) {
  var t = document.getElementById('error-toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.remove('hidden');
  setTimeout(function() { t.classList.add('hidden'); }, 5000);
}

// ── Sync lines (navbar + dashboard card) ──────────────────────────
function renderSyncLines() {
  document.querySelectorAll('.sync-line').forEach(function(el) {
    var ts = parseInt(el.dataset.ts || '0', 10);
    if (!ts) { el.textContent = 'Never synced'; return; }
    var diff = Math.floor(Date.now() / 1000) - ts;
    var text;
    if (diff < 60) text = 'just now';
    else if (diff < 3600) text = Math.floor(diff / 60) + 'm ago';
    else if (diff < 86400) text = Math.floor(diff / 3600) + 'h ago';
    else text = Math.floor(diff / 86400) + 'd ago';
    el.textContent = 'Synced ' + text;
    el.title = el.dataset.full;
  });
}
renderSyncLines();

// ── Refresh (all data-refresh buttons) ────────────────────────────
function ref(quiet) {
  var btns = Array.prototype.slice.call(document.querySelectorAll('[data-refresh]'));
  var icons = document.querySelectorAll('.refresh-icon');
  btns.forEach(function(b) { b.disabled = true; });
  icons.forEach(function(i) { i.classList.add('animate-spin'); });
  document.querySelectorAll('.sync-line').forEach(function(el) { el.textContent = 'Syncing…'; });
  if (!quiet) document.getElementById('overlay').showModal();
  fetch('/api/refresh', {method: 'POST'})
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) { location.reload(); return; }
      document.getElementById('overlay').close();
      btns.forEach(function(b) { b.disabled = false; });
      icons.forEach(function(i) { i.classList.remove('animate-spin'); });
      renderSyncLines();
      if (!quiet) showError(d.error || 'Refresh failed');
      else console.debug('background sync failed:', d.error);
    }).catch(function () {
      document.getElementById('overlay').close();
      btns.forEach(function(b) { b.disabled = false; });
      icons.forEach(function(i) { i.classList.remove('animate-spin'); });
      renderSyncLines();
      if (!quiet) showError('Network error \u2014 is the server reachable?');
    });
}
document.querySelectorAll('[data-refresh]').forEach(function(b) {
  b.addEventListener('click', function() { ref(false); });
});

// ── Tabs (desktop navbar + mobile dock) ───────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll('[data-tabpanel]').forEach(function(p) {
    p.style.display = (p.id === 'tab-' + name) ? '' : 'none';
  });
  document.querySelectorAll('[data-tab]').forEach(function(b) {
    var on = (b === btn) || (b.dataset.tab === name && !btn);
    b.classList.toggle('tab-active', on);   // navbar buttons
    b.classList.toggle('dock-active', on);  // dock items
    b.classList.toggle('btn-active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
    if (b.hasAttribute('aria-current')) b.setAttribute('aria-current', on ? 'page' : 'false');
    b.tabIndex = on ? 0 : -1;
  });
  if (history.replaceState) history.replaceState(null, '', '#' + name);
  if (btn && btn.offsetParent) btn.focus();
}
var tabButtons = Array.prototype.slice.call(document.querySelectorAll('[data-tab]'));
tabButtons.forEach(function(b) {
  b.addEventListener('click', function() { switchTab(b.dataset.tab, b); });
  b.addEventListener('keydown', function(e) {
    // cycle within the visible nav set (navbar OR dock), not across both
    var vis = tabButtons.filter(function(x) { return x.offsetParent !== null; });
    var idx = vis.indexOf(b), next = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = vis[(idx + 1) % vis.length];
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = vis[(idx - 1 + vis.length) % vis.length];
    else if (e.key === 'Home') next = vis[0];
    else if (e.key === 'End') next = vis[vis.length - 1];
    if (next) { e.preventDefault(); switchTab(next.dataset.tab, next); }
  });
});
// Restore tab from hash (survives refresh/reload); default dashboard
(function() {
  var h = (location.hash || '').replace('#', '');
  var valid = document.getElementById('tab-' + h);
  switchTab(valid ? h : 'dashboard');
})();

// ── Copy email ────────────────────────────────────────────────────
var copyBtn = document.getElementById('copyEmail');
if (copyBtn) copyBtn.addEventListener('click', function() {
  var email = copyBtn.dataset.email || '';
  function done() {
    var span = copyBtn.querySelector('span');
    var old = span.textContent;
    span.textContent = 'Copied!';
    setTimeout(function() { span.textContent = old; }, 1200);
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(email).then(done).catch(function() { showError('Copy failed'); });
  } else { showError('Clipboard unavailable'); }
});

// ── Auto-sync on open: show cached data instantly, refresh quietly in
//    background when stale (>10min). Quiet failures stay silent.
(function() {
  var first = document.querySelector('.sync-line');
  if (!first) return;
  var ts = parseInt(first.dataset.ts || '0', 10);
  var stale = !ts || (Math.floor(Date.now() / 1000) - ts > 600);
  if (stale && navigator.onLine !== false) ref(true);
})();

window.addEventListener('offline', function() {
  var el = document.getElementById('offline-banner');
  el.className = 'alert alert-soft alert-warning fixed bottom-0 left-0 right-0 z-50 rounded-none';
  el.textContent = 'You are offline \u2014 showing cached data';
});
window.addEventListener('online', function() {
  var el = document.getElementById('offline-banner');
  el.className = '';
  el.textContent = '';
});
