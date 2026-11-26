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
const syncLines = (): HTMLElement[] =>
  Array.from(document.querySelectorAll<HTMLElement>('.sync-line'));

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
