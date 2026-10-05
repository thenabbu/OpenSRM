const CACHE_NAME = 'opensrm-v16';

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(c =>
      c.addAll(['/static/icon-192.png', '/static/icon-512.png', '/static/icon-1024.png', '/static/icon-maskable-512.png', '/static/favicon.ico'])
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Network-only: login, API. Logout is intercepted ONLY to wipe the cache —
  // cached HTML holds personal data (attendance, marks, profile) and must not
  // stay readable on the device after logout.
  if (url.pathname === '/logout') {
    // Also drop this device's push subscription: /logout is a plain
    // navigation, this is the only hook we get. (Server-side the UNIQUE
    // endpoint rebind is the safety net if this never runs.)
    e.respondWith(fetch(e.request).finally(() =>
      Promise.all([
        caches.delete(CACHE_NAME),
        self.registration.pushManager.getSubscription()
          .then(s => (s ? s.unsubscribe().catch(() => {}) : null))
          .catch(() => {})
      ])
    ));
    return;
  }
  if (url.pathname === '/login' || url.pathname.startsWith('/api/')) return;

  // Static assets: network-first with cache fallback.
  // Cache-first once served pre-deploy JS with post-deploy HTML → dead navbar
  // until a hard refresh. Network-first keeps HTML+JS from the same deploy;
  // the cache still serves offline. Only 2xx responses are cached (audit:
  // resp.ok guard) so error pages can never be served as the offline copy.
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      fetch(e.request).then(resp => {
        if (resp.ok) {
          const cl = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, cl));
        }
        return resp;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // HTML pages: network-first, offline fallback
  if (e.request.headers.get('accept')?.includes('text/html')) {
    e.respondWith(
      fetch(e.request).then(resp => {
        if (resp.ok) {
          const cl = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, cl));
        }
        return resp;
      }).catch(() =>
        caches.match(e.request).then(r => r || new Response(
          '<html><body style="background:#111;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center"><div><h1>OpenSRM</h1><p>You are offline and this page was not cached.</p><p>Connect to the internet and try again.</p></div></body></html>',
          { headers: { 'Content-Type': 'text/html' } }
        ))
      )
    );
  }
});


// ── Web push ──────────────────────────────────────────────────────────

function urlB64ToUint8Array(b64) {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4);
  const raw = (b64 + pad).replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(raw);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// Every push MUST produce a visible notification (Chrome userVisibleOnly,
// Safari revokes permission otherwise). Test pushes additionally report a
// receipt so the server can prove on-device arrival — the receipt runs
// AFTER showNotification starts, never instead of it.
async function handlePush(event) {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (err) {
    data = { title: 'OpenSRM', body: event.data ? event.data.text() : '' };
  }
  const opts = {
    body: data.body || '',
    tag: data.tag || 'opensrm-reminder',
    renotify: true,                       // updated reminder re-alerts (Android)
    icon: '/static/icon-192.png',         // brand tile
    badge: '/static/icon-badge.png',      // white silhouette for the status bar
    data: { url: data.url || '/' }
  };
  if (data.image) opts.image = data.image;   // hero banner (logo-rect) on reminders
  const shown = self.registration.showNotification(data.title || 'OpenSRM', opts);
  let receipt = null;
  if (data.test_id) {
    receipt = shown.then(() => fetch('/api/push/receipt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ test_id: data.test_id })
    }).catch(() => {}));
  }
  event.waitUntil(receipt ? Promise.all([shown, receipt]) : shown);
}

async function handleNotificationClick(event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  for (const c of windows) {
    if ('focus' in c) {
      // focus() can throw InvalidAccessError (window not focusable) — fall
      // through to openWindow instead of failing the whole click.
      try {
        await c.focus();
        if (url && url !== '/' && 'navigate' in c) {
          try { await c.navigate(url); } catch (err) { /* focus alone is fine */ }
        }
        return;
      } catch (err) { /* open a fresh window below */ }
    }
  }
  // openWindow needs user activation — real notificationclick has it; if the
  // browser refuses anyway there is nothing left to do, don't fail the handler.
  try { await self.clients.openWindow(url); } catch (err) { /* done */ }
}

// Browser invalidated the subscription (rotation/expiry): re-subscribe with
// the same VAPID key and re-register server-side. Best effort — the
// dashboard also re-syncs on load.
self.addEventListener('pushsubscriptionchange', e => {
  e.waitUntil((async () => {
    try {
      const st = await (await fetch('/api/push/status')).json();
      if (!st.ok || !st.vapid_public_key) return;
      const sub = await self.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlB64ToUint8Array(st.vapid_public_key)
      });
      const payload = sub.toJSON();
      payload.ua_label = 'resubscribed';
      await fetch('/api/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } catch (err) { /* best effort */ }
  })());
});

self.addEventListener('push', e => handlePush(e));
self.addEventListener('notificationclick', e => e.waitUntil(handleNotificationClick(e)));
