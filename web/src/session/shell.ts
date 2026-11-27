/**
 * Snapshot the app for offline while the student is online.
 *
 * A service worker can only serve what it already has, and it cannot fetch a
 * page at install time: every route needs a session, and at install nobody has
 * logged in yet. So the app fetches its own pages AFTER load, when the cookie is
 * present, and stores them in the Cache API.
 *
 * What is stored is the REAL rendered page — chrome, identity box, email,
 * register number, island props (which carry the whole dashboard view model,
 * marks summary, exams and teacher groups) — not the blanked `/shell/<panel>`
 * copy. Offline therefore opens the same document the server would have sent,
 * and the islands hydrate from the embedded props, blobatar included. Personal
 * data in the HTTP cache is accepted here by owner decision (2026-11-27).
 *
 * Warming runs on every authenticated load, exactly like the shell warm it
 * replaces: a deploy that renames a chunk must overwrite yesterday's snapshot,
 * and a throttle would leave a stale page offline for its whole window.
 *
 * Two properties keep the cache from becoming a leak:
 *   * every entry is keyed by netid (`/__snap/<netid>/<panel>`), and a warm by
 *     student B DELETES every entry belonging to any other netid — so one
 *     device holds one student's snapshot at a time;
 *   * logout clears the whole Cache API (sw.js `/logout` route).
 * The service worker finds the right snapshot through the owner record this
 * module writes (`/__snap/__owner`), never by guessing.
 */
import { warn as logWarn } from '../log';

/** Route per panel. `/` is the dashboard; `settings` is included now that a
 *  snapshot carries its real values instead of an empty form. */
const PANEL_ROUTES: Record<string, string> = {
  dashboard: '/',
  attendance: '/attendance',
  timetable: '/timetable',
  marks: '/marks',
  campus: '/campus',
  academics: '/academics',
  fees: '/fees',
  tools: '/tools',
  settings: '/settings',
};

const SNAP_CACHE = 'opensrm-snap';
const SNAP_PREFIX = '/__snap/';
const OWNER_KEY = SNAP_PREFIX + '__owner';

const log = (msg: string, e?: unknown): void =>
  logWarn('shell', msg, e instanceof Error ? e.message : (e ?? ''));

/** Surface the warm result on window for the offline DUT: console events from a
 *  page that navigates are dropped by Playwright, so a log is not evidence. */
function expose(diag: string[], verdict: string, done = false): void {
  try {
    (window as unknown as { __shellWarm?: unknown }).__shellWarm = { verdict, diag, done };
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

/**
 * Claim this device's snapshot for the signed-in student.
 *
 * Runs at BOOT, not at warm time, and that timing is the whole point: the
 * service worker resolves a cached page through the owner record, so a warm
 * that only wrote the owner four seconds after load left a window where student
 * B's page could be served student A's snapshot. Measured in the two-student
 * e2e leg (B4: eight of A's rows on B's offline page). Claiming first closes
 * that window: the moment B's page renders, A's entries are gone.
 */
export async function claimSnapshotOwner(): Promise<void> {
  if (typeof caches === 'undefined') return;
  const netid = document.body?.dataset.netid;
  if (!netid) return;
  try {
    const cache = await caches.open(SNAP_CACHE);
    await cache.put(OWNER_KEY, new Response(netid));
    const mine = `${SNAP_PREFIX}${netid}/`;
    for (const key of await cache.keys()) {
      const path = new URL(key.url).pathname;
      if (path.startsWith(SNAP_PREFIX) && path !== OWNER_KEY && !path.startsWith(mine)) {
        await cache.delete(key);
      }
    }
  } catch (err) {
    log('could not claim snapshot owner', err);
  }
}

export async function warmShells(): Promise<number> {
  const diag: string[] = [`start ctrl=${!!navigator.serviceWorker?.controller} online=${navigator.onLine}`];
  if (typeof caches === 'undefined' || !navigator.onLine) { expose(diag, 'bailed: caches or offline'); return 0; }
  // No owner, nothing to warm. An anonymous visitor (the login page) has no
  // page to come back to, so on /login this fired fetches that every one of
  // them answered 401 outside a session. Auth headers plus a 401 body are what
  // Playwright's networkidle never counts as settled — measured: goto('/login')
  // timed out at 30 s with those still in flight, and the same load with the
  // fetches aborted reached networkidle in 2.0 s.
  const netid = document.body?.dataset.netid;
  if (!netid) { expose(diag, 'bailed: no netid (signed out)'); return 0; }

  let stored = 0;
  try {
    const cache = await caches.open(SNAP_CACHE);
    // One student's snapshot at a time on a device; the owner is (re)asserted
    // here too so a warm that runs without a preceding claim cannot leave the
    // record pointing at a previous student.
    await claimSnapshotOwner();

    for (const [panel, route] of Object.entries(PANEL_ROUTES)) {
      try {
        const resp = await fetch(route, { credentials: 'same-origin' });
        // Only a 200 is a snapshot. A 401 (logged out mid-loop), a redirect to
        // /login or a 503 maintenance page would poison it with a document that
        // has no islands.
        if (!resp.ok) continue;
        const type = resp.headers.get('content-type') || '';
        if (!type.includes('text/html')) continue;
        await cache.put(`${SNAP_PREFIX}${netid}/${panel}`, resp.clone());
        stored += 1;
      } catch (err) {
        log(`could not snapshot ${route}`, err);
      }
    }
  } catch (err) {
    log('snapshot cache unavailable', err);
  }
  void warmChunks().then(() => {
    // `done` flips only after the chunk warm too. Both halves fire their own
    // fetches, and a navigation that lands mid-flight cancels them; WebKit
    // surfaces a cancelled background fetch as a page error on the NEXT
    // document, which the route-paint harness then reads as this route's
    // console noise. Exposing one "everything settled" flag lets the harness
    // wait for the prefetch instead of racing it.
    expose(diag, `done stored=${stored}`, true);
  });
  return stored;
}

/** Drop every cached snapshot and the legacy shell cache. Logout already clears
 *  the whole Cache API from the service worker; this is the belt for the case
 *  where that never ran (worker update pending, SW disabled, etc). */
export async function clearShells(): Promise<void> {
  if (typeof caches === 'undefined') return;
  try {
    await caches.delete(SNAP_CACHE);
    await caches.delete('opensrm-shell');
  } catch (err) {
    log('could not clear shells', err);
  }
}
