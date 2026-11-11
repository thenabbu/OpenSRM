import Dexie, { type Table } from 'dexie';
import type { z } from 'zod';
import {
  AcademicsData, CampusData, FeesData, MarksData, TimetableData,
} from '../contracts';
import { attendanceProps } from '../panels/attendance/contract';

// ── The one module that owns IndexedDB. Nothing else may touch `indexedDB` ──
//
// Every store is NETID-SCOPED. A key of only `groupKey` would hand student A's
// timetable to student B on a shared device (classmates share a group), so the
// netid is part of the primary key, not merely a filter.
//
// ── Upgrade policy (db.version) ──────────────────────────────────────────────
// * NEVER wipe on upgrade. A new store is a new `version(n).stores({…})`
//   entry: Dexie creates it empty and leaves every existing store intact.
// * A field rename is `version(n).stores({s: 'newName,…'}).upgrade(tx =>
//   tx.table('s').toCollection().modify(r => { r.newName = r.oldName;
//   delete r.oldName; }))` — migrate in place, key path unchanged.
// * A record that no longer parses under the CURRENT schema is dropped and
//   logged by `readPanel`, never a crash. That is the net for a migration that
//   missed a row; a dropped row costs exactly one refetch.
// * A change that cannot be an in-place modify (the key path itself moves)
//   gets a NEW store name, and the old one is left for the next `wipeAll` —
//   dead bytes nobody reads beat a half-migrated table.

export const SCHEMA_VERSION = 1;

/** Payload schema per panel — the same contracts the read path validates with. */
const RECORD_SCHEMA = {
  // The ATTENDANCE ISLAND payload, not the /api/attendance panel slice: that is
  // what load.ts caches (it reads /api/attendance/island), so this is what
  // readPanel must validate on the way back out. They were different schemas,
  // so every cached row read as "corrupt" and was deleted on the next visit.
  attendance: attendanceProps,
  marks: MarksData, // the array: /api/marks stores its json as a list
  timetable: TimetableData,
  fees: FeesData,
  campus: CampusData,
  academics: AcademicsData,
} as const;

export type Panel = keyof typeof RECORD_SCHEMA;
export type PanelData<P extends Panel> = z.output<(typeof RECORD_SCHEMA)[P]>;

/** fees/campus/academics are per-student; the rest are per-group. */
const PER_STUDENT: ReadonlySet<Panel> = new Set<Panel>(['fees', 'campus', 'academics']);
export const keyPath = (p: Panel) => (PER_STUDENT.has(p) ? 'netid' : '[netid+groupKey]');

type Row = {
  netid: string;
  groupKey: string; // '' for per-student stores
  payload: unknown;
  fetchedAt: number;
  schemaVersion: number;
};

export type MetaRecord = {
  netid: string;
  last_sync: Record<string, number>; // panel -> epoch ms of the last good write
  schemaVersion: number;
  flags: Record<string, unknown>;
};

class OpenSRMDB extends Dexie {
  attendance!: Table<Row, [string, string]>;
  marks!: Table<Row, [string, string]>;
  timetable!: Table<Row, [string, string]>;
  fees!: Table<Row, string>;
  campus!: Table<Row, string>;
  academics!: Table<Row, string>;
  meta!: Table<MetaRecord, string>;

  constructor() {
    super('opensrm');
    this.version(1).stores({
      attendance: '[netid+groupKey], netid, fetchedAt',
      marks: '[netid+groupKey], netid, fetchedAt',
      timetable: '[netid+groupKey], netid, fetchedAt',
      fees: 'netid, fetchedAt',
      campus: 'netid, fetchedAt',
      academics: 'netid, fetchedAt',
      meta: 'netid',
    });
    this.version(2).stores({
      attendance: '[netid+groupKey], netid, fetchedAt',
      marks: '[netid+groupKey], netid, fetchedAt',
      timetable: '[netid+groupKey], netid, fetchedAt',
      campus: 'netid, fetchedAt',
      academics: 'netid, fetchedAt',
      meta: 'netid',
    });
  }
}

export const db = new OpenSRMDB();

export const PANELS = Object.keys(RECORD_SCHEMA) as Panel[];

const table = (p: Panel) => db.table<Row>(p);
const log = (what: string, err?: unknown) =>
  console.warn(`[db] ${what}`, err instanceof Error ? err.message : (err ?? ''));

const isQuotaError = (e: unknown) =>
  e instanceof DOMException
    ? e.name === 'QuotaExceededError' || e.name === 'NS_ERROR_DOM_QUOTA_REACHED'
    : (e as { name?: string } | null)?.name === 'QuotaExceededError';

/** Cheap pre-check so a bulk write doesn't walk into a full device. */
export async function hasRoom(): Promise<boolean> {
  try {
    const { usage, quota } = await navigator.storage.estimate();
    return usage === undefined || !quota || usage / quota < 0.95;
  } catch {
    return true; // no estimate API — let the write decide
  }
}

/** Oldest account cached (min last_sync) is the eviction victim: its records
 *  ARE the space. Returns true when something was actually freed. */
async function evictOldest(): Promise<boolean> {
  try {
    const metas = await db.meta.toArray();
    if (!metas.length) return false;
    const age = (m: MetaRecord) => Math.min(Infinity, ...Object.values(m.last_sync));
    const victim = metas.sort((a, b) => age(a) - age(b))[0]!;
    await wipeAll(victim.netid);
    log(`quota: evicted cache for ${victim.netid}`);
    return true;
  } catch (e) {
    log('evict failed', e);
    return false;
  }
}

/** The one write primitive — swappable in tests so the quota path can be
 *  exercised without a full device. Nothing else should call `db.table().put`. */
export const io = { put: (p: Panel, row: Row) => table(p).put(row as never) };

/** Write one panel record. Never throws and never rejects unhandled: on
 *  QuotaExceededError evict the oldest account once, retry, and if it still
 *  fails return false — the caller then runs network-only. */
export async function writePanel<P extends Panel>(
  panel: P,
  rec: { netid: string; groupKey?: string; payload: PanelData<P>; fetchedAt?: number },
): Promise<boolean> {
  const row: Row = {
    netid: rec.netid,
    groupKey: PER_STUDENT.has(panel) ? '' : (rec.groupKey ?? ''),
    payload: rec.payload,
    fetchedAt: rec.fetchedAt ?? Date.now(),
    schemaVersion: SCHEMA_VERSION,
  };
  const commit = async () => {
    await io.put(panel, row);
    await db.meta.update(rec.netid, (m) => {
      if (m) m.last_sync[panel] = row.fetchedAt;
    });
  };
  try {
    await commit();
    return true;
  } catch (e) {
    if (!isQuotaError(e)) {
      log(`write ${panel} failed`, e);
      return false;
    }
    if (await evictOldest()) {
      try {
        await commit();
        return true;
      } catch (e2) {
        log(`write ${panel} failed after evict`, e2);
      }
    }
    log(`write ${panel}: degrading to network-only`);
    return false;
  }
}

/** Read + validate one panel record. A payload failing the current schema is
 *  deleted and logged; caller gets `undefined` and refetches. Never throws. */
export async function readPanel<P extends Panel>(
  panel: P,
  netid: string,
  groupKey = '',
): Promise<PanelData<P> | undefined> {
  const key: string | [string, string] = PER_STUDENT.has(panel) ? netid : [netid, groupKey];
  try {
    const row = await table(panel).get(key);
    if (!row) return undefined;
    const parsed = (RECORD_SCHEMA[panel] as z.ZodType).safeParse(row.payload);
    if (!parsed.success) {
      log(`dropping corrupt ${panel} for ${netid}`, parsed.error.message);
      await table(panel).delete(key);
      return undefined;
    }
    return parsed.data as PanelData<P>;
  } catch (e) {
    log(`read ${panel} failed`, e);
    return undefined;
  }
}

export async function writeMeta(meta: MetaRecord): Promise<void> {
  try {
    await db.meta.put({ ...meta, schemaVersion: SCHEMA_VERSION });
  } catch (e) {
    log('write meta failed', e);
  }
}

export async function readMeta(netid: string): Promise<MetaRecord | undefined> {
  try {
    return await db.meta.get(netid);
  } catch (e) {
    log('read meta failed', e);
    return undefined;
  }
}

/**
 * True when this browser can open an IndexedDB at all. Safari private mode —
 * and a page whose storage is denied — throw synchronously from
 * `indexedDB.open`; `undefined` is a browser with no API. Both are KNOWN
 * UP FRONT, so `wipeAll` bails before a query: a Dexie query on a poisoned
 * singleton fails its ready promise for the rest of the page, which in private
 * mode would mean paying that cost on every load, not just at logout.
 *
 * `indexedDB.databases()` (rather than `open()`) is the probe: it throws under
 * the same conditions and never hands back a request whose `.result` is still
 * null. Browsers without it skip the probe and let Dexie decide — the old
 * behaviour, for a browser that is not Safari 14.
 *
 * `probe` is injectable only so the guard is testable with a factory that
 * throws — a real browser that throws cannot be simulated from the outside.
 */
export function canStore(probe: Pick<IDBFactory, 'databases'> | undefined = globalThis.indexedDB): boolean {
  if (!probe) return false;
  const databases = probe.databases;
  if (typeof databases !== 'function') return true; // no probe available: trust it
  try {
    void databases.call(probe).catch(() => {});
    return true;
  } catch {
    return false;
  }
}

/** Logout ⇒ everything goes, matching the SW dropping its cache. With a netid
 *  only that student's rows go; without, every account on this device. Never
 *  rejects: a logout must complete on a device with no usable storage.
 *  (`canStore()` is checked per call, not once at load: storage can be denied
 *  after first paint and re-granted after a reload.) */
export async function wipeAll(netid?: string): Promise<void> {
  if (!canStore()) {
    log('no usable IndexedDB — nothing to wipe');
    return;
  }
  try {
    if (netid === undefined) {
      await Promise.all([...PANELS, 'meta'].map((t) => db.table(t).clear()));
    } else {
      await Promise.all([
        ...PANELS.map((p) => table(p).where('netid').equals(netid).delete()),
        db.meta.delete(netid),
      ]);
    }
  } catch (e) {
    log('wipe failed', e);
  }
}
