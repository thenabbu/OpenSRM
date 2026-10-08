// Error toast helper (global — used by timetable.js too)
function showError(msg) {
  var t = document.getElementById('error-toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.remove('hidden');
  setTimeout(function() { t.classList.add('hidden'); }, 5000);
}

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

// ── Refresh (all data-refresh buttons) ────────────────────────────
function ref(quiet) {
  var btns = Array.prototype.slice.call(document.querySelectorAll('[data-refresh]'));
  var icons = document.querySelectorAll('.refresh-icon');
  btns.forEach(function(b) { b.disabled = true; });
  icons.forEach(function(i) { i.classList.add('animate-spin'); });
  document.querySelectorAll('.sync-line').forEach(function(el) { el.textContent = 'Syncing…'; el.classList.remove('hidden'); });
  if (!quiet) document.getElementById('overlay').showModal();
  fetch('/api/refresh', {method: 'POST'})
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.ok) { location.reload(); return; }
      document.getElementById('overlay').close();
      btns.forEach(function(b) { b.disabled = false; });
      icons.forEach(function(i) { i.classList.remove('animate-spin'); });
      renderSyncLines();
      if (!quiet) showError(d.error || 'Refresh failed');
      else console.debug('background sync failed:', d.error);
    }).catch(function () {
      document.getElementById('overlay').close();
      btns.forEach(function(b) { b.disabled = false; });
      icons.forEach(function(i) { i.classList.remove('animate-spin'); });
      renderSyncLines();
      if (!quiet) showError('Network error \u2014 is the server reachable?');
    });
}
document.querySelectorAll('[data-refresh]').forEach(function(b) {
  b.addEventListener('click', function() { ref(false); });
});

// ── Tabs (desktop navbar + mobile dock) ───────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll('[data-tabpanel]').forEach(function(p) {
    var show = (p.id === 'tab-' + name);
    if (show && p.style.display === 'none') {
      p.style.display = '';
      p.classList.add('tab-enter');
      void p.offsetHeight;   // start from the invisible state, then let CSS transition in
      p.classList.remove('tab-enter');
    } else if (!show) {
      p.style.display = 'none';
    }
  });
  document.querySelectorAll('[data-tab]').forEach(function(b) {
    var on = (b === btn) || (b.dataset.tab === name && !btn);
    b.classList.toggle('tab-active', on);   // navbar buttons
    b.classList.toggle('dock-active', on);  // dock items
    b.classList.toggle('btn-active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
    if (b.hasAttribute('aria-current')) b.setAttribute('aria-current', on ? 'page' : 'false');
    b.tabIndex = on ? 0 : -1;
  });
  if (history.replaceState) history.replaceState(null, '', '#' + name);
  if (btn && btn.offsetParent) btn.focus();
}
var tabButtons = Array.prototype.slice.call(document.querySelectorAll('[data-tab]'));
tabButtons.forEach(function(b) {
  b.addEventListener('click', function() { switchTab(b.dataset.tab, b); });
  b.addEventListener('keydown', function(e) {
    // cycle within the visible nav set (navbar OR dock), not across both
    var vis = tabButtons.filter(function(x) { return x.offsetParent !== null; });
    var idx = vis.indexOf(b), next = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = vis[(idx + 1) % vis.length];
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = vis[(idx - 1 + vis.length) % vis.length];
    else if (e.key === 'Home') next = vis[0];
    else if (e.key === 'End') next = vis[vis.length - 1];
    if (next) { e.preventDefault(); switchTab(next.dataset.tab, next); }
  });
});
// Restore tab from hash (survives refresh/reload); default dashboard
(function() {
  var h = (location.hash || '').replace('#', '');
  var valid = document.getElementById('tab-' + h);
  switchTab(valid ? h : 'dashboard');
})();

// ── Click-to-copy: any element with data-copy gets copied on click (task 10).
//    Values only — keys/labels never carry data-copy.
(function() {
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
  // Static listeners for server-rendered values
  document.querySelectorAll('[data-copy]').forEach(function(el) {
    el.title = el.title || 'Click to copy';
    el.classList.add('cursor-copy');
    // audit a11y: div/span copy targets must be keyboard-operable
    el.setAttribute('tabindex', '0');
    el.setAttribute('role', 'button');
    function trigger() {
      copyText(el.dataset.copy || el.textContent.trim(), el);
    }
    el.addEventListener('click', trigger);
    el.addEventListener('keydown', function(ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); trigger(); }
    });
  });
  // Copy email button keeps its icon feedback
  var copyBtn = document.getElementById('copyEmail');
  if (copyBtn) copyBtn.addEventListener('click', function() {
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
})();

// ── Personal groups: all open on desktop (dense fact-sheet scan), first
//    group only on mobile (compact lookup — matches the design mockup).
//    ponytail: evaluated once at load; rotating across the sm breakpoint
//    keeps whatever state the user has toggled (still fully toggleable).
(function() {
  var groups = document.querySelectorAll('#tab-personal .collapse input');
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

// audit: register here too — a valid session lands on / directly and never
// loads /login, so login.js alone would never register the SW for those users.
if ("serviceWorker" in navigator && location.pathname !== "/login") {
  navigator.serviceWorker.register("/static/sw.js", {scope: "/"}).catch(function(){});
}

// ── Mid-sem feedback (OPT-IN auto-fill) ─────────────────────────────
// CTA opens the explainer modal; ONLY the confirm button inside the modal
// writes to the portal (sync harvests read-only). Same builder rendered the
// modal list, so what the student saw IS what gets sent.
var fbCta = document.getElementById('fb-cta');
var fbSubmit = document.getElementById('fb-submit');
if (fbCta) {
  fbCta.addEventListener('click', function() { document.getElementById('fb-modal').showModal(); });
}
if (fbSubmit) {
  fbSubmit.addEventListener('click', function() {
    var status = document.getElementById('fb-status');
    fbSubmit.disabled = true;
    status.textContent = 'Submitting to the portal…';
    status.className = 'mt-2 text-xs text-base-content/70';
    fetch('/api/feedback/fill', {method: 'POST'})
      .then(function(r) { return r.json(); })
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
