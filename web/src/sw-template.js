/* OpenSRM service worker — GENERATED. Do not edit app/static/sw.js by hand.
 *
 * Source: web/src/sw-template.js · built by web/workbox-config.js (workbox-build
 * injectManifest) during `pnpm build`. Edit the template, then rebuild.
 *
 * P8.2 is a parity swap: this file performs exactly the policies the previous
 * hand-written worker did, now expressed as Workbox routes.
 */

import { CacheFirst, NetworkFirst } from 'workbox-strategies';
import { clientsClaim } from 'workbox-core';
import { cleanupOutdatedCaches, matchPrecache, precacheAndRoute } from 'workbox-precaching';
import { registerRoute } from 'workbox-routing';
import { ExpirationPlugin } from 'workbox-expiration';

// The name is written as a single-quoted literal by the build (see
// web/workbox-config.js:stampCacheName). Three Python gates regex it —
// tests/e2e/test_sw.py, tests/test_audit_findings L37, scripts/check_docs.py D1 —
// and a template literal would read as `?` to all of them.
//
// The build suffix is derived from the FULL injected manifest (urls + revisions,
// not revisions alone: Workbox sets revision:null for content-hashed files, so
// revisions alone are near-constant across builds). A bundle change therefore
// changes the cache name, which is the property the ?v= generations relied on.
const CACHE_NAME = '__CACHE_NAME__';

// Precache the built bundle. The WB manifest below is the injection point:
// Workbox replaces that token at build time with the file list derived from
// app/static/dist. The list comes from the build (web/workbox-config.js
// globs app/static/dist), never hand-written. Workbox also installs a route that
// serves these entries cache-first and cleans superseded revisions on activate.
precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();

// Navigation preload: the HTML request starts while the worker boots, so a
// controlled page does not pay worker startup latency on its document.
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    if (self.registration.navigationPreload) {
      try {
        const st = await self.registration.navigationPreload.getState();
        if (!st.enabled) await self.registration.navigationPreload.enable();
      } catch (err) { /* preload unsupported: the HTML route just fetches */ }
    }
    // Drop every cache from an earlier generation. Precache entries are
    // repopulated by precacheAndRoute's install step, which ran before this.
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE_NAME && !k.startsWith('workbox-precache')).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});
clientsClaim();

// ── /logout: wipe the cache and this device's push subscription ─────────────
// Cached HTML holds personal data (attendance, marks, profile) and must not
// stay readable on the device after logout. /logout is a plain navigation, so
// this is the only hook we get; server-side the UNIQUE endpoint rebind is the
// safety net if this never runs.
registerRoute(
  ({ url }) => url.pathname === '/logout',
  async ({ request }) => {
    try {
      return await fetch(request);
    } finally {
      caches.delete(CACHE_NAME);
      self.registration.pushManager.getSubscription()
        .then((s) => (s ? s.unsubscribe().catch(() => {}) : null))
        .catch(() => {});
    }
  },
  'GET',
);

// ── Versioned assets (?v=<content-hash> from asset()): cache-first ──────────
// The hash guarantees the bytes under this URL never change, so the cache can
// answer without touching the network — warm visits move zero CSS/JS bytes.
// On store, older ?v= generations of the same pathname are dropped so the
// cache never piles up deploy generations.
const versioned = new CacheFirst({
  cacheName: 'opensrm-versioned',
  matchOptions: { ignoreSearch: false },
  plugins: [
    {
      cachedResponseWillBeUsed: async ({ cacheName, request, cachedResponse }) => cachedResponse,
      // Evict the other ?v= generations of this pathname after a store.
      cacheDidUpdate: async ({ cacheName, request }) => {
        const cache = await caches.open(cacheName);
        const target = new URL(request.url);
        for (const key of await cache.keys()) {
          const u = new URL(key.url);
          if (u.pathname === target.pathname && u.search !== target.search) await cache.delete(key);
        }
      },
    },
    new ExpirationPlugin({ maxEntries: 200, purgeOnQuotaError: true }),
  ],
});
registerRoute(
  ({ url }) => url.pathname.startsWith('/static/') && url.searchParams.get('v'),
  versioned,
  'GET',
);

// ── Vite's content-hashed chunks: cache-first, drop older hashes ─────��──────
// Immutable by construction (the hash IS the content) and the DYNAMIC IMPORTS
// every island loads lazily. They carry no ?v=, so falling through to
// network-first meant every island failed offline with "Failed to fetch
// dynamically imported module".
const HASHLESS = /-[A-Za-z0-9_-]{8,}\.(js|css)$/;
const hashed = new CacheFirst({
  cacheName: 'opensrm-hashed',
  plugins: [
    {
      // Same policy as the ?v= assets: on store, drop older hashes of the same
      // basename so a deploy does not pile generations up.
      cacheDidUpdate: async ({ cacheName, request }) => {
        const cache = await caches.open(cacheName);
        const target = new URL(request.url);
        const base = target.pathname.replace(HASHLESS, '');
        for (const key of await cache.keys()) {
          const u = new URL(key.url);
          if (u.pathname.replace(HASHLESS, '') === base && u.pathname !== target.pathname) await cache.delete(key);
        }
      },
    },
    new ExpirationPlugin({ maxEntries: 200, purgeOnQuotaError: true }),
  ],
});
registerRoute(
  ({ url }) => url.pathname.startsWith('/static/dist/assets/') && HASHLESS.test(url.pathname),
  hashed,
  'GET',
);

// ── Unversioned statics (icons, manifest): network-first, cache fallback ────
// Cache-first once served pre-deploy JS with post-deploy HTML → dead navbar
// until a hard refresh. Network-first keeps HTML and JS from the same deploy;
// the cache still serves offline. Workbox only caches 2xx by default.
registerRoute(
  ({ url }) => url.pathname.startsWith('/static/'),
  new NetworkFirst({ cacheName: 'opensrm-static' }),
  'GET',
);

// ── HTML: network-first; offline gets the SHELL, never a rendered page ──────
// Personal data may live on the device (that is what makes offline work), but
// a rendered page must never be one of the places it lives. The shell is the
// panel's own markup with every personal value blanked server-side, so it is
// the same bytes for every student.
//
// Offline ladder: /shell/<panel> → /shell/dashboard → /shell/ → generic 503.
const OFFLINE_503 = new Response(
  '<html><body style="background:#111;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center"><div><h1>OpenSRM</h1><p>You are offline and this device has no saved copy yet.</p><p>Connect to the internet and open the site once to enable offline access.</p></div></body></html>',
  { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } },
);

async function offlineShell(url) {
  const panel = url.pathname.replace(/^\/+|\/+$/g, '') || 'dashboard';
  for (const path of ['/shell/' + panel, '/shell/dashboard', '/shell/']) {
    const hit = await caches.match(path);
    if (hit) return hit;
  }
  return OFFLINE_503;
}

const html = new NetworkFirst({
  cacheName: 'opensrm-html',
  // Offline must reach the shell ladder, not a cached rendered page: nothing
  // here is ever written to the cache, so a cached response cannot be served.
  plugins: [
    {
      cacheWillUpdate: async () => null,
      handlerDidError: async ({ request }) => offlineShell(new URL(request.url)),
    },
  ],
});

registerRoute(
  ({ request }) => request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html'),
  async (params) => {
    // Navigation preload: use the response started at navigation time.
    const preloaded = params.event && params.event.preloadResponse && await params.event.preloadResponse;
    if (preloaded) return preloaded;
    return html.handle(params);
  },
  'GET',
);

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
