import { schemas } from '../islands/contract';
import type { IslandName } from '../islands/contract';
import type { Panel } from '../db';
import { loadPanel } from './load';
import { propsFromCache } from './props';
import { showError } from './errorToast';
import { ageCaption } from '../lib/syncAge';
import { warn } from '../log';

// ── A sync carries DATA, not markup (W5.1b) ──────────────────────────────
//
// Every island that renders a `/api` slice can repaint itself from that slice:
// refetch → validate → hand the props back to Preact, which patches the nodes
// that actually changed. Nothing is torn down, so scroll position, focus, open
// <details> and the attendance view survive BY CONSTRUCTION instead of being
// carried across a rebuild by hand (which is what dash.js used to do, and what
// clamped a phone's scrollY from 250 to 0 when the watched nodes vanished).
//
// Two feeds, one rule:
//   * the six store-backed panels go through loadPanel ({fresh:true}) and then
//     propsFromCache — the SAME projection the offline read path uses, so a
//     live repaint and an offline paint can never disagree, and the Dexie row
//     is refreshed as a side effect;
//   * `dashboard` and `tools` have an endpoint but no store (see props.ts), so
//     their payload is fetched and validated directly.
//
// Absent on purpose:
//   * `settings` — identity is server-rendered only; there is no endpoint, so
//     its data cannot change without a navigation;
//   * `sync-age` — a clock, not a feed. Its caption is written in place by the
//     sync-age island (and by renderSyncCaptions below after a sync) from
//     `data-ts`, so re-rendering it would only arm a second 60 s timer.
const PANEL_FEED: Partial<Record<IslandName, Panel>> = {
  attendance: 'attendance',
  academics: 'academics',
  campus: 'campus',
  fees: 'fees',
  marks: 'marks',
  timetable: 'timetable',
};

const RAW_FEED: Partial<Record<IslandName, string>> = {
  dashboard: '/api/dashboard',
  tools: '/api/tools/island',
};

export type RefreshOpts = {
  netid: string;
  groupKey?: string;
  /** Injected by tests; defaults to the ambient `fetch`. */
  fetcher?: typeof fetch;
};

const log = (what: string, err?: unknown) =>
  console.warn(`[refresh] ${what}`, err instanceof Error ? err.message : (err ?? ''));

/**
 * Island props for a fresh repaint, or `undefined` when this island has no feed
 * (or the server answered something the island's own schema rejects — the
 * caller then keeps the paint that is already on screen rather than
 * half-updating it).
 */
export async function refreshProps(
  name: IslandName,
  opts: RefreshOpts,
): Promise<Record<string, unknown> | undefined> {
  const panel = PANEL_FEED[name];
  if (panel) {
    const out = await loadPanel(panel, { ...opts, fresh: true });
    return out.ok ? propsFromCache(panel, out.data) : undefined;
  }

  const url = RAW_FEED[name];
  if (!url) return undefined;

  const fetcher = opts.fetcher ?? fetch;
  try {
    const res = await fetcher(url, {
      credentials: 'same-origin',
      headers: { accept: 'application/json' },
    });
    // 401 (logged out) / 404 (panel gated) are normal answers, not faults: keep
    // what the user is looking at.
    if (!res.ok) return undefined;
    const body = (await res.json()) as { data?: unknown };
    const parsed = schemas[name].safeParse(body?.data);
    if (!parsed.success) {
      log(`${name} feed failed its own schema`, parsed.error);
      return undefined;
    }
    return parsed.data as Record<string, unknown>;
  } catch (e) {
    log(`${name} feed failed`, e);
    return undefined;
  }
}

// ── The shared refresh primitive (W5.2a) ─────────────────────────────────
//
// Ported out of `dash.js`: `ref()`, the [data-refresh] click binding, and the
// `syncData()` the timetable editor used to borrow. Three callers reached into
// that file for it — the nav buttons, the pull-to-refresh gesture (pull.js) and
// the timetable editor (timetable.js) — so a route that did not load dash.js
// had no way to refresh at all, and deleting dash.js (W5.4) would have deleted
// the only refresh in the app.
//
// A refresh is two separate things and this module keeps them apart:
//   1. ask the SERVER to re-sync from the portal (POST /api/refresh), then
//   2. repaint each island from its own /api slice — `refreshProps` above,
//      looped by main.ts's `refreshIslands`. No markup is fetched, no node is
//      replaced, so scroll/focus/open-panels survive by construction
//      (DESIGN §10.16 rule 3).
//
// dash.js, pull.js and timetable.js are classic <script>s and cannot import
// this module, so they reach it through `window.__osrmRevalidate` — the same
// bridge shape as `__osrmOutbox` and `__osrmRefreshData`.
const REFRESH_URL = '/api/refresh';

type Reply = { ok?: boolean; cached?: boolean; error?: string };
type Repaint = () => Promise<unknown> | unknown;

const buttons = (): HTMLElement[] =>
  Array.from(document.querySelectorAll<HTMLElement>('[data-refresh]'));
const icons = (): HTMLElement[] => Array.from(document.querySelectorAll<HTMLElement>('.refresh-icon'));
/** 2 min: fast enough that an open page keeps up, slow enough for a phone. */
export const DATA_POLL_MS = 120_000;

const syncLines = (): HTMLElement[] =>
  Array.from(document.querySelectorAll<HTMLElement>('.sync-line'));

/**
 * This bundle's own build stamp, as the build wrote it into the service
 * worker's cache name (`opensrm-v<N>-<hash>`, workbox-config.js
 * `stampCacheName`). Both files ship from the same build, so the name the
 * running worker was built with is the name this bundle came from: equal names
 * mean the page and the worker it talks to are the same build, and a difference
 * is a bundle swap that never reloaded the document.
 *
 * Read from the SW because nothing else is readable from a page whose main
 * document the service worker served from cache (a shell).
 */
export function bundleVersion(): Promise<string> {
  const fetcher = (window as unknown as { fetch?: typeof fetch }).fetch;
  if (typeof fetcher !== 'function') return Promise.resolve('');
  return fetcher('/static/sw.js', { cache: 'no-store' })
    .then((r) => (r.ok ? (r.text() as Promise<string>) : ''))
    .then((src) => (/opensrm-v[\w-]+/.exec(src) || [''])[0])
    .catch(() => '');
}

/**
 * True while a gesture or a sync is in flight — the refresh spinner, or the
 * pull-to-refresh indicator. A boot swap stands down on both: reloading over a
 * running sync throws away the numbers it was about to paint, and the student
 * is watching it.
 */
export function refreshBusy(): boolean {
  if (document.querySelector('.refresh-icon.animate-spin')) return true;
  const btn = document.querySelector<HTMLElement>('[data-refresh]');
  return !!btn && btn.getAttribute('aria-disabled') === 'true';
}

/**
 * Ask the SERVER whether this account's data is old, once per page.
 *
 * `checks_stale` is `auto_sync_kick_if_stale` + the SCOPE kick — the exact pair
 * a page render already runs — so this can never disagree with what a reload
 * would have shown: it starts the same background sync a reload would have
 * started, and the scope poll repaints when that run lands.
 *
 * The page used to decide this itself, from `data-ts` baked into its markup.
 * That stamp is one moment in time: a tab left open all day stayed "fresh" by
 * its own reckoning, which is the "data is old until I reload" report. Now the
 * server answers.
 */
export function revalidatePage(): Promise<void> {
  return fetch(REFRESH_URL, { credentials: 'same-origin', headers: { accept: 'application/json' } })
    .then((r) => (r.ok ? (r.json() as Promise<{ sync?: boolean }>) : null))
    .then((d) => {
      // The server started a background portal sync; both pollers repaint when
      // their run lands, so there is nothing else to do here.
      if (d?.sync) void syncData();
    })
    .catch(() => {});
}

/**
 * What the page does when it comes back into view: look at the build stamp,
 * swap onto a newer one when nothing would be lost, and otherwise ask the
 * server about the data.
 *
 * The build check goes FIRST and the data check is skipped on a tab that is
 * about to be replaced: the reload loses that answer anyway, and the reloaded
 * page runs its own checks.
 *
 * Never rejects. Everything is injectable, so a test drives every leg.
 */
export function revalidateOnReturn(opts: {
  doc?: Document;
  version?: () => Promise<string>;
  revalidate?: () => Promise<void>;
  swap?: () => Promise<void>;
  /** The stamp this document loaded with. */
  loadedWith?: string;
  /** True once a swap has been decided: no more data work on this document. */
  swapping?: () => boolean;
} = {}): Promise<void> {
  const doc = opts.doc ?? document;
  const version = opts.version ?? bundleVersion;
  const revalidate = opts.revalidate ?? revalidatePage;
  const swapping = opts.swapping ?? (() => false);

  return version()
    .then((now) => {
      // No stamp to compare (an older SW, a failed fetch): the page keeps its
      // data check, and the update hook still gets its chance at boot.
      if (!now || now === (opts.loadedWith ?? '') || swapping()) return false;
      if (!opts.swap) return false;
      return opts.swap().then(() => true);
    })
    .catch(() => false)
    .then((swapped) => {
      if (swapped || swapping()) return;
      // Only while the tab is on screen. A hidden tab swaps a worker instead of
      // asking for data, and polling a server from a background tab is the
      // request storm SCHEDULERS.md exists to prevent.
      if (doc.visibilityState !== 'visible') return;
      return revalidate();
    });
}

/**
 * The data half of staying current, on a timer rather than once at load.
 *
 * `autoRefreshIfStale` reads `data-ts` from the markup, so a dashboard left
 * open never looks again: the user had to reload to see new numbers. This
 * re-runs the same server check every interval while the tab is visible, so an
 * open page keeps up on its own.
 *
 * Skipped when there is nothing to check (a shell with no caption, a page whose
 * meta says the browser holds no credential), while a sync is in flight, and
 * while offline. Returns a stop() for tests and for a route change.
 */
export function startDataRefreshLoop(opts: {
  doc?: Document;
  win?: Window;
  intervalMs?: number;
  refresh?: () => Promise<void>;
} = {}): () => void {
  const doc = opts.doc ?? document;
  const win = opts.win ?? window;
  const refresh = opts.refresh ?? revalidatePage;
  const interval = opts.intervalMs ?? DATA_POLL_MS;

  const can = doc.querySelector('meta[name="can-sync"]');
  if (can && can.getAttribute('content') === '0') return () => {};
  if (!doc.querySelector('.sync-line')) return () => {};

  let stopped = false;
  let timer: ReturnType<typeof setTimeout>;
  const tick = (): void => {
    if (stopped) return;
    if (doc.visibilityState === 'visible' && win.navigator?.onLine !== false && !refreshBusy()) {
      void refresh();
    }
    // setTimeout, not setInterval: a slow answer delays the next check instead
    // of stacking requests behind it.
    timer = setTimeout(tick, interval);
  };
  timer = setTimeout(tick, interval);
  return () => { stopped = true; clearTimeout(timer); };
}

/** 2 min: fast enough that an open page keeps up, slow enough for a phone. */

/**
 * Repaint every mounted island from its own feed — the data half of a sync.
 *
 * Never rejects: a failed repaint keeps the paint that is already on screen,
 * which is the whole reason a sync no longer fetches markup.
 */
export function syncData(): Promise<void> {
  const hook = (window as unknown as { __osrmRefreshData?: Repaint }).__osrmRefreshData;
  if (!hook) return Promise.resolve();     // no bundle on this page: the server paint stands
  return Promise.resolve(hook())
    .then(() => undefined)
    .catch((err) => warn('refresh', 'repaint failed', err));
}

/**
 * Put the caption back to the honest age of the last real sync.
 *
 * One formatter: `ageCaption` is the client mirror of app/views/sync_age.py and
 * the same function the sync-age island paints with, so a refreshed caption and
 * an island-painted one can never disagree. (W5.4: dash.js used to own this and
 * exposed `renderSyncLines` for us to call; that file is gone and the loop it
 * ran is the island's 60 s timer now.)
 */
export function renderSyncCaptions(): void {
  const nowS = Math.floor(Date.now() / 1000);
  syncLines().forEach((el) => {
    const ts = Number(el.dataset.ts || 0);
    const text = ageCaption(ts, nowS);
    el.textContent = text;
    // BOTH spellings: the class for the flex gap, the attribute for the UA
    // default that the server may have set (see the templates).
    el.classList.toggle('hidden', !text);
    el.toggleAttribute('hidden', !text);
    el.title = el.dataset.full || '';
  });
}

/**
 * POST /api/refresh, hold the busy state until the repaint finishes, then put
 * focus back where the user left it.
 *
 * `quiet` is the background path (a stale page refreshing itself): failures
 * there are logged, never shown. Never rejects — one unhandled rejection per
 * page open is not a debugging aid.
 */
export async function triggerRefresh(quiet = false): Promise<void> {
  const btns = buttons();
  const ics = icons();
  // aria-disabled, NOT the `disabled` attribute: setting `disabled` on the
  // focused element makes the browser blur it to <body> immediately, which is
  // what used to drop a user onto the dock mid-sync. Remember whatever had
  // focus (not just a refresh button) so it can be handed back.
  const hadFocus =
    document.activeElement && document.activeElement !== document.body
      ? document.activeElement
      : null;

  btns.forEach((b) => {
    b.setAttribute('aria-disabled', 'true');
    b.dataset.busy = '1';
  });
  ics.forEach((i) => i.classList.add('animate-spin'));
  // BOTH spellings, because renderSyncLines hides the caption with the class on
  // some routes and with the attribute on others.
  syncLines().forEach((el) => {
    el.textContent = 'Syncing…';
    el.classList.remove('hidden');
    el.removeAttribute('hidden');
  });

  const restore = (): void => {
    btns.forEach((b) => {
      b.removeAttribute('aria-disabled');
      delete b.dataset.busy;
    });
    ics.forEach((i) => i.classList.remove('animate-spin'));
    // Only pull focus back if it went nowhere: never steal it from a user who
    // moved on during the round trip, never onto a node that was replaced.
    if (hadFocus && hadFocus.isConnected && document.activeElement === document.body) {
      (hadFocus as HTMLElement).focus();
    }
    renderSyncCaptions();
  };

  try {
    const r = await fetch(REFRESH_URL, { method: 'POST' });
    // Dead session: the server 302s API calls to /login and fetch() follows it,
    // so `r.json()` would throw and the user would read "network error" instead
    // of being sent to the login page. Restore FIRST — the legacy code returned
    // before its restore, so a blocked navigation left the button busy forever.
    if (r.redirected) {
      restore();
      window.location.href = '/login';
      return;
    }
    const d = (await r.json()) as Reply;
    if (d.ok && !d.cached) {
      // This sync DID land, so the caption's age resets to now and every island
      // repaints from its own feed. A cached answer (SYNC_MIN_INTERVAL_S) takes
      // the restore-only path below: the stored data did not change, so the
      // caption keeps the honest age of the last real sync instead of claiming
      // a fresh one this request did not deliver.
      const nowS = Math.floor(Date.now() / 1000);
      syncLines().forEach((el) => {
        el.dataset.ts = String(nowS);
        el.dataset.full = new Date(nowS * 1000).toLocaleString();
      });
      await syncData();
      restore();
      return;
    }
    restore();
    if (d.ok) return;
    if (quiet) warn('refresh', `background sync failed: ${d.error ?? ''}`);
    else showError(d.error || 'Refresh failed');
  } catch (e) {
    restore();
    if (quiet) warn('refresh', 'background sync failed', e);
    else showError('Network error — is the server reachable?');
  }
}

/**
 * Bind every [data-refresh] button on the page.
 *
 * dash.js binds the same buttons only as the PREACT_ISLANDS=0 fallback (no
 * bundle → no bridge) and its handler stands down as soon as
 * `__osrmRevalidate` exists. One binder, or a single click starts two syncs.
 */
export function bindRefreshButtons(): void {
  buttons().forEach((b) => {
    b.addEventListener('click', () => {
      // aria-disabled is the busy marker; honour it here or a double-click
      // starts two syncs and two repaints race each other.
      if (b.getAttribute('aria-disabled') === 'true') return;
      void triggerRefresh(false);
    });
  });
}
