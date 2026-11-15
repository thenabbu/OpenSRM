import { db } from '../db/db';
import type { OutboxRow } from '../db/db';
import { warn as logWarn } from '../log';

/**
 * P7.4 — the write queue for deferred offline actions.
 *
 * WHY this exists at all: `/marks/tag` is a tag the student typed by hand. Every
 * other mutating endpoint on the site is auth or lifecycle, where replaying an
 * old action is worse than failing loudly — so those are NOT queued, and this
 * module deliberately does not name them (a route that appears here at all is a
 * bug: `OUTBOX_ROUTES` is the entire allow-list).
 *
 * CONFLICT POLICY, one line: last-write-wins per (code, component), scoped to
 * the student — the queue key IS `<netid>|tag|<code>|<component>`, so re-tagging
 * the same component offline replaces the pending row instead of replaying both,
 * and two accounts on one device never share a row.
 *
 * The form fields are the SAME names `marks_tag` reads (app/app.py:922-927), so
 * a replay is byte-identical to the fetch dash.js would have made.
 */

/** The only two routes that may ever be deferred. Anything else is a bug. */
export const OUTBOX_ROUTES = {
  tag: '/marks/tag',
} as const;

export type OutboxKind = keyof typeof OUTBOX_ROUTES;

/** Narrow an arbitrary stored `kind` back to a routable one. A row written by a
 *  future version (or a hand-edited DB) must not POST to `undefined`. */
const routeFor = (kind: string): string | undefined =>
  (OUTBOX_ROUTES as Record<string, string | undefined>)[kind];

/** Bounded retry: a 5xx or a network blip gets one more try; after this the row
 *  is dropped and the failure is surfaced, never silently forgotten. */
export const MAX_ATTEMPTS = 3;

/** Stop draining after this many rows in one pass, so a huge backlog cannot
 *  hold the main thread. The next `online` or page load resumes. */
const BATCH = 20;

const key = (kind: OutboxKind, netid: string, identity: string) => `${netid}|${kind}|${identity}`;

/** `/marks/tag`'s identity is subject code + component name: the same grain the
 *  server keys its upsert on (`class|code|name`, app/app.py:941). */
const tagIdentity = (form: Record<string, string>) => `${form.code ?? ''}|${form.component ?? ''}`;

/**
 * Put a write in the queue. Returns the row's key.
 *
 * `put` (not `add`) on the unique `k` index is the whole conflict policy: a
 * second tag for the same subject+component overwrites the first, so the replay
 * carries the student's LAST choice, never a stale earlier one.
 */
export async function queueWrite(netid: string, kind: OutboxKind, form: Record<string, string>): Promise<string> {
  const k = key(kind, netid, kind === 'tag' ? tagIdentity(form) : '');
  await db.outbox.put({ k, netid, kind, at: Date.now(), attempts: 0, form });
  return k;
}

/** Everything still waiting, oldest first — what the visible surface reports. */
export async function pendingWrites(netid?: string): Promise<OutboxRow[]> {
  const rows = netid
    ? await db.outbox.where('netid').equals(netid).toArray()
    : await db.outbox.toArray();
  return rows.sort((a, b) => a.at - b.at);
}

/** Injectable so the test can count REAL network calls and simulate a cut link
 *  without touching the global fetch every other suite shares. */
export const io = {
  post: (url: string, body: FormData): Promise<Response> =>
    fetch(url, { method: 'POST', body, credentials: 'same-origin', headers: { Accept: 'application/json' } }),
  online: (): boolean => navigator.onLine,
};

export type DrainResult = { sent: number; dropped: number; failed: number; remaining: number };

/** One POST per row. A redirected response means the session died: the server
 *  302s to /login, and retrying a deferred write against a dead session just
 *  burns the retry budget, so it is dropped AND counted as a failure to surface. */
async function send(row: OutboxRow): Promise<'ok' | 'retry' | 'session'> {
  const url = routeFor(row.kind);
  if (!url) return 'retry'; // unroutable kind: never guess an endpoint
  const body = new FormData();
  for (const [k, v] of Object.entries(row.form)) body.append(k, v);
  const r = await io.post(url, body);
  if (r.redirected) return 'session';
  if (!r.ok) return 'retry';
  // The endpoint answers {ok:false} with 200 for a rejected tag ("Component not
  // found"), so `ok` in the body is the real verdict, not the status code.
  const j = (await r.json()) as { ok?: boolean };
  return j.ok ? 'ok' : 'retry';
}

/**
 * Replay the queue. Called on `online` and once at app start.
 *
 * Serial on purpose: two tags for the same subject must land in the order the
 * student typed them, and `marks_tag` upserts on the same key — parallel sends
 * would make the winner a race, not a last write.
 *
 * Never throws: a dead queue must not break the page it drains into.
 */
export async function drainOutbox(): Promise<DrainResult> {
  const result: DrainResult = { sent: 0, dropped: 0, failed: 0, remaining: 0 };
  let rows: OutboxRow[];
  try {
    rows = (await pendingWrites()).slice(0, BATCH);
  } catch (e) {
    logWarn('outbox', 'could not read the queue', e instanceof Error ? e.message : e);
    return result;
  }
  for (const row of rows) {
    // Offline again mid-drain: stop, keep every remaining row for the next
    // `online` event. This is the property the network-cut test measures.
    if (!io.online()) break;
    let verdict: 'ok' | 'retry' | 'session';
    try {
      verdict = await send(row);
    } catch {
      verdict = 'retry'; // network error, not a rejection: keep the row
    }
    if (verdict === 'ok') {
      await db.outbox.delete(row.k);
      result.sent++;
      continue;
    }
    result.failed++;
    const attempts = row.attempts + 1;
    // Bounded: past MAX_ATTEMPTS the row is dropped so a permanently-rejected
    // write (a component that no longer exists) cannot sit in the queue forever.
    if (verdict === 'session' || attempts >= MAX_ATTEMPTS) {
      await db.outbox.delete(row.k);
      result.dropped++;
      logWarn('outbox', `dropped ${row.k} after ${attempts} attempt(s) — ${verdict}`);
    } else {
      await db.outbox.put({ ...row, attempts });
    }
  }
  try {
    result.remaining = await db.outbox.count();
  } catch {
    result.remaining = 0;
  }
  return result;
}

/**
 * Visible state surface, reusing the stale.ts idiom (one `data-` attribute, a
 * sibling element, `aria-live="polite"`).
 *
 * The QUEUE is invisible by nature — a student offline writes a tag, sees
 * nothing happen, and has no way to know whether it was lost. This is the only
 * thing that says otherwise, so it must paint on enqueue, not only on failure.
 */
export const OUTBOX_ATTR = 'data-outbox-pending';

export function showPending(el: HTMLElement, n: number): HTMLElement | null {
  removePending(el);
  if (n <= 0) return null;
  const span = document.createElement('span');
  span.setAttribute(OUTBOX_ATTR, String(n));
  span.setAttribute('aria-live', 'polite');
  span.className = 'block text-[11px] text-warning leading-5 mt-1';
  span.textContent = n === 1
    ? '1 change is saved and will be sent when you are back online.'
    : `${n} changes are saved and will be sent when you are back online.`;
  // Sibling, not child: the island replaces its own children on re-mount and
  // would take the message with it (same reason as showStale/showFailure).
  el.insertAdjacentElement('afterend', span);
  return span;
}

export function removePending(el: HTMLElement): void {
  el.parentElement?.querySelectorAll(`[${OUTBOX_ATTR}]`).forEach((n) => n.remove());
}

/** Boot: replay whatever survived the last session, then paint the count.
 *  Idempotent — a second call with nothing queued paints nothing. */
export async function startOutbox(el?: HTMLElement | null): Promise<DrainResult> {
  const result = io.online()
    ? await drainOutbox()
    : { sent: 0, dropped: 0, failed: 0, remaining: await db.outbox.count().catch(() => 0) };
  if (el) {
    if (result.remaining > 0) showPending(el, result.remaining);
    else removePending(el);
  }
  return result;
}
