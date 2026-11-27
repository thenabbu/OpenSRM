import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { applyUpdate, refreshOnVisible, reloadOnNextBoot, STALE_KEY, watchForUpdate } from './update';

/**
 * P8.3 — update banner.
 *
 * Two signals hold this feature up now that the worker waits on an update:
 *
 *   - a worker that installs and reaches `installed` while a controller exists
 *     (the notice must appear BEFORE the swap, that is the whole point);
 *   - `controllerchange` when the controller is replaced on a page that already
 *     had one (the leg that fires when Reload promotes the waiting worker).
 *
 * Plus the one distinction that must never invert: the FIRST controller is a
 * normal load, and telling that visitor to reload is a banner on every visit.
 */

type FakeWorker = {
  state: string;
  addEventListener: (t: string, l: () => void) => void;
  removeEventListener: (t: string, l: () => void) => void;
  finish: (next?: string) => void;
};

function fakeWorker(state = 'installing'): FakeWorker {
  const target = new EventTarget();
  const w: FakeWorker = {
    state,
    addEventListener: target.addEventListener.bind(target) as FakeWorker['addEventListener'],
    removeEventListener: target.removeEventListener.bind(target) as FakeWorker['removeEventListener'],
    // Drive the lifecycle the way the browser does: state first, then the event.
    finish: (next = 'installed') => {
      w.state = next;
      target.dispatchEvent(new Event('statechange'));
    },
  };
  return w;
}

function fakeReg() {
  const target = new EventTarget();
  const reg = {
    installing: null as FakeWorker | null,
    waiting: null as { postMessage: (m: unknown) => void } | null,
    update: vi.fn(async () => {}),
    addEventListener: target.addEventListener.bind(target) as (t: string, l: () => void) => void,
    removeEventListener: target.removeEventListener.bind(target) as (t: string, l: () => void) => void,
    fire: (type: string) => target.dispatchEvent(new Event(type)),
  };
  return reg;
}

/** Minimal ServiceWorkerContainer stand-in; jsdom has none. */
function fakeSW(reg = fakeReg()) {
  const target = new EventTarget();
  const sw = {
    controller: null as unknown,
    getRegistration: vi.fn(async () => reg as unknown as ServiceWorkerRegistration),
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    fire: (type: string) => target.dispatchEvent(new Event(type)),
  };
  Object.defineProperty(navigator, 'serviceWorker', { value: sw, configurable: true });
  return { sw, reg };
}

/** Let the async `getRegistration()` chain settle. */
const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

const unsubscribes: Array<() => void> = [];
const setVisibility = (v: 'visible' | 'hidden'): void =>
  Object.defineProperty(document, 'visibilityState', { value: v, configurable: true });
const fireVisibility = (): void => document.dispatchEvent(new Event('visibilitychange'));
const watchVisibility = (): ReturnType<typeof vi.fn> => {
  const update = vi.fn(async () => {});
  return update;
};

beforeEach(() => {
  Object.defineProperty(navigator, 'serviceWorker', { value: undefined, configurable: true });
  setVisibility('visible');
  // The swap budget is sessionStorage, which jsdom keeps across tests: a test
  // that spends it would silently disarm the next one.
  sessionStorage.clear();
  (document.activeElement as HTMLElement | null)?.blur?.();
  document.body.replaceChildren();
});
afterEach(() => {
  unsubscribes.splice(0).forEach((off) => off());
  Object.defineProperty(navigator, 'serviceWorker', { value: undefined, configurable: true });
  vi.useRealTimers();
});

describe('watchForUpdate', () => {
  it('fires when a worker replaces the one this page was already running', () => {
    const { sw } = fakeSW();
    sw.controller = { scriptURL: '/static/sw.js' };          // page already controlled
    const onUpdate = vi.fn();
    watchForUpdate(onUpdate);

    sw.controller = { scriptURL: '/static/sw.js' };          // new worker claimed
    sw.fire('controllerchange');

    expect(onUpdate).toHaveBeenCalledTimes(1);
  });

  it('stays silent for the FIRST controller (a normal first load)', () => {
    const { sw } = fakeSW();                                 // controller === null
    const onUpdate = vi.fn();
    watchForUpdate(onUpdate);

    sw.controller = { scriptURL: '/static/sw.js' };
    sw.fire('controllerchange');

    expect(onUpdate).not.toHaveBeenCalled();
  });

  it('fires when an update worker installs and WAITS (no controllerchange needed)', async () => {
    const { sw, reg } = fakeSW();
    sw.controller = { scriptURL: '/static/sw.js' };          // an old worker is running
    const onUpdate = vi.fn();
    watchForUpdate(onUpdate);
    await flush();                                           // updatefound listener attached

    const worker = fakeWorker('installing');
    reg.installing = worker;
    reg.fire('updatefound');
    expect(onUpdate).not.toHaveBeenCalled();                 // still downloading

    worker.finish('installed');                              // now it is waiting, page untouched
    expect(onUpdate).toHaveBeenCalledTimes(1);
  });

  it('stays silent when a FIRST install reaches installed', async () => {
    const { sw, reg } = fakeSW();                            // controller === null
    const onUpdate = vi.fn();
    watchForUpdate(onUpdate);
    await flush();

    const worker = fakeWorker('installing');
    reg.installing = worker;
    reg.fire('updatefound');
    worker.finish('installed');

    expect(onUpdate).not.toHaveBeenCalled();
  });

  it('does not throw and does not subscribe when serviceWorkers are unsupported', () => {
    expect(() => watchForUpdate(() => {})).not.toThrow();
  });

  it('stops listening once unsubscribed', async () => {
    const { sw, reg } = fakeSW();
    sw.controller = {};
    const onUpdate = vi.fn();
    const off = watchForUpdate(onUpdate);
    await flush();
    off();

    sw.fire('controllerchange');
    const worker = fakeWorker();
    reg.installing = worker;
    reg.fire('updatefound');
    worker.finish('installed');

    expect(onUpdate).not.toHaveBeenCalled();
  });
});

describe('applyUpdate', () => {
  it('messages the WAITING worker, never the controller, and reloads once', async () => {
    const { sw, reg } = fakeSW();
    const controllerPost = vi.fn();
    sw.controller = { postMessage: controllerPost };         // the OLD, already-active worker
    const waitingPost = vi.fn();
    reg.waiting = { postMessage: waitingPost };
    const reload = vi.fn();
    // `window` here only supplies `location`; the worker comes from navigator.
    applyUpdate({ location: { reload } } as unknown as Pick<Window, 'location'>);
    await flush();

    expect(waitingPost).toHaveBeenCalledWith({ type: 'SKIP_WAITING' });
    expect(controllerPost).not.toHaveBeenCalled();           // messaging it is a no-op
    expect(reload).not.toHaveBeenCalled();

    sw.fire('controllerchange');                             // the new worker claimed
    sw.fire('controllerchange');                             // a second fire must not reload again

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('falls back to a plain reload when nothing is waiting (never a dead button)', async () => {
    const { sw, reg } = fakeSW();
    sw.controller = { postMessage: vi.fn() };
    reg.waiting = null;
    const reload = vi.fn();
    applyUpdate({ location: { reload } } as unknown as Pick<Window, 'location'>);
    await flush();

    expect(reload).toHaveBeenCalledTimes(1);
  });
});

describe('refreshOnVisible', () => {
  it('asks the registration for an update when the tab becomes visible', async () => {
    const { sw, reg } = fakeSW();
    reg.update = watchVisibility();
    unsubscribes.push(refreshOnVisible());

    setVisibility('visible');
    fireVisibility();
    await flush();

    expect(reg.update).toHaveBeenCalledTimes(1);
    expect(sw.getRegistration).toHaveBeenCalled();
  });

  it('does not poll while the tab is hidden', async () => {
    const { reg } = fakeSW();
    reg.update = watchVisibility();
    unsubscribes.push(refreshOnVisible());

    setVisibility('hidden');
    fireVisibility();
    await flush();

    expect(reg.update).not.toHaveBeenCalled();
  });

  it('throttles tab-flapping instead of hammering the network', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-17T00:00:00Z'));
    const { reg } = fakeSW();
    reg.update = watchVisibility();
    unsubscribes.push(refreshOnVisible());

    fireVisibility();
    await flush();
    fireVisibility();                                        // same second: throttled
    await flush();
    expect(reg.update).toHaveBeenCalledTimes(1);

    vi.setSystemTime(new Date('2026-11-17T00:00:06Z'));      // past the 5 s window
    fireVisibility();
    await flush();
    expect(reg.update).toHaveBeenCalledTimes(2);
  });

  it('does not throw when service workers are unsupported', () => {
    expect(() => refreshOnVisible()).not.toThrow();
    expect(() => fireVisibility()).not.toThrow();
  });
});

describe('reloadOnNextBoot', () => {
  const state = (): string => sessionStorage.getItem(STALE_KEY) ?? '';

  it('swaps a waiting worker at boot and reloads ONCE, unasked', async () => {
    const { sw, reg } = fakeSW();
    const waitingPost = vi.fn();
    reg.waiting = { postMessage: waitingPost };
    sw.controller = { scriptURL: '/static/sw.js' };
    const reload = vi.fn();
    const win = { document, navigator, location: { reload } } as unknown as Window & typeof globalThis;

    reloadOnNextBoot({ win });
    await flush();

    expect(waitingPost).toHaveBeenCalledWith({ type: 'SKIP_WAITING' });
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('does not swap while a field is focused — a typed value is never lost', async () => {
    const { sw, reg } = fakeSW();
    reg.waiting = { postMessage: vi.fn() };
    sw.controller = { scriptURL: '/static/sw.js' };
    const reload = vi.fn();
    const win = { document, navigator, location: { reload } } as unknown as Window & typeof globalThis;

    const input = document.createElement('input');
    document.body.append(input);
    input.focus();

    reloadOnNextBoot({ win });
    await flush();
    expect(sw.controller).toBeTruthy();
    expect(reload).not.toHaveBeenCalled();      // stood down: the field is in use

    input.remove();                             // this doc's focus is NOT the next test's
  });

  it('never reloads twice in one session, so a failed takeover cannot loop', async () => {
    const { sw, reg } = fakeSW();
    reg.waiting = { postMessage: vi.fn() };
    sw.controller = { scriptURL: '/static/sw.js' };
    const reload = vi.fn();
    const win = { document, navigator, location: { reload } } as unknown as Window & typeof globalThis;

    reloadOnNextBoot({ win });
    await flush();
    expect(reload).toHaveBeenCalledTimes(1);

    // The reload came back on the SAME document (the old worker answered it).
    // A second boot must not try again — that is the infinite reload.
    reloadOnNextBoot({ win });
    await flush();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(state()).toBe('1');   // one swap spent, this session
  });

  it('a first install is a normal load: nothing is reloaded', async () => {
    const { sw } = fakeSW();                    // controller === null
    const reload = vi.fn();
    const win = { document, navigator, location: { reload } } as unknown as Window & typeof globalThis;

    reloadOnNextBoot({ win });
    await flush();
    expect(reload).not.toHaveBeenCalled();
  });
});
