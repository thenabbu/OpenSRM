document.getElementById('f').onsubmit = function (ev) {
  ev.preventDefault();
  var btn = document.getElementById('b'), status = document.getElementById('status');
  btn.disabled = true;
  document.getElementById('loginSpinner').classList.remove('hidden');
  document.getElementById('btnLabel').textContent = 'Signing in\u2026';
  status.className = 'text-center text-sm text-base-content/60'; status.textContent = 'Logging in and reading attendance\u2026';
  fetch('/api/login', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({netid: this.netid.value, password: this.pw.value})
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.ok) { location.href = '/'; return; }
    status.className = 'text-center text-sm text-error'; status.textContent = d.error || 'Login failed';
    btn.disabled = false; document.getElementById('loginSpinner').classList.add('hidden');
    document.getElementById('btnLabel').textContent = 'Sign in';
  }).catch(function () {
    status.className = 'text-center text-sm text-error'; status.textContent = 'Network error \u2014 is the server reachable?';
    btn.disabled = false; document.getElementById('loginSpinner').classList.add('hidden');
    document.getElementById('btnLabel').textContent = 'Sign in';
  });
};

document.getElementById('pw-toggle').onclick = function() {
  var inp = document.getElementById('pw');
  inp.type = inp.type === 'password' ? 'text' : 'password';
  this.textContent = inp.type === 'password' ? '\u25c9' : '\u25cb';
};
