import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement } from 'preact';
import { hydrateAll, mountBounded } from './main';

// Exactly what the server emits (templates + app/views/sync_age.py): the same
// two spans, the same caption/title/classes, `data-island` on each, and ONE
// inert JSON block they both point at. The only thing absent is data-hydrated:
// that marker can only exist after Preact mounts.
const BLOCK = (ts: number, id = 'island-sync-age') =>
  `<script type="application/json" id="${id}">` +
  `{"ts":${ts},"full":"2026-11-01 10:00:00","busy":null}</script>`;

const SSR = (text: string, mobile = false, id = 'island-sync-age') => `
  <span class="sync-line ${mobile ? 'text-[11px]' : 'text-xs'} text-base-content/60"
        data-island="sync-age" data-props="#${id}"
        title="2026-11-01 10:00:00">${text}</span>`;

// A page per test, under its own id: no test can read another's block.
let pageId = 0;
const newPage = (text: string, ts: number) => {
  const id = `island-sync-age-${++pageId}`;
  return SSR(text, false, id) + SSR(text, true, id) + BLOCK(ts, id);
};

/** Every structured warning the boundary emits (console.warn is the channel).
 *  Installed in beforeEach: vitest restores spies between tests, and a spy
 *  installed at module scope is silently gone by test 2. */
const LOG: string[] = [];
beforeEach(async () => {
  LOG.length = 0;
  // each test is a fresh page load: reset the module's warn-once dedupe
  (await import('./main')).__resetWarnOnce();
  vi.spyOn(console, 'warn').mockImplementation((msg: unknown) => {
    LOG.push(String(msg));
  });
});

const now = () => Date.now() / 1000;
const ago = (s: number) => Math.floor(now()) - s;
const spans = () => Array.from(document.querySelectorAll<HTMLElement>('.sync-line'));

describe('P4.1 island hydration', () => {
  it('progressive enhancement: the server markup is correct with no JS', () => {
    document.body.innerHTML = newPage('(15m ago)', ago(900));
    for (const el of spans()) {
      expect(el.textContent).toBe('(15m ago)');
      expect(el.title).toBe('2026-11-01 10:00:00');
      expect(el.hasAttribute('data-hydrated')).toBe(false);
    }
  });

  it('hydration actually happened: both spans mounted, text unchanged', async () => {
    document.body.innerHTML = newPage('(15m ago)', ago(900));
    await hydrateAll(document, now());
    for (const el of spans()) {
      expect(el.getAttribute('data-hydrated')).toBe('1');
      expect(el.textContent).toBe('(15m ago)');
      expect(el.className).toContain('sync-line');
    }
  });

  it('a fresh (dormant) caption stays empty and hidden after mounting', async () => {
    document.body.innerHTML = newPage('', ago(60));
    await hydrateAll(document, now());
    for (const el of spans()) {
      expect(el.getAttribute('data-hydrated')).toBe('1');
      expect(el.textContent).toBe('');
      expect(el.classList.contains('hidden')).toBe(true);
    }
  });

  it('re-ages itself on its own 60s tick (nobody repaints it from outside)', async () => {
    vi.useFakeTimers({ now: Date.now() });
    try {
      document.body.innerHTML = newPage('(15m ago)', ago(900));
      await hydrateAll(document, now());
      vi.advanceTimersByTime(45 * 60_000);   // +45m wall clock, zero fetches
      for (const el of spans()) expect(el.textContent).toBe('(1h ago)');
    } finally {
      vi.useRealTimers();
    }
  });

  it('preserves a live "Syncing…" (dash.js in-flight refresh) instead of clobbering it', async () => {
    vi.useFakeTimers({ now: Date.now() });
    try {
      document.body.innerHTML = newPage('(15m ago)', ago(900));
      await hydrateAll(document, now());
      spans()[0]!.textContent = 'Syncing…';
      vi.advanceTimersByTime(60_000);
      expect(spans()[0]!.textContent).toBe('Syncing…');
    } finally {
      vi.useRealTimers();
    }
  });

  it('unknown island: warned once, untouched, neighbour still hydrates', async () => {
    document.body.innerHTML =
      `<span class="sync-line" data-island="no-such-island">keep me</span>` +
      newPage('(15m ago)', ago(900));
    const [bad, ...good] = spans();
    await expect(hydrateAll(document, now())).resolves.toBeUndefined();
    await hydrateAll(document, now());   // a second pass must stay quiet too
    expect(LOG.filter((w) => w.includes('unknown island'))).toHaveLength(1);
    expect(bad!.textContent).toBe('keep me');
    expect(bad!.hasAttribute('data-hydrated')).toBe(false);
    expect(good.every((el) => el.getAttribute('data-hydrated') === '1')).toBe(true);
  });

  it('invalid props: renders nothing, structured warn, no throw, siblings intact', async () => {
    document.body.innerHTML = newPage('(15m ago)', 0).replace('{"ts":0,', '{"ts":"not-a-number",');
    await expect(hydrateAll(document, now())).resolves.toBeUndefined();
    for (const el of spans()) {
      expect(el.hasAttribute('data-hydrated')).toBe(false);
      expect(el.textContent).toBe('(15m ago)');   // server text intact
    }
    expect(LOG.some((w) => w.includes('invalid props'))).toBe(true);
  });

  it('missing or corrupt props block (stale cache) degrades instead of throwing', async () => {
    // a page with no props block at all (its own id: never another test's)
    const id = `island-sync-age-${++pageId}`;
    document.body.innerHTML = SSR('Never synced', false, id) + SSR('Never synced', true, id);
    await expect(hydrateAll(document, now())).resolves.toBeUndefined();   // no throw
    expect(spans().every((el) => !el.hasAttribute('data-hydrated'))).toBe(true);

    const id2 = `island-sync-age-${++pageId}`;
    document.body.innerHTML = SSR('Never synced', false, id2) + SSR('Never synced', true, id2) +
      `<script type="application/json" id="${id2}">{oops</script>`;
    await expect(hydrateAll(document, now())).resolves.toBeUndefined();
    expect(spans().every((el) => !el.hasAttribute('data-hydrated'))).toBe(true);
    expect(LOG.some((w) => w.includes('invalid props'))).toBe(true);
  });

  it('a throwing island is isolated: server child nodes restored, page stays usable', async () => {
    // Test the boundary directly rather than mocking a lazily-imported chunk
    // (vitest does not reliably intercept `registry[name]()`'s dynamic import).
    // mountBounded is the unit that guarantees isolation.
    const fresh = await import('./main');
    const el = document.createElement('span');
    el.dataset.island = 'sync-age';
    el.textContent = '(15m ago)';                    // the server markup
    const before = el.textContent;

    const thrower = (): never => { throw new Error('boom'); };
    const ok = fresh.mountBounded('sync-age', thrower as never, el, {}, now());

    expect(ok).toBe(false);                          // boundary caught it
    expect(el.textContent).toBe(before);             // server markup restored, not blanked
    expect(el.hasAttribute('data-hydrated')).toBe(false);
    expect(LOG.some((w) => w.includes('failed to render'))).toBe(true);

    // a real render through the same boundary succeeds -> boundary isn't just "always false"
    const el2 = document.createElement('span');
    el2.textContent = '(15m ago)';
    const ok2 = fresh.mountBounded('sync-age', (() => null) as never, el2, {}, now());
    expect(ok2).toBe(true);
  });
});

describe('one island mounts at most once per element per document', () => {
  // The bug this pins: `claimed` was declared and read but never populated, so
  // hydrateAll() twice over the same document mounted every island twice. On a
  // real page that is what the offline DUT saw — Preact renders on a microtask,
  // so the second tree reconciles against the first and the container ends up
  // with 0 children (["attendance:children=8", "attendance:children=0"]).
  //
  // Counting mounts, not inspecting the DOM: a re-mount RE-STAMPS data-hydrated
  // and re-paints the same text, so every DOM assertion in this file stays green
  // through a double mount. The observable that actually doubles is the island's
  // own work — each mount sets its own 60s timer.
  it('hydrateAll twice: each island mounts once, children kept', async () => {
    const timers = vi.spyOn(globalThis, 'setInterval');
    try {
      document.body.innerHTML = newPage('(15m ago)', ago(900));
      await hydrateAll(document, now());
      const afterFirst = spans().map((el) => el.childNodes.length);
      expect(timers).toHaveBeenCalledTimes(2);           // one per span, first pass
      expect(afterFirst.every((n) => n > 0)).toBe(true); // server paint is there

      await hydrateAll(document, now());                 // the second boot
      expect(timers).toHaveBeenCalledTimes(2);           // NO second mount
      expect(spans().map((el) => el.childNodes.length)).toEqual(afterFirst);
      for (const el of spans()) expect(el.textContent).toBe('(15m ago)');
    } finally {
      timers.mockRestore();
    }
  });
});

describe('mountBounded clears the mount before rendering', () => {
  // Preact's render() APPENDS into a container that already has children
  // (<b>NEW</b><span>SERVER</span>) and a null component leaves them alone;
  // both verified by direct probe. The server's markup is still in the mount
  // at hydrate time, so without an explicit clear an island painting fewer
  // nodes than the server painted leaves stale content on the page.
  // mountBounded is the boundary that must guarantee the clear.
  it('removes the server children before rendering the island', () => {
    const el = document.createElement('div');
    el.innerHTML = '<span>SERVER</span><span>PAINT</span>';
    const Comp = () => createElement('b', null, 'NEW');
    expect(mountBounded('t', Comp as never, el, {}, 0)).toBe(true);
    expect(el.innerHTML).not.toContain('SERVER');
    expect(el.innerHTML).not.toContain('PAINT');
    expect(el.textContent).toBe('NEW');
  });

  it('restores the server markup when the island throws', () => {
    const el = document.createElement('div');
    el.innerHTML = '<span>SERVER</span>';
    const Boom = () => { throw new Error('boom'); };
    expect(mountBounded('t', Boom as never, el, {}, 0)).toBe(false);
    expect(el.textContent).toContain('SERVER');
  });
});
