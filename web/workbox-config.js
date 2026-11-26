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

// ── Bundle the template first ────────────────────────────────────────────────
// injectManifest only injects the precache list into swSrc; it never bundles.
// A template with bare `workbox-*` imports therefore ships verbatim into a file
// the browser cannot resolve under CSP script-src 'self' (no import map), the
// module fails to evaluate, and no worker installs.
//
// Rollup is already in workbox-build's dependency tree (its deps include rollup
// + @rollup/plugin-node-resolve), so the bundler is a build-time tool that is
// ALREADY installed — no new dependency. pnpm's isolated node_modules hides it
// from this file, so resolve the real workbox-build path and require from there.
// ponytail: rollup only; a second Vite pass would drag in a second plugin graph.
// Built next to the emitted worker, not in src/: it is regenerated on every
// build, so it must not show up as a source file anyone edits.
const BUNDLE = '../app/static/.sw-bundled.js';

async function loadFromWorkbox(spec) {
  const { createRequire } = await import('node:module');
  const { realpathSync } = await import('node:fs');
  // The pnpm symlink is not the resolution root: the real dir is, because its
  // sibling node_modules/ holds rollup and the workbox-* runtime packages.
  const req = createRequire(new URL('workbox-build/package.json', import.meta.url));
  const pkg = realpathSync(req.resolve('workbox-build/package.json'));
  const fromWorkbox = createRequire(pkg);
  return { module: await import(new URL('file://' + fromWorkbox.resolve(spec)).href), root: pkg };
}

export async function bundleSw(src = 'src/sw-template.js', dest = BUNDLE) {
  const rollup = await loadFromWorkbox('rollup');
  const plugin = await loadFromWorkbox('@rollup/plugin-node-resolve');
  // Minified: un-minified workbox runtime is ~184 KB here vs a 13 KB
  // hand-written predecessor. output.intro restores the template's own header —
  // the "GENERATED, do not edit" banner must survive into the emitted worker.
  const header = (await readFile(src, 'utf8')).match(/^\/\*[\s\S]*?\*\//)[0];
  const bundle = await rollup.module.rollup({
    input: src,
    // Resolve the worker's imports from workbox-build's tree, not from ./src —
    // the workbox-* runtime packages are workbox-build's deps.
    plugins: [
      plugin.module.nodeResolve({ modulePaths: [new URL('../', 'file://' + plugin.root).pathname] }),
      // workbox-core ships `process.env.NODE_ENV` guards. Vite replaces those in
      // the main bundle; this hand-rolled rollup does not, so the literal
      // `process.env.NODE_ENV` survived into the emitted worker. A service worker
      // has no `process`, so the script threw ReferenceError the moment the
      // browser evaluated it and the registration failed with
      // "ServiceWorker script evaluation failed" — no worker, no cache, no
      // offline. Strip them here; production semantics are the only semantics a
      // shipped worker needs.
      {
        name: 'define-node-env',
        transform(code) {
          if (!code.includes('process.env.NODE_ENV')) return null;
          return { code: code.replaceAll('process.env.NODE_ENV', '"production"'), map: null };
        },
      },
    ],
  });
  // format:'iife', not 'es': the page registers this worker WITHOUT
  // {type:'module'} (app/static/dash.js:415, login.js:112, push.js:62), so the
  // browser parses it as a CLASSIC script — top-level `import`/`export` is a
  // SyntaxError there even with every dependency inlined. IIFE yields one
  // self-contained classic script with zero bare imports.
  //
  // No `intro`: rollup places intro INSIDE the IIFE wrapper, which buried the
  // "GENERATED, do not edit" banner one level deep (and in the emitted swDest
  // it ends up past column 0, so a `^/\*` scan misses it). Prepend it after.
  const { output } = await bundle.generate({ format: 'iife', inlineDynamicImports: true });
  await bundle.close();
  const code = output.filter((o) => o.type === 'chunk').map((o) => o.code).join('\n');
  const bare = code.split('\n').filter((l) => /^import .*from '[a-z]/.test(l));
  if (bare.length) throw new Error('workbox: sw bundle still has bare imports: ' + bare.join(' | '));
  // The bare-import count alone does NOT prove the file parses as a classic
  // script (an `es` bundle has no bare imports but still carries `export`).
  // Registration is classic, so any module syntax here is a dead worker.
  const modSyntax = code.split('\n').filter((l) => /^(import|export)\b/.test(l));
  if (modSyntax.length) throw new Error('workbox: sw bundle has module syntax (registered classic): ' + modSyntax.join(' | '));
  const terser = (await loadFromWorkbox('terser')).module;
  // terser is CJS: the ESM namespace puts the API under .default
  const { code: min } = await (terser.minify ?? terser.default.minify)(code, {
    format: { comments: /GENERATED/ },
    // Three Python gates scrape the built worker by name:
    //   tests/e2e/test_sw.py + scripts/check_docs.py (D1) -> `CACHE_NAME = '<name>'`
    //   tests/test_audit_findings.py (L37)              -> `precacheAndRoute(`
    // Terser renames both by default (`const CACHE_NAME` became `const se`), which
    // would silently un-gate the cache-name invariant instead of failing it.
    mangle: { reserved: ['CACHE_NAME', 'precacheAndRoute', 'offlineShell'] },
  });
  await writeFile(dest, header + '\n' + min);
  return { dest, bytes: min.length };
}

export const config = {
  swSrc: BUNDLE,
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
  // Terser is told to reserve that identifier, but the template's call site is
  // still renamed in practice — `precacheAndRoute(` was absent from the built
  // worker while `CACHE_NAME` survived. Rather than depend on a name, find the
  // injected manifest by its own shape: Workbox writes a JSON array whose
  // entries carry "revision". That survives minification because the data does.
  let manifest;
  const named = src.match(/precacheAndRoute\((\[.*?\])\)/s);
  if (named) {
    manifest = JSON.parse(named[1]);
  } else {
    const arr = src.match(/\[\{[^[\]]*?"revision".*?\}\s*\]/s);
    if (!arr) throw new Error('workbox: no injected manifest found in ' + swDest);
    manifest = JSON.parse(arr[0]);
  }
  if (!Array.isArray(manifest) || manifest.length === 0) {
    throw new Error('workbox: injected manifest is empty in ' + swDest);
  }

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
  // terser normalises string quotes to double quotes, so the template's
  // `'__CACHE_NAME__'` arrives here as `"__CACHE_NAME__"`. Match either form —
  // searching only for the single-quoted literal silently never stamps and the
  // build dies with "CACHE_NAME placeholder missing".
  const placeholder = /(['"])__CACHE_NAME__\1/;
  if (!placeholder.test(src)) throw new Error('workbox: CACHE_NAME placeholder missing in ' + swDest);
  const stamped = src.replace(placeholder, `'opensrm-v69-${hash}'`);
  await writeFile(swDest, stamped);
  return `opensrm-v69-${hash}`;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  bundleSw()
    .then((b) => {
      console.log(`workbox: bundled ${b.dest} (${b.bytes} bytes, 0 bare imports)`);
      return injectManifest(config);
    })
    .then(async ({ count, size, warnings }) => {
      warnings.forEach((w) => console.warn('workbox: ' + w));
      const name = await stampCacheName();
      console.log(`workbox: precached ${count} files, ${size} bytes -> ${config.swDest}`);
      console.log(`workbox: cache name ${name}`);
    })
    .catch((e) => { console.error(e); process.exit(1); });
}
