/**
 * Warm the offline shell while the student is online.
 *
 * The service worker can only serve a shell it already has, and it cannot fetch
 * one at install time: the shell route needs a session, and at install nobody
 * has logged in yet. So the app asks for the panels' shells AFTER the page has
 * loaded, when the cookie is present.
 *
 * Why the shells are safe to keep in the Cache API at all: `/shell/<panel>`
 * renders the real panel markup with the view model emptied
 * (app/views/dashboard.py:shell()), so the bytes are identical for every
 * student. Rows never go in this cache — they live in IndexedDB keyed by netid,
 * and logout clears both.
 */

/** Panels worth a shell. `settings` is excluded on purpose: it is identity data
 *  with no cached rows behind it, so an offline settings page would show an
 *  empty form — worse than the honest "no saved copy" state. */
const SHELL_PANELS = [
  'dashboard',
  'attendance',
  'timetable',
  'marks',
  'campus',
  'academics',
  'fees',
  'tools',
] as const;

const SHELL_CACHE = 'opensrm-shell';

const log = (msg: string, e?: unknown): void =>
  console.warn(`[shell] ${msg}`, e instanceof Error ? e.message : (e ?? ''));

/**
 * Fetch each panel shell and put it in the shell cache, one at a time.
 *
 * Sequential on purpose: eight parallel HTML fetches compete with the real page
 * load for the browser's connection budget, and this runs immediately after
 * first paint. A failure is logged and skipped — a missing shell degrades to the
 * existing "offline and no saved copy" page, never to a broken app.
 */
/**
 * Warm the island CHUNKS through the service worker.
 *
 * The SW caches hashed chunks on first request (sw.js, the
 * /static/dist/assets/ branch), but a lazy import that happens BEFORE the
 * worker controls the page never passes through it — so the chunk is never
 * cached, and the next offline visit dies with "Failed to fetch dynamically
 * imported module" even though the shell and the rows are both present.
 *
 * The chunk list comes from Vite's own manifest, served at
 * /static/dist/manifest.json. Probing window.__vite__mapDeps looked
 * clever and returned the WRONG hashes: it is keyed by import index, so a
 * mistyped range silently warms chunks that no longer exist.
 */
/** Surface the warm result on window for the offline DUT: console events from a
 *  page that navigates are dropped by Playwright, so a log is not evidence. */
function expose(diag: string[], verdict: string): void {
  try {
    (window as unknown as { __shellWarm?: unknown }).__shellWarm = { verdict, diag };
  } catch {
    // non-browser context (unit tests): nothing to expose
  }
}

async function warmChunks(): Promise<number> {
  if (typeof caches === 'undefined' || !navigator.onLine) return 0;
  if (!navigator.serviceWorker?.controller) return 0;   // nothing would cache them
  try {
    const res = await fetch('/static/dist/manifest.json', { credentials: 'same-origin' });
    if (!res.ok) return 0;
    const manifest = (await res.json()) as Record<string, { file?: string }>;
    const files = Object.values(manifest)
      .map((v) => v.file)
      .filter((f): f is string => typeof f === 'string' && f.endsWith('.js'));
    let n = 0;
    for (const f of new Set(files)) {
      try {
        const r = await fetch(`/static/dist/${f}`, { credentials: 'same-origin' });
        if (r.ok) n += 1;
      } catch {
        // a missing chunk degrades that one island offline, nothing else
      }
    }
    return n;
  } catch (err) {
    log('chunk warm failed', err);
    return 0;
  }
}

export async function warmShells(): Promise<number> {
  const diag: string[] = [`start ctrl=${!!navigator.serviceWorker?.controller} online=${navigator.onLine}`];
  if (typeof caches === 'undefined' || !navigator.onLine) { expose(diag, 'bailed: caches or offline'); return 0; }
  // No owner, nothing to warm. A shell is the page the SW serves for the NEXT
  // load OF THAT PANEL; an anonymous visitor (the login page) has no panel to
  // come back to, so on /login this fired eight /shell/<panel> GETs that every
  // one of them answered 401 outside a session. Auth headers plus a 401 body
  // are what Playwright's networkidle never counts as settled — measured:
  // goto('/login') timed out at 30 s with those eight still in flight, and the
  // same load with /shell/* aborted reached networkidle in 2.0 s.
  if (!document.body?.dataset.netid) { expose(diag, 'bailed: no netid (signed out)'); return 0; }
  let stored = 0;
  try {
    const cache = await caches.open(SHELL_CACHE);
    for (const panel of SHELL_PANELS) {
      const url = `/shell/${panel}`;
      try {
        const resp = await fetch(url, { credentials: 'same-origin' });
        // Only a 200 is a shell. A 401 (logged out mid-loop) or a redirect to
        // /login would poison the cache with a page that has no islands.
        if (!resp.ok) continue;
        const type = resp.headers.get('content-type') || '';
        if (!type.includes('text/html')) continue;
        await cache.put(url, resp.clone());
        stored += 1;
      } catch (err) {
        log(`could not cache ${url}`, err);
      }
    }
  } catch (err) {
    log('shell cache unavailable', err);
  }
  void warmChunks();
  expose(diag, `done stored=${stored}`);
  return stored;
}

/** Drop every cached shell. Logout already clears the whole Cache API from the
 *  service worker; this is the belt for the case where that never ran (worker
 *  update pending, SW disabled by the browser, etc). */
export async function clearShells(): Promise<void> {
  if (typeof caches === 'undefined') return;
  try {
    await caches.delete(SHELL_CACHE);
  } catch (err) {
    log('could not clear shells', err);
  }
}
