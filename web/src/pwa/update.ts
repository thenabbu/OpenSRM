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
 */

export const UPDATE_EVENT = 'controllerchange';

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
