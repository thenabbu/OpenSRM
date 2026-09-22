// Internal Marks tab — fetch /api/marks and render per-subject cards.
// Loaded lazily on first tab visit; cached in memory after.
(function () {
  var loaded = false;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (m) {
      var map = { 38: "amp", 60: "lt", 62: "gt", 34: "quot", 39: "#39" };
      return String.fromCharCode(38) + map[m.charCodeAt(0)] + String.fromCharCode(59);
    });
  }

  function pct(scored, max) {
    if (!max) return 0;
    return Math.round((scored / max) * 1000) / 10;
  }

  function statusFor(p) {
    if (p >= 75) return "success";
    if (p >= 50) return "warning";
    return "error";
  }

  function renderSubject(s) {
    var p = pct(s.scored_total, s.max_total);
    var st = statusFor(p);
    var comps = s.components.map(function (c) {
      var cp = pct(c.scored, c.max);
      return '<tr><td>' + esc(c.name) + '</td>' +
        '<td class="font-mono">' + c.scored.toFixed(2) + ' / ' + c.max.toFixed(2) + '</td>' +
        '<td class="font-mono font-bold">' + cp + '%</td></tr>';
    }).join("");
    return (
      '<div class="card bg-base-200 border border-base-300">' +
      '  <div class="card-body p-5">' +
      '    <div class="flex items-start justify-between gap-3">' +
      '      <div class="min-w-0">' +
      '        <span class="badge badge-soft badge-secondary font-mono">' + esc(s.code) + '</span>' +
      '        <h3 class="text-sm capitalize leading-snug mt-2">' + esc(s.title || "") + '</h3>' +
      '      </div>' +
      '      <span class="font-mono font-bold text-' + st + '">' + p + '%</span>' +
      '    </div>' +
      '    <progress class="progress progress-' + st + '" value="' + p + '" max="100"></progress>' +
      '    <div class="flex gap-3 font-mono text-xs text-base-content/50 flex-wrap">' +
      '      <span>' + s.scored_total.toFixed(2) + ' scored</span>' +
      '      <span>' + s.max_total.toFixed(2) + ' max</span>' +
      '    </div>' +
      (comps
        ? '    <div class="overflow-x-auto border border-base-300 rounded-box mt-2">' +
          '      <table class="table table-sm">' +
          '        <thead><tr class="bg-base-200"><th class="text-base-content">Assessment</th><th class="text-base-content">Mark</th><th class="text-base-content">%</th></tr></thead>' +
          '        <tbody>' + comps + '</tbody>' +
          '      </table>' +
          '    </div>'
        : "") +
      '  </div>' +
      "</div>"
    );
  }

  function render(data) {
    var el = document.getElementById("marks-content");
    if (!el) return;
    if (!data || !data.length) {
      el.innerHTML =
        '<div class="alert alert-soft alert-info">No internal marks published yet. ' +
        "They appear here once your faculty publishes FT/CT marks on the portal.</div>";
      return;
    }
    var totS = 0, totM = 0;
    data.forEach(function (s) { totS += s.scored_total; totM += s.max_total; });
    var overall = pct(totS, totM);
    var ost = statusFor(overall);
    el.innerHTML =
      '<div class="card bg-base-200 border border-base-300 mb-5">' +
      '  <div class="card-body p-5 flex items-center gap-5">' +
      '    <div class="radial-progress text-' + ost + '" style="--value:' + overall + '; --size:5rem; --thickness:6px;" role="progressbar">' +
      '      <span class="text-base-content font-bold text-sm">' + overall + '%</span>' +
      "    </div>" +
      '    <div>' +
      '      <h2 class="text-base font-semibold">Overall internal marks</h2>' +
      '      <p class="text-sm text-base-content/60">' + totS.toFixed(2) + ' of ' + totM.toFixed(2) + ' total marks</p>' +
      "    </div>" +
      "  </div>" +
      "</div>" +
      '<h3 class="text-base font-semibold mb-3">Subjects</h3>' +
      '<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-5">' +
      data.map(renderSubject).join("") +
      "</div>";
  }

  function load() {
    if (loaded) return;
    loaded = true;
    fetch("/api/marks", { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) render(d.marks);
        else
          document.getElementById("marks-content").innerHTML =
            '<div class="alert alert-soft alert-error">' + esc(d.error || "Failed to load marks") + "</div>";
      })
      .catch(function () {
        loaded = false;
        document.getElementById("marks-content").innerHTML =
          '<div class="alert alert-soft alert-error">Network error — could not load marks.</div>';
      });
  }

  // Lazy-load on first tab activation
  document.addEventListener("DOMContentLoaded", function () {
    var tab = document.querySelector('[data-tab="marks"]');
    if (tab) tab.addEventListener("click", load, { once: true });
  });
})();
