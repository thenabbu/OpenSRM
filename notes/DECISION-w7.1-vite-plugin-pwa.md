# Decision: keep `workbox-build`; do not move the service worker to `vite-plugin-pwa`

**Status:** proposed — **no migration.** The experiment is the evidence, not the argument.
**Date:** 2026-11-17 · **Task:** W7.1 (`RECOVERY_PLAN.md:206`, "an experiment with a
decision at the end, and 'no' is an acceptable answer").

## The question

With `strategies:'injectManifest'`, `registerType:'prompt'` and no `navigateFallback`,
does the plugin reproduce today's worker — the same served URL and scope, the privacy
rules as code, the SHELL cache behaviour, and the logout wipe?

## Answer

**Runtime behaviour: yes, proved. As a migration: no.**

Both workers were built from the same `web/src/sw-template.js` at `c1a5ed1` and graded
by the network-cut suite in `tests/e2e/test_offline_routes.py`:

| build | result |
|---|---|
| committed worker (control) | 74/74 PASS |
| plugin worker, faithful dist, `manifest:false` | 74/74 PASS |
| plugin worker, plugin default webmanifest injection | A0 FAIL + 16 legs, `ERR_INTERNET_DISCONNECTED` |

`injectManifest` never rewrites the worker template, so the privacy plugins, the 503
ladder, the `opensrm-shell` keep-list and the logout route all survive verbatim. That is
the half the plugin cannot break — and also the half it does not provide.

## What the plugin does not reproduce

1. **Served URL and scope.** The plugin writes `<build.outDir>/sw.js`
   (`/static/dist/sw.js`) and registers relative to `base`, i.e. scope `/static/dist/`.
   Today: `/static/sw.js` at scope `/` (`web/src/data/pageChrome.ts:191`,
   `app/static/login.js:112`) plus Flask's `Service-Worker-Allowed: /`
   (`app/app.py:833`). Parity needs `outDir:'../app/static'` **and** a rename, because
   the plugin's output name is its source name — it emits `sw-template.js`.
2. **A working install, by default.** The plugin precaches a bare relative
   `manifest.webmanifest`, which resolves to `/static/manifest.webmanifest` → 404 →
   the Workbox install rejects and no worker ever activates. Only `manifest:false`
   restores the 15 clean `/static/dist/…` entries.
3. **The per-build cache name.** esbuild emits ``const ke=`__CACHE_NAME__` ``, and the
   existing `stampCacheName()` matches only `'`/`"`, so it throws. Shipped unstamped,
   `tests/unit/test_audit_findings.py` raises `SystemExit("L37/D58 cannot run")` and no
   deploy invalidates caches. The post-build node step therefore stays anyway.
4. **The `GENERATED, do not edit` banner** — stripped by the vite build.
5. **The update signal.** With `injectRegister:null` (mandatory — registration is ours)
   the plugin emits *no* registration code: no `registerSW.js`, no `workbox-window` in
   any asset. So `registerType:'prompt'` has zero effect, and the "new version" signal
   remains the `controllerchange` watcher in `web/src/pwa/update.ts`. A worker that
   calls `skipWaiting()` on install never sits in `waiting`; `prompt` neither waits nor
   prompts here.
6. **It costs six dependencies.** pnpm's isolated `node_modules` cannot resolve
   `workbox-strategies` from `web/src` (the reason `web/workbox-config.js` uses
   `createRequire` from `workbox-build`'s tree), so `vite-plugin-pwa` plus five
   `workbox-*` packages must become direct devDeps.

## Consequence

Net: delete ~60 lines of bundling plumbing; add 6 devDeps, 4 config escapes, a rename
and two post-build steps; ship two regressions — for zero user-visible change. Per the
plan, this decision does **not** block W7.2–W7.5. Reopen if a second worker ever needs
bundling, or if the plugin ships an official out-of-`outDir` worker plus a post-build
hook.

## Unrelated finding worth its own card

`srm.200871.xyz` serves `/static/sw.js` with `cache-control: max-age=14400` — the edge
overrides the app's `no-cache`, so a new worker can lag up to four hours. That is a
W7.3 concern and is true today, whatever builds the worker.
