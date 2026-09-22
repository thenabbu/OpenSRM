// Internal Marks tab — all data visible inline, no expand/collapse friction.
// Lazy-loaded on first tab click; cached in memory after.
(function () {
  var loaded = false;
  var _data = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (m) {
      var map = { 38: "amp", 60: "lt", 62: "gt", 34: "quot", 39: "#39" };
      return String.fromCharCode(38) + map[m.charCodeAt(0)] + String.fromCharCode(59);
    });
  }
  function pct(s, m) { return !m ? 0 : Math.round((s / m) * 1000) / 10; }
  function statusFor(p) { return p >= 75 ? "success" : p >= 50 ? "warning" : "error"; }

  // DESIGN.md: primary=black(invisible on dark), secondary=pink, accent=white, ghost=neutral
  function compBadge(name) {
    var n = name.toLowerCase();
    if (n.indexOf("att") >= 0) return "badge-secondary";  // pink for attendance
    if (n.indexOf("ft") >= 0) return "badge-accent";      // white for finals
    return "badge-ghost";                                   // neutral for CT/others
  }

  function subjectCard(s) {
    var p = pct(s.scored_total, s.max_total), st = statusFor(p);
    var comps = s.components.map(function (c) {
      var cp = pct(c.scored, c.max), cst = statusFor(cp);
      return '<div class="flex items-center gap-2 py-1">' +
        '<span class="badge badge-sm badge-outline font-mono ' + compBadge(c.name) + '">' + esc(c.name) + '</span>' +
        '<span class="font-mono text-xs text-base-content/70">' + c.scored.toFixed(2) + '/' + c.max.toFixed(2) + '</span>' +
        '<span class="font-mono text-xs font-bold text-' + cst + ' ml-auto">' + cp + '%</span>' +
        '<progress class="progress progress-' + cst + ' h-1.5 w-16" value="' + cp + '" max="100"></progress>' +
        '</div>';
    }).join("");

    return '<div class="bg-base-200 border border-base-300 rounded-box p-4">' +
      '<div class="flex items-baseline gap-2 mb-0.5">' +
        '<span class="font-mono font-bold text-' + st + ' text-lg">' + p + '%</span>' +
        '<span class="font-mono text-xs text-base-content/50">' + s.scored_total.toFixed(2) + '/' + s.max_total.toFixed(2) + '</span>' +
      '</div>' +
      '<h3 class="text-sm font-semibold text-base-content/80 capitalize mb-0.5">' + esc(s.title || s.code) + '</h3>' +
      '<span class="font-mono text-xs text-base-content/40 mb-2 block">' + esc(s.code) + '</span>' +
      '<div class="border-t border-base-300/50 pt-2">' +
        (comps || '<p class="text-xs text-base-content/40 italic">No assessment data</p>') +
      '</div>' +
      '</div>';
  }

  function render(data) {
    var el = document.getElementById("marks-content");
    if (!el) return;
    _data = data;
    if (!data || !data.length) {
      el.innerHTML =
        '<div class="flex flex-col items-center justify-center py-12 text-center">' +
          '<div class="text-4xl mb-3 opacity-30">📊</div>' +
          '<h3 class="text-base font-semibold text-base-content/70">No internal marks published yet</h3>' +
          '<p class="text-sm text-base-content/50 mt-1 max-w-sm">They appear here once your faculty publishes FT/CT marks on the portal.</p></div>';
      return;
    }
    var totS = 0, totM = 0;
    data.forEach(function (s) { totS += s.scored_total; totM += s.max_total; });
    var overall = pct(totS, totM), ost = statusFor(overall);
    el.innerHTML =
      '<div class="flex items-center gap-4 mb-5 p-4 bg-base-200 border border-base-300 rounded-box">' +
        '<div class="radial-progress text-' + ost + ' font-bold text-sm" style="--value:' + overall + '; --size:4rem; --thickness:4px;" role="progressbar">' + overall + '%</div>' +
        '<div class="min-w-0">' +
          '<h2 class="text-sm font-semibold text-base-content">Overall internal marks</h2>' +
          '<p class="text-xs text-base-content/50">' + totS.toFixed(2) + ' / ' + totM.toFixed(2) + ' across ' + data.length + ' subject' + (data.length !== 1 ? "s" : "") + '</p>' +
        '</div>' +
      '</div>' +
      '<div class="grid grid-cols-1 md:grid-cols-2 gap-3">' + data.map(subjectCard).join("") + '</div>';
  }

  function err(msg) {
    document.getElementById("marks-content").innerHTML =
      '<div class="alert alert-soft alert-error">' + esc(msg) + '</div>';
  }

  function load() {
    if (loaded && _data) return;
    loaded = true;
    document.getElementById("marks-content").innerHTML =
      '<div class="flex justify-center py-8"><span class="loading loading-dots loading-md text-base-content"></span></div>';
    fetch("/api/marks", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d.ok) render(d.marks); else err(d.error || "Failed"); })
      .catch(function () { loaded = false; err("Network error"); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var t = document.querySelector('[data-tab="marks"]');
    if (t) t.addEventListener("click", load, { once: true });
  });
})();
