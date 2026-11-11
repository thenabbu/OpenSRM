/**
 * P8.3 — "a new version is ready, reload to get it".
 *
 * WHY THIS DOES NOT WATCH FOR A `waiting` WORKER
 * ----------------------------------------------
 * The obvious implementation is `reg.addEventListener('updatefound', ...)` and
 * then waiting for `reg.waiting`. That code would be dead: `web/src/sw-template.js:45`
 * calls `skipWaiting()` on install, so a new worker never sits in `waiting` —
 * it installs, activates, claims the clients and boots the OLD page out from
 * under itself. Measured consequence of that pair: `controllerchange`.
 *
 * So the signal here is what actually happens: the controller CHANGED after the
 * page was already controlled. The browser has swapped the bundle and the
 * running page is now executing stale JS against a new cache — reloading is the
 * fix, and it also means the check runs by inspecting the live system instead of
 * trusting the worker's lifecycle state.
 *
 * The first controller (null -> a worker) is the normal first load and must NOT
 * raise the banner, or every fresh visitor would be told to reload the page they
 * just opened.
 */

export const UPDATE_EVENT = 'controllerchange';

type SWContainer = Pick<ServiceWorkerContainer, 'controller' | 'addEventListener' | 'removeEventListener'>;

function container(): SWContainer | undefined {
  // jsdom has no `navigator.serviceWorker`; browsers on plain HTTP don't either.
  return (navigator as Navigator & { serviceWorker?: SWContainer }).serviceWorker;
}

/**
 * Calls `onUpdate` when a worker takes over a page that was ALREADY controlled.
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

  const onChange = (): void => {
    const now = sw.controller !== null;
    const swapped = had && now;
    had = now;                     // keep in step: the next change compares to this
    if (swapped) onUpdate();
  };

  sw.addEventListener(UPDATE_EVENT, onChange);
  return () => sw.removeEventListener(UPDATE_EVENT, onChange);
}

/**
 * Hands the waiting worker its cue and reloads exactly once, when the new
 * worker becomes the controller.
 *
 * With `skipWaiting()` on install there is usually no waiting worker to message,
 * so `postMessage` is best-effort — the `controllerchange` listener is the part
 * that makes this work, and it works for both worker shapes.
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

  sw.controller?.postMessage({ type: 'SKIP_WAITING' });
}
