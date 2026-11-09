import { type z } from 'zod';
import {
  type ParseResult,
  parseAcademicsResponse,
  parseAttendanceResponse,
  parseCampusResponse,
  parseFeesResponse,
  parseMarksResponse,
  parseTimetableResponse,
} from '../contracts';
import { type Panel, type PanelData, db, keyPath, readPanel, writePanel } from '../db';

// ── The one read path every island calls ─────────────────────────────────
//
// Order is the contract: cache first (instant, offline-capable), then network,
// then the cache again as a stale fallback. A record that fails validation is
// already discarded by `readPanel`, so a corrupt row can only ever cause a
// refetch — the store never renders or returns data it did not validate.
//
// Network responses are validated through the SAME parsers the server tests
// use. Anything unparseable is a failure, never a partial success.

/** A cached payload older than this is labelled stale. This is a PRODUCT
 *  decision, not a guess: attendance/marks are the panels a student opens to
 *  act on (the next class, a due date) and a half-day-old copy is where that
 *  stops being trustworthy; a timetable a day old is still right. */
export const STALE_MS = 6 * 60 * 60 * 1000;

/** Normalises the three response shapes (envelope, `marks`, bare grid) to one
 *  `{ok, data}`. Two parsers speak `.ok`/`.reason`, two speak zod's
 *  `.success`/`.error` — hence the switch rather than one indexed call. */
type ParseOut<T> = { ok: true; data: T } | { ok: false; message: string };

const normalise = <T>(r: ParseResult<T>): ParseOut<T> =>
  r.ok ? r : { ok: false, message: r.reason };

const schemaError = <T>(r: z.ZodSafeParseResult<T>): ParseOut<T> =>
  r.success ? { ok: true, data: r.data } : { ok: false, message: r.error.message };

/** Returns the per-panel union; `loadPanel` casts once, at the one call site
 *  where `panel: P` is already in scope. Narrowing a generic `P` inside the
 *  switch is not something the compiler can do, and pretending otherwise cost
 *  four unsound casts. */
function parsePanel(panel: Panel, json: unknown): ParseOut<unknown> {
  switch (panel) {
    case 'attendance':
      return normalise(parseAttendanceResponse(json));
    case 'fees':
      return normalise(parseFeesResponse(json));
    case 'campus':
      return normalise(parseCampusResponse(json));
    case 'academics':
      return normalise(parseAcademicsResponse(json));
    case 'marks':
      return schemaError(parseMarksResponse(json));
    case 'timetable':
      return schemaError(parseTimetableResponse(json));
  }
}

const ENDPOINT: Record<Panel, string> = {
  attendance: '/api/attendance',
  fees: '/api/fees',
  campus: '/api/campus',
  academics: '/api/academics',
  // The island feeds, not the legacy ones: /api/marks (app.py:741) returns raw
  // stored JSON and /api/timetable is the GET+POST the user WRITES the grid
  // through. Neither carries the payload the island's zod schema validates,
  // so caching them would poison the store with a shape propsFromCache refuses.
  marks: '/api/marks/island',
  timetable: '/api/timetable/island',
};

/** Which reason an island acts on:
 *  `unauthenticated` → redirect to /login · `not_found` → empty state (panel
 *  gated) · `network` → offline banner, cached copy if there was one ·
 *  `http`/`invalid` → generic retry. One shape, never a raw rejection. */
export type LoadFailure = {
  reason: 'unauthenticated' | 'not_found' | 'http' | 'network' | 'invalid';
  status?: number;
  message: string;
};

export type LoadOutcome<P extends Panel> = {
  ok: true;
  data: PanelData<P>;
  source: 'cache' | 'network';
  fetchedAt: number;
  stale: boolean;
} | ({ ok: false } & LoadFailure);

type Failure = { ok: false } & LoadFailure;

export type LoadOpts = {
  netid: string;
  /** Only timetable really needs one; per-student panels ignore it. */
  groupKey?: string;
  /** Injected by tests; defaults to the ambient `fetch`. */
  fetcher?: typeof fetch;
};

const log = (what: string, err?: unknown) =>
  console.warn(`[load] ${what}`, err instanceof Error ? err.message : (err ?? ''));

export async function loadPanel<P extends Panel>(
  panel: P,
  opts: LoadOpts,
): Promise<LoadOutcome<P>> {
  const { netid, groupKey = '', fetcher = fetch } = opts;

  const cached = await readPanel(panel, netid, groupKey);
  // `readPanel` validates but returns only the payload, so the stamp comes from
  // the row — read AFTER the validation, so a corrupt row is already deleted.
  const stamp = cached === undefined ? undefined : await fetchedAtOf(panel, netid, groupKey);
  if (cached !== undefined && stamp !== undefined) {
    return { ok: true, data: cached, source: 'cache', fetchedAt: stamp, stale: isStale(stamp) };
  }

  let res: Response;
  try {
    res = await fetcher(ENDPOINT[panel], {
      credentials: 'same-origin',
      headers: { accept: 'application/json' },
    });
  } catch (e) {
    log(`network failed for ${panel}`, e);
    return fail('network', undefined, 'offline — could not reach the server');
  }

  // Nothing but a 2xx is cached: 401 means logged out (never PII to keep),
  // 404 means the panel is gated — both are normal outcomes, not errors to
  // bury in a generic http failure.
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => undefined);
    const message =
      (body as { error?: string } | undefined)?.error ?? `HTTP ${res.status}`;
    if (res.status === 401) return fail('unauthenticated', 401, message);
    if (res.status === 404) return fail('not_found', 404, message);
    return fail('http', res.status, message);
  }

  const json: unknown = await res.json().catch(() => undefined);
  const parsed = parsePanel(panel, json) as ParseOut<PanelData<P>>;
  if (!parsed.ok) {
    log(`dropping invalid ${panel} response`, parsed.message);
    return fail('invalid', res.status, parsed.message);
  }

  const fetchedAt = Date.now();
  // A failed write is not a failed read: the payload is valid and the caller
  // gets it; only the next visit loses the cache (writePanel already logged).
  await writePanel(panel, { netid, groupKey, payload: parsed.data, fetchedAt });
  return { ok: true, data: parsed.data, source: 'network', fetchedAt, stale: false };
}

const fail = (reason: LoadFailure['reason'], status: number | undefined, message: string): Failure =>
  status === undefined ? { ok: false, reason, message } : { ok: false, reason, status, message };

const isStale = (fetchedAt: number, now = Date.now()) => now - fetchedAt > STALE_MS;

/** fetchedAt of a row `readPanel` just validated. A pre-fetchedAt row reads as
 *  epoch 0 — present, but maximally stale rather than a crash. */
async function fetchedAtOf(panel: Panel, netid: string, groupKey: string): Promise<number> {
  const key = keyPath(panel).startsWith('[') ? [netid, groupKey] : netid;
  try {
    const row = await db.table(panel).get(key);
    return typeof row?.fetchedAt === 'number' ? row.fetchedAt : 0;
  } catch (e) {
    log(`fetchedAt read failed for ${panel}`, e);
    return 0;
  }
}
