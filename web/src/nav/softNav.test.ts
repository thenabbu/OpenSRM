import { describe, expect, it, vi } from 'vitest';
import {
  PREFETCH_TTL_MS,
  ROUTE_END,
  ROUTE_START,
  bindSoftNav,
  resolveLink,
  shouldIntercept,
  swapRegion,
  syncChrome,
  tabOf,
} from './softNav';

const HERE = { origin: 'https://srm.example', pathname: '/', search: '', href: 'https://srm.example/' };
const A = (href: string, attrs: Record<string, string> = {}): HTMLAnchorElement => {
  const a = document.createElement('a');
  a.setAttribute('href', href);
  for (const [k, v] of Object.entries(attrs)) a.setAttribute(k, v);
  return a;
};
const click = (extra: Partial<MouseEvent> = {}) =>
  ({ button: 0, defaultPrevented: false, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...extra }) as MouseEvent;

/** A document whose body is `chrome | route:start | … | route:end | scripts`. */
function docWith(routeHtml: string, bodyAttrs: Record<string, string> = {}): Document {
  const d = document.implementation.createHTMLDocument('t');
  d.body.innerHTML =
    `<header class="navbar"><nav class="navbar-center"><a data-tab="dashboard" aria-current="page" class="btn tab-active">D</a></nav></header>` +
    `<!-- ${ROUTE_START} -->${routeHtml}<!-- ${ROUTE_END} -->` +
    `<script src="/static/gaze.js"></script>`;
  for (const [k, v] of Object.entries(bodyAttrs)) d.body.setAttribute(k, v);
  return d;
}

describe('resolveLink', () => {
  it('allows a same-origin route link', () => {
    expect(resolveLink(A('/attendance'), HERE)?.pathname).toBe('/attendance');
  });

  it('refuses everything the browser must own', () => {
    expect(resolveLink(A('https://elsewhere.example/attendance'), HERE)).toBeNull(); // cross-origin
    expect(resolveLink(A('/logout'), HERE)).toBeNull();                             // SW wipes caches on it
    expect(resolveLink(A('/attendance', { target: '_blank' }), HERE)).toBeNull();
    expect(resolveLink(A('/attendance', { download: '' }), HERE)).toBeNull();
    expect(resolveLink(A('/attendance', { rel: 'external' }), HERE)).toBeNull();
    expect(resolveLink(A('#tab-marks'), HERE)).toBeNull();                           // same document
    expect(resolveLink(A('/'), HERE)).toBeNull();                                    // already here
    expect(resolveLink(null, HERE)).toBeNull();
  });
});

describe('shouldIntercept', () => {
  it('takes a plain left click', () => {
    expect(shouldIntercept(click(), A('/marks'), HERE)?.pathname).toBe('/marks');
  });

  it('leaves modified clicks and non-left buttons to the browser', () => {
    for (const mod of ['metaKey', 'ctrlKey', 'shiftKey', 'altKey'] as const) {
      expect(shouldIntercept(click({ [mod]: true }), A('/marks'), HERE)).toBeNull();
    }
    expect(shouldIntercept(click({ button: 1 }), A('/marks'), HERE)).toBeNull();
    expect(shouldIntercept(click({ defaultPrevented: true }), A('/marks'), HERE)).toBeNull();
  });
});

describe('swapRegion', () => {
  it('replaces the route markup and nothing else', () => {
    const live = docWith('<main id="old">attendance</main>');
    const next = docWith('<main id="new">marks</main>');
    const header = live.querySelector('header');
    const script = live.querySelector('script');
    const startMarker = live.body.innerHTML.indexOf(ROUTE_START);

    expect(swapRegion(live, next)).toBe(true);

    expect(live.querySelector('#old')).toBeNull();
    expect(live.querySelector('#new')?.textContent).toBe('marks');
    // the chrome and the scripts are the SAME nodes: nothing outside the markers moved
    expect(live.querySelector('header')).toBe(header);
    expect(live.querySelector('script')).toBe(script);
    expect(live.body.innerHTML.indexOf(ROUTE_START)).toBe(startMarker);
  });

  it('refuses a document with no markers instead of blanking the page', () => {
    const live = docWith('<main>attendance</main>');
    const bare = document.implementation.createHTMLDocument('login');
    bare.body.innerHTML = '<main>log in</main>';
    expect(swapRegion(live, bare)).toBe(false);
    expect(live.querySelector('main')?.textContent).toBe('attendance');
  });
});

describe('syncChrome', () => {
  it('moves the active state and aria-current to the new tab', () => {
    const live = docWith('<main></main>');
    live.head.innerHTML = '<title>old</title>';
    live.body.insertAdjacentHTML('beforeend', '<div class="dock"><a data-tab="marks" href="/marks">M</a></div>');
    const next = document.implementation.createHTMLDocument('n');
    next.head.innerHTML = '<title>OpenSRM - marks</title>';

    syncChrome(live, next, new URL('https://srm.example/marks'));

    const dash = live.querySelector('nav.navbar-center a[data-tab="dashboard"]')!;
    const marks = live.querySelector('a[data-tab="marks"]')!;
    expect(dash.hasAttribute('aria-current')).toBe(false);
    expect(dash.classList.contains('tab-active')).toBe(false);
    // the dock link is outside .navbar-center, so it takes dock-active — the
    // class each navbar actually draws its bar with (DESIGN §10.11)
    expect(marks.getAttribute('aria-current')).toBe('page');
    expect(marks.classList.contains('dock-active')).toBe(true);
    expect(live.title).toBe('OpenSRM - marks');
  });

  it('maps the root path to the dashboard tab', () => {
    expect(tabOf(new URL('https://srm.example/'))).toBe('dashboard');
    expect(tabOf(new URL('https://srm.example/attendance'))).toBe('attendance');
  });
});

describe('bindSoftNav', () => {
  it('swaps on a tab click, pushes history, and hydrates the new markup', async () => {
    const live = docWith('<main id="dash">dashboard</main>', { 'data-netid': 'zz9999' });
    const next = docWith('<main id="marks">marks</main>', { 'data-netid': 'zz9999' });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(next.documentElement.outerHTML, { status: 200 })));
    live.body.insertAdjacentHTML('beforeend', '<a id="go" data-tab="marks" href="/marks">Marks</a>');

    const hydrate = vi.fn(async () => {});
    const win = {
      location: { ...HERE, assign: vi.fn() },
      history: { pushState: vi.fn() },
      scrollTo: vi.fn(),
      addEventListener: vi.fn(),
    } as unknown as Window;
    bindSoftNav(live, win, { hydrate, now: () => 0 });

    const ev = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    live.getElementById('go')!.dispatchEvent(ev);
    await vi.waitFor(() => expect(hydrate).toHaveBeenCalled());

    expect(ev.defaultPrevented).toBe(true);
    expect(live.querySelector('#dash')).toBeNull();
    expect(live.querySelector('#marks')?.textContent).toBe('marks');
    expect(win.history.pushState).toHaveBeenCalledWith({ softNav: true }, '', 'https://srm.example/marks');
    expect(hydrate).toHaveBeenCalledWith(live);
    expect(win.location.assign).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('falls back to a real navigation when the route fetch fails', async () => {
    const live = docWith('<main id="dash">dashboard</main>');
    live.body.insertAdjacentHTML('beforeend', '<a id="go" href="/attendance">Attendance</a>');
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
    const hydrate = vi.fn(async () => {});
    const win = {
      location: { ...HERE, assign: vi.fn() },
      history: { pushState: vi.fn() },
      scrollTo: vi.fn(),
      addEventListener: vi.fn(),
    } as unknown as Window;
    bindSoftNav(live, win, { hydrate, now: () => 0 });

    live.getElementById('go')!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await vi.waitFor(() => expect(win.location.assign).toHaveBeenCalledWith('https://srm.example/attendance'));

    expect(hydrate).not.toHaveBeenCalled();
    expect(live.querySelector('#dash')).not.toBeNull();     // page left intact
    vi.unstubAllGlobals();
  });

  it('serves a hover-prefetched route from the prefetch, not a second fetch', async () => {
    const live = docWith('<main id="dash">dashboard</main>');
    const next = docWith('<main id="marks">marks</main>');
    live.body.insertAdjacentHTML('beforeend', '<a id="go" href="/marks">Marks</a>');
    const fetchSpy = vi.fn(async () => new Response(next.documentElement.outerHTML, { status: 200 }));
    vi.stubGlobal('fetch', fetchSpy);
    const win = {
      location: { ...HERE, assign: vi.fn() },
      history: { pushState: vi.fn() },
      scrollTo: vi.fn(),
      addEventListener: vi.fn(),
    } as unknown as Window;
    bindSoftNav(live, win, { hydrate: async () => {}, now: () => 0 });

    const anchor = live.getElementById('go')!;
    anchor.dispatchEvent(new Event('pointerenter', { bubbles: false }));
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    anchor.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await vi.waitFor(() => expect(live.querySelector('#marks')).not.toBeNull());

    expect(fetchSpy).toHaveBeenCalledTimes(1);                // the prefetch was reused
    expect(PREFETCH_TTL_MS).toBeGreaterThan(0);
    vi.unstubAllGlobals();
  });
});

describe('bindSoftNav + view transitions', () => {
  it('hydrates AFTER the deferred swap, never the previous route (the empty-grid bug)', async () => {
    const live = docWith('<main id="dash">dashboard</main>');
    const next = docWith('<main id="marks">marks</main>');
    vi.stubGlobal('fetch', vi.fn(async () => new Response(next.documentElement.outerHTML, { status: 200 })));
    live.body.insertAdjacentHTML('beforeend', '<a id="go" href="/marks">Marks</a>');

    // A view transition defers its callback to the next frame; hydrate must wait
    // for it. Chrome does exactly this, and hydrating straight after the call
    // hydrated the route that was already on screen.
    const order: string[] = [];
    (live as Document & { startViewTransition?: unknown }).startViewTransition = ((cb: () => void) => {
      const updateCallbackDone = new Promise<void>((resolve) =>
        setTimeout(() => {
          cb();
          order.push('swapped');
          resolve();
        }, 0),
      );
      return { updateCallbackDone, finished: updateCallbackDone };
    }) as unknown;
    const hydrate = vi.fn(async () => {
      order.push(live.querySelector('#marks') ? 'hydrated-after-swap' : 'hydrated-before-swap');
    });
    const win = {
      location: { ...HERE, assign: vi.fn() },
      history: { pushState: vi.fn() },
      scrollTo: vi.fn(),
      addEventListener: vi.fn(),
    } as unknown as Window;
    bindSoftNav(live, win, { hydrate, now: () => 0 });

    live.getElementById('go')!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await vi.waitFor(() => expect(hydrate).toHaveBeenCalled());
    expect(order).toEqual(['swapped', 'hydrated-after-swap']);
    vi.unstubAllGlobals();
  });
});

describe('bindSoftNav: history and focus', () => {
  const mkWin = (assign = vi.fn()) => ({
    location: { ...HERE, assign },
    history: { pushState: vi.fn() },
    scrollTo: vi.fn(),
    addEventListener: vi.fn(),
  }) as unknown as Window;

  it('scrolls to the top on a forward nav and moves focus into the new main', async () => {
    const live = docWith('<main id="dash">dashboard</main>');
    const next = docWith('<main id="marks">marks</main>');
    live.body.insertAdjacentHTML('beforeend', '<a id="go" href="/marks">M</a>');
    vi.stubGlobal('fetch', vi.fn(async () => new Response(next.documentElement.outerHTML, { status: 200 })));
    const win = mkWin();
    bindSoftNav(live, win, { hydrate: async () => {}, now: () => 0 });

    live.getElementById('go')!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await vi.waitFor(() => expect(live.querySelector('#marks')).not.toBeNull());

    expect(win.scrollTo).toHaveBeenCalledWith(0, 0);
    // focus() is inert on a detached document (jsdom), so the assertion here is
    // the part that makes focus possible: the landmark is focusable and in the
    // document. The real focus move is checked in the browser run.
    expect(live.querySelector('main')?.getAttribute('tabindex')).toBe('-1');
    vi.unstubAllGlobals();
  });

  it('falls back to a real navigation when the response is not a route document', async () => {
    const live = docWith('<main id="dash">dashboard</main>');
    live.body.insertAdjacentHTML('beforeend', '<a id="go" href="/marks">M</a>');
    // a login page: real HTML, no route markers
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<!doctype html><body><main>log in</main>', { status: 200 })));
    const win = mkWin();
    const hydrate = vi.fn(async () => {});
    bindSoftNav(live, win, { hydrate, now: () => 0 });

    live.getElementById('go')!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await vi.waitFor(() => expect(win.location.assign).toHaveBeenCalledWith('https://srm.example/marks'));
    expect(hydrate).not.toHaveBeenCalled();
    expect(live.querySelector('#dash')).not.toBeNull();
    vi.unstubAllGlobals();
  });
});
