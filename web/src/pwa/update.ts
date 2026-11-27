/**
 * P8.3 — "a new version is ready, reload to get it".
 *
 * TWO SIGNALS, ONE MEANING
 * ------------------------
 * `web/src/sw-template.js` skips the wait on a FIRST install only
 * (`self.registration.active === null`). An update therefore installs into
 * `waiting` and stays there, so nothing is swapped under a page that is still
 * running: the swap is what the user opts into by pressing Reload.
 *
 * That leaves the banner needing a signal that exists BEFORE the swap:
 *
 *   1. `updatefound` on the registration, then the installing worker reaching
 *      `installed` while a controller is already present. A first install reaches
 *      the same state with `controller === null` and must stay silent, or every
 *      visitor is told to reload the page they just opened.
 *   2. `controllerchange` on a page that already had a controller — the leg that
 *      fires when Reload's SKIP_WAITING promotes the waiting worker, and the only
 *      leg that existed while skipWaiting was unconditional.
 *
 * `decisions.md` (2026-11-13, row `8.3-DOWNGRADE`) records that iOS Safari does
 * not fire `controllerchange` reliably, so signal 2 alone can leave an iPhone
 * with a waiting worker and no banner at all. Signal 1 plus the
 * `visibilitychange` re-poll below (`refreshOnVisible`) cover that.
 *
 * NO BANNER, NO RELOAD
 * --------------------
 * A student does not care which worker is serving them, so nothing here asks
 * them to reload. This module used to paint "a new version is ready" and
 * reload on a click; now the page repaints its own data in place and the first
 * `controllerchange` reloads once, unasked (`reloadOnNextBoot`), for a bundle
 * the running page was never loaded with. `applyUpdate` survives only as the
 * one forced way out (a route the new worker may have removed).
 */

export const UPDATE_EVENT = 'controllerchange';

/**
 * sessionStorage flag meaning "the worker took over under this document".
 *
 * `sessionStorage`, not memory, because a reload clears memory: the only place
 * evidence of a swap can survive the swap is storage that outlives the
 * document. Set at most once per session, so a page that keeps finding itself
 * on an old build reloads at most twice.
 */
export const STALE_KEY = 'osrm-swapped';

/** Swaps allowed per session. One is enough; the env override exists so a
 *  deployment that keeps finding itself on an old build can prove it. */
export function maxSwaps(): number {
  const raw = (globalThis as unknown as { __OSRM_MAX_SWAPS?: number }).__OSRM_MAX_SWAPS;
  return typeof raw === 'number' ? raw : 1;
}

/** Count one spent swap. Never throws: private mode has no storage. */
function bumpSwaps(): void {
  try {
    sessionStorage.setItem(STALE_KEY, String(Number(sessionStorage.getItem(STALE_KEY) || 0) + 1));
  } catch { /* private mode: the loop risk is accepted over a broken page */ }
}

/** How often a tab regaining focus may force a worker check. */
const REFRESH_MS = 5000;

type SWContainer = Pick<
  ServiceWorkerContainer,
  'controller' | 'addEventListener' | 'removeEventListener' | 'getRegistration'
>;

function container(): SWContainer | undefined {
  // jsdom has no `navigator.serviceWorker`; browsers on plain HTTP don't either.
  return (navigator as Navigator & { serviceWorker?: SWContainer }).serviceWorker;
}

/**
 * Calls `onUpdate` when a new worker is waiting for this page to accept it.
 * Returns an unsubscribe function. Never throws: an unsupported browser (no
 * serviceWorkers, e.g. non-secure context) is a normal state, not a fault.
 */
export function watchForUpdate(onUpdate: () => void): () => void {
  const sw = container();
  if (!sw) return () => {};

  // Captured at subscribe time, which is the only moment "did this page already
  // have a worker?" can be answered truthfully. Reading it inside the listener
  // would see the NEW controller and conclude nothing changed.
  let had = sw.controller !== null;

  // Signal 2: the controller was replaced on a page that already had one.
  const onChange = (): void => {
    const now = sw.controller !== null;
    const swapped = had && now;
    had = now;                     // keep in step: the next change compares to this
    if (swapped) onUpdate();
  };
  sw.addEventListener(UPDATE_EVENT, onChange);

  // Signal 1: a worker installed and went into `waiting`. `updatefound` only
  // fires on a registration that already exists, so the lookup is async; an
  // update found before the listener is attached is still caught by signal 2.
  let reg: ServiceWorkerRegistration | undefined;
  let live = true;
  const offs: Array<() => void> = [];

  const onFound = (): void => {
    const installing = reg?.installing;
    if (!installing) return;
    const onState = (): void => {
      if (installing.state !== 'installed') return;
      installing.removeEventListener('statechange', onState);
      // "Installed while a controller exists" is an update. A first install
      // reaches 'installed' with `controller === null` and must stay silent.
      if (sw.controller !== null) onUpdate();
    };
    installing.addEventListener('statechange', onState);
  };

  const getReg = sw.getRegistration;
  if (getReg) {
    void getReg
      .call(sw)
      .then((r) => {
        if (!r || !live) return;
        reg = r;
        r.addEventListener('updatefound', onFound);
        offs.push(() => r.removeEventListener('updatefound', onFound));
      })
      .catch(() => {});
  }

  return () => {
    live = false;
    sw.removeEventListener(UPDATE_EVENT, onChange);
    offs.forEach((off) => off());
  };
}

/**
 * Hands the WAITING worker its cue and reloads exactly once, when the new
 * worker becomes the controller.
 *
 * The message target is `registration.waiting`, not `controller`: the controller
 * is the old worker, which is already active, so messaging it does nothing.
 * With a waiting worker the `controllerchange` that follows the promotion is the
 * reload trigger. If nothing is waiting (no registration, an edge-case browser)
 * a plain reload is the only action left, so the button is never dead.
 *
 * `location.reload()` sits INSIDE the guard because `controllerchange` fires
 * once per claim; a second fire without the flag would reload the newly-loaded
 * page again, forever.
 */
export function applyUpdate(w: Pick<Window, 'location'> = window): void {
  const sw = container();
  if (!sw) return;

  let done = false;
  const reload = (): void => {
    if (done) return;
    done = true;
    sw.removeEventListener(UPDATE_EVENT, reload);
    w.location.reload();
  };
  sw.addEventListener(UPDATE_EVENT, reload);

  const getReg = sw.getRegistration;
  if (!getReg) {
    reload();
    return;
  }
  void getReg.call(sw).then((reg) => {
    if (reg?.waiting) reg.waiting.postMessage({ type: 'SKIP_WAITING' });
    else reload();
  }, reload);
}

/**
 * Asks the browser to check for a new worker whenever the tab becomes visible.
 *
 * Discovery is otherwise up to the browser: a tab left open for days may never
 * look for a new worker on its own, and iOS Safari does not fire
 * `controllerchange` reliably (decisions.md `8.3-DOWNGRADE`), so without this an
 * iPhone can sit on an old bundle with no notice at all. Throttled, because
 * flipping between tabs fires `visibilitychange` far faster than a release is
 * published. Never throws: no `document` or no service workers is a normal
 * state, not a fault.
 */
export function refreshOnVisible(): () => void {
  const sw = container();
  const getReg = sw?.getRegistration;
  if (typeof document === 'undefined' || !sw || !getReg) return () => {};

  let last = 0;
  const onVisible = (): void => {
    if (document.visibilityState !== 'visible') return;
    const now = Date.now();
    if (now - last < REFRESH_MS) return;
    last = now;
    void getReg.call(sw).then((reg) => reg?.update()).catch(() => {});
  };

  document.addEventListener('visibilitychange', onVisible);
  return () => document.removeEventListener('visibilitychange', onVisible);
}

/**
 * Take a waiting new worker at the next moment nothing is going on, then reload
 * ONCE so the page runs the bundle that worker carries.
 *
 * Why a reload at all: repainting in place refreshes DATA, never markup —
 * `refreshIslands` patches islands from their `/api` slices, so a release that
 * changed a template would otherwise reach an open tab only on its next open.
 * The swap is therefore automatic, never asked for: taken at boot (a fresh
 * document, nothing typed) or while the tab is hidden (nobody looking), and
 * `pending` is the boot-time backstop for a swap taken mid-session.
 *
 * The rules that must hold:
 *   * nothing typed is lost — `dialog[open]`, `details[open]`, a focused input
 *     and a running sync all stand the swap down, and it looks again later;
 *   * a first install is a normal load and never reloads;
 *   * a swap that reloads onto the SAME build stops after `STALE_MAX` boots,
 *     or a worker that cannot take over reloads the tab for ever.
 *
 * `beforeSwap` is the last look at the page before it goes. Returns an
 * unsubscribe.
 */
export function reloadOnNextBoot(
  opts: { beforeSwap?: () => boolean; win?: Window & typeof globalThis; loadedWith?: () => string } = {},
): () => void {
  const win = opts.win ?? window;
  const sw = container();
  if (!sw) return () => {};
  let done = false;

  const idle = (): boolean => {
    const d = win.document;
    if (!d) return false;
    if (d.querySelector('dialog[open]') || d.querySelector('details[open]')) return true;
    const a = d.activeElement as HTMLElement | null;
    if (a && a !== d.body) {
      const tag = a.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || a.isContentEditable) return true;
    }
    return !!opts.beforeSwap?.();
  };

  const swap = (): void => {
    if (done || !sw.controller) return;
    if (win.navigator?.onLine === false) return;
    if (idle()) return;
    done = true;
    bumpSwaps();                  // spent BEFORE the reload, not after it
    void sw.getRegistration?.call(sw).then((reg) => {
      if (reg?.waiting) {
        reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        win.location.reload();     // queued behind the worker: the new one serves it
        return;
      }
      void reg?.update?.().then(() => win.location.reload(), () => {});
    }, () => { done = false; });
  };

  // A boot swap in flight: this document keeps its data work but never swaps
  // again, or a worker that fails to take over would reload in a loop.
  if (sessionStorage.getItem(STALE_KEY) === '1') return () => {};   // already swapped once

  // The worker took over under this document (`controllerchange`): the next
  // boot swaps once, which is the backstop for a swap decided mid-session.
  const onChange = (): void => {
    bumpSwaps();
  };

  const onVisibility = (): void => {
    if (win.document.visibilityState === 'hidden') swap();
  };

  sw.addEventListener(UPDATE_EVENT, onChange);
  win.document.addEventListener('visibilitychange', onVisibility);
  // A focused field was left: the swap it stood down on is now allowed.
  win.document.addEventListener('focusout', swap);

  // A hidden tab is still on the line, and `hidden` fires at load for a
  // prerendered or background tab, so read it before the boot swap.
  if (win.document.visibilityState === 'hidden') swap();
  else if (win.document.readyState === 'complete') setTimeout(swap, 0);
  else win.addEventListener('load', swap, { once: true });

  return () => {
    sw.removeEventListener(UPDATE_EVENT, onChange);
    win.document.removeEventListener('visibilitychange', onVisibility);
    win.document.removeEventListener('focusout', swap);
  };
}
