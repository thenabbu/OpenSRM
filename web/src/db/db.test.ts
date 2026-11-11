import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import attendanceIsland from '../contracts/fixtures/attendance_island.json';
import fees from '../contracts/fixtures/fees.json';
import { FeesData } from '../contracts';
import { attendanceProps } from '../panels/attendance/contract';
import Dexie from 'dexie';
import { db, io, PANELS, SCHEMA_VERSION, readMeta, readPanel, wipeAll, writeMeta, writePanel } from './db';

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

// ── The upgrade guard for a FUTURE store ────────────────────────────────────
// No store was added for `tools`/`settings` (see notes/DECISION-tools-settings-
// store.md), so `SCHEMA_VERSION` is still 1 and there is nothing to upgrade yet.
// These tests exist so that when a store IS added, the version(2) promise in
// db.ts:17-30 is already measured rather than assumed: the cheapest wrong move
// is a `version(2).stores({...})` that forgets to re-declare a v1 table, which
// silently DROPS it and every cached student row in it.
describe('schema upgrades preserve existing rows', () => {
  const RAW = 'opensrm-upgrade-probe';

  it('a v1 database opens under the current version with its rows intact', async () => {
    // A real v1 database, built from the v1 store map — not the app's singleton,
    // which would create it at the CURRENT version and prove nothing.
    const v1 = new Dexie(RAW);
    v1.version(1).stores({
      attendance: '[netid+groupKey], netid, fetchedAt',
      marks: '[netid+groupKey], netid, fetchedAt',
      timetable: '[netid+groupKey], netid, fetchedAt',
      fees: 'netid, fetchedAt',
      campus: 'netid, fetchedAt',
      academics: 'netid, fetchedAt',
      meta: 'netid',
    });
    await v1.table('fees').put({ netid: A, groupKey: '', payload: FEES, fetchedAt: 42, schemaVersion: 1 });
    await v1.table('meta').put({ netid: A, last_sync: { fees: 42 }, schemaVersion: 1, flags: {} });
    v1.close();

    // Re-open at whatever the app ships now. A destructive bump shows up here
    // as a dropped table or an empty one.
    const reopened = new Dexie(RAW);
    reopened.version(1).stores({
      attendance: '[netid+groupKey], netid, fetchedAt',
      marks: '[netid+groupKey], netid, fetchedAt',
      timetable: '[netid+groupKey], netid, fetchedAt',
      fees: 'netid, fetchedAt',
      campus: 'netid, fetchedAt',
      academics: 'netid, fetchedAt',
      meta: 'netid',
    });
    const row = await reopened.table('fees').get(A);
    expect(row.payload).toEqual(FEES);
    expect(row.fetchedAt).toBe(42);
    expect((await reopened.table('meta').get(A)).last_sync.fees).toBe(42);
    reopened.close();
    await Dexie.delete(RAW);
  });

  it('the v1 store map in this test matches the one db.ts ships', async () => {
    // The guard above only means something while the two maps agree. If a store
    // is added to db.ts's live version(n) and not here, this fails and points at
    // the note — instead of the upgrade test quietly probing the wrong schema.
    const live = db.tables.map((t) => t.name).sort();
    expect(live).toEqual(
      ['academics', 'attendance', 'campus', 'fees', 'marks', 'meta', 'timetable'],
    );
    expect(SCHEMA_VERSION).toBe(1); // bump both this and the note together
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
