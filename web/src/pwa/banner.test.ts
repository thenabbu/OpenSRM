import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mountBanner } from './banner';
import { __resetInstall } from './install';

/**
 * P8.3 — the banner is the USER-VISIBLE half of the update + install flow.
 *
 * `update.test.ts` covers the event wiring underneath it: which lifecycle event
 * counts as "a new version". It asserts nothing about what a student meets, so a
 * banner that never painted, painted the wrong words, or offered a button that
 * did nothing would keep that suite green. That is what this file covers: the
 * update strip (every device, per session) and the install card (phone only,
 * per device, and the cross hands the job to the navbar).
 */

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

/** The same, plus a registration: the shape an UPDATE actually arrives in. */
function fakeSWWithRegistration() {
  const swTarget = new EventTarget();
  const regTarget = new EventTarget();
  const workerTarget = new EventTarget();
  const worker = {
    state: 'installing',
    addEventListener: workerTarget.addEventListener.bind(workerTarget),
    removeEventListener: workerTarget.removeEventListener.bind(workerTarget),
    // The browser sets `state` and then fires the event; do the same.
    finish: (): void => {
      worker.state = 'installed';
      workerTarget.dispatchEvent(new Event('statechange'));
    },
  };
  const reg = {
    installing: null as unknown,
    waiting: null as unknown,
    update: vi.fn(async () => {}),
    addEventListener: regTarget.addEventListener.bind(regTarget),
    removeEventListener: regTarget.removeEventListener.bind(regTarget),
    fire: (type: string) => regTarget.dispatchEvent(new Event(type)),
  };
  const sw = {
    controller: null as unknown,
    getRegistration: vi.fn(async () => reg),
    addEventListener: swTarget.addEventListener.bind(swTarget),
    removeEventListener: swTarget.removeEventListener.bind(swTarget),
    fire: (type: string) => swTarget.dispatchEvent(new Event(type)),
  };
  Object.defineProperty(navigator, 'serviceWorker', { value: sw, configurable: true });
  return { sw, reg, worker };
}

const bannerEl = (): HTMLElement => {
  const el = document.getElementById('pwa-banner');
  if (!el) throw new Error('banner was never mounted into <body>');
  return el;
};
const shown = (el: HTMLElement): boolean => !el.classList.contains('hidden');
const labels = (el: HTMLElement): string[] =>
  Array.from(el.querySelectorAll('button')).map((b) => (b.textContent || '').trim());
const click = (el: HTMLElement | null, label: string): void => {
  if (!el) throw new Error(`no element to click "${label}" in`);
  const btn = Array.from(el.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === label);
  if (!btn) throw new Error(`no "${label}" button; banner offers: ${labels(el).join(' | ')}`);
  btn.click();
};

const realLocation = Object.getOwnPropertyDescriptor(window, 'location');
const realMatchMedia = Object.getOwnPropertyDescriptor(window, 'matchMedia');

/**
 * jsdom implements no media queries at all, so the device state the card keys on
 * has to be stated: `phone` is the `(pointer: coarse) and (hover: none)` answer
 * and `standalone` is `(display-mode: standalone)`.
 */
function fakeDevice({ phone = true, standalone = false } = {}): void {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: (query: string) => ({
      matches: query.includes('pointer: coarse') ? phone : query.includes('display-mode: standalone') ? standalone : false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

/** The phone navbar the card's dismissal hands over to (base.html markup). */
function mobileNavbar(): HTMLElement {
  const nav = document.createElement('div');
  nav.id = 'mobile-navbar';
  const end = document.createElement('div');
  end.className = 'navbar-end';
  nav.append(end);
  document.body.append(nav);
  return nav;
}
const navButton = (): HTMLElement | null => document.getElementById('pwa-install-btn');

type PromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
};

/** What Chromium fires when the app is installable (never on iOS Safari). */
function offerInstallPrompt(outcome: 'accepted' | 'dismissed' = 'dismissed'): PromptEvent {
  const e = new Event('beforeinstallprompt') as PromptEvent;
  Object.assign(e, {
    prompt: vi.fn(async () => {}),
    userChoice: Promise.resolve({ outcome }),
  });
  window.dispatchEvent(e);
  return e;
}

/**
 * Pretend to be the one browser family with no install API. Safari never fires
 * `beforeinstallprompt`, so this state is what an iPhone actually gives us.
 */
function fakeIOS(standalone = false): void {
  Object.defineProperty(navigator, 'userAgent', {
    value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    configurable: true,
  });
  Object.defineProperty(navigator, 'standalone', { value: standalone, configurable: true });
}
const dropUaOverrides = (): void => {
  delete (navigator as unknown as Record<string, unknown>).userAgent;
  delete (navigator as unknown as Record<string, unknown>).standalone;
};

/**
 * Node 26 exports a global `localStorage` that is `undefined` unless the process
 * was started with `--localstorage-file`, and it shadows jsdom's. The card keys
 * its one-per-device state on localStorage, so the test states that store itself.
 */
function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() { return m.size; },
    clear: () => m.clear(),
    getItem: (k: string) => m.get(k) ?? null,
    key: (i: number) => [...m.keys()][i] ?? null,
    removeItem: (k: string) => void m.delete(k),
    setItem: (k: string, v: string) => void m.set(k, v),
  } as Storage;
}

let local: Storage;

beforeEach(() => {
  document.body.replaceChildren();
  sessionStorage.clear();
  local = memoryStorage();
  vi.stubGlobal('localStorage', local);
  __resetInstall();
  Object.defineProperty(navigator, 'serviceWorker', { value: undefined, configurable: true });
  if (realMatchMedia) Object.defineProperty(window, 'matchMedia', realMatchMedia);
});
afterEach(() => {
  document.body.replaceChildren();
  dropUaOverrides();
  if (realMatchMedia) Object.defineProperty(window, 'matchMedia', realMatchMedia);
  else delete (window as unknown as Record<string, unknown>).matchMedia;
  // jsdom's Location is not spy-able (`Cannot redefine property: reload`), so the
  // reload test swaps the whole object; put the real one back for the next test.
  if (realLocation) Object.defineProperty(window, 'location', realLocation);
  vi.restoreAllMocks();
});

describe('update banner', () => {
  it('is invisible on a normal load, then appears with a Reload button', () => {
    const sw = fakeSW();
    sw.controller = { scriptURL: '/static/sw.js' };        // page already controlled
    mountBanner();

    // Positive control: the element exists but the user sees nothing yet.
    expect(shown(bannerEl())).toBe(false);

    sw.controller = { scriptURL: '/static/sw.js' };        // a new worker claimed
    sw.fire('controllerchange');

    const el = bannerEl();
    expect(shown(el)).toBe(true);
    expect(el.textContent).toContain('A new version of openSRM is ready.');
    expect(labels(el)).toContain('Reload');
  });

  it('appears from updatefound + installed, with no controllerchange (the iOS path)', async () => {
    const { sw, reg, worker } = fakeSWWithRegistration();
    sw.controller = { scriptURL: '/static/sw.js' };         // page already controlled
    mountBanner();
    await new Promise((resolve) => setTimeout(resolve, 0)); // getRegistration() settles

    reg.installing = worker;
    reg.fire('updatefound');
    expect(shown(bannerEl())).toBe(false);                 // still downloading: nothing to say yet

    worker.finish();                                       // installed, waiting, page untouched
    expect(shown(bannerEl())).toBe(true);
    expect(bannerEl().textContent).toContain('A new version of openSRM is ready.');
    expect(labels(bannerEl())).toContain('Reload');
  });

  it('never tells a first-time visitor to reload the page they just opened', () => {
    const sw = fakeSW();                                   // controller === null
    mountBanner();

    sw.controller = { scriptURL: '/static/sw.js' };
    sw.fire('controllerchange');

    expect(shown(bannerEl())).toBe(false);
  });

  it('clicking Reload promotes the WAITING worker, then reloads exactly once', async () => {
    const { sw, reg } = fakeSWWithRegistration();
    const waitingPost = vi.fn();
    reg.waiting = { postMessage: waitingPost };
    sw.controller = { scriptURL: '/static/sw.js' };
    const reload = vi.fn();
    Object.defineProperty(window, 'location', { value: { reload }, configurable: true });
    mountBanner();
    await new Promise((resolve) => setTimeout(resolve, 0)); // getRegistration() settles

    sw.controller = { scriptURL: '/static/sw.js' };
    sw.fire('controllerchange');
    click(bannerEl(), 'Reload');
    await new Promise((resolve) => setTimeout(resolve, 0)); // applyUpdate's lookup settles

    // The cue goes to the waiting worker; the reload is armed by the click and
    // fires when that worker actually takes over.
    expect(waitingPost).toHaveBeenCalledWith({ type: 'SKIP_WAITING' });
    expect(reload).not.toHaveBeenCalled();
    sw.fire('controllerchange');
    expect(reload).toHaveBeenCalledTimes(1);

    sw.fire('controllerchange');                            // must not reload again
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('dismiss hides the banner and keeps it away for the session', () => {
    const sw = fakeSW();
    sw.controller = { scriptURL: '/static/sw.js' };
    mountBanner();

    sw.controller = { scriptURL: '/static/sw.js' };
    sw.fire('controllerchange');
    click(bannerEl(), '✕');

    expect(shown(bannerEl())).toBe(false);
    expect(sessionStorage.getItem('pwa-banner-dismissed')).toBe('1');

    sw.fire('controllerchange');                            // a later fire must stay quiet
    expect(shown(bannerEl())).toBe(false);
  });
});

describe('iOS install instructions', () => {
  it('tells an iPhone how to install, because Safari never fires the prompt', () => {
    fakeDevice();
    fakeIOS();
    mountBanner();

    const el = bannerEl();
    expect(shown(el)).toBe(true);
    expect(el.textContent).toContain('Install OpenSRM');
    expect(el.textContent).toContain('Add to Home Screen');
    expect(el.textContent).toContain('Share');
    // No dead button: there is no prompt event on iOS to hand it to.
    expect(labels(el)).not.toContain('Install app');
  });

  it('says nothing to an iPhone already running from the Home Screen', () => {
    fakeDevice();
    fakeIOS(true);
    mountBanner();

    expect(shown(bannerEl())).toBe(false);
  });

  it('the iOS wording stays dismissed across a remount', () => {
    fakeDevice();
    fakeIOS();
    mountBanner();
    click(bannerEl(), '✕');

    document.body.replaceChildren();
    fakeIOS();
    mountBanner();

    expect(shown(bannerEl())).toBe(false);
  });
});

describe('install card (phone only, once per device)', () => {
  it('offers Install on a phone when the browser fires the prompt', () => {
    fakeDevice({ phone: true });
    mountBanner();
    expect(shown(bannerEl())).toBe(false);                 // nothing to install yet

    offerInstallPrompt();

    const el = bannerEl();
    expect(shown(el)).toBe(true);
    expect(el.textContent).toContain('Install OpenSRM');
    expect(labels(el)).toContain('Install app');
  });

  it('stays off a desktop pointer — same event, different device', () => {
    fakeDevice({ phone: false });
    mountBanner();
    offerInstallPrompt();

    expect(shown(bannerEl())).toBe(false);                 // positive control is the test above
    expect(navButton()).toBeNull();
  });

  it('stays off once the page is already running as an installed app', () => {
    fakeDevice({ phone: true, standalone: true });
    mountBanner();
    offerInstallPrompt();

    expect(shown(bannerEl())).toBe(false);
  });

  it('the cross moves it into the navbar instead of coming back next session', () => {
    fakeDevice({ phone: true });
    mobileNavbar();
    mountBanner();
    offerInstallPrompt();
    expect(navButton()).toBeNull();                        // not before the cross

    click(bannerEl(), '✕');

    expect(shown(bannerEl())).toBe(false);
    expect(local.getItem('pwa-install-dismissed')).toBe('1');
    expect(navButton()).not.toBeNull();
    expect(navButton()?.getAttribute('aria-label')).toBe('Install app');

    // A fresh page load: the card must not return, the navbar button must.
    document.body.replaceChildren();
    mobileNavbar();
    Object.defineProperty(navigator, 'serviceWorker', { value: undefined, configurable: true });
    mountBanner();
    offerInstallPrompt();

    expect(shown(bannerEl())).toBe(false);
    expect(navButton()).not.toBeNull();
  });

  it('the navbar button raises the real prompt, and an accepted install clears it', async () => {
    fakeDevice({ phone: true });
    mobileNavbar();
    mountBanner();
    offerInstallPrompt();
    click(bannerEl(), '✕');

    const second = offerInstallPrompt('accepted');
    navButton()?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(second.prompt).toHaveBeenCalledTimes(1);
    expect(shown(bannerEl())).toBe(false);                 // installed: nothing left to offer
    expect(navButton()).toBeNull();
  });

  it('repaints as the manual route when the prompt is refused, never a dead button', async () => {
    fakeDevice({ phone: true });
    mountBanner();
    offerInstallPrompt('dismissed');

    click(bannerEl(), 'Install app');
    await new Promise((resolve) => setTimeout(resolve, 0));

    const el = bannerEl();
    expect(shown(el)).toBe(true);
    expect(labels(el)).not.toContain('Install app');       // the event is single-use
    expect(el.textContent).toContain('browser menu');
  });
});
