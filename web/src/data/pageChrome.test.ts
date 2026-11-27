import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  OFFLINE_PILL_LABEL,
  SCROLL_CLASS,
  SCROLL_LINGER_MS,
  applyGroupDefaults,
  bindItemBeacon,
  bindOfflineBanner,
  bindScrollIndicator,
  registerServiceWorker,
} from './pageChrome';

// W5.4b ported five dash.js page-chrome rows. This file is the per-row check
// that fails if the port is removed — one describe block per matrix row, named
// the way the matrix names it. No @testing-library: these are DOM/listener
// assertions, and the local install cannot resolve that package.

const fresh = (): Document => document.implementation.createHTMLDocument('page');

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ── dash-scroll-indicator ─────────────────────────────────────────────────
describe('dash-scroll-indicator', () => {
  it('marks html.is-scrolling on scroll and clears it after the linger', () => {
    vi.useFakeTimers();
    const doc = fresh();
    bindScrollIndicator(doc, window);

    expect(doc.documentElement.classList.contains(SCROLL_CLASS)).toBe(false);
    window.dispatchEvent(new Event('scroll'));
    expect(doc.documentElement.classList.contains(SCROLL_CLASS)).toBe(true);

    vi.advanceTimersByTime(SCROLL_LINGER_MS - 1);
    expect(doc.documentElement.classList.contains(SCROLL_CLASS)).toBe(true);

    vi.advanceTimersByTime(2);
    expect(doc.documentElement.classList.contains(SCROLL_CLASS)).toBe(false);
  });

  it('restarts the linger on a second scroll instead of clearing early', () => {
    vi.useFakeTimers();
    const doc = fresh();
    bindScrollIndicator(doc, window);

    window.dispatchEvent(new Event('scroll'));
    vi.advanceTimersByTime(SCROLL_LINGER_MS - 100);
    window.dispatchEvent(new Event('scroll'));
    // the original timer would have fired by now; the restart must not
    vi.advanceTimersByTime(200);
    expect(doc.documentElement.classList.contains(SCROLL_CLASS)).toBe(true);

    vi.advanceTimersByTime(SCROLL_LINGER_MS);
    expect(doc.documentElement.classList.contains(SCROLL_CLASS)).toBe(false);
  });
});

// ── dash-item-beacon ──────────────────────────────────────────────────────
describe('dash-item-beacon', () => {
  const page = (item: string): Document => {
    const doc = fresh();
    doc.body.innerHTML = `<div id="card"><button id="b" data-track-item="${item}"><span id="inner">x</span></button></div>`;
    return doc;
  };

  it('POSTs /api/track/tab with the tab, the item and keepalive', () => {
    const doc = page('marks-component');
    const spy = vi.fn(async () => new Response(null, { status: 204 }));
    bindItemBeacon(doc, spy as unknown as typeof fetch);

    doc.getElementById('inner')!.dispatchEvent(
      new MouseEvent('click', { bubbles: true }),
    );

    expect(spy).toHaveBeenCalledTimes(1);
    const [url, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/track/tab');
    expect(init.method).toBe('POST');
    expect(init.keepalive).toBe(true);
    expect(init.credentials).toBe('same-origin');
    expect(JSON.parse(init.body as string)).toEqual({
      tab: 'marks',
      item: 'marks-component',
    });
  });

  it('falls back to tab=dashboard for an item outside the vocabulary', () => {
    const doc = page('something-new');
    const spy = vi.fn(async () => new Response(null, { status: 204 }));
    bindItemBeacon(doc, spy as unknown as typeof fetch);

    doc.getElementById('b')!.click();
    const [, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string).tab).toBe('dashboard');
  });

  it('ignores a click that is not on a tracked element', () => {
    const doc = page('marks-component');
    const spy = vi.fn(async () => new Response(null, { status: 204 }));
    bindItemBeacon(doc, spy as unknown as typeof fetch);

    doc.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(spy).not.toHaveBeenCalled();
  });

  it('a throwing fetch does not break the click', () => {
    const doc = page('marks-component');
    let clicked = false;
    doc.getElementById('b')!.addEventListener('click', () => {
      clicked = true;
    });
    const spy = vi.fn(() => {
      throw new Error('telemetry exploded');
    });
    bindItemBeacon(doc, spy as unknown as typeof fetch);

    expect(() => doc.getElementById('b')!.click()).not.toThrow();
    expect(clicked).toBe(true);
  });
});

// ── dash-settings-groups ──────────────────────────────────────────────────
describe('dash-settings-groups', () => {
  const settings = (): Document => {
    const doc = fresh();
    // Mirrors settings.html:84 — the ROW is #personal-details, and after the
    // island repaints there is a SECOND one inside it. The row's own toggle
    // must never be checked by this rule.
    doc.body.innerHTML = `
      <div class="collapse" id="personal-details">
        <input type="checkbox" id="row-toggle" />
        <div class="collapse-content">
          <div id="block" class="collapse" data-island="settings">
            <div class="collapse-content">
              <div class="flex flex-col">
                <div class="collapse"><input type="checkbox" id="g0" /></div>
                <div class="collapse"><input type="checkbox" id="g1" /></div>
                <div class="collapse"><input type="checkbox" id="g2" /></div>
              </div>
            </div>
          </div>
        </div>
      </div>`;
    return doc;
  };

  const checked = (doc: Document): boolean[] =>
    ['g0', 'g1', 'g2'].map((id) => (doc.getElementById(id) as HTMLInputElement).checked);

  const withWidth = (wide: boolean): Window => {
    const win = { matchMedia: () => ({ matches: wide }) } as unknown as Window;
    return win;
  };

  it('opens every group at >=640 px', () => {
    const doc = settings();
    applyGroupDefaults(doc, withWidth(true));
    expect(checked(doc)).toEqual([true, true, true]);
  });

  it('opens only the first group below 640 px', () => {
    const doc = settings();
    applyGroupDefaults(doc, withWidth(false));
    expect(checked(doc)).toEqual([true, false, false]);
  });

  it("never checks the row's own toggle", () => {
    const doc = settings();
    applyGroupDefaults(doc, withWidth(true));
    expect((doc.getElementById('row-toggle') as HTMLInputElement).checked).toBe(false);
  });

  it('a re-arm after an island repaint does not undo a user toggle', () => {
    const doc = settings();
    applyGroupDefaults(doc, withWidth(true));
    (doc.getElementById('g1') as HTMLInputElement).checked = false; // user collapsed it
    applyGroupDefaults(doc, withWidth(true)); // osrm:island-mounted fires again
    expect(checked(doc)).toEqual([true, false, true]);
  });

  it('is a no-op on a page with no personal-details block', () => {
    const doc = fresh();
    doc.body.innerHTML = '<p>no settings here</p>';
    expect(() => applyGroupDefaults(doc, withWidth(true))).not.toThrow();
  });

  it('survives a window with no matchMedia (jsdom) and applies the phone rule', () => {
    const doc = settings();
    const bare = {} as unknown as Window;
    expect(() => applyGroupDefaults(doc, bare)).not.toThrow();
    expect(checked(doc)).toEqual([true, false, false]);
  });
});

// ── dash-offline-pill ─────────────────────────────────────────────────────
describe('dash-offline-pill', () => {
  const PILL = `<span data-offline-pill hidden role="status" aria-live="polite"></span>`;
  const withPill = (onLine: boolean): Document => {
    const doc = fresh();
    // Both navbars carry one; the binder must paint every match, not the first.
    doc.body.innerHTML = `${PILL}<div id="mobile-navbar">${PILL}</div>`;
    Object.defineProperty(window.navigator, 'onLine', { value: onLine, configurable: true });
    return doc;
  };
  const pills = (doc: Document) => Array.from(doc.querySelectorAll('[data-offline-pill]'));

  afterEach(() => {
    Object.defineProperty(window.navigator, 'onLine', { value: true, configurable: true });
  });

  it('shows every pill on offline and hides them on online', () => {
    const doc = withPill(true);
    bindOfflineBanner(doc, window);
    expect(pills(doc).map((p) => p.hasAttribute('hidden'))).toEqual([true, true]);

    window.dispatchEvent(new Event('offline'));
    expect(pills(doc).map((p) => p.hasAttribute('hidden'))).toEqual([false, false]);

    window.dispatchEvent(new Event('online'));
    expect(pills(doc).map((p) => p.hasAttribute('hidden'))).toEqual([true, true]);
  });

  it('paints immediately on a page that loads while already offline', () => {
    const doc = withPill(false);
    bindOfflineBanner(doc, window);
    // no event has fired — the seed must have painted it
    expect(pills(doc).map((p) => p.hasAttribute('hidden'))).toEqual([false, false]);
  });

  it('never writes text: the node is an icon, the label lives in the markup', () => {
    const doc = withPill(false);
    bindOfflineBanner(doc, window);
    expect(pills(doc).map((p) => p.textContent)).toEqual(['', '']);
    expect(OFFLINE_PILL_LABEL).toContain('Offline');
  });

  it('is a no-op on a route that ships no pill', () => {
    const doc = fresh();
    expect(() => bindOfflineBanner(doc, window)).not.toThrow();
  });
});

// ── dash-sw-register ──────────────────────────────────────────────────────
describe('dash-sw-register', () => {
  const windowAt = (pathname: string, register: () => Promise<ServiceWorkerRegistration | void>) => {
    return {
      navigator: { serviceWorker: { register } },
      location: { pathname },
    } as unknown as Window;
  };

  it('registers /static/sw.js at scope "/" on a panel route', () => {
    const register = vi.fn(async () => undefined);
    registerServiceWorker(windowAt('/attendance', register));
    expect(register).toHaveBeenCalledTimes(1);
    expect(register).toHaveBeenCalledWith('/static/sw.js', { scope: '/' });
  });

  it('does not register on /login (login.js owns that route)', () => {
    const register = vi.fn(async () => undefined);
    registerServiceWorker(windowAt('/login', register));
    expect(register).not.toHaveBeenCalled();
  });

  it('swallows a rejected registration instead of breaking boot', () => {
    const register = vi.fn(() => Promise.reject(new Error('insecure origin')));
    expect(() => registerServiceWorker(windowAt('/marks', register))).not.toThrow();
  });

  it('is a no-op where the page has no serviceWorker API', () => {
    const win = { navigator: {}, location: { pathname: '/' } } as unknown as Window;
    expect(() => registerServiceWorker(win)).not.toThrow();
  });
});
