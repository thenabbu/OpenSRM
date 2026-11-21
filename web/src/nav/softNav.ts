// ── Soft navigation (route swap in place) ─────────────────────────────────
//
// Why this exists: on `main` every view lived in ONE document and a tab switch
// was a div flip — instant, no reload, no flash. The preact migration gave each
// view a real URL (correct for deep links and for the module budget), but the
// navigation stayed a plain <a href>, so every tab tap became a full document
// load: the shell re-parsed, the favicon re-fetched, the CSS re-applied and the
// screen flashed white in between. On a phone that is ~0.5-1 s of nothing per
// tap, and it is the whole reason the app stopped feeling snappy.
//
// So: intercept same-origin link clicks, fetch the route's HTML, and swap the
// region between the `route:start` / `route:end` markers in base.html. CSS, JS
// and the service worker are not touched on the swap (they are already loaded),
// and islands hydrate into the new markup exactly as they do on first load.
//
// This is deliberately NOT a router: no route table, no component per page. The
// server stays the router — the URL is the only state — which is why back and
// forward work by re-fetching the same URL the browser already knows.
//
// Privacy: nothing here caches HTML. Every fetch is a live request, so the
// "a rendered page is never stored" rule (web/src/sw-template.js) still holds.

/** The markers base.html wraps the route's markup in. Both must be comments. */
export const ROUTE_START = 'route:start';
export const ROUTE_END = 'route:end';

/** How long a prefetched route stays usable. HTML is `no-store` server-side, so
 *  a prefetch lives in this map and nowhere else — keep it short-lived. */
export const PREFETCH_TTL_MS = 30_000;

/** Routes that must never soften: the service worker wipes every cache on
 *  /logout, and that only runs on a real navigation. */
const NEVER_SOFT = new Set(['/logout', '/login']);

/** `/` is the dashboard route; every other route's tab is its path segment. */
export function tabOf(url: URL): string {
  const path = url.pathname.replace(/^\/+|\/+$/g, '');
  return path === '' ? 'dashboard' : path;
}

/**
 * The link half of the decision, with no event involved: the URL this anchor
 * navigates to, or null when the browser must handle it itself. Pure, so the
 * prefetcher and the click handler agree by construction.
 */
export function resolveLink(a: HTMLAnchorElement | null, here: Pick<Location, 'origin' | 'pathname' | 'search' | 'href'>): URL | null {
  if (!a) return null;
  if (a.hasAttribute('download')) return null;
  const target = a.getAttribute('target');
  if (target && target !== '_self') return null;
  if ((a.getAttribute('rel') || '').split(/\s+/).includes('external')) return null;

  const href = a.getAttribute('href');
  if (!href) return null;
  let url: URL;
  try {
    url = new URL(href, here.href);
  } catch {
    return null;
  }
  if (url.origin !== here.origin) return null;
  if (NEVER_SOFT.has(url.pathname)) return null;
  // Same document: a hash link (or a no-op) is the browser's business.
  if (url.pathname === here.pathname && url.search === here.search) return null;
  return url;
}

/**
 * The decision half of soft navigation, kept pure so it is testable without a
 * DOM: given a click event and the anchor it landed on, either return the URL to
 * swap in, or null meaning "let the browser navigate".
 */
export function shouldIntercept(
  ev: Pick<MouseEvent, 'button' | 'defaultPrevented' | 'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey'>,
  a: HTMLAnchorElement | null,
  here: Pick<Location, 'origin' | 'pathname' | 'search' | 'href'>,
): URL | null {
  if (ev.defaultPrevented || ev.button !== 0) return null;
  if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return null;
  return resolveLink(a, here);
}

/** The comment markers bounding the route's markup, in document order.
 *
 *  Both sides are normalised: jsdom and Chromium keep the comment's own padding
 *  (`<!-- route:start -->` exits as `' route:start '`), so comparing the raw
 *  nodeValue finds nothing in either — the same mistake that would make a
 *  template's markers silently unmatchable at runtime.
 */
export function findRegion(doc: Document): { start: Comment; end: Comment } | null {
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_COMMENT);
  let start: Comment | null = null;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const c = n as Comment;
    const text = (c.nodeValue ?? '').trim();
    if (text === ROUTE_START) start = c;
    else if (text === ROUTE_END && start) return { start, end: c };
  }
  return null;
}

/** Replace the nodes between the markers of `live` with the ones from `next`. */
export function swapRegion(live: Document, next: Document): boolean {
  const a = findRegion(live);
  const b = findRegion(next);
  if (!a || !b) return false;
  for (let n = a.start.nextSibling; n && n !== a.end;) {
    const after = n.nextSibling;
    n.parentNode?.removeChild(n);
    n = after;
  }
  const frag = live.createDocumentFragment();
  for (let n = b.start.nextSibling; n && n !== b.end;) {
    const after = n.nextSibling;
    frag.appendChild(n);
    n = after;
  }
  a.start.after(frag);
  return true;
}

/**
 * Move the chrome's selected state to the route we just swapped in: the two
 * navbars use `tab-active`, the dock uses `dock-active`, and both carry
 * `aria-current="page"` on exactly the active link (DESIGN §10.11 — the class is
 * decoration, the attribute is the state).
 */
export function syncChrome(live: Document, next: Document, url: URL): void {
  const tab = tabOf(url);
  for (const a of Array.from(live.querySelectorAll<HTMLAnchorElement>('a[data-tab]'))) {
    const on = a.dataset.tab === tab;
    // Which class to toggle is decided by the NAV the link lives in, not by a
    // container class: the desktop navbar's links are `.navbar-center a` (server
    // emits `tab-active`), everything else draws the dock's bar (`dock-active`) —
    // including the mobile navbar's settings gear, which is neither a dock link
    // nor a navbar-center one but is the ONLY way to reach /settings on a phone.
    // Toggling is what the server does per route: on for the active tab, removed
    // otherwise, so the gear carries its state only while /settings is shown.
    const inNavbarCenter = a.closest('.navbar-center') !== null;
    a.classList.toggle(inNavbarCenter ? 'tab-active' : 'dock-active', on);
    if (on) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  live.title = next.title;
  // The server publishes per-session facts on <body>; a route swap can change
  // them (a gated panel appearing or not), so carry them over.
  for (const attr of ['data-netid', 'data-scope-sync']) {
    const v = next.body.getAttribute(attr);
    if (v === null) live.body.removeAttribute(attr);
    else live.body.setAttribute(attr, v);
  }
}

type Prefetched = { at: number; html: Promise<string | null> };

export interface SoftNavOptions {
  /** Runs after the swap: hydrate the islands in the new markup. */
  hydrate: (root: ParentNode) => Promise<void>;
  now?: () => number;
}

/** Fetch a route's HTML; null on anything that is not a clean same-route 200. */
async function fetchRoute(url: URL): Promise<string | null> {
  try {
    const res = await fetch(url.href, {
      credentials: 'same-origin',
      // Not text/html: the service worker's navigation route is `mode ===
      // 'navigate'` only, so this request goes straight to the network and can
      // never be answered with a cached shell.
      headers: { Accept: 'text/x-soft-nav' },
    });
    if (!res.ok) return null;
    return await res.text();
  } catch {
    return null;
  }
}

export function bindSoftNav(doc: Document, win: Window, opts: SoftNavOptions): void {
  const now = opts.now ?? (() => Date.now());
  const cache = new Map<string, Prefetched>();
  let busy = false;

  const prefetch = (url: URL): void => {
    const key = url.href;
    const hit = cache.get(key);
    if (hit && now() - hit.at < PREFETCH_TTL_MS) return;
    cache.set(key, { at: now(), html: fetchRoute(url) });
  };

  const html = async (url: URL): Promise<string | null> => {
    const key = url.href;
    const hit = cache.get(key);
    if (hit && now() - hit.at < PREFETCH_TTL_MS) {
      cache.delete(key);
      return hit.html;
    }
    return fetchRoute(url);
  };

  const go = async (url: URL, push: boolean): Promise<void> => {
    if (busy) return;
    busy = true;
    try {
      const body = await html(url);
      if (body === null) {
        win.location.assign(url.href);       // offline, 401, 5xx: real navigation
        return;
      }
      const next = new DOMParser().parseFromString(body, 'text/html');
      if (!findRegion(next)) {
        win.location.assign(url.href);       // not a route document (a login page)
        return;
      }
      if (push) win.history.pushState({ softNav: true }, '', url.href);
      const apply = (): void => {
        swapRegion(doc, next);
        syncChrome(doc, next, url);
        // Forward navigation starts at the top, like a page load. Back/forward
        // does NOT: the browser is restoring a position the user already had, and
        // scrolling to 0 there loses their place in the list they were reading.
        if (push) win.scrollTo(0, 0);
        // A swap fires no document load, so assistive tech gets no route-change
        // announcement and keyboard focus would stay on the nav link. Move focus
        // to the new <main> (a landmark, so the screen reader names where it is);
        // tabindex=-1 makes it focusable without inserting it into the tab order.
        const main = doc.querySelector('main');
        if (main) {
          if (!main.hasAttribute('tabindex')) main.setAttribute('tabindex', '-1');
          main.focus({ preventScroll: true });
        }
      };
      // View transitions are the reason the swap reads as a transition rather
      // than a repaint: the browser snapshots before and after and cross-fades.
      // No CSS needed — the default is the right cross-fade for a route change.
      //
      // But startViewTransition does NOT call its callback synchronously: it
      // captures the old state first and runs the callback on the next frame.
      // Hydrating straight after the call would therefore hydrate the PREVIOUS
      // route's markup — the new islands are not in the document yet and the
      // swap then inserts them unhydrated (measured: /timetable arrived as an
      // empty grid after a tab tap, and only after a hard load did it paint).
      // updateCallbackDone is the promise that says the DOM is actually swapped.
      const vts = (doc as Document & { startViewTransition?: (cb: () => void) => unknown })
        .startViewTransition;
      if (typeof vts === 'function') {
        const transition = vts.call(doc, apply) as { updateCallbackDone?: Promise<void> };
        await transition.updateCallbackDone?.catch(() => undefined);
      } else {
        apply();
      }
      // Hydrate AFTER the swap; the server paint is already on screen and a
      // failed island keeps it (mountBounded restores the server's children).
      await opts.hydrate(doc);
      // A route landed. `osrm:island-mounted` is NOT enough to announce this:
      // a route can arrive with no island of its own (the timetable panel is
      // server markup plus a grid the bundle fills), so page-level binders that
      // re-arm on island mount alone never hear about it. Those binders listen
      // for this as well and are idempotent.
      doc.dispatchEvent(new CustomEvent('osrm:route-swapped', { detail: url.pathname }));
    } finally {
      busy = false;
    }
  };

  doc.addEventListener(
    'click',
    (ev) => {
      if (ev instanceof MouseEvent && ev.button !== 0) return;
      const a = (ev.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null;
      const url = shouldIntercept(ev as MouseEvent, a, win.location);
      if (!url) return;
      ev.preventDefault();
      void go(url, true);
    },
    true,                                     // capture: a handler that stops
                                              // propagation must not disable this
  );

  // Warm the likely next route on intent (hover on desktop, touch-down on
  // phones) so the swap usually has its HTML already in hand.
  for (const type of ['pointerenter', 'pointerdown', 'focus'] as const) {
    doc.addEventListener(
      type,
      (ev) => {
        const a = (ev.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null;
        const url = resolveLink(a, win.location);
        if (url) prefetch(url);
      },
      { capture: true, passive: true },
    );
  }

  win.addEventListener('popstate', () => {
    void go(new URL(win.location.href), false);
  });

}
