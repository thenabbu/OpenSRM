// ── User actions (W5.4c) — the four dash.js rows that are a *thing the user
//    did*, not page chrome and not a panel's paint.
//
// Rows this module owns (matrix names, so a future grep finds them):
//   dash-marks-tag-save  → bindTagSave        (delegated submit on /marks/tag)
//   dash-delete-account  → bindDeleteAccount  (#delete-account-btn + #del-confirm)
//   dash-details-dismiss → bindDetailsDismiss (outside-click closes details[open])
//   dash-scope-poll      → startScopePoll     (/api/scope/status, bounded)
//
// Why one file: same property as pageChrome.ts — each is bound once at boot,
// none renders, and none of them persists (the card said to reuse
// `web/src/data/local.ts`; that module does not exist in this tree and nothing
// here writes storage, so there is nothing to route through it).
//
// STAND-DOWN: dash.js stays as the PREACT_ISLANDS=0 fallback until W5.4 deletes
// it, so each binder publishes a `window.__osrm*` marker and the legacy block
// checks it. Without that both copies listen and one Save POSTs twice — and for
// the delete row, one confirm would DELETE TWICE.

import { showError } from './errorToast';
import { syncData } from './refresh';

// ─ 1. dash-marks-tag-save ─────────────────────────────────────────────────
export const TAG_URL = '/marks/tag';

type Outbox = {
  queueWrite: (netid: string, kind: 'tag', form: Record<string, string>) => Promise<unknown>;
  startOutbox: () => Promise<unknown>;
};

/**
 * Intercept every submit whose form action is /marks/tag.
 *
 * DELEGATED on the document, not an onSubmit prop on MarksPanel. The tag form
 * is inside the marks ISLAND, and mountBounded() `replaceChildren`s that mount
 * on every repaint (save → syncData → refreshIslands) — so a Preact onSubmit
 * handler does work, but it would also mean re-deriving the interception inside
 * a component that is re-created under it. One document listener survives every
 * repaint by construction, which is exactly the bug the island's repaint model
 * keeps reintroducing. The plain POST stays the no-JS path.
 *
 * Order of operations is dash.js's, unchanged: preventDefault first, collect
 * FormData BEFORE the attempt (so a failed POST still has exactly what was
 * submitted), then only a TRANSPORT failure is deferred — a rejected tag
 * ({"ok":false}) is a real answer and retrying it would be a lie.
 */
export function bindTagSave(doc: Document = document): void {
  doc.addEventListener('submit', (ev) => {
    const f = ev.target;
    if (!(f instanceof HTMLFormElement)) return;
    if ((f.getAttribute('action') || '') !== TAG_URL) return;
    ev.preventDefault();

    const fields: Record<string, string> = {};
    new FormData(f).forEach((v, k) => {
      fields[k] = String(v);
    });
    const body = new FormData(f);
    const queue = (window as unknown as { __osrmOutbox?: Outbox }).__osrmOutbox;
    const offline = !navigator.onLine;

    fetch(TAG_URL, {
      method: 'POST',
      body,
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then((r) => {
        if (r.redirected) {
          location.href = '/login';
          return new Promise<never>(() => {});
        }
        return r.json() as Promise<{ ok?: boolean; error?: string }>;
      })
      .then((j) => {
        if (!j.ok) {
          showError(j.error || 'Tag not saved');
          return;
        }
        void syncData();
      })
      .catch(() => {
        if (!queue) {
          showError('Network error — tag not saved');
          return;
        }
        const netid = doc.body?.getAttribute('data-netid');
        if (!offline && !netid) {
          showError('Network error — tag not saved');
          return;
        }
        queue
          .queueWrite(netid || '', 'tag', fields)
          .then(() => queue.startOutbox())
          .then(() => {
            showError('Offline — tag saved and will be sent when you reconnect');
          })
          .catch(() => showError('Network error — tag not saved'));
      });
  });
}

// ─ 2. dash-delete-account ─────────────────────────────────────────────────
export const DELETE_URL = '/api/account/delete';
export const DEL_ERR_CLASS = 'mt-2 text-xs text-error';
export const DEL_IDLE_CLASS = 'mt-2 text-xs text-base-content/70';

/**
 * The settings ROW only OPENS the explainer; only the confirm button inside it
 * POSTs. That is the whole safety property of this row and it is preserved
 * verbatim: no listener on anything else reaches the fetch, the confirm node
 * exists only inside the closed <dialog>, and a <dialog> that was never
 * showModal()'d cannot receive the click.
 *
 * On failure the button re-enables and the status line says nothing was
 * removed — the student must be able to see that a destructive action did NOT
 * half-happen.
 */
export function bindDeleteAccount(doc: Document = document): boolean {
  const btn = doc.getElementById('delete-account-btn');
  // Idempotent per element: main.ts re-arms this binder after every soft-nav
  // route swap, and a second listener on #del-confirm would make ONE confirm
  // POST twice. False means this route has no delete row (nothing to bind).
  if (!btn) return false;
  if (btn.dataset.delBound) return true;
  btn.dataset.delBound = '1';
  const confirm = doc.getElementById('del-confirm');
  btn?.addEventListener('click', () => {
    (doc.getElementById('delete-account-modal') as HTMLDialogElement | null)?.showModal();
  });
  confirm?.addEventListener('click', () => {
    const status = doc.getElementById('del-status');
    const btnEl = confirm as HTMLButtonElement;
    btnEl.disabled = true;
    if (status) {
      status.textContent = 'Erasing your data…';
      status.className = DEL_IDLE_CLASS;
    }
    fetch(DELETE_URL, { method: 'POST' })
      .then((r) => {
        if (r.redirected) {
          location.href = '/login';
          return new Promise<never>(() => {});
        }
        return r.json() as Promise<{ ok?: boolean; error?: string }>;
      })
      .then((j) => {
        if (!j.ok) {
          if (status) {
            status.textContent = j.error || 'failed — nothing was removed';
            status.className = DEL_ERR_CLASS;
          }
          showError('Delete failed: ' + (j.error || 'unknown error'));
          btnEl.disabled = false;
          return;
        }
        location.href = '/login';
      })
      .catch(() => {
        if (status) {
          status.textContent = 'network error — nothing was removed';
          status.className = DEL_ERR_CLASS;
        }
        showError('Delete: network error — nothing was removed');
        btnEl.disabled = false;
      });
  });
  return true;
}

// ─ 3. dash-details-dismiss ────────────────────────────────────────────────
/**
 * Tap-away closes the open popover <details> (the marks tag panel). Clicks
 * inside it — summary included — are ignored, so the pencil toggle still works
 * and Save is never the only way out of a panel opened by accident.
 */
export function bindDetailsDismiss(doc: Document = document): void {
  doc.addEventListener('click', (e) => {
    const open = doc.querySelector('details[open]');
    if (open && !open.contains(e.target as Node | null)) (open as HTMLDetailsElement).open = false;
  });
}

// ─ 4. dash-scope-poll ─────────────────────────────────────────────────────
export const SCOPE_STATUS_URL = '/api/scope/status';
/** First attempt delay. dash.js: setTimeout(poll, 1500). */
export const SCOPE_FIRST_DELAY_MS = 1500;
/** Attempts before the 8 s backoff kicks in (dash.js: `if (tries > 10)`). */
export const SCOPE_BACKOFF_AFTER = 10;
export const SCOPE_DELAY_MS = 4000;
export const SCOPE_SLOW_DELAY_MS = 8000;
/**
 * Width of the budget. A 14-op run measured 27-31 s upstream, but a cold first
 * sync on a slow day plus the 8 s backoff can pass 4 minutes — the old cap (45)
 * then stopped polling SILENTLY while the server was still syncing, leaving the
 * page on its pre-sync render forever. At ~4-8 s a tick, 150 tries ~= 15-20 min.
 */
export const SCOPE_MAX_TRIES = 150;

/**
 * Poll /api/scope/status while the page arrived mid-sync, and repaint ONCE when
 * the run completes. Bounded, backed off, and it never restarts itself: the
 * template renders 'complete' on the next load.
 *
 * Semantics are dash.js's EXACTLY (interval, backoff, caps, stop conditions) —
 * this is a port, not a redesign. The stop set:
 *   * `complete` → one syncData(), done;
 *   * `off`      → done, silently (the feature is disabled upstream);
 *   * tries     > SCOPE_MAX_TRIES → done;
 *   * a reply that is not `{ok:true}` or a transport error → retry on schedule.
 *
 * Returns a stop() for tests and for a route change; production never calls it.
 */
export function startScopePoll(
  doc: Document = document,
  doFetch: typeof fetch = fetch,
  repaint: () => Promise<unknown> | unknown = syncData,
  schedule: (fn: () => void, ms: number) => unknown = (fn, ms) => setTimeout(fn, ms),
): () => void {
  const state = doc.body?.getAttribute('data-scope-sync') || '';
  if (state !== 'stale' && state !== 'running') return () => {};

  let tries = 0;
  let delay = SCOPE_DELAY_MS;
  let done = false;

  const tick = (): void => {
    if (done || tries++ > SCOPE_MAX_TRIES) return;
    doFetch(SCOPE_STATUS_URL, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? (r.json() as Promise<{ ok?: boolean; state?: string }>) : null))
      .then((d) => {
        if (!d || !d.ok) {
          schedule(tick, delay);
          return;
        }
        if (d.state === 'complete') {
          done = true;
          void Promise.resolve(repaint()).catch(() => {});
          return;
        }
        if (d.state === 'off') {
          done = true;
          return;
        }
        if (tries > SCOPE_BACKOFF_AFTER) delay = SCOPE_SLOW_DELAY_MS;
        schedule(tick, delay);
      })
      .catch(() => schedule(tick, delay));
  };

  schedule(tick, SCOPE_FIRST_DELAY_MS);
  return () => {
    done = true;
  };
}
