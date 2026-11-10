import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import attendanceIsland from '../contracts/fixtures/attendance_island.json';
import { attendanceProps } from '../panels/attendance/contract';
import { db, readPanel, wipeAll, writePanel } from '../db';
import { loadPanel, STALE_MS } from './load';

const A = 'zz1111';
const G = 'g1';
// Attendance caches the ISLAND payload, not the /api/attendance panel slice:
// load.ts points it at /api/attendance/island, and the island's own schema is
// what validates what goes into IndexedDB. Deriving the fixture from the island
// contract keeps this file honest about which shape the cache actually holds.
const ATTN = attendanceProps.parse(attendanceIsland.data);
const HOUR = 60 * 60 * 1000;

/** A fresh valid payload per test, distinguishable from what is cached. */
const payload = (marker: string) => ({ ...ATTN, courses: [{ ...ATTN.courses[0]!, code: marker }] });

/** Responses are whatever shape the test says — including a thrown fetch. */
const respond = (status: number, body: unknown): typeof fetch =>
  vi.fn(async () => new Response(JSON.stringify(body), { status }));

const net = (json: unknown): typeof fetch => respond(200, { ok: true, data: json });

const LOG: string[] = [];
beforeEach(() => {
  LOG.length = 0;
  vi.spyOn(console, 'warn').mockImplementation((m: unknown) => void LOG.push(String(m)));
});
afterEach(async () => {
  vi.restoreAllMocks();
  await wipeAll();
});

const seed = (body: unknown, fetchedAt = Date.now()) => writePanel('attendance', {
  netid: A, groupKey: G, payload: body as never, fetchedAt,
});

describe('cache first', () => {
  it('a cache hit returns immediately and never touches the network', async () => {
    await seed(ATTN, 1000);
    // Positive control: the row IS in the store, under the key the loader reads.
    expect(await readPanel('attendance', A, G)).toEqual(ATTN);

    const fetcher = vi.fn<typeof fetch>();
    const out = await loadPanel('attendance', { netid: A, groupKey: G, fetcher });

    expect(out).toMatchObject({ ok: true, source: 'cache', fetchedAt: 1000, stale: true });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('a cache hit inside the window is labelled fresh, outside it stale', async () => {
    await seed(ATTN, Date.now() - HOUR);
    const fresh = await loadPanel('attendance', { netid: A, groupKey: G, fetcher: net({}) });
    expect(fresh).toMatchObject({ ok: true, source: 'cache', stale: false });

    await seed(ATTN, Date.now() - STALE_MS - 1);
    const old = await loadPanel('attendance', { netid: A, groupKey: G, fetcher: net({}) });
    expect(old).toMatchObject({ ok: true, source: 'cache', stale: true });
  });

  it("another student's cache is not this student's cache", async () => {
    await seed(ATTN);
    const fetcher = net(payload('FWDT22'));
    const out = await loadPanel('attendance', { netid: 'zz9999', groupKey: G, fetcher });
    // Positive control: the seeded row is readable for A…
    expect(await readPanel('attendance', A, G)).toEqual(ATTN);
    // …so B falling through to the network means the key is netid-scoped.
    expect(out).toMatchObject({ ok: true, source: 'network', data: payload('FWDT22') });
    expect(fetcher).toHaveBeenCalledOnce();
  });
});

describe('cache miss → network', () => {
  it('fetches, validates, stores and returns the payload as network-fresh', async () => {
    const body = payload('NET001');
    const fetcher = net(body);
    const before = Date.now();
    const out = await loadPanel('attendance', { netid: A, groupKey: G, fetcher });

    expect(fetcher).toHaveBeenCalledWith('/api/attendance/island', expect.anything());
    expect(out).toMatchObject({ ok: true, source: 'network', stale: false, data: body });
    if (!out.ok) throw new Error('unreachable');
    expect(out.fetchedAt).toBeGreaterThanOrEqual(before);
    // Stored, and stamped with what we returned — a second load is a cache hit.
    expect(await readPanel('attendance', A, G)).toEqual(body);
    const again = await loadPanel('attendance', { netid: A, groupKey: G, fetcher: vi.fn<typeof fetch>() });
    expect(again).toMatchObject({ ok: true, source: 'cache', fetchedAt: out.fetchedAt });
  });

  it('an unparseable 200 is a typed failure and is NOT cached', async () => {
    const fetcher = respond(200, { ok: true, data: { courses: 'nope' } });
    const out = await loadPanel('attendance', { netid: A, groupKey: G, fetcher });

    expect(out).toMatchObject({ ok: false, reason: 'invalid' });
    expect(LOG.join()).toContain('dropping invalid attendance response');
    // Positive control: the SAME endpoint with a valid body DOES cache, so the
    // empty store below is caused by validation, not by a dead write path.
    await loadPanel('attendance', { netid: A, groupKey: G, fetcher: net(payload('GOOD01')) });
    expect(await readPanel('attendance', A, G)).toEqual(payload('GOOD01'));
  });
});

describe('corrupt cache', () => {
  it('a corrupt row is discarded, the network is used, and nothing throws', async () => {
    // A real, good row next to the bad one: a per-panel delete must not take it.
    await seed(payload('SURVIVE'));
    await db.table('attendance').put({
      netid: A, groupKey: G, fetchedAt: 1, schemaVersion: 1,
      payload: { courses: 'corrupt', monthly: [] },
    } as never);
    // …and a second panel for the same student, to prove nothing global is wiped.
    await writePanel('fees', { netid: A, groupKey: G, payload: { due: 0 } as never });

    const fetcher = net(payload('REFETCHED'));
    const out = await loadPanel('attendance', { netid: A, groupKey: G, fetcher });

    // Positive control #1: the failure was a bad payload, not a missing read —
    // readPanel said so, which is the only way it can have returned undefined.
    expect(LOG.join()).toContain('dropping corrupt attendance');
    // Positive control #2: the bad row is gone and the good one survived.
    expect(await db.attendance.get([A, G])).toMatchObject({ payload: payload('REFETCHED') });
    expect(await db.fees.get(A)).toBeDefined();
    // The behaviour: network filled the hole, no throw, typed as cache-miss.
    expect(fetcher).toHaveBeenCalledOnce();
    expect(out).toMatchObject({ ok: true, source: 'network', data: payload('REFETCHED') });
  });

  it('positive control: a VALID row is returned from cache, not discarded', async () => {
    await seed(ATTN, 2000);
    const fetcher = vi.fn<typeof fetch>();
    const out = await loadPanel('attendance', { netid: A, groupKey: G, fetcher });
    expect(out).toMatchObject({ ok: true, source: 'cache', data: ATTN, fetchedAt: 2000 });
    expect(fetcher).not.toHaveBeenCalled();
    expect(LOG.join()).not.toContain('dropping corrupt');
  });
});

describe('network failure', () => {
  it('offline with a cache returns the cache, marked stale when past the window', async () => {
    // The cache must be POPULATED by the loader itself before the network dies,
    // otherwise step 1 returns and step 3 never runs — that test would pass
    // while proving nothing about the fallback.
    const ok = vi.fn<typeof fetch>(async () => new Response(
      JSON.stringify({ ok: true, data: ATTN }),
      { status: 200 },
    ));
    await expect(loadPanel('attendance', { netid: A, groupKey: G, fetcher: ok }))
      .resolves.toMatchObject({ ok: true, source: 'network' });
    expect(await readPanel('attendance', A, G)).toEqual(ATTN); // it really is cached

    const down = vi.fn<typeof fetch>(async () => {
      throw new TypeError('Failed to fetch');
    });
    const offline = () => loadPanel('attendance', { netid: A, groupKey: G, fetcher: down });

    // Inside the window: the cache answers and the network is never touched.
    const fresh = await offline();
    expect(fresh).toMatchObject({ ok: true, source: 'cache', stale: false });
    expect(down).not.toHaveBeenCalled();

    // Past it: still served (that is the point of the fallback), now labelled stale.
    await writePanel('attendance', { netid: A, groupKey: G, payload: ATTN, fetchedAt: Date.now() - STALE_MS - 1000 });
    const out = await offline();
    expect(out).toMatchObject({ ok: true, source: 'cache', stale: true, data: ATTN });
  });

  it('offline with NO cache is one typed failure, no rejection', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => {
      throw new TypeError('Failed to fetch');
    });
    const p = loadPanel('attendance', { netid: A, groupKey: G, fetcher });
    await expect(p).resolves.toMatchObject({ ok: false, reason: 'network' });
    expect(LOG.join()).toContain('network failed for attendance');
    // Positive control: the same call WITH a cache resolves ok — so `ok:false`
    // above is the absence of data, not a loader that always fails.
    await seed(ATTN);
    await expect(loadPanel('attendance', { netid: A, groupKey: G, fetcher })).resolves
      .toMatchObject({ ok: true, source: 'cache' });
  });
});

describe('auth and gating never cache', () => {
  it('401 is unauthenticated, cache untouched — and a 200 afterwards still works', async () => {
    await seed(ATTN, 5000);
    const out401 = await loadPanel('attendance', { netid: 'zz9999', groupKey: G, fetcher: respond(401, { ok: false, error: 'not logged in' }) });
    expect(out401).toMatchObject({ ok: false, reason: 'unauthenticated', status: 401, message: 'not logged in' });
    expect(await db.attendance.get(['zz9999', G])).toBeUndefined();

    // Positive control: the same unknown student's 200 response IS cached.
    await loadPanel('attendance', { netid: 'zz9999', groupKey: G, fetcher: net(payload('CACHED')) });
    expect(await readPanel('attendance', 'zz9999', G)).toEqual(payload('CACHED'));
    // …and the seeded student's cache was left intact throughout.
    expect(await readPanel('attendance', A, G)).toEqual(ATTN);
  });

  it('404 (gated panel) is its own reason and is not cached', async () => {
    const fetcher = respond(404, { ok: false, error: 'no fees data yet — sync first' });
    const out = await loadPanel('fees', { netid: A, fetcher });
    expect(out).toMatchObject({ ok: false, reason: 'not_found', status: 404, message: 'no fees data yet — sync first' });
    expect(await db.fees.get(A)).toBeUndefined();

    // Positive control: 404 then 200 — the second visit caches. So the empty
    // store above is the 404's doing, not a read path that never writes.
    await loadPanel('fees', { netid: A, fetcher: net({ due: 0, due_disp: '0', dues: [], ledger: [], level: '', paid_total: '0', years: [] }) });
    expect(await db.fees.get(A)).toBeDefined();
  });
});
