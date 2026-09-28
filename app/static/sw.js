const CACHE_NAME = 'opensrm-v13';

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
    e.respondWith(fetch(e.request).finally(() => caches.delete(CACHE_NAME)));
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
