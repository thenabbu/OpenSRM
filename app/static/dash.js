// Error toast (W5.2a): the implementation lives in web/src/data/errorToast.ts.
// This is a plain <script> and cannot import the bundle, so it calls the bridge.
// The body below is the PREACT_ISLANDS=0 rollback path (no bundle => no bridge),
// where a toast is still better than a swallowed save failure. timetable.js no
// longer borrows this name — it calls the bridge itself.
function showError(msg) {
  var bridge = window.__osrmShowError;
  if (bridge) { bridge(msg); return; }
  var t = document.getElementById('error-toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.remove('hidden');
  setTimeout(function() { t.classList.add('hidden'); }, 5000);
}

// ── Scroll state for the overlay scrollbar (theme.html) ──
// The bar is width 0 until the page is hovered or scrolled: `is-scrolling`
// keeps it visible for a moment after the scroll ends so it does not blink.
(function () {
  var t;
  window.addEventListener('scroll', function () {
    document.documentElement.classList.add('is-scrolling');
    clearTimeout(t);
    t = setTimeout(function () {
      document.documentElement.classList.remove('is-scrolling');
    }, 1200);
  }, {passive: true});
})();

// ── Sync lines (navbar): relative age, caption to the right of the sync
//    button. Fresh (<5min) reads as nothing — the button itself is the status. ──
function renderSyncLines() {
  document.querySelectorAll('.sync-line').forEach(function(el) {
    var ts = parseInt(el.dataset.ts || '0', 10);
    var diff = ts ? Math.floor(Date.now() / 1000) - ts : 0;
    var text;
    if (!ts) text = 'Never synced';
    else if (diff < 300) text = '';
    else if (diff < 3600) text = '(' + Math.floor(diff / 60) + 'm ago)';
    else if (diff < 86400) text = '(' + Math.floor(diff / 3600) + 'h ago)';
    else text = '(' + Math.floor(diff / 86400) + 'd ago)';
    el.textContent = text;
    // BOTH representations: the caption drops out of the flex gap via the class,
    // and the server marks a no-age caption with the `hidden` ATTRIBUTE (whose
    // UA default is display:none). Toggling only the class left that attribute
    // set forever, so a page that started without a sync could never show the
    // caption it later gained. One writer, both spellings.
    el.classList.toggle('hidden', !text);
    el.toggleAttribute('hidden', !text);
    el.title = el.dataset.full;
  });
}
renderSyncLines();
setInterval(renderSyncLines, 60000);   // "(15m ago)" must keep ageing, and reappear once fresh

// ── A data-changing sync updates DATA, not markup (DESIGN §10.16 rule 3) ──
// The bundle owns the repaint: every mounted island refetches its own
// /api/<panel> slice and Preact patches the text nodes that changed. Nothing is
// torn down, so scroll position, focus, open <details> and the attendance view
// survive BY CONSTRUCTION — the three compensations this file used to carry
// (re-focus the old id, re-open the open panels, re-show the table view) only
// existed to survive the markup swap that is now gone.
//
// dash.js is a plain <script> and cannot import the bundle, so it reaches the
// repaint through one hook (the same shape as __osrmOutbox). No hook yet (the
// module has not run) means a sync changes nothing on screen — strictly better
// than downloading this route's HTML again on a phone to change one number.
function syncData() {
  var hook = window.__osrmRefreshData;
  if (!hook) return Promise.resolve();
  return Promise.resolve(hook()).catch(function (err) {
    console.error('sync refresh failed:', err);
  });
}

// ── Refresh (all data-refresh buttons) ────────────────────────────
// W5.2a: the whole primitive — POST /api/refresh, busy state, focus restore,
// repaint, 401 -> /login — lives in web/src/data/refresh.ts now, and so does
// the [data-refresh] click binding. This forwarder is what remains here: the
// PREACT_ISLANDS=0 (no bundle) path, this file's own background auto-sync, and
// pull.js before it learned to call the bridge itself.
function ref(quiet) {
  var bridge = window.__osrmRevalidate;
  if (bridge) return bridge(quiet);
  return Promise.resolve();
}
document.querySelectorAll('[data-refresh]').forEach(function(b) {
  b.addEventListener('click', function() {
    // With the bundle present, refresh.ts bound every one of these buttons
    // itself (W5.2a). This listener is then the PREACT_ISLANDS=0 fallback and
    // must stand down, or one click starts two syncs.
    if (window.__osrmRevalidate) return;
    // aria-disabled replaces the `disabled` attribute so focus is never
    // dropped mid-sync; honour it here or a double-click starts two syncs.
    if (b.getAttribute('aria-disabled') === 'true') return;
    ref(false);
  });
});

// ── Item-level interaction beacon ─────────────────────────────────────────
// "Which tab" is already measured; "what inside the tab" is not, and adding a
// listener per widget would rot the moment markup changes. One delegated
// click handler instead: any element carrying data-track-item reports itself,
// and the server holds the closed vocabulary of valid names (an unknown value
// is dropped there, so a stale attribute can never mint a new label).
// Fire-and-forget with keepalive, wrapped — telemetry must never break a click.
(function () {
  var ITEM_TAB = {  // which tab a given item belongs to, for the beacon body
    'attendance-graph': 'attendance', 'attendance-table': 'attendance',
    'attendance-sort': 'attendance',
    'timetable-day': 'timetable', 'timetable-subject': 'timetable',
    'marks-component': 'marks', 'marks-semester': 'marks',
    'fees-breakdown': 'fees',
    'academics-transcript': 'academics', 'academics-credits': 'academics',
    'tools-feedback': 'tools', 'tools-push': 'tools',
    'profile-card': 'dashboard', 'sync-button': 'dashboard',
    'settings-device': 'settings'
  };
  document.addEventListener('click', function (ev) {
    try {
      var el = ev.target && ev.target.closest ? ev.target.closest('[data-track-item]') : null;
      if (!el || !self.fetch) return;
      var item = el.getAttribute('data-track-item');
      if (!item) return;
      self.fetch('/api/track/tab', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tab: ITEM_TAB[item] || 'dashboard', item: item}),
        keepalive: true,
        credentials: 'same-origin'
      }).catch(function () {});
    } catch (e) {}
  }, {passive: true});
})();
// Tools rows name the panel their surface belongs to (app/static_data.TOOLS).
// P3.1 made those panels real routes, so the row is a plain link: rewrite the
// legacy '#panel' href to the route. A row naming a panel that is neither on
// this page nor a route is marked inert (no pointer affordance, click
// prevented) rather than becoming a dead hash.
var ROUTES = ['dashboard', 'attendance', 'timetable', 'marks', 'campus',
              'academics', 'fees', 'tools', 'settings'];
document.querySelectorAll('[data-tool-tab]').forEach(function(a) {
  var panel = a.dataset.toolTab;
  if (document.getElementById('tab-' + panel)) return;          // still a link, unchanged
  if (ROUTES.indexOf(panel) !== -1) {
    a.setAttribute('href', panel === 'dashboard' ? '/' : '/' + panel);
    return;
  }
  a.removeAttribute('href');
  a.setAttribute('aria-disabled', 'true');
  a.removeAttribute('data-tool-tab');
  a.classList.remove('pressable');
  a.classList.add('cursor-default');
  a.querySelector('svg').classList.replace('text-base-content/60', 'text-base-content/50');
  a.addEventListener('click', function(e) { e.preventDefault(); });
});

// ── Click-to-copy (W5.2b): the whole cluster — the [data-copy] handler, the
//    #copyEmail branch, the a11y stamps and the re-arm after an island repaint
//    — lives in web/src/data/copy.ts and is bound by main.ts. It moved because
//    the islands OWN the attributes: SettingsPanel/DashboardPanel/FeesPanel emit
//    `data-copy` and nothing here could see a repaint before it happened. One
//    copy implementation, in the bundle, so an island edit has one contract.

// ── Attendance view toggle (graph ↔ table). Persisted in localStorage;
//    visibility via the `hidden` attribute ONLY (never a Tailwind class).
(function() {
  var graph = document.getElementById('att-graph');
  var table = document.getElementById('att-table');
  var bg = document.getElementById('att-view-graph');
  var bt = document.getElementById('att-view-table');
  if (!graph || !table || !bg || !bt) return;
  function apply(view) {
    var isTable = view === 'table';
    table.hidden = !isTable;
    graph.hidden = isTable;
    bt.setAttribute('aria-pressed', isTable ? 'true' : 'false');
    bg.setAttribute('aria-pressed', isTable ? 'false' : 'true');
    bt.classList.toggle('btn-active', isTable);
    bg.classList.toggle('btn-active', !isTable);
  }
  try { apply(localStorage.getItem('attView') || 'graph'); } catch (e) { apply('graph'); }
  bg.addEventListener('click', function() { apply('graph'); try { localStorage.setItem('attView', 'graph'); } catch (e) {} });
  bt.addEventListener('click', function() { apply('table'); try { localStorage.setItem('attView', 'table'); } catch (e) {} });
})();

// ── Personal-details groups (Settings tab): all open on desktop (dense
//    fact-sheet scan), first group only on mobile (compact lookup).
//    The Personal-details ROW itself stays collapsed on both — it's one
//    settings row among several now; the group rule applies once opened.
//    A named function, not an IIFE: the settings island repaints the block
//    after hydration and the fresh inputs arrive unchecked, so this re-arms on
//    `osrm:island-mounted` exactly like armAvatarOffscreen. Keyed per input, so
//    a re-arm never undoes a toggle the user made.
//    ponytail: evaluated once per node; rotating across the sm breakpoint
//    keeps whatever state the user has toggled (still fully toggleable).
function applyGroupDefaults() {
  // .flex.flex-col, not `#personal-details .collapse input`: after hydration the
  // island's own block is a SECOND #personal-details, and the row's toggle input
  // would match that selector — opening the row the user has not opened.
  var wrap = document.querySelector('#personal-details .collapse-content > .flex.flex-col');
  if (!wrap) return;
  var wide = window.matchMedia('(min-width: 640px)').matches;
  Array.prototype.forEach.call(wrap.querySelectorAll('.collapse > input'), function(g, i) {
    if (g.dataset.groupDefault) return;
    g.dataset.groupDefault = '1';
    g.checked = wide || i === 0;
  });
}
applyGroupDefaults();
document.addEventListener('osrm:island-mounted', applyGroupDefaults);

// ── Auto-sync on open: show cached data instantly, refresh quietly in
//    background when stale (>10min). Quiet failures stay silent.
(function() {
  var first = document.querySelector('.sync-line');
  if (!first) return;
  // No readable stored credentials = /api/refresh can only answer 401, and the
  // browser logs that 401 as a console error on THIS page. Nothing to gain
  // from firing it; the server's own auto_sync_kick_if_stale already ran.
  var can = document.querySelector('meta[name="can-sync"]');
  if (can && can.content === '0') return;
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

// Phase 6: pause the avatar's idle loops while it is offscreen. IO needs
// no polling; paused pose is preserved (motion.css). Low-tier is paused by
// CSS from perf.js (html[data-perf="low"]).
//
// A named function, not an IIFE: the dashboard island paints its OWN avatar
// node, so the one armed at load is detached by hydration. main.ts fires
// `osrm:island-mounted` after every successful mount and this re-arms on the
// new node. Keyed on the element itself, so a no-op re-arm costs nothing.
function armAvatarOffscreen() {
  var wrap = document.querySelector('.blobatar-gaze');
  if (!wrap || !('IntersectionObserver' in window) || wrap.dataset.offscreenObs) return;
  wrap.dataset.offscreenObs = '1';
  var root = wrap.querySelector('.mo-root') || wrap;
  new IntersectionObserver(function(es) {
    es.forEach(function(e) { root.classList.toggle('is-offscreen', !e.isIntersecting); });
  }, {threshold: 0}).observe(wrap);
}
armAvatarOffscreen();
document.addEventListener('osrm:island-mounted', armAvatarOffscreen);

// audit: register here too — a valid session lands on / directly and never
// loads /login, so login.js alone would never register the SW for those users.
if ("serviceWorker" in navigator && location.pathname !== "/login") {
  navigator.serviceWorker.register("/static/sw.js", {scope: "/"}).catch(function(){});
}

// ── Mid-sem feedback (OPT-IN auto-fill) ─────────────────────────────
// CTA opens the explainer modal; ONLY the confirm button inside the modal
// writes to the portal (sync harvests read-only). Same builder rendered the
// modal list, so what the student saw IS what gets sent.
// #fb-cta only renders when a plan exists and #fb-submit sits inside
// #fb-modal — both are delegated at document level, so they work whatever
// painted them.
document.addEventListener('click', function(ev) {
  if (!ev.target.closest) return;
  if (ev.target.closest('#fb-cta')) {
    var m = document.getElementById('fb-modal');
    if (m) m.showModal();
    return;
  }
  var fbSubmit = ev.target.closest('#fb-submit');
  if (!fbSubmit) return;
  var status = document.getElementById('fb-status');
  fbSubmit.disabled = true;
  status.textContent = 'Submitting to the portal…';
  status.className = 'mt-2 text-xs text-base-content/70';
  fetch('/api/feedback/fill', {method: 'POST'})
    .then(function(r) {
      if (r.redirected) { location.href = '/login'; return new Promise(function() {}); }
      return r.json();
    })
    .then(function(j) {
      if (!j.ok) {
        status.textContent = j.error || 'failed — nothing submitted';
        status.className = 'mt-2 text-xs text-error';
        showError('Feedback autofill failed: ' + (j.error || 'unknown error'));
        return;
      }
      var parts = [];
      if (j.filled && j.filled.length) parts.push(j.filled.length + ' submitted');
      if (j.already && j.already.length) parts.push(j.already.length + ' already filled');
      if (j.failed && j.failed.length) {
        parts.push(j.failed.length + ' failed: ' + j.failed.map(function(f) { return f[0]; }).join(', '));
        showError('Feedback: ' + j.failed.map(function(f) { return f[0] + ' — ' + f[1]; }).join('; '));
      }
      status.textContent = parts.join(' · ') || 'nothing to submit';
      status.className = 'mt-2 text-xs ' + (j.failed && j.failed.length ? 'text-error' : 'text-success');
    })
    .catch(function() {
      status.textContent = 'network error — try again';
      status.className = 'mt-2 text-xs text-error';
      showError('Feedback autofill: network error — try again');
    })
    .finally(function() { fbSubmit.disabled = false; });
});

// ── Marks tag save: fetch + data repaint (no-JS fallback = plain POST) ──
// The tag forms are repainted in place on save (island repaint), so the submit
// is delegated. The server returns JSON when the request asks for it and keeps
// the POST/redirect for the no-JS path.
document.addEventListener('submit', function(ev) {
  var f = ev.target;
  if (!(f instanceof HTMLFormElement)) return;
  var action = f.getAttribute('action') || '';
  if (action !== '/marks/tag') return;
  ev.preventDefault();
  // P7.4: a tag is DATA the student typed, so a dead link must not lose it.
  // The bundle owns the queue (web/src/data/outbox.ts) and publishes it here;
  // until the module loads the hook is absent and this path degrades to the
  // old toast. The fields are collected BEFORE the attempt so a failed POST
  // still has exactly what was submitted.
  var fields = {};
  new FormData(f).forEach(function(v, k) { fields[k] = String(v); });
  var queue = window.__osrmOutbox;
  var offline = !navigator.onLine;
  fetch('/marks/tag', {method: 'POST', body: new FormData(f),
                       credentials: 'same-origin',
                       headers: {Accept: 'application/json'}})
    .then(function(r) {
      if (r.redirected) { location.href = '/login'; return new Promise(function() {}); }
      return r.json();
    })
    .then(function(j) {
      if (!j.ok) { showError(j.error || 'Tag not saved'); return; }
      syncData();
    })
    .catch(function() {
      // Only a TRANSPORT failure is deferred: a rejected tag ({"ok":false}) is
      // a real answer from the server and retrying it would be a lie.
      if (!queue) { showError('Network error — tag not saved'); return; }
      var netid = document.body.getAttribute('data-netid');
      if (!offline && !netid) { showError('Network error — tag not saved'); return; }
      queue.queueWrite(netid || '', 'tag', fields)
        .then(function() { return queue.startOutbox(); })
        .then(function() {
          showError('Offline — tag saved and will be sent when you reconnect');
        })
        .catch(function() { showError('Network error — tag not saved'); });
    });
});

// ── Delete my data (OPT-IN destructive) ──────────────────────────────
// Same shape as the feedback flow: the settings ROW opens the explainer
// modal; ONLY the confirm button inside the modal POSTs. Status shows in
// the modal (+ the global toast on failure); success lands on /login
// (the server also clears the session cookie).
var delBtn = document.getElementById('delete-account-btn');
var delConfirm = document.getElementById('del-confirm');
if (delBtn) {
  delBtn.addEventListener('click', function() { document.getElementById('delete-account-modal').showModal(); });
}
if (delConfirm) {
  delConfirm.addEventListener('click', function() {
    var status = document.getElementById('del-status');
    delConfirm.disabled = true;
    status.textContent = 'Erasing your data…';
    status.className = 'mt-2 text-xs text-base-content/70';
    fetch('/api/account/delete', {method: 'POST'})
      .then(function(r) {
        if (r.redirected) { location.href = '/login'; return new Promise(function() {}); }
        return r.json();
      })
      .then(function(j) {
        if (!j.ok) {
          status.textContent = j.error || 'failed — nothing was removed';
          status.className = 'mt-2 text-xs text-error';
          showError('Delete failed: ' + (j.error || 'unknown error'));
          delConfirm.disabled = false;
          return;
        }
        location.href = '/login';
      })
      .catch(function() {
        status.textContent = 'network error — nothing was removed';
        status.className = 'mt-2 text-xs text-error';
        showError('Delete: network error — nothing was removed');
        delConfirm.disabled = false;
      });
  });
}

// ── Outside-click dismiss for popover <details> (marks tag panel) ────
// Tap-away is the expected dismiss gesture; without it the panel covers the
// next card until Save or a re-tap of the pencil — Save must never be the
// only way out of a panel the user opened by accident. Clicks inside the
// details (summary included) are ignored, so the pencil toggle still works.
document.addEventListener('click', function(e) {
  var open = document.querySelector('details[open]');
  if (open && !open.contains(e.target)) open.open = false;
});

// ── SCOPE: the SCOPE surfaces fill in after a BACKGROUND sync (each SOAP op
//    is 4-8s upstream), so the page they were rendered on can be missing them.
//    Poll the status endpoint — bounded, backed off — and repaint the page's
//    islands exactly ONCE when the sync completes (no reload, no tab change:
//    the repaint only rewrites the numbers). The template renders the state as
//    'complete' on the next load, so the loop cannot restart: one repaint per
//    completed run, never a poll storm, never an endless loop.
(function () {
  var body = document.body;
  if (!body) return;
  var state = body.getAttribute('data-scope-sync') || '';
  if (state !== 'stale' && state !== 'running') return;
  // Budget: a full 14-op run measured 27-31s, but a slow upstream day plus the
  // 8s backoff after the 10th try can push a cold first sync past 4 minutes --
  // the old cap (45 tries) then stopped polling SILENTLY while the server was
  // still syncing, leaving the page on the pre-sync render forever. Widen to
  // ~20 min and re-check the body state each tick: the marker JS can't update
  // (it is server-rendered), so this poll is the only way to learn a background
  // run finished while this page was open.
  var tries = 0, MAX_TRIES = 150, delay = 4000, done = false;
  function poll() {
    if (done || tries++ > MAX_TRIES) return;
    fetch('/api/scope/status', { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.ok) { setTimeout(poll, delay); return; }
        if (d.state === 'complete') { done = true; syncData(); return; }
        if (d.state === 'off') { done = true; return; }
        if (tries > 10) delay = 8000;   // back off once the wait gets long
        setTimeout(poll, delay);
      })
      .catch(function () { setTimeout(poll, delay); });
  }
  setTimeout(poll, 1500);
})();
