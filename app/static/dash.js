// Error toast helper (global — used by timetable.js too)
function showError(msg) {
  var t = document.getElementById('error-toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.remove('hidden');
  setTimeout(function() { t.classList.add('hidden'); }, 5000);
}

(function () {
  var el = document.getElementById('lastSync');
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
})();

function ref() {
  var btn = document.getElementById('refreshBtn');
  var icon = document.getElementById('refreshIcon');
  btn.disabled = true;
  icon.classList.add('animate-spin');
  document.getElementById('overlay').showModal();
  fetch('/api/refresh', {method: 'POST'})
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) { location.reload(); return; }
      document.getElementById('overlay').close();
      btn.disabled = false; icon.classList.remove('animate-spin');
      showError(d.error || 'Refresh failed');
    }).catch(function () {
      document.getElementById('overlay').close();
      btn.disabled = false; icon.classList.remove('animate-spin');
      showError('Network error \u2014 is the server reachable?');
    });
}

function switchTab(name, btn) {
  document.querySelectorAll('[data-tabpanel]').forEach(function(p) {
    p.style.display = (p.id === 'tab-' + name) ? '' : 'none';
  });
  document.querySelectorAll('[data-tab]').forEach(function(b) {
    var on = (b === btn) || (b.dataset.tab === name && !btn);
    b.classList.toggle('tab-active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
    b.tabIndex = on ? 0 : -1;
  });
  if (btn) btn.focus();
}
var tabButtons = Array.prototype.slice.call(document.querySelectorAll('[data-tab]'));
tabButtons.forEach(function(b) {
  b.addEventListener('click', function() { switchTab(b.dataset.tab, b); });
  b.addEventListener('keydown', function(e) {
    var idx = tabButtons.indexOf(b), next = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = tabButtons[(idx + 1) % tabButtons.length];
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = tabButtons[(idx - 1 + tabButtons.length) % tabButtons.length];
    else if (e.key === 'Home') next = tabButtons[0];
    else if (e.key === 'End') next = tabButtons[tabButtons.length - 1];
    if (next) { e.preventDefault(); switchTab(next.dataset.tab, next); }
  });
});

document.getElementById('refreshBtn').addEventListener('click', ref);

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
