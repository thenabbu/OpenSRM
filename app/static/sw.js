const CACHE_NAME = 'opensrm-v68';

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(c =>
      c.addAll(['/static/icon-192.png', '/static/icon-512.png', '/static/icon-1024.png', '/static/icon-maskable-512.png', '/static/favicon.ico'])
    ).then(() => self.skipWaiting())
  );
});

// Precache the BUILT BUNDLE at activate time, from Vite's own manifest.
//
// Why here and not from the page: the page can only fetch a chunk through this
// worker, and this worker only stores a chunk when it gets one from the NETWORK
// (cache-first branch, cache miss path). A fetch issued once the entry has
// already been served from cache therefore never populates anything. Doing it
// in the worker is the one place the list is authoritative and the fetch is
// guaranteed to reach the network.
//
// This is what makes offline actually paint: the entry (app-<hash>.js) and its
// shared deps are imported by every island chunk, so ONE missing file fails
// every dynamic import with "Failed to fetch dynamically imported module" —
// exactly what happened while the shell, the netid and the rows were all fine.
async function precacheBundle() {
  try {
    const res = await fetch('/static/dist/manifest.json', { cache: 'no-store' });
    // Visible from the page via the client postMessage below and from DevTools:
    // without it, "did activate even run the precache?" is unanswerable, which is
    // exactly the hole this cost.
    self.clients.matchAll().then(cs => cs.forEach(c => c.postMessage({ precache: 'start', status: res.status })));
    if (!res.ok) return;
    const manifest = await res.json();
    const files = Object.values(manifest)
      .map(v => v && v.file)
      .filter(f => typeof f === 'string' && /\.(js|css)$/.test(f));
    const urls = [...new Set(files)].map(f => '/static/dist/' + f);
    const cache = await caches.open(CACHE_NAME);
    await Promise.all(urls.map(async u => {
      try {
        const r = await fetch(u, { cache: 'reload' });
        if (r.ok) await cache.put(u, r);
      } catch (err) { /* one missing file degrades one island, not the app */ }
    }));
    self.clients.matchAll().then(cs => cs.forEach(c => c.postMessage({ precache: 'done', files: urls.length })));
  } catch (err) { /* no manifest (dev build / first deploy): skip */ }
}

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    // Navigation preload: the HTML request starts while the SW boots, so a
    // controlled page doesn't pay worker startup latency on its document.
    if (self.registration.navigationPreload) {
      try {
        const st = await self.registration.navigationPreload.getState();
        if (!st.enabled) await self.registration.navigationPreload.enable();
      } catch (err) { /* preload unsupported: the HTML branch just fetches */ }
    }
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)));
    await precacheBundle();
    await self.clients.claim();
  })());
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

  // Versioned assets (?v=<content-hash> from asset()): CACHE-FIRST. The
  // hash guarantees the bytes under this URL never change, so the cache can
  // answer without touching the network — warm visits move zero CSS/JS
  // bytes. On store, older ?v= generations of the same pathname are deleted
  // so the cache never piles up deploy generations. Offline: a cached
  // version still answers.
  // Vite's content-hashed chunks: /static/dist/assets/<Name>-<hash>.js
  //
  // These are immutable by construction (the hash IS the content), and they are
  // the DYNAMIC IMPORTS every island loads lazily. They carry no ?v= param, so
  // before this branch existed they fell through to network-first, failed
  // offline, and every island reported "Failed to fetch dynamically imported
  // module" — the shell loaded, the netid was recovered, the cached rows were
  // sitting in IndexedDB, and the panel still painted nothing because the
  // component could not be fetched.
  //
  // Same policy as the ?v= assets: cache-first, and on store drop older hashes
  // of the same basename so a deploy does not pile generations up.
  if (url.pathname.startsWith('/static/dist/assets/') && /-[A-Za-z0-9_-]{8,}\.(js|css)$/.test(url.pathname)) {
    e.respondWith((async () => {
      const hit = await caches.match(e.request);
      if (hit) return hit;
      try {
        const resp = await fetch(e.request);
        if (resp.ok) {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(e.request, resp.clone());
          const base = url.pathname.replace(/-[A-Za-z0-9_-]{8,}\.(js|css)$/, '');
          const keys = await cache.keys();
          await Promise.all(keys.map(k => {
            const ku = new URL(k.url);
            return (ku.pathname.replace(/-[A-Za-z0-9_-]{8,}\.(js|css)$/, '') === base
                    && ku.pathname !== url.pathname)
              ? cache.delete(k) : null;
          }));
        }
        return resp;
      } catch (err) {
        const stale = await caches.match(e.request);
        if (stale) return stale;
        throw err;
      }
    })());
    return;
  }

  if (url.pathname.startsWith('/static/') && url.searchParams.get('v')) {
    e.respondWith((async () => {
      const hit = await caches.match(e.request);
      if (hit) return hit;
      try {
        const resp = await fetch(e.request);
        if (resp.ok) {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(e.request, resp.clone());
          const keys = await cache.keys();
          await Promise.all(keys.map(k => {
            const ku = new URL(k.url);
            return (ku.pathname === url.pathname && ku.search !== url.search)
              ? cache.delete(k) : null;
          }));
        }
        return resp;
      } catch (err) {
        const stale = await caches.match(e.request);
        if (stale) return stale;
        throw err;
      }
    })());
    return;
  }

  // Unversioned static assets (icons, manifest): network-first with cache
  // fallback. Cache-first once served pre-deploy JS with post-deploy HTML →
  // dead navbar until a hard refresh. Network-first keeps HTML+JS from the
  // same deploy; the cache still serves offline. Only 2xx responses are
  // cached (audit: resp.ok guard) so error pages can never be served as the
  // offline copy.
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

  // HTML pages: network-first, and offline gets the SHELL — never a rendered
  // page. This is the design Navya set on 2026-11-09: personal data may live on
  // the device (that is what makes offline work), but the app must remove it
  // completely on logout, and a rendered page must never be one of the places
  // it lives. The shell is the panel's own markup with every personal value
  // blanked server-side (/shell/<panel>, app/views/dashboard.py:shell()), so it
  // is the same bytes for every student and safe to keep in this cache.
  //
  // Offline flow: serve shell -> islands mount with no props -> each asks
  // IndexedDB for ITS OWN netid's rows -> a different student simply misses.
  if (e.request.headers.get('accept')?.includes('text/html')) {
    e.respondWith((async () => {
      try {
        const preloaded = await e.preloadResponse;
        if (preloaded) return preloaded;
        return await fetch(e.request);
      } catch (err) {
        // Offline. Which panel? Ask from the URL, so an offline visit to
        // /marks gets the marks shell rather than the dashboard one.
        const panel = (url.pathname.replace(/^\/+|\/+$/g, '') || 'dashboard');
        const shell = await caches.match('/shell/' + panel)
                   || await caches.match('/shell/dashboard')
                   || await caches.match('/shell/');
        if (shell) return shell;
        return new Response(
          '<html><body style="background:#111;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center"><div><h1>OpenSRM</h1><p>You are offline and this device has no saved copy yet.</p><p>Connect to the internet and open the site once to enable offline access.</p></div></body></html>',
          { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      }
    })());
    return;
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
    icon: '/static/icon-192.png',         // large icon (brand tile)
    badge: '/static/icon-badge.png',      // Android small icon: white mark,
                                          // alpha-defined, circle-mask safe
    data: { url: data.url || '/' }
  };
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
