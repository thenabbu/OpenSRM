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
  btn.disabled = true; btn.classList.add('spinning');
  document.getElementById('overlay').classList.add('show');
  fetch('/api/refresh', {method: 'POST'})
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) { location.reload(); return; }
      document.getElementById('overlay').classList.remove('show');
      btn.disabled = false; btn.classList.remove('spinning');
      alert(d.error || 'Refresh failed');
    }).catch(function () {
      document.getElementById('overlay').classList.remove('show');
      btn.disabled = false; btn.classList.remove('spinning');
      alert('Network error \u2014 refresh failed');
    });
}

function switchTab(name, btn) {
  document.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.tab-bar button').forEach(function(b) { b.classList.remove('active'); });
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
}
