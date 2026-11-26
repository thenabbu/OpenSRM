import { triggerRefresh } from './refresh';

// ── Pull-to-refresh (W5.4e) — the four pull-* rows, ported out of
//    `app/static/pull.js`. Matrix names, so a future grep finds them:
//
//   pull-refresh-gesture        → bindPullToRefresh()  (touchstart/move/end + the fired refresh)
//   pull-excluded-regions       → excludedRegion()     (.widget-scroll, #tt-editor, [draggable=true])
//   pull-dialog-guard           → dialogOpen()         (dialog[open], .modal-open)
//   pull-refresh-running-guard  → refreshRunning()     (.refresh-icon.animate-spin / [data-refresh] busy)
//
// Why this is a PORT and not a KEEP: pull.js was the LAST caller of dash.js's
// global `ref()` — reached through `typeof ref === "function"` — so deleting
// dash.js first degraded pull-to-refresh to a SILENT no-op that no test would
// catch (the matrix's ordering trap). This module calls `triggerRefresh()`
// directly, so the gesture depends on no classic <script> at all and W5.4 can
// delete pull.js and dash.js in either order.
//
// COARSE POINTERS ONLY: the whole binder is a no-op unless `(pointer: coarse)`
// matches — that is why a desktop mouse can never pull.
//
// ONE BINDER: pull.js stays until W5.4 deletes it, so main.ts publishes
// `window.__osrmPull` and pull.js returns before binding when it sees it. Two
// binders means two POST /api/refresh per gesture — the double-fire t_d051895a
// chased — and `test_pull_dut`'s `delta == 1` check is what catches it.
//
// Nothing here persists, so there is no `local.ts` route: the gesture keeps all
// of its state in this closure and resets it on every release.

export const PULL_THRESHOLD = 80;
/** Rubber-band denominator: pull = raw * (1 - exp(-raw / 120)). */
export const RUBBER_DENOM = 120;
/** Indicator rotation in degrees per pulled px (pull.js used 1.6). */
export const ROTATE_PER_PX = 1.6;
export const SPRING_MS = 420;
export const EXCLUDED_SELECTOR = '.widget-scroll, #tt-editor, [draggable=true]';
/** Inline styles only — CSP allows style attributes on this page. */
export const INDICATOR_CSS =
  'position:fixed;top:14px;left:50%;width:22px;height:22px;margin:-11px 0 0 -11px;' +
  'border:2.5px solid rgba(255,255,255,.25);border-top-color:rgba(255,255,255,.85);' +
  'border-radius:50%;opacity:0;z-index:60;pointer-events:none;will-change:transform;';

export type Refresh = (quiet?: boolean) => Promise<unknown> | unknown;
type Touchish = { clientY: number };
type TouchEvt = Event & { touches?: ArrayLike<Touchish> };

/** 1:1 finger tracking with rubber-band resistance (saturates under the finger). */
export const rubberBand = (raw: number): number => raw * (1 - Math.exp(-raw / RUBBER_DENOM));

/** `pull-refresh-running-guard`: a refresh is already in flight. */
export const refreshRunning = (doc: Document): boolean => {
  if (doc.querySelector('.refresh-icon.animate-spin')) return true;
  const btn = doc.querySelector('[data-refresh]') as HTMLButtonElement | null;
  // aria-disabled is the busy marker (W5.2a); `disabled` is the old one.
  return !!btn && (btn.disabled || btn.getAttribute('aria-disabled') === 'true');
};

/** `pull-dialog-guard`: a modal owns the screen, so the gesture is not available. */
export const dialogOpen = (doc: Document): boolean =>
  !!doc.querySelector('dialog[open]') || !!doc.querySelector('.modal-open');

/** `pull-excluded-regions`: a scroller, the timetable editor or a draggable got the touch. */
export const excludedRegion = (target: EventTarget | null): boolean => {
  const el = target as (Element & { closest?: (s: string) => Element | null }) | null;
  return !!el && typeof el.closest === 'function' && !!el.closest(EXCLUDED_SELECTOR);
};

/**
 * Bind the pull gesture once. No-ops entirely on a fine pointer.
 *
 * `refresh` is injected so the row-level test can count calls without a server;
 * the default is the one refresh primitive (W5.2a), never a second copy.
 */
export function bindPullToRefresh(
  doc: Document = document,
  win: Window = window,
  refresh: Refresh = triggerRefresh,
): void {
  const mm = (q: string): boolean => !!win.matchMedia?.(q).matches;
  if (!mm('(pointer: coarse)')) return;

  const body = doc.body;
  const reduced = (): boolean => mm('(prefers-reduced-motion: reduce)');
  let ind: HTMLDivElement | undefined;
  let startY = -1;
  let dy = 0;
  let pulling = false;
  let springing = false;

  const ensureIndicator = (): void => {
    if (ind) return;
    ind = doc.createElement('div');
    ind.setAttribute('aria-hidden', 'true');
    ind.style.cssText = INDICATOR_CSS;
    body.appendChild(ind);
  };

  const apply = (pullPx: number, rot: number): void => {
    body.style.transform = `translateY(${pullPx}px)`;
    body.style.transition = 'none';
    if (!ind) return;
    ind.style.transform = `translateY(${pullPx}px)${rot ? ` rotate(${rot}deg)` : ''}`;
    ind.style.opacity = Math.min(1, pullPx / PULL_THRESHOLD).toFixed(3);
  };

  const clear = (): void => {
    body.style.transition = '';
    body.style.transform = '';
    if (!ind) return;
    ind.style.transition = '';
    ind.style.transform = '';
    ind.style.opacity = '0';
  };

  const settle = (animate: boolean): void => {
    if (animate && ind && !reduced()) {
      body.style.transition = 'transform 380ms var(--ease-spring)';
      ind.style.transition = 'transform 380ms var(--ease-spring), opacity 240ms linear';
      body.style.transform = 'translateY(0)';
      ind.style.transform = 'translateY(0)';
      ind.style.opacity = '0';
      springing = true;
      setTimeout(() => {
        springing = false;
        clear();
      }, SPRING_MS);
    } else {
      clear();
    }
    pulling = false;
    startY = -1;
    dy = 0;
  };

  const onStart = (e: Event): void => {
    const te = e as TouchEvt;
    if (springing || refreshRunning(doc) || dialogOpen(doc)) { startY = -1; return; }
    if (win.scrollY !== 0) { startY = -1; return; }
    if (excludedRegion(e.target)) { startY = -1; return; }
    const touches = te.touches;
    if (!touches || touches.length !== 1) { startY = -1; return; }
    const first = touches[0];
    if (!first) { startY = -1; return; }
    startY = first.clientY;
    dy = 0;
    pulling = false;
  };

  const onMove = (e: Event): void => {
    const te = e as TouchEvt;
    if (startY < 0 || springing) return;
    const touches = te.touches;
    if (!touches || !touches.length) return;
    const first = touches[0];
    if (!first) return;
    const raw = first.clientY - startY;
    if (raw <= 0) { if (pulling) settle(false); return; }
    if (win.scrollY !== 0) { settle(false); return; }
    pulling = true;
    dy = rubberBand(raw);
    // Reduced motion drops the ROTATION only (decoration). Tracking stays 1:1
    // with the finger — that is direct manipulation, not animation.
    apply(dy, reduced() ? 0 : dy * ROTATE_PER_PX);
  };

  const onEnd = (): void => {
    // startY < 0 is also the double-fire guard: a repeated touchend (iOS emits
    // one for some cancelled gestures) must not start a second refresh.
    if (startY < 0) return;
    if (pulling && dy >= PULL_THRESHOLD) {
      settle(false);                 // snap the content away; the nav spinner is the state
      void refresh(false);
    } else if (pulling) {
      settle(true);                  // spring back (instant under reduced motion)
    } else {
      pulling = false;
      startY = -1;
    }
    startY = -1;
  };

  const onCancel = (): void => {
    if (startY >= 0) settle(false);
  };

  ensureIndicator();
  doc.addEventListener('touchstart', onStart, { passive: true });
  doc.addEventListener('touchmove', onMove, { passive: true });
  doc.addEventListener('touchend', onEnd, { passive: true });
  doc.addEventListener('touchcancel', onCancel, { passive: true });
}
