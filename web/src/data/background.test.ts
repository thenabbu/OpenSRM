import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AVATAR_SELECTOR,
  FB_FILL_URL,
  OFFSCREEN_CLASS,
  autoRefreshIfStale,
  bindAvatarOffscreen,
  bindFeedbackModal,
} from './background';

// W5.4d ported the three dash.js background rows. One describe block per matrix
// row, named the way the matrix names it: each block is the check that fails if
// that row's port is removed.

const fresh = (html = ''): Document => {
  const doc = document.implementation.createHTMLDocument('bg');
  doc.body.innerHTML = html;
  return doc;
};

const click = (el: Element): void => {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
};

const json = (body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

/** jsdom has no IntersectionObserver; this is the whole deferral contract. */
class FakeIO {
  static all: FakeIO[] = [];
  readonly observed: Element[] = [];
  constructor(private readonly cb: IntersectionObserverCallback) {
    FakeIO.all.push(this);
  }
  observe(el: Element): void {
    this.observed.push(el);
  }
  unobserve(): void {}
  disconnect(): void {}
  trigger(el: Element, isIntersecting: boolean): void {
    this.cb(
      [{ target: el, isIntersecting } as unknown as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }
}

beforeEach(() => {
  FakeIO.all = [];
  (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver = FakeIO;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
  document.body.innerHTML = '';
});

// ── dash-avatar-offscreen ─────────────────────────────────────────────────
describe('dash-avatar-offscreen', () => {
  // The real shape after the migration: @blobatar/preact renders <svg>, and its
  // <g> carries .mo-root — that <g> is the node the observer keys on AND the
  // node the pause rule targets, so it is the one that gets the class.
  const avatar = (): string =>
    `<svg viewBox="0 0 100 100"><g class="${AVATAR_SELECTOR.slice(1)}"></g></svg>`;
  const page = (): Document => fresh(avatar());

  it('observes the avatar at threshold 0 and pauses it while it is out of view', () => {
    const doc = page();
    bindAvatarOffscreen(doc, window);

    expect(FakeIO.all.length).toBe(1);
    const io = FakeIO.all[0];
    const wrap = doc.querySelector(AVATAR_SELECTOR) as HTMLElement;
    const root = doc.querySelector('.mo-root') as HTMLElement;
    expect(io.observed).toEqual([wrap]);

    // in view first (a fresh page is intersecting) — no paused class
    io.trigger(wrap, true);
    expect(root.classList.contains(OFFSCREEN_CLASS)).toBe(false);

    io.trigger(wrap, false);
    expect(root.classList.contains(OFFSCREEN_CLASS)).toBe(true);

    io.trigger(wrap, true);
    expect(root.classList.contains(OFFSCREEN_CLASS)).toBe(false);
  });

  it('re-arms on osrm:island-mounted for the avatar the island just painted', () => {
    const doc = page();
    bindAvatarOffscreen(doc, window);
    // hydration replaces the server-rendered avatar with the island's own node
    doc.body.innerHTML = avatar();
    doc.dispatchEvent(new Event('osrm:island-mounted'));

    expect(FakeIO.all.length).toBe(2);
    const fresh_Wrap = doc.querySelector(AVATAR_SELECTOR) as Element;
    expect(FakeIO.all[1].observed).toEqual([fresh_Wrap]);
    FakeIO.all[1].trigger(fresh_Wrap, false);
    expect(doc.querySelector('.mo-root')!.classList.contains(OFFSCREEN_CLASS)).toBe(true);
  });

  it('does not stack a second observer on the same node', () => {
    const doc = page();
    bindAvatarOffscreen(doc, window);
    doc.dispatchEvent(new Event('osrm:island-mounted'));
    doc.dispatchEvent(new Event('osrm:island-mounted'));
    expect(FakeIO.all.length).toBe(1);
  });

  it('degrades to an animating avatar when the engine has no IntersectionObserver', () => {
    delete (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
    expect(() => bindAvatarOffscreen(page(), window)).not.toThrow();
    expect(FakeIO.all.length).toBe(0);
  });
});

// ── dash-fb-modal ─────────────────────────────────────────────────────────
describe('dash-fb-modal', () => {
  // A FRESH document per test: bindFeedbackModal delegates on the document, so a
  // shared one would carry the previous test's listener and count two POSTs.
  // showError() still writes to the real document — that is where the toast
  // lives — so its node is parked there.
  let doc: Document;
  beforeEach(() => {
    doc = fresh(`
      <button id="fb-cta">Auto-fill</button>
      <dialog id="fb-modal"><button id="fb-submit">Fill</button>
        <div id="fb-status"></div></dialog>`);
    document.body.innerHTML = '<div id="error-toast" class="hidden"></div>';
  });
  const status = (): HTMLElement => doc.getElementById('fb-status') as HTMLElement;
  const submit = (): HTMLButtonElement => doc.getElementById('fb-submit') as HTMLButtonElement;

  it('opens the explainer dialog on a CTA click and posts nothing', () => {
    const show = vi.fn();
    (doc.getElementById('fb-modal') as HTMLDialogElement).showModal = show;
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    bindFeedbackModal(doc, window);

    click(doc.getElementById('fb-cta')!);
    expect(show).toHaveBeenCalledTimes(1);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('posts once on confirm, reports the counts, and re-enables the button', async () => {
    const fetchSpy = vi.fn(async () => json({ ok: true, filled: [1, 2], already: [3] }));
    vi.stubGlobal('fetch', fetchSpy);
    bindFeedbackModal(doc, window);

    click(submit());
    expect(submit().disabled).toBe(true);

    await vi.waitFor(() => expect(status().textContent).toBe('2 submitted · 1 already filled'));
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe(FB_FILL_URL);
    expect(fetchSpy.mock.calls[0][1]).toEqual({ method: 'POST' });
    expect(status().className).toContain('text-success');
    expect(submit().disabled).toBe(false);
  });

  it('shows the failure inline AND through the toast, and still re-enables', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ ok: false, error: 'portal closed' })));
    bindFeedbackModal(doc, window);

    click(submit());
    await vi.waitFor(() => expect(status().textContent).toBe('portal closed'));
    expect(status().className).toContain('text-error');
    const toast = document.getElementById('error-toast')!;
    expect(toast.classList.contains('hidden')).toBe(false);
    expect(toast.textContent).toContain('Feedback autofill failed: portal closed');
    expect(submit().disabled).toBe(false);
  });
});

// ── dash-auto-refresh ─────────────────────────────────────────────────────
describe('dash-auto-refresh', () => {
  const page = (canSync = '1'): Document =>
    fresh(`
      <meta name="can-sync" content="${canSync}">
      <span class="sync-line" data-ts="0"></span>`);

  it('asks the SERVER, and fires ONE quiet refresh when it says stale', async () => {
    const refresh = vi.fn(async () => {});
    const state = vi.fn(async () => true);
    expect(autoRefreshIfStale(page(), window, refresh, state)).toBe(true);
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(state).toHaveBeenCalledTimes(1);
    // quiet=true — a background sync never toasts
    expect(refresh).toHaveBeenCalledWith(true);
  });

  it('repaints nothing when the server says the data is fresh', async () => {
    const refresh = vi.fn(async () => {});
    const state = vi.fn(async () => false);
    autoRefreshIfStale(page(), window, refresh, state);
    await vi.waitFor(() => expect(state).toHaveBeenCalled());
    expect(refresh).not.toHaveBeenCalled();
  });

  it('does not fire without credentials, offline, or without a caption', () => {
    const refresh = vi.fn(async () => {});
    const state = vi.fn(async () => true);
    expect(autoRefreshIfStale(page('0'), window, refresh, state)).toBe(false);
    expect(autoRefreshIfStale(fresh('<span class="sync-line" data-ts="1"></span>'), window, refresh, state)).toBe(true);
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false);
    expect(autoRefreshIfStale(page(), window, refresh, state)).toBe(false);
    expect(autoRefreshIfStale(fresh(''), window, refresh, state)).toBe(false);
    // Only the one page with credentials + a caption asked: the first three
    // returned before the check, so the server saw exactly one question.
    expect(state).toHaveBeenCalledTimes(1);
  });

  it('a failed check never starts a portal sync on a guess', async () => {
    const refresh = vi.fn(async () => {});
    const state = vi.fn(async () => { throw new Error('offline'); });
    autoRefreshIfStale(page(), window, refresh, state);
    await vi.waitFor(() => expect(state).toHaveBeenCalled());
    expect(refresh).not.toHaveBeenCalled();
  });
});
