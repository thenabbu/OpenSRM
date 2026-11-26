import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import attendanceIsland from '../contracts/fixtures/attendance_island.json';
import fees from '../contracts/fixtures/fees.json';
import { FeesData } from '../contracts';
import { attendanceProps } from '../panels/attendance/contract';
import Dexie from 'dexie';
import { db, io, OpenSRMDB, PANELS, SCHEMAS, SCHEMA_VERSION, readMeta, readPanel, wipeAll, writeMeta, writePanel } from './db';
import type { OutboxRow } from './db';

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
    expect(row?.schemaVersion).toBe(SCHEMA_VERSION);
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

// ── Upgrade path: EVERY prior version ───────────────────────────────────────
// FIXTURE RULE, not negotiable: every version below SCHEMA_VERSION must open
// under it with its rows intact and nothing wiped. The loop below builds a real
// database at each prior version FROM `SCHEMAS` itself — no hand-copied store
// map to drift — and covers all of them automatically. When version 3 lands,
// nothing needs adding here: the v1 AND v2 fixtures are generated, and
// `covers every prior version` fails the run if a declared version has no
// fixture. Deleting the loop instead of extending it is what that guard catches.
describe('upgrade path', () => {
  const nameFor = (v: number) => `opensrm-upgrade-v${v}`;

  /** The stores that exist at version `v`: a store left out of a later version
   *  keeps its previous shape, so the union of every spec up to `v` is the real
   *  table list. */
  const storesAt = (v: number): string[] => [
    ...new Set(SCHEMAS.slice(0, v).flatMap((s) => Object.keys(s))),
  ];

  const rowFor = (store: string, v: number) => ({
    netid: A, groupKey: 'g1', payload: { store, v }, fetchedAt: v, schemaVersion: v,
  });

  const upgrades: number[] = [];
  for (let v = 1; v < SCHEMA_VERSION; v++) upgrades.push(v);

  it('covers every prior version (a fixture per version, none skipped)', () => {
    expect(upgrades).toEqual(Array.from({ length: SCHEMA_VERSION - 1 }, (_, i) => i + 1));
    expect(SCHEMAS.length).toBe(SCHEMA_VERSION); // one source, not two
  });

  for (const v of upgrades) {
    it(`a v${v} database opens at v${SCHEMA_VERSION} with its rows intact and no wipe`, async () => {
      const name = nameFor(v);
      // A REAL database at version v, declared from the same specs the app uses.
      const before = new Dexie(name);
      SCHEMAS.slice(0, v).forEach((stores, i) => { before.version(i + 1).stores(stores); });
      for (const store of storesAt(v)) await before.table(store).put(rowFor(store, v));
      before.close();

      // Open it through the app's own class: this runs the real upgrade.
      const after = new OpenSRMDB(name);
      await after.open();
      expect(after.verno).toBe(SCHEMA_VERSION); // the number Dexie actually uses
      expect(after.tables.map((t) => t.name).sort()).toEqual(storesAt(SCHEMA_VERSION).sort());

      for (const store of storesAt(v)) {
        const rows = await after.table(store).toArray();
        expect(rows, `${store} survived v${v} -> v${SCHEMA_VERSION}`).toHaveLength(1);
        expect(rows[0]?.payload).toEqual({ store, v }); // same row, not a re-created empty store
      }

      // `outbox` must be ABSENT before v3, so the assertions below measure what
      // the upgrade created rather than a store that was already on the device.
      if (v < 3) {
        expect(storesAt(v), `outbox must not exist at v${v}`).not.toContain('outbox');
      }

      // `&k` has to be UNIQUE on the UPGRADED database, not only on a fresh one.
      // Dexie applies the declared spec when it creates or migrates the store, so
      // an upgrade that spelled the index `k` (no `&`) would still create the
      // table, still pass every assertion above, and silently lose last-write-
      // wins for every user who has an older database — the exact population the
      // migration exists for. Two puts on one key must leave ONE row carrying
      // the SECOND write.
      const outbox = after.table<OutboxRow, string>('outbox');
      const row: OutboxRow = { k: 'zz1111|tag|X|CAT-1', netid: A, kind: 'tag', at: 1, attempts: 0, form: { role: 'IE-1' } };
      await outbox.put(row);
      await outbox.put({ ...row, at: 2, form: { role: 'IE-2' } });
      expect(await outbox.count(), `&k unique after v${v} -> v${SCHEMA_VERSION}`).toBe(1);
      expect((await outbox.toArray())[0]).toMatchObject({ at: 2, form: { role: 'IE-2' } });

      // The stale stamp is REPAIRED on open (never a wipe): these rows were
      // written with schemaVersion = v, and the repair runs from the ready hook.
      await vi.waitFor(async () => {
        const meta = await after.table('meta').toArray();
        expect(meta[0]?.schemaVersion).toBe(SCHEMA_VERSION);
      });

      after.close();
      await Dexie.delete(name);
    });
  }

  it("the shipped database's real Dexie version IS SCHEMA_VERSION", async () => {
    await db.open();
    expect(db.verno).toBe(SCHEMA_VERSION);
  });
});

// ── Atomicity: a partial write must never be observable ─────────────────────
// db.ts has exactly two multi-table writers — `writePanel` (panel + meta) and
// `wipeAll` (every store + meta) — and each one is a single transaction. Each
// test here makes a REAL Dexie write land inside that transaction and then
// fails it, so the assertion is "the write ran and was rolled back", not "the
// write never happened". The positive control beside each one proves the same
// call does persist when nothing throws: without it, a silently no-op writer
// would satisfy every rollback assertion below.
describe('multi-table writes are atomic', () => {
  it('writePanel: a failure after the row landed rolls back the row AND the meta stamp', async () => {
    await writeMeta({ netid: A, last_sync: {}, schemaVersion: SCHEMA_VERSION, flags: {} });
    const realPut = io.put;
    io.put = async (p, row) => {
      await realPut(p, row);                  // the row really reaches the store...
      throw new Error('boom after the row');  // ...then the transaction fails
    };
    try {
      await expect(writePanel('fees', { netid: A, payload: FEES })).resolves.toBe(false);
    } finally {
      io.put = realPut;
    }
    expect(LOG.join()).toContain('write fees failed');
    expect(await db.fees.count()).toBe(0);                         // rolled back
    expect((await readMeta(A))?.last_sync.fees).toBeUndefined();    // and so is the stamp
  });

  it('writePanel: the same write with no fault persists both (positive control)', async () => {
    await writeMeta({ netid: A, last_sync: {}, schemaVersion: SCHEMA_VERSION, flags: {} });
    await expect(writePanel('fees', { netid: A, payload: FEES, fetchedAt: 7 })).resolves.toBe(true);
    expect(await db.fees.count()).toBe(1);
    expect((await readMeta(A))?.last_sync.fees).toBe(7);
  });

  it('wipeAll: a failure part-way leaves EVERY store intact', async () => {
    const seed = async () => {
      await writePanel('attendance', { netid: A, groupKey: 'g1', payload: ATTN });
      await writePanel('fees', { netid: A, payload: FEES });
      await writeMeta({ netid: A, last_sync: { fees: 1 }, schemaVersion: SCHEMA_VERSION, flags: {} });
    };

    // Positive control: with no fault the wipe really does empty everything, so
    // "nothing was deleted" below cannot pass on a no-op wipe.
    await seed();
    await wipeAll();
    expect(await db.fees.count()).toBe(0);
    expect(await db.meta.count()).toBe(0);

    await seed();
    // Fail ONE store's clear AFTER it has cleared, inside the wipe's own
    // transaction: every other store's delete has already been issued by then.
    const rigged = db.table('academics');
    const realClear = rigged.clear.bind(rigged);
    Object.defineProperty(rigged, 'clear', {
      configurable: true,
      value: () => realClear().then(() => { throw new Error('boom mid-wipe'); }),
    });
    try {
      await wipeAll();
    } finally {
      Reflect.deleteProperty(rigged, 'clear');
    }

    expect(LOG.join()).toContain('wipe failed');
    expect(await db.attendance.count()).toBe(1);
    expect(await db.fees.count()).toBe(1);
    expect(await db.meta.count()).toBe(1);
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
