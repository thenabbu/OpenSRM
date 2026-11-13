// Error toast helper (global — used by timetable.js too)
function showError(msg) {
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
    el.classList.toggle('hidden', !text);   // empty caption drops out of the flex gap
    el.title = el.dataset.full;
  });
}
renderSyncLines();
setInterval(renderSyncLines, 60000);   // "(15m ago)" must keep ageing, and reappear once fresh

// ── Soft refresh: update the page in place (DESIGN §10.16 rule 3) ──
// A data-changing sync morphs <main> from a freshly fetched render of THIS
// route with idiomorph: nodes with the same id are kept (their listeners
// survive), client state listed in PRESERVE_ATTR survives, and
// [data-morph="ignore"] subtrees (avatar wrapper, push card) are skipped
// wholesale. A full location.reload() remains only as the catch net.
function PRESERVE_ATTR(attr, el) {
  // visible-tab display state lives on the panel's inline style
  if (attr === 'style' && el.closest('[data-tabpanel]')) return true;
  // attendance graph/table choice
  if (attr === 'hidden' && (el.id === 'att-graph' || el.id === 'att-table')) return true;
  // personal-details collapse groups (user-toggled at load)
  if (attr === 'checked' && el.matches('.collapse input[type="checkbox"]')) return true;
  // open marks-tag panels
  if (attr === 'open' && el.tagName === 'DETAILS') return true;
  return false;
}

var MORPH_OPTS = {
  morphStyle: 'innerHTML',
  ignoreActiveValue: true,
  // no restoreFocus: it blurs elements without an id; nodes outside <main>
  // (tab buttons etc.) are never morphed, so their focus survives untouched.
  callbacks: {
    beforeNodeMorphed: function (oldNode) {
      return !(oldNode.nodeType === 1 && oldNode.closest('[data-morph="ignore"]'));
    },
    beforeAttributeUpdated: function (attr, el) { return !PRESERVE_ATTR(attr, el); }
  }
};

function softRefresh() {
  // P3.1: one panel per route — re-render THIS page, never the dashboard.
  // ('/' would morph the dashboard's <main> into /marks and leave the URL
  // saying /marks over dashboard content.)
  return fetch(location.pathname + location.search,
               {credentials: 'same-origin', headers: {Accept: 'text/html'}})
    .then(function (r) {
      // dead session: server 302s to /login — go there, not "network error".
      if (r.redirected && new URL(r.url).pathname === '/login') { location.href = '/login'; return null; }
      return r.text();
    })
    .then(function (html) {
      if (html == null) return;                      // already leaving for /login
      var doc = new DOMParser().parseFromString(html, 'text/html');
      try {
        Idiomorph.morph(document.querySelector('main'), doc.querySelector('main'), MORPH_OPTS);
        // the opt-in feedback plan can change with the learned fb_open state:
        // morph the modal too, but only while closed (an open modal is
        // mid-conversation — never swap it under the user). outerHTML style:
        // idiomorph 0.8.0's innerHTML path throws HierarchyRequestError when
        // the target is a top-level <dialog> sliced from the fetched document;
        // outerHTML morphs the dialog node in place instead (verified: same
        // node kept, so the delegated submit listener survives).
        var fbm = document.getElementById('fb-modal');
        var fbmSrc = doc.getElementById('fb-modal');
        if (fbm && fbmSrc && !fbm.open) {
          Idiomorph.morph(fbm, fbmSrc, Object.assign({}, MORPH_OPTS, {morphStyle: 'outerHTML'}));
        }
      } catch (err) { console.error('softRefresh morph failed:', err); location.reload(); return; }   // safety net only
      // navbar is outside <main>: update the sync captions by hand
      var src = doc.querySelector('.sync-line');
      if (src) document.querySelectorAll('.sync-line').forEach(function (el) {
        el.dataset.ts = src.dataset.ts;
        el.dataset.full = src.dataset.full;
      });
      renderSyncLines();
      // Swap <main>'s markup for the freshly rendered one. idiomorph left the
      // panel offset by one extra edge after a sync (card x / top gutter 15px
      // -> 30px on a real device); a plain markup swap lands the panel AND the
      // shells on the template's classes with nothing restored. What the morph
      // callbacks used to protect is kept by hand: [data-morph="ignore"]
      // subtrees stay the LIVE nodes, open <details> ride along, and the
      // attendance view choice is re-shown after the swap. (The fetched
      // document is THIS route, so its only panel is the visible one — there
      // is no tab to carry.)
      (function () {
        var mainEl = document.querySelector('main');
        // [data-morph="ignore"] subtrees stay the LIVE nodes. Key on the id
        // when there is one; the avatar wrapper carries none but holds the
        // gaze driver's inline vars, so it is keyed by its class instead.
        var live = {};
        var keyOf = function (el) {
          if (el.id) return '#' + el.id;
          return el.classList.contains('blobatar-gaze') ? '.blobatar-gaze' : null;
        };
        mainEl.querySelectorAll('[data-morph="ignore"]').forEach(function (el) {
          var k = keyOf(el);
          if (k) live[k] = el;
        });
        // live open panels stay the LIVE nodes: the tag form's submit listener
        // and the user's focus ride on them (the old morph kept the node too)
        var openDets = Array.prototype.slice.call(mainEl.querySelectorAll('details[open]'));
        // The swap below DESTROYS every node in <main>, so whatever had focus
        // goes with it and the browser drops focus to <body>. Carry the focused
        // node across the rebuild the same way details[open] is carried: a user
        // who was parked on the graph/table toggle must still be on it after a
        // sync. Keyed by id; a control with no id can't be re-found, so it gets
        // its focus restored by matching selector+position instead.
        var focusEl = document.activeElement;
        var focusKey = (focusEl && focusEl !== document.body && mainEl.contains(focusEl))
          ? (focusEl.id ? '#' + focusEl.id : null) : null;
        var attTable = !!(mainEl.querySelector('#att-table') && !mainEl.querySelector('#att-table').hidden);
        while (mainEl.firstChild) mainEl.removeChild(mainEl.firstChild);
        mainEl.append.apply(mainEl, Array.prototype.slice.call(doc.querySelector('main').childNodes));
        Object.keys(live).forEach(function (k) {
          var fresh = mainEl.querySelector(k);
          if (fresh && fresh !== live[k]) fresh.parentNode.replaceChild(live[k], fresh);
        });
        if (focusKey) {
          var again = mainEl.querySelector(focusKey);
          if (again && document.activeElement === document.body) again.focus();
        }
        openDets.forEach(function (old) {
          var fresh = old.id ? document.getElementById(old.id) : null;
          if (!fresh || fresh === old) return;
          var keepHost = fresh.parentNode;
          keepHost.replaceChild(old, fresh);
          old.open = true;
        });
        if (attTable) {
          var g = mainEl.querySelector('#att-graph'), t = mainEl.querySelector('#att-table');
          if (g && t) { g.hidden = true; t.hidden = false; }
        }
      })();
      setupCopyTargets(document.querySelector('main'));
    })
    .catch(function (err) { console.error('softRefresh fetch failed:', err); location.reload(); });   // safety net only
}

// ── Refresh (all data-refresh buttons) ────────────────────────────
function ref(quiet) {
  var btns = Array.prototype.slice.call(document.querySelectorAll('[data-refresh]'));
  var icons = document.querySelectorAll('.refresh-icon');
  // Disabling any button blurs the focused element to <body>. Remember
  // WHATEVER had focus (not just a refresh button): a user parked on the
  // graph/table toggle was being dropped onto the dock after every sync.
  var hadFocus = document.activeElement && document.activeElement !== document.body
    ? document.activeElement : null;
  // aria-disabled, not the disabled attribute: `disabled` on the focused
  // element forces the browser to blur it to <body> immediately, which is what
  // dropped the user onto the dock mid-sync. aria-disabled keeps focus where it
  // is and still blocks a second click (see the handler below).
  btns.forEach(function(b) { b.setAttribute('aria-disabled', 'true'); b.dataset.busy = '1'; });
  icons.forEach(function(i) { i.classList.add('animate-spin'); });
  document.querySelectorAll('.sync-line').forEach(function(el) { el.textContent = 'Syncing…'; el.classList.remove('hidden'); });
  function restore() {
    btns.forEach(function(b) { b.removeAttribute('aria-disabled'); delete b.dataset.busy; });
    icons.forEach(function(i) { i.classList.remove('animate-spin'); });
    // only pull focus back if it went nowhere; never steal it from a user who
    // moved on during the round trip, and never onto a node that was replaced
    if (hadFocus && hadFocus.isConnected && document.activeElement === document.body) {
      hadFocus.focus();
    }
    renderSyncLines();
  }
  fetch('/api/refresh', {method: 'POST'})
    .then(function (r) {
      // dead session: server 302s API calls to /login; fetch() followed it
      // and r.json() would throw — go to the login page, not "network error".
      if (r.redirected) { location.href = '/login'; return new Promise(function() {}); }
      return r.json();
    })
    .then(function (d) {
      // cached answer (SYNC_MIN_INTERVAL_S): the server's stored data did
      // not change, so restore the UI in place — no reload flash, and the
      // sync-line keeps showing the honest age of the last real sync
      if (d.ok && !d.cached) { softRefresh().then(restore); return; }
      restore();
      if (d.ok) return;
      if (!quiet) showError(d.error || 'Refresh failed');
      else console.debug('background sync failed:', d.error);
    }).catch(function () {
      restore();
      if (!quiet) showError('Network error \u2014 is the server reachable?');
    });
}
document.querySelectorAll('[data-refresh]').forEach(function(b) {
  b.addEventListener('click', function() {
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

// ── Click-to-copy: any element with data-copy gets copied on click (task 10).
//    Values only — keys/labels never carry data-copy.
function flash(el) {
  if (el.dataset.origText === undefined) el.dataset.origText = el.textContent;
  el.textContent = 'Copied!';
  el.classList.add('text-success');
  clearTimeout(el._copyTimer);
  el._copyTimer = setTimeout(function() {
    el.textContent = el.dataset.origText;
    el.classList.remove('text-success');
  }, 1200);
}
function copyText(t, el) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(t).then(function() { flash(el); }).catch(function() {});
  }
}

// Click-to-copy after a soft refresh: copy nodes inside <main> can be
// replaced by the morph (no ids to key on), so the handlers live at
// document level and setupCopyTargets() just re-stamps the a11y/cursor
// attrs on any fresh nodes — idempotent, safe to re-run per morph.
function setupCopyTargets(root) {
  (root || document).querySelectorAll('[data-copy]').forEach(function(el) {
    if (el.dataset.copyReady) return;
    el.dataset.copyReady = '1';
    el.title = el.title || 'Click to copy';
    el.classList.add('cursor-copy');
    // audit a11y: div/span copy targets must be keyboard-operable
    el.setAttribute('tabindex', '0');
    el.setAttribute('role', 'button');
  });
}
setupCopyTargets(document);
document.addEventListener('click', function(ev) {
  var el = ev.target.closest ? ev.target.closest('[data-copy]') : null;
  if (el) { copyText(el.dataset.copy || el.textContent.trim(), el); return; }
  var copyBtn = ev.target.closest ? ev.target.closest('#copyEmail') : null;
  if (!copyBtn) return;
  var email = copyBtn.dataset.email || '';
  function done() {
    var span = copyBtn.querySelector('span');
    var old = span.textContent;
    span.textContent = 'Copied!';
    setTimeout(function() { span.textContent = old; }, 1200);
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(email).then(done).catch(function() { showError('Copy failed'); });
  } else { showError('Clipboard unavailable'); }
});
document.addEventListener('keydown', function(ev) {
  if (ev.key !== 'Enter' && ev.key !== ' ') return;
  var el = ev.target.closest ? ev.target.closest('[data-copy]') : null;
  if (el) { ev.preventDefault(); copyText(el.dataset.copy || el.textContent.trim(), el); }
});

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
//    ponytail: evaluated once at load; rotating across the sm breakpoint
//    keeps whatever state the user has toggled (still fully toggleable).
(function() {
  var groups = document.querySelectorAll('#personal-details .collapse input');
  if (!groups.length) return;
  var wide = window.matchMedia('(min-width: 640px)').matches;
  groups.forEach(function(g, i) { g.checked = wide || i === 0; });
})();

// ── Auto-sync on open: show cached data instantly, refresh quietly in
//    background when stale (>10min). Quiet failures stay silent.
(function() {
  var first = document.querySelector('.sync-line');
  if (!first) return;
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
// #fb-modal, which softRefresh morphs while it is closed — both are
// delegated at document level so post-morph nodes keep working.
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

// ── Marks tag save: fetch + soft refresh (no-JS fallback = plain POST) ──
// The tag forms sit inside <main> and morph on refresh, so the submit is
// delegated. The server returns JSON when the request asks for it and keeps
// the POST/redirect for the no-JS path.
document.addEventListener('submit', function(ev) {
  var f = ev.target;
  if (!(f instanceof HTMLFormElement)) return;
  var action = f.getAttribute('action') || '';
  if (action !== '/marks/tag') return;
  ev.preventDefault();
  fetch('/marks/tag', {method: 'POST', body: new FormData(f),
                       credentials: 'same-origin',
                       headers: {Accept: 'application/json'}})
    .then(function(r) {
      if (r.redirected) { location.href = '/login'; return new Promise(function() {}); }
      return r.json();
    })
    .then(function(j) {
      if (!j.ok) { showError(j.error || 'Tag not saved'); return; }
      softRefresh();
    })
    .catch(function() { showError('Network error — tag not saved'); });
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
//    Poll the status endpoint — bounded, backed off — and soft-refresh the
//    dashboard exactly ONCE when the sync completes (no hard reload: the
//    perf contract keeps location.reload to softRefresh's catch net, and a
//    morph keeps the active tab). The server renders the state as 'complete'
//    after that refresh, so the loop cannot restart: one refresh per
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
  // (it is server-rendered), but a morph from softRefresh re-renders it, so a
  // stale/pending attribute with a completed sync means "done" is behind us.
  var tries = 0, MAX_TRIES = 150, delay = 4000, done = false;
  function poll() {
    if (done || tries++ > MAX_TRIES) return;
    fetch('/api/scope/status', { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.ok) { setTimeout(poll, delay); return; }
        if (d.state === 'complete') { done = true; softRefresh(); return; }
        if (d.state === 'off') { done = true; return; }
        if (tries > 10) delay = 8000;   // back off once the wait gets long
        setTimeout(poll, delay);
      })
      .catch(function () { setTimeout(poll, delay); });
  }
  setTimeout(poll, 1500);
})();
