import { schemas } from '../islands/contract';
import type { IslandName } from '../islands/contract';
import type { Panel } from '../db';
import { loadPanel } from './load';
import { propsFromCache } from './props';

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
//   * `sync-age` — a clock, not a feed. Its caption is written in place by
//     dash.js/sync-age from `data-ts`, so re-rendering it would only arm a
//     second 60 s timer.
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
