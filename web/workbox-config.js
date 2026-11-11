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
// generateSW replaces the whole file and would drop all three.
import { injectManifest } from 'workbox-build';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

export const config = {
  swSrc: 'src/sw-template.js',
  swDest: '../app/static/sw.js',
  globDirectory: '../app/static',
  // The Vite bundle only. Everything else under app/static keeps its existing
  // runtime policy (versioned = cache-first, unversioned = network-first);
  // precaching hand-written JS/CSS here would change behaviour, not keep it.
  globPatterns: ['dist/assets/*.{js,css}', 'dist/manifest.json'],
  modifyURLPrefix: { 'dist/': '/static/dist/' },
  // Vite's file names already carry the content hash, so no ?__WB_REVISION
  // query is needed — the hash IS the revision.
  dontCacheBustURLsMatching: /-[A-Za-z0-9_-]{8,}\./,
  maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
};

// The cache name must change when the build changes. Workbox sets
// revision:null for the content-hashed assets, so revisions alone are nearly
// constant — hash the whole injected manifest (urls included) instead.
//
// It is written as a single-quoted literal because tests/e2e/test_sw.py,
// tests/test_audit_findings.py (L37) and scripts/check_docs.py (D1) all regex
// `CACHE_NAME = '<name>'` out of the built file.
export async function stampCacheName(swDest = config.swDest) {
  const src = await readFile(swDest, 'utf8');
  // Workbox injects inline, so the list sits inside precacheAndRoute([...]).
  const m = src.match(/precacheAndRoute\((\[.*?\])\)/s);
  if (!m) throw new Error('workbox: no injected manifest found in ' + swDest);
  const manifest = JSON.parse(m[1]);

  // Hash the URL list AND the bytes on disk. Workbox's own `revision` field is
  // null for content-hashed files (dontCacheBustURLsMatching), so trusting it
  // makes the cache name blind to a bundle that changed shape in place — which
  // is exactly the kind of edit a hand-patched dist produces.
  const root = new URL('../app/static/', import.meta.url);
  const parts = [];
  for (const entry of [...manifest].sort((a, b) => a.url.localeCompare(b.url))) {
    const rel = entry.url.replace(/^\/static\//, '');
    const bytes = await readFile(new URL(rel, root)).catch(() => Buffer.alloc(0));
    parts.push(`${entry.url}@${entry.revision ?? ''}@${createHash('sha256').update(bytes).digest('hex')}`);
  }
  const hash = createHash('sha256').update(parts.join('|')).digest('hex').slice(0, 8);
  const stamped = src.replace("'__CACHE_NAME__'", `'opensrm-v69-${hash}'`);
  if (stamped === src) throw new Error('workbox: CACHE_NAME placeholder missing in ' + swDest);
  await writeFile(swDest, stamped);
  return `opensrm-v69-${hash}`;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  injectManifest(config)
    .then(async ({ count, size, warnings }) => {
      warnings.forEach((w) => console.warn('workbox: ' + w));
      const name = await stampCacheName();
      console.log(`workbox: precached ${count} files, ${size} bytes -> ${config.swDest}`);
      console.log(`workbox: cache name ${name}`);
    })
    .catch((e) => { console.error(e); process.exit(1); });
}
