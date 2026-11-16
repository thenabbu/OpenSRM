// ── Background (W5.4d) — the three dash.js rows that run with no click: one
//    defers work while the avatar is offscreen, one opens and submits the
//    feedback dialog, one warms a stale page at load.
//
// Rows this module owns (matrix names, so a future grep finds them):
//   dash-avatar-offscreen → bindAvatarOffscreen (IntersectionObserver, re-armed per mount)
//   dash-fb-modal         → bindFeedbackModal   (#fb-cta / #fb-submit, delegated)
//   dash-auto-refresh     → autoRefreshIfStale  (ONE load-time check, quiet POST)
//
// Why one file: same property as pageChrome.ts / userActions.ts — each is bound
// once at boot from main.ts, none renders, none persists (the card said to reuse
// `web/src/data/local.ts`; that module does not exist in this tree and nothing
// here writes storage).
//
// TIMER SEMANTICS, read off dash.js:226-237, :258-268 and :283-324 and kept
// literal, because a schedule that only looks right is a schedule that is wrong:
//   * auto-refresh is NOT an interval. It is one check at load: the FIRST
//     `.sync-line`'s data-ts, stale when absent or older than 600 s, skipped
//     entirely when `meta[name=can-sync]` is '0' (no stored credentials) or
//     `navigator.onLine` is false, then the same quiet path a click uses.
//     Nothing cancels it later because nothing repeats it.
//   * avatar-offscreen is an IntersectionObserver at threshold 0, not a timer:
//     it toggles `is-offscreen` on `.mo-root` (CSS pauses the idle loops) every
//     time the node crosses the viewport edge, and re-arms on
//     `osrm:island-mounted` because the dashboard island paints its OWN avatar.
//   * fb-modal is delegated on the document, which is what makes it survive the
//     dashboard island repainting `#fb-cta`.
//
// STAND-DOWN: dash.js stays the PREACT_ISLANDS=0 fallback until W5.4 deletes it,
// so each binder publishes a `window.__osrm*` marker and the legacy block checks
// it. Without that, two document-level click handlers answer #fb-submit and one
// confirm POSTs /api/feedback/fill twice — the portal gets two fills per teacher.

import { showError } from './errorToast';
import { triggerRefresh } from './refresh';

// ─ 1. dash-avatar-offscreen ────────────────────────────────────────────────
export const AVATAR_SELECTOR = '.blobatar-gaze';
export const OFFSCREEN_CLASS = 'is-offscreen';
/** Key on the WRAPPER, so a re-arm never stacks a second observer on one node. */
export const OBSERVED_ATTR = 'offscreenObs';

/**
 * Pause the avatar's idle loops while it is offscreen.
 *
 * The deferral is the point, not the rendering: `arm()` runs at load AND on
 * every `osrm:island-mounted`, because hydration detaches the server-rendered
 * avatar and mounts a new one — an observer left on the old node would report
 * intersection for a node nobody can see, and the new one would run its loops
 * forever. Keyed per wrapper, so a mount that paints the same node costs nothing.
 */
type IOConstructor = new (
  cb: (entries: IntersectionObserverEntry[]) => void,
  opts?: IntersectionObserverInit,
) => IntersectionObserver;

export function bindAvatarOffscreen(doc: Document = document, win: Window = window): void {
  // Read off `win`, not the global: the tests hand in a fake, and the whole row
  // is untestable otherwise (jsdom ships no IntersectionObserver).
  const IO = (win as unknown as { IntersectionObserver?: IOConstructor }).IntersectionObserver;
  const arm = (): void => {
    const wrap = doc.querySelector<HTMLElement>(AVATAR_SELECTOR);
    // No IntersectionObserver (old engine, jsdom) => the avatar just keeps
    // animating, which is the pre-Phase-6 behaviour, not a crash.
    if (!wrap || typeof IO !== 'function' || wrap.dataset[OBSERVED_ATTR]) {
      return;
    }
    wrap.dataset[OBSERVED_ATTR] = '1';
    const root = wrap.querySelector<HTMLElement>('.mo-root') ?? wrap;
    new IO(
      (entries) => {
        entries.forEach((e) => root.classList.toggle(OFFSCREEN_CLASS, !e.isIntersecting));
      },
      { threshold: 0 },
    ).observe(wrap);
  };
  arm();
  doc.addEventListener('osrm:island-mounted', arm);
}

// ─ 2. dash-fb-modal ───────────────────────────────────────────────────────
export const FB_FILL_URL = '/api/feedback/fill';
export const FB_IDLE_STATUS_CLASS = 'mt-2 text-xs text-base-content/70';

type FbReply = {
  ok?: boolean;
  error?: string;
  filled?: unknown[];
  already?: unknown[];
  failed?: [string, string][];
};

/**
 * The mid-sem feedback explainer + its one write.
 *
 * Both hooks are delegated: `#fb-cta` is rendered by DashboardPanel (an island
 * that repaints), `#fb-modal`/`#fb-submit` by whichever page template carried
 * the plan. A component-local handler would be recreated per repaint; one
 * document listener survives by construction.
 *
 * Order is dash.js's: disable the button, write "Submitting…", POST, then map
 * the reply onto `#fb-status` (failures listed by subject AND toasted, because
 * a partial fill is the case the student must not miss) and always re-enable.
 */
export function bindFeedbackModal(doc: Document = document, win: Window = window): void {
  doc.addEventListener('click', (ev) => {
    const target = ev.target as Element | null;
    if (!target || typeof target.closest !== 'function') return;
    if (target.closest('#fb-cta')) {
      (doc.getElementById('fb-modal') as HTMLDialogElement | null)?.showModal();
      return;
    }
    const submit = target.closest('#fb-submit') as HTMLButtonElement | null;
    if (!submit) return;

    const status = doc.getElementById('fb-status');
    const paint = (text: string, cls: string): void => {
      if (!status) return;
      status.textContent = text;
      status.className = cls;
    };
    submit.disabled = true;
    paint('Submitting to the portal…', FB_IDLE_STATUS_CLASS);

    fetch(FB_FILL_URL, { method: 'POST' })
      .then((r) => {
        // The server 302s API calls to /login and fetch follows it, so json()
        // would throw and read as "network error" instead of a dead session.
        if (r.redirected) {
          win.location.href = '/login';
          return new Promise<never>(() => {});
        }
        return r.json() as Promise<FbReply>;
      })
      .then((j) => {
        if (!j.ok) {
          paint(j.error || 'failed — nothing submitted', 'mt-2 text-xs text-error');
          showError('Feedback autofill failed: ' + (j.error || 'unknown error'));
          return;
        }
        const parts: string[] = [];
        if (j.filled?.length) parts.push(`${j.filled.length} submitted`);
        if (j.already?.length) parts.push(`${j.already.length} already filled`);
        const failed = j.failed ?? [];
        if (failed.length) {
          parts.push(`${failed.length} failed: ` + failed.map((f) => f[0]).join(', '));
          showError('Feedback: ' + failed.map((f) => `${f[0]} — ${f[1]}`).join('; '));
        }
        paint(
          parts.join(' · ') || 'nothing to submit',
          'mt-2 text-xs ' + (failed.length ? 'text-error' : 'text-success'),
        );
      })
      .catch(() => {
        paint('network error — try again', 'mt-2 text-xs text-error');
        showError('Feedback autofill: network error — try again');
      })
      .finally(() => {
        submit.disabled = false;
      });
  });
}

// ─ 3. dash-auto-refresh ───────────────────────────────────────────────────
/** The staleness threshold dash.js used: 10 minutes. */
export const STALE_AFTER_S = 600;

/**
 * Ask the server to re-sync ONCE if the page it just painted is stale.
 *
 * Why the server and not the local cache: `load.ts`'s cache->network fallback
 * re-reads what the app already stored; only POST /api/refresh re-reads the
 * PORTAL. So this is not deletable-by-Dexie, it is the one thing a stale page
 * does for itself without the user pressing anything.
 *
 * Returns whether it fired — the only way to assert a load-time decision
 * without a network, and the DUT reads it too.
 */
export function autoRefreshIfStale(
  doc: Document = document,
  win: Window = window,
  refresh: (quiet?: boolean) => Promise<void> = triggerRefresh,
): boolean {
  // No navbar caption on this page => no sync-age to judge. (A shell page.)
  const first = doc.querySelector<HTMLElement>('.sync-line');
  if (!first) return false;
  // No readable stored credentials: /api/refresh can only answer 401, and the
  // browser logs that 401 as a console error on THIS page. Nothing to gain —
  // the server's own auto_sync_kick_if_stale already ran.
  const can = doc.querySelector('meta[name="can-sync"]');
  if (can && can.getAttribute('content') === '0') return false;

  const ts = parseInt(first.dataset.ts || '0', 10);
  const stale = !ts || Math.floor(Date.now() / 1000) - ts > STALE_AFTER_S;
  if (!stale || win.navigator?.onLine === false) return false;

  // quiet=true: a background sync that fails is a log line, never a toast.
  void refresh(true);
  return true;
}
