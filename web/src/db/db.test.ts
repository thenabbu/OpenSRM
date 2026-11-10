import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import attendanceIsland from '../contracts/fixtures/attendance_island.json';
import fees from '../contracts/fixtures/fees.json';
import { FeesData } from '../contracts';
import { attendanceProps } from '../panels/attendance/contract';
import { db, io, PANELS, readMeta, readPanel, wipeAll, writeMeta, writePanel } from './db';

const A = 'zz1111';
const B = 'zz2222';
// The ISLAND payload: that is what the attendance store holds (see RECORD_SCHEMA).
const ATTN = attendanceProps.parse(attendanceIsland.data);
const FEES = FeesData.parse(fees.data);

const LOG: string[] = [];
beforeEach(() => {
  LOG.length = 0;
  vi.spyOn(console, 'warn').mockImplementation((m: unknown) => void LOG.push(String(m)));
});
afterEach(async () => {
  vi.restoreAllMocks();
  await wipeAll();
});

describe('round trip', () => {
  it('writes and reads a validated payload back intact', async () => {
    expect(await writePanel('attendance', { netid: A, groupKey: 'g1', payload: ATTN })).toBe(true);
    expect(await readPanel('attendance', A, 'g1')).toEqual(ATTN);
    const row = await db.attendance.get([A, 'g1']);
    expect(row?.netid).toBe(A);
    expect(row?.schemaVersion).toBe(1);
    expect(typeof row?.fetchedAt).toBe('number');
  });

  it('stamps meta.last_sync for the account', async () => {
    await writeMeta({ netid: A, last_sync: {}, schemaVersion: 1, flags: {} });
    await writePanel('fees', { netid: A, payload: FEES, fetchedAt: 1234 });
    expect((await readMeta(A))?.last_sync.fees).toBe(1234);
  });
});

describe('netid isolation on a shared device', () => {
  it("student B cannot read student A's records", async () => {
    await writePanel('attendance', { netid: A, groupKey: 'g1', payload: ATTN });
    await writePanel('fees', { netid: A, payload: FEES });
    // Positive control: A reads their OWN data back. Without this the two
    // assertions below would also pass if the write path silently stored
    // nothing — exactly the "passes for the wrong reason" failure this
    // project has been bitten by before.
    expect(await readPanel('attendance', A, 'g1')).toEqual(ATTN);
    expect(await readPanel('fees', A)).toEqual(FEES);
    // SAME group key — the classmates-share-a-group case.
    expect(await readPanel('attendance', B, 'g1')).toBeUndefined();
    expect(await readPanel('fees', B)).toBeUndefined();
  });

  it('a wipe scoped to A leaves B untouched', async () => {
    await writePanel('fees', { netid: A, payload: FEES });
    await writePanel('fees', { netid: B, payload: FEES });
    await wipeAll(A);
    expect(await readPanel('fees', A)).toBeUndefined();
    expect(await readPanel('fees', B)).toEqual(FEES);
  });
});

describe('wipeAll', () => {
  it('empties every store and a re-open reads nothing', async () => {
    await writePanel('attendance', { netid: A, groupKey: 'g1', payload: ATTN });
    await writePanel('fees', { netid: A, payload: FEES });
    await writeMeta({ netid: A, last_sync: { fees: 1 }, schemaVersion: 1, flags: {} });
    await wipeAll();
    for (const p of PANELS) expect(await db.table(p).count()).toBe(0);
    expect(await db.meta.count()).toBe(0);
    expect(await readPanel('attendance', A, 'g1')).toBeUndefined();
    expect(await readPanel('fees', A)).toBeUndefined();
  });
});

describe('corrupt records', () => {
  it('a bad payload is rejected on read, deleted, and not thrown', async () => {
    await db.table('fees').put({
      netid: A, groupKey: '', fetchedAt: 1, schemaVersion: 1,
      payload: { due: 'not-a-number', dues: [] }, // missing + wrong-typed fields
    });
    await expect(readPanel('fees', A)).resolves.toBeUndefined();
    expect(await db.fees.count()).toBe(0);
    expect(LOG.join()).toContain('dropping corrupt fees');
  });

  it('a record written by an older shape (no fetchedAt) still validates on payload', async () => {
    await db.table('campus').put({ netid: A, payload: { show: false, cards: [] } } as never);
    await expect(readPanel('campus', A)).resolves.toEqual({ show: false, cards: [] });
  });
});

describe('quota', () => {
  const realPut = io.put;
  afterEach(() => {
    io.put = realPut;
  });

  it('evicts the oldest account and retries, without throwing', async () => {
    // B cached long ago, A recently: B is the victim.
    await writeMeta({ netid: B, last_sync: { fees: 1 }, schemaVersion: 1, flags: {} });
    await writePanel('fees', { netid: B, payload: FEES, fetchedAt: 1 });
    await writeMeta({ netid: A, last_sync: { fees: 9e12 }, schemaVersion: 1, flags: {} });

    let n = 0;
    io.put = (p, row) => {
      if (++n === 1) throw new DOMException('full', 'QuotaExceededError');
      return realPut(p, row);
    };

    await expect(writePanel('fees', { netid: A, payload: FEES })).resolves.toBe(true);
    expect(await readPanel('fees', B)).toBeUndefined(); // oldest went first
    expect(await readPanel('fees', A)).toEqual(FEES); // retry landed
  });

  it('degrades to network-only (false, no throw) when nothing can be freed', async () => {
    io.put = () => {
      throw new DOMException('full', 'QuotaExceededError');
    };
    await expect(writePanel('fees', { netid: A, payload: FEES })).resolves.toBe(false);
    expect(LOG.join()).toContain('degrading to network-only');
  });
});
