import 'fake-indexeddb/auto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import attendanceIsland from '../contracts/fixtures/attendance_island.json';
import { attendanceProps } from '../panels/attendance/contract';
import { wipeAll } from '../db';
import { bindRefreshButtons, refreshProps, syncData, triggerRefresh } from './refresh';

// The sync path: a repaint is only allowed to touch the DOM when the server
// answered something the island's OWN schema accepts. Everything else keeps the
// paint that is already on screen.

const A = 'zz1111';
const ATTN = attendanceProps.parse(attendanceIsland.data);

const ok = (data: unknown): typeof fetch =>
  vi.fn(async () => new Response(JSON.stringify({ ok: true, data }), { status: 200 }));

const DASH = {
  profile: { netid: A, name: 'T', email: 't@example.com', reg_no: 'R1' },
  ticker: null,
  week: { days: 1, hours: 2, dates: [], marks: [], today_absent: false },
  budgets: [],
  marks: [],
  exams: null,
  teachers: [],
  fb_plan: false,
};

afterEach(async () => {
  vi.restoreAllMocks();
  await wipeAll();
});

describe('islands without a feed', () => {
  it('settings and sync-age never fetch (server-rendered / a clock)', async () => {
    const fetcher = vi.fn();
    for (const name of ['settings', 'sync-age'] as const) {
      const props = await refreshProps(name, { netid: A, fetcher: fetcher as never });
      expect(props).toBeUndefined();
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe('raw feeds (dashboard, tools)', () => {
  it('dashboard reads /api/dashboard and hands back the validated payload', async () => {
    const fetcher = ok(DASH);
    const props = await refreshProps('dashboard', { netid: A, fetcher });
    expect(fetcher).toHaveBeenCalledWith('/api/dashboard', expect.anything());
    expect(props).toEqual(DASH);
  });

  it('rejects a payload the island schema does not accept', async () => {
    const props = await refreshProps('dashboard', {
      netid: A,
      fetcher: ok({ profile: DASH.profile }),   // missing week/budgets/...
    });
    expect(props).toBeUndefined();
  });

  it('a 404 (panel gated) keeps the current paint', async () => {
    const props = await refreshProps('tools', {
      netid: A,
      fetcher: vi.fn(async () => new Response('{}', { status: 404 })),
    });
    expect(props).toBeUndefined();
  });
});

describe('store-backed panels', () => {
  it('a fresh network answer is projected onto the island schema', async () => {
    const props = await refreshProps('attendance', { netid: A, fetcher: ok(ATTN) });
    expect(props).toEqual(ATTN);
  });

  it('reads the network, not the cached row (fresh: true)', async () => {
    // A cached copy with a DIFFERENT subject name: if the repaint served the
    // cache the name below would come back unchanged.
    await expect(
      refreshProps('attendance', { netid: A, fetcher: ok(ATTN) }),
    ).resolves.toEqual(ATTN);
    const renamed = { ...ATTN, courses: [{ ...ATTN.courses[0]!, description: 'NETWORK' }] };
    const props = await refreshProps('attendance', { netid: A, fetcher: ok(renamed) });
    expect((props as typeof ATTN).courses[0]!.description).toBe('NETWORK');
  });

  it('an unparseable answer leaves the paint alone', async () => {
    const props = await refreshProps('marks', { netid: A, fetcher: ok({ nope: true }) });
    expect(props).toBeUndefined();
  });
});

// ── The refresh primitive (W5.2a) ────────────────────────────────────────
// Ported out of dash.js. The behaviour that has to survive the move is the
// busy state (a second click must not start a second sync), the caption's
// honesty (a cached answer is not a fresh sync) and the fact that a failure
// never leaves a button stuck or a promise unhandled.
describe('the refresh primitive (W5.2a)', () => {
  const page = (): HTMLElement => {
    document.body.innerHTML =
      '<div id="error-toast" class="hidden"></div>' +
      '<button data-refresh aria-label="Refresh"><svg class="refresh-icon"></svg></button>' +
      '<span class="sync-line" data-ts="0"></span>';
    return document.querySelector('[data-refresh]') as HTMLElement;
  };
  const reply = (body: unknown) =>
    vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));
  const caption = (): HTMLElement => document.querySelector('.sync-line') as HTMLElement;
  const toast = (): HTMLElement => document.getElementById('error-toast') as HTMLElement;

  afterEach(() => {
    vi.unstubAllGlobals();
    delete (window as unknown as { __osrmRefreshData?: unknown }).__osrmRefreshData;
    document.body.innerHTML = '';
  });

  it('POSTs /api/refresh once and drops the busy state again', async () => {
    const b = page();
    const fetcher = reply({ ok: true, cached: true });
    vi.stubGlobal('fetch', fetcher);
    await triggerRefresh(false);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect((fetcher.mock.calls[0] as unknown[])[0]).toBe('/api/refresh');
    expect((fetcher.mock.calls[0] as unknown[])[1]).toMatchObject({ method: 'POST' });
    expect(b.hasAttribute('aria-disabled')).toBe(false);
    expect(document.querySelector('.refresh-icon')!.classList.contains('animate-spin')).toBe(false);
  });

  it('stamps the sync age when the sync landed, and leaves it alone when cached', async () => {
    page();
    vi.stubGlobal('fetch', reply({ ok: true, cached: false }));
    await triggerRefresh(false);
    const stamped = Number(caption().dataset.ts);
    expect(stamped).toBeGreaterThan(0);

    caption().dataset.ts = '42';
    vi.stubGlobal('fetch', reply({ ok: true, cached: true }));
    await triggerRefresh(false);
    expect(caption().dataset.ts).toBe('42');   // a cached answer claims nothing
  });

  it('reports the server error, and stays silent on the background path', async () => {
    page();
    vi.stubGlobal('fetch', reply({ ok: false, error: 'SCOPE down' }));
    await triggerRefresh(false);
    expect(toast().textContent).toBe('SCOPE down');
    expect(toast().classList.contains('hidden')).toBe(false);

    toast().classList.add('hidden');
    await triggerRefresh(true);
    expect(toast().classList.contains('hidden')).toBe(true);
  });

  it('never rejects on a transport failure, and never leaves the button busy', async () => {
    const b = page();
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline'); }));
    await expect(triggerRefresh(false)).resolves.toBeUndefined();
    expect(b.hasAttribute('aria-disabled')).toBe(false);
    expect(toast().textContent).toContain('Network error');
  });

  it('syncData repaints through the bundle hook and swallows a failed repaint', async () => {
    const okHook = vi.fn(async () => undefined);
    (window as unknown as { __osrmRefreshData?: unknown }).__osrmRefreshData = okHook;
    await syncData();
    expect(okHook).toHaveBeenCalledTimes(1);

    (window as unknown as { __osrmRefreshData?: unknown }).__osrmRefreshData = vi.fn(async () => {
      throw new Error('boom');
    });
    await expect(syncData()).resolves.toBeUndefined();

    delete (window as unknown as { __osrmRefreshData?: unknown }).__osrmRefreshData;
    await expect(syncData()).resolves.toBeUndefined();   // no bundle: nothing to do
  });

  it('binds the buttons, and a second click while busy starts no second sync', async () => {
    const b = page();
    const fetcher = reply({ ok: true, cached: true });
    vi.stubGlobal('fetch', fetcher);
    bindRefreshButtons();
    b.click();
    b.click();                     // aria-disabled is set synchronously by the first click
    await vi.waitFor(() => expect(b.hasAttribute('aria-disabled')).toBe(false));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
