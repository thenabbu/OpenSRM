document.getElementById('f').onsubmit = function (ev) {
  ev.preventDefault();
  var btn = document.getElementById('b'), status = document.getElementById('status');
  btn.disabled = true; btn.classList.add('loading');
  document.getElementById('btnLabel').textContent = 'Signing in\u2026';
  status.className = 'status'; status.textContent = 'Logging in and reading attendance\u2026';
  fetch('/api/login', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({netid: this.netid.value, password: this.pw.value})
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) { location.href = '/'; return; }
    status.className = 'status err'; status.textContent = d.error || 'Login failed';
    btn.disabled = false; btn.classList.remove('loading');
    document.getElementById('btnLabel').textContent = 'Sign in';
  }).catch(function () {
    status.className = 'status err'; status.textContent = 'Network error \u2014 is the server reachable?';
    btn.disabled = false; btn.classList.remove('loading');
    document.getElementById('btnLabel').textContent = 'Sign in';
  });
};
