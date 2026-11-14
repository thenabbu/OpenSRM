import 'fake-indexeddb/auto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import attendanceIsland from '../contracts/fixtures/attendance_island.json';
import { attendanceProps } from '../panels/attendance/contract';
import { wipeAll } from '../db';
import { refreshProps } from './refresh';

// The sync path: a repaint is only allowed to touch the DOM when the server
// answered something the island's OWN schema accepts. Everything else keeps the
// paint that is already on screen.

const A = 'zz1111';
const ATTN = attendanceProps.parse(attendanceIsland.data);

const ok = (data: unknown): typeof fetch =>
  vi.fn(async () => new Response(JSON.stringify({ ok: true, data }), { status: 200 }));

const DASH = {
  profile: { netid: A, name: 'T', email: 't@example.com', reg_no: 'R1', avatar: '<svg></svg>' },
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
