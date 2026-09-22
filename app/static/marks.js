// Internal Marks tab — fetch /api/marks and render expandable subject cards.
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
  function cl(name) {
    var n = name.toLowerCase();
    if (n.indexOf("att") >= 0) return { badge: "badge-accent", txt: "text-accent" };
    if (n.indexOf("ft") >= 0) return { badge: "badge-secondary", txt: "text-secondary" };
    return { badge: "badge-primary", txt: "text-primary" };
  }

  function compRow(c) {
    var p = pct(c.scored, c.max), st = statusFor(p), k = cl(c.name);
    return '<tr class="border-base-300/50 hover:bg-base-300/30 transition-colors">' +
      '<td class="py-2 px-3"><span class="badge badge-sm badge-soft font-mono ' + k.badge + '">' + esc(c.name) + '</span></td>' +
      '<td class="py-2 px-3 font-mono text-sm text-base-content/70">' + c.scored.toFixed(2) + ' / ' + c.max.toFixed(2) + '</td>' +
      '<td class="py-2 px-3 font-mono font-bold text-sm text-' + st + '">' + p + '%</td>' +
      '<td class="py-2 px-3"><progress class="progress progress-' + st + ' h-2" value="' + p + '" max="100"></progress></td></tr>';
  }

  function card(s, i) {
    var p = pct(s.scored_total, s.max_total), st = statusFor(p);
    var ct = s.components.filter(function (c) { return c.name.toLowerCase().indexOf("ct") >= 0; }).length;
    var ft = s.components.filter(function (c) { return c.name.toLowerCase().indexOf("ft") >= 0; }).length;
    var chips = [];
    if (ct) chips.push(ct + " CT");
    if (ft) chips.push(ft + " FT");
    chips.push(s.components.length + " item" + (s.components.length !== 1 ? "s" : ""));
    return '<div class="card bg-base-200 border border-base-300 marks-card transition-all hover:border-base-content/20 cursor-pointer" data-i="' + i + '">' +
      '<div class="card-body p-4">' +
      '<div class="flex items-center gap-3">' +
        '<span class="badge badge-soft badge-secondary font-mono text-xs">' + esc(s.code) + '</span>' +
        '<span class="font-mono font-bold text-' + st + ' text-lg leading-none">' + p + '%</span>' +
        '<span class="ml-auto text-base-content/40 marks-chevron transition-transform duration-200">▾</span>' +
      '</div>' +
      (s.title ? '<p class="text-sm text-base-content/70 mt-1 capitalize leading-snug">' + esc(s.title) + '</p>' : '') +
      '<div class="flex items-center gap-3 mt-3">' +
        '<progress class="progress progress-' + st + ' flex-1 h-2" value="' + p + '" max="100"></progress>' +
        '<span class="font-mono text-xs text-base-content/50 whitespace-nowrap">' + s.scored_total.toFixed(2) + ' / ' + s.max_total.toFixed(2) + '</span>' +
      '</div>' +
      '<div class="flex gap-1.5 mt-2 flex-wrap">' +
        chips.map(function (t) { return '<span class="text-xs text-base-content/50">' + t + '</span>'; }).join("") +
      '</div>' +
      '<div class="marks-detail hidden mt-3 pt-3 border-t border-base-300/50">' +
        (s.components.length
          ? '<table class="table table-sm"><thead><tr class="bg-base-300/30">' +
            '<th class="text-base-content/60 text-xs">Assessment</th>' +
            '<th class="text-base-content/60 text-xs">Mark</th>' +
            '<th class="text-base-content/60 text-xs">%</th>' +
            '<th class="text-base-content/60 text-xs w-24"></th></tr></thead>' +
            '<tbody>' + s.components.map(compRow).join("") + '</tbody></table>'
          : '<p class="text-sm text-base-content/40 italic">No assessment data</p>') +
      '</div></div></div>';
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
      '<div class="card bg-base-200 border border-base-300 mb-5">' +
      '  <div class="card-body p-5 flex flex-row items-center gap-5 flex-wrap">' +
      '    <div class="radial-progress text-' + ost + ' font-bold text-sm" style="--value:' + overall + '; --size:4.5rem; --thickness:5px;" role="progressbar">' + overall + '%</div>' +
      '    <div class="min-w-0"><h2 class="text-sm font-semibold">Overall internal marks</h2>' +
      '      <p class="text-xs text-base-content/50">' + totS.toFixed(2) + ' / ' + totM.toFixed(2) + ' across ' + data.length + ' subject' + (data.length !== 1 ? "s" : "") + '</p></div></div></div>' +
      '<div class="grid grid-cols-1 md:grid-cols-2 gap-3">' + data.map(card).join("") + '</div>';
    el.querySelectorAll(".marks-card").forEach(function (c) {
      c.addEventListener("click", function () {
        var d = c.querySelector(".marks-detail"), ch = c.querySelector(".marks-chevron");
        var open = !d.classList.contains("hidden");
        d.classList.toggle("hidden", open);
        ch.style.transform = open ? "" : "rotate(180deg)";
        c.classList.toggle("ring-1", !open);
        c.classList.toggle("ring-primary/30", !open);
      });
    });
  }

  function err(msg) {
    document.getElementById("marks-content").innerHTML =
      '<div class="alert alert-soft alert-error">' + esc(msg) + '</div>';
  }

  function load() {
    if (loaded && _data) return;
    loaded = true;
    document.getElementById("marks-content").innerHTML =
      '<div class="flex justify-center py-8"><span class="loading loading-dots loading-md text-primary"></span></div>';
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
