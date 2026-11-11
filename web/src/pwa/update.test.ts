import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { applyUpdate, watchForUpdate } from './update';

/**
 * P8.3 — update banner.
 *
 * The whole feature hinges on ONE distinction, so that is what is asserted:
 * the first controller arriving is a normal load (silent), and a controller
 * that REPLACES an existing one is a new version (banner). Getting that
 * backwards means a banner on every page load.
 */

/** Minimal ServiceWorkerContainer stand-in; jsdom has none. */
function fakeSW() {
  const target = new EventTarget();
  const sw = {
    controller: null as unknown,
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    fire: (type: string) => target.dispatchEvent(new Event(type)),
  };
  Object.defineProperty(navigator, 'serviceWorker', { value: sw, configurable: true });
  return sw;
}

beforeEach(() => {
  Object.defineProperty(navigator, 'serviceWorker', { value: undefined, configurable: true });
});
afterEach(() => {
  Object.defineProperty(navigator, 'serviceWorker', { value: undefined, configurable: true });
});

describe('watchForUpdate', () => {
  it('fires when a worker replaces the one this page was already running', () => {
    const sw = fakeSW();
    sw.controller = { scriptURL: '/static/sw.js' };          // page already controlled
    const onUpdate = vi.fn();
    watchForUpdate(onUpdate);

    sw.controller = { scriptURL: '/static/sw.js' };          // new worker claimed
    sw.fire('controllerchange');

    expect(onUpdate).toHaveBeenCalledTimes(1);
  });

  it('stays silent for the FIRST controller (a normal first load)', () => {
    const sw = fakeSW();                                     // controller === null
    const onUpdate = vi.fn();
    watchForUpdate(onUpdate);

    sw.controller = { scriptURL: '/static/sw.js' };
    sw.fire('controllerchange');

    expect(onUpdate).not.toHaveBeenCalled();
  });

  it('does not throw and does not subscribe when serviceWorkers are unsupported', () => {
    expect(() => watchForUpdate(() => {})).not.toThrow();
  });

  it('stops listening once unsubscribed', () => {
    const sw = fakeSW();
    sw.controller = {};
    const onUpdate = vi.fn();
    const off = watchForUpdate(onUpdate);
    off();

    sw.fire('controllerchange');
    expect(onUpdate).not.toHaveBeenCalled();
  });
});

describe('applyUpdate', () => {
  it('messages the worker and reloads exactly once on controllerchange', () => {
    const sw = fakeSW();
    const postMessage = vi.fn();
    sw.controller = { postMessage };
    const reload = vi.fn();
    // `window` here only supplies `location`; the worker comes from navigator.
    applyUpdate({ location: { reload } } as unknown as Pick<Window, 'location'>);

    expect(postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' });
    expect(reload).not.toHaveBeenCalled();

    sw.fire('controllerchange');                             // a second fire must not reload again
    sw.fire('controllerchange');

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('reloads even when there is no waiting worker to message', () => {
    // skipWaiting() is on install, so this is the REAL path: no message target.
    const sw = fakeSW();
    const reload = vi.fn();
    applyUpdate({ location: { reload } } as unknown as Pick<Window, 'location'>);

    sw.fire('controllerchange');
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
