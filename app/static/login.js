document.getElementById("f").onsubmit = function (ev) {
  ev.preventDefault();
  var btn = document.getElementById("b"), status = document.getElementById("status");
  btn.disabled = true;
  // loading class handled by loginSpinner
  document.getElementById("loginSpinner").classList.remove("hidden");
  document.getElementById("btnLabel").textContent = "Signing in\u2026";
  status.className = "text-center text-sm text-base-content/60";
  status.textContent = "Connecting to SRM portal\u2026";
  var wrap = document.getElementById("progressWrap"),
      bar = document.getElementById("progressBar"),
      f = this;
  wrap.classList.remove("hidden");
  bar.value = 3;
  var progTimer = setInterval(function () {
    fetch("/api/login/progress?netid=" + encodeURIComponent(f.netid.value.trim().toLowerCase()), {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.step) { status.textContent = d.step; bar.value = d.pct; }
      }).catch(function () {});
  }, 600);

  fetch("/api/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({netid: this.netid.value, password: this.pw.value})
  }).then(function (r) { return r.json(); }).then(function (d) {
    clearInterval(progTimer);
    if (d.ok) { location.href = "/"; return; }
    wrap.classList.add("hidden");
    status.className = "text-center text-sm text-error mt-2";
    status.textContent = d.error || "Login failed";
    btn.disabled = false;
    
    document.getElementById("loginSpinner").classList.add("hidden");
    document.getElementById("btnLabel").textContent = "Sign in";
  }).catch(function () {
    clearInterval(progTimer);
    wrap.classList.add("hidden");
    status.className = "text-center text-sm text-error mt-2";
    status.textContent = "Network error \u2014 is the server reachable?";
    btn.disabled = false;
    
    document.getElementById("loginSpinner").classList.add("hidden");
    document.getElementById("btnLabel").textContent = "Sign in";
  });
};

document.getElementById("pw-toggle").onclick = function() {
  var inp = document.getElementById("pw");
  var open = document.getElementById("pw-eye-open");
  var closed = document.getElementById("pw-eye-closed");
  if (inp.type === "password") {
    inp.type = "text";
    open.classList.add("hidden");
    closed.classList.remove("hidden");
  } else {
    inp.type = "password";
    open.classList.remove("hidden");
    closed.classList.add("hidden");
  }
};
