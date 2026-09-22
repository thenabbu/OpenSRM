const CACHE_NAME = 'opensrm-v9';

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

  // Network-only: login, logout, API
  if (url.pathname === '/login' || url.pathname === '/logout' ||
      url.pathname.startsWith('/api/')) return;

  // Static assets: cache-first
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(e.request).then(r =>
        r || fetch(e.request).then(resp => {
          const cl = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, cl));
          return resp;
        })
      )
    );
    return;
  }

  // HTML pages: network-first, offline fallback
  if (e.request.headers.get('accept')?.includes('text/html')) {
    e.respondWith(
      fetch(e.request).then(resp => {
        const cl = resp.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, cl));
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
