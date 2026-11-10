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
export async function warmShells(): Promise<number> {
  if (typeof caches === 'undefined' || !navigator.onLine) return 0;
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
