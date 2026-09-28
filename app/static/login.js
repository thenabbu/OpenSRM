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
  var done = false;
  var progTimer = setInterval(function () {
    if (done) return;
    fetch("/api/login/progress", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({netid: f.netid.value.trim().toLowerCase()}), cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!done && d.step) { status.textContent = d.step; bar.value = d.pct; }
      }).catch(function () {});
  }, 600);

  fetch("/api/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({netid: this.netid.value, password: this.pw.value})
  }).then(function (r) { return r.json(); }).then(function (d) {
    done = true;
    clearInterval(progTimer);
    if (d.ok) { location.href = "/"; return; }
    wrap.classList.add("hidden");
    status.className = "text-center text-sm text-error";
    status.textContent = d.error || "Login failed";
    document.getElementById("pw").value = "";  // keep the identifier, clear only the password
    btn.disabled = false;
    
    document.getElementById("loginSpinner").classList.add("hidden");
    document.getElementById("btnLabel").textContent = "Sign in";
  }).catch(function () {
    done = true;
    clearInterval(progTimer);
    wrap.classList.add("hidden");
    status.className = "text-center text-sm text-error";
    status.textContent = "Network error \u2014 is the server reachable?";
    btn.disabled = false;
    
    document.getElementById("loginSpinner").classList.add("hidden");
    document.getElementById("btnLabel").textContent = "Sign in";
  });
};

// ── Preflight: warming the portal session + captcha solver while the
//    user is still typing the password. Server no-ops if busy/stale;
//    submit consumes it automatically via /api/login.
(function() {
  var pw = document.getElementById("pw");
  var firedFor = null;
  function maybePreflight() {
    var netid = (document.getElementById("netid").value || "").trim().toLowerCase().split("@")[0];
    if (!netid || netid === firedFor) return;
    firedFor = netid;
    fetch("/api/login/preflight", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({netid: netid})
    }).catch(function() {});
  }
  pw.addEventListener("focus", maybePreflight);
  pw.addEventListener("input", maybePreflight);  // covers autofill that skips focus
})();

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

// Caps Lock: an invisible, common cause of failed logins. The hint row in
// login.html is always reserved, so showing this never shifts the layout.
(function () {
  var pw = document.getElementById("pw"), caps = document.getElementById("caps");
  function sync(e) {
    caps.textContent = (e && e.getModifierState && e.getModifierState("CapsLock"))
      ? "Caps Lock is on" : "";
  }
  pw.addEventListener("keydown", sync);
  pw.addEventListener("keyup", sync);   // state may change without a keydown here
  pw.addEventListener("blur", function () { caps.textContent = ""; });
})();

// audit 2026-09-27: SW registration must live in an EXTERNAL file — the old
// inline <script> in login.html was blocked by script-src 'self', so the PWA
// never registered on any device (scope "/" also needs the
// Service-Worker-Allowed header, set in app.py static_no_cache).
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js", {scope: "/"}).catch(function(){});
}
