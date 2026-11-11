// Workbox build config for the OpenSRM service worker.
//
// Parity swap only (P8.2): the emitted worker must do exactly what the
// hand-written one did. Nothing here adds caching behaviour.
//
// injectManifest, not generateSW: the worker still owns three things Workbox
// routes cannot express —
//   * /logout wipes every cache AND unsubscribes this device's push sub;
//   * push / notificationclick / pushsubscriptionchange handlers;
//   * the panel-shell-then-dashboard-then-503 offline ladder.
// generateSW would replace the whole file and drop all three. injectManifest
// keeps src/sw-template.js as the source of truth and injects the precache
// manifest the build derives from app/static/dist — the point of the swap.
import { injectManifest } from 'workbox-build';

export const config = {
  swSrc: 'src/sw-template.js',
  swDest: '../app/static/sw.js',
  globDirectory: '../app/static',
  // The Vite bundle only. Everything else under app/static keeps its existing
  // runtime policy (versioned = cache-first, unversioned = network-first);
  // precaching hand-written JS/CSS here would change behaviour, not preserve it.
  globPatterns: ['dist/assets/*.{js,css}', 'dist/manifest.json'],
  // Revision derives from CONTENT, so the injected manifest — and the cache
  // name built from it — change whenever the bundle changes.
  modifyURLPrefix: { 'dist/': '/static/dist/' },
  dontCacheBustURLsMatching: /-[A-Za-z0-9_-]{8,}\./,
  maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
};

if (import.meta.url === `file://${process.argv[1]}`) {
  injectManifest(config).then(({ count, size, warnings }) => {
    warnings.forEach((w) => console.warn('workbox: ' + w));
    console.log(`workbox: precached ${count} files, ${size} bytes -> ${config.swDest}`);
  }).catch((e) => { console.error(e); process.exit(1); });
}
