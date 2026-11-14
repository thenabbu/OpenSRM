import Dexie, { type Table } from 'dexie';
import type { z } from 'zod';
import {
  AcademicsData, CampusData, FeesData,
} from '../contracts';
import { attendanceProps } from '../panels/attendance/contract';
import { warn as logWarn } from '../log';
import { marksProps } from '../panels/marks/contract';
import { timetableProps } from '../panels/timetable/contract';

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

// ── Schema version: ONE source ──────────────────────────────────────────────
// `SCHEMAS[i]` IS `version(i + 1)`, and `SCHEMA_VERSION` is that array's
// length. Bumping the schema is appending one entry; the version number moves
// with it, so the two cannot drift. They had drifted: this constant said 1
// while the database had been at version 2, and that number is stamped into
// every row and every `meta` record.
//
// APPEND ONLY. Editing an entry that already shipped is invisible to Dexie —
// it compares the declared map against what is on the device, and a changed
// entry at the same version number never reaches existing rows.
const V1 = {
  attendance: '[netid+groupKey], netid, fetchedAt',
  marks: '[netid+groupKey], netid, fetchedAt',
  timetable: '[netid+groupKey], netid, fetchedAt',
  fees: 'netid, fetchedAt',
  campus: 'netid, fetchedAt',
  academics: 'netid, fetchedAt',
  meta: 'netid',
} satisfies Record<string, string>;

// v2 adds no store and deletes none: a store left out of a later version keeps
// its previous shape, so `fees` is unchanged. Re-spelling the v1 map here would
// only be a second copy that can drift — add the new store beside it when one
// lands (notes/DECISION-tools-settings-store.md:150).
const V2 = { ...V1 };

// v3 adds ONE store: the write queue for deferred offline actions (P7.4).
// `&k` is unique: enqueuing the same tag twice must REPLACE, not append, so a
// student who changes their mind offline replays one write, not two. `netid`
// and `at` are indexed for the per-student drain and the retry order.
const V3 = { ...V2, outbox: '&k, netid, at' };

export const SCHEMAS = [V1, V2, V3] as const;
export const SCHEMA_VERSION = SCHEMAS.length;

/** Payload schema per panel — the same contracts the read path validates with. */
const RECORD_SCHEMA = {
  // The ATTENDANCE ISLAND payload, not the /api/attendance panel slice: that is
  // what load.ts caches (it reads /api/attendance/island), so this is what
  // readPanel must validate on the way back out. They were different schemas,
  // so every cached row read as "corrupt" and was deleted on the next visit.
  attendance: attendanceProps,
  // marks/timetable: the ISLAND payloads, for the same reason as attendance —
  // load.ts caches the island feeds (/api/marks/island, /api/timetable/island),
  // so these validators must accept that shape. They used to hold the LEGACY
  // shapes (the raw `marks` array, `{ok, slots, …}`), which rejected every
  // cached row as corrupt: the store never kept marks or a timetable at all.
  marks: marksProps,
  timetable: timetableProps,
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

/** One deferred write. `k` is the conflict grain, not a random id — see
 *  `queueWrite` in outbox.ts for why that matters. `kind` is kept a plain
 *  string here so the storage layer does not import the route table (that
 *  would make db.ts depend on a panel-level module, and it is the one module
 *  allowed to own IndexedDB). */
export type OutboxRow = {
  k: string;                        // unique: `${kind}|<identity>` — LWW key
  netid: string;
  kind: string;
  at: number;                       // enqueue time, ms; drain order
  attempts: number;                 // bounded retry counter
  form: Record<string, string>;     // the exact POST body that was typed
};

export class OpenSRMDB extends Dexie {
  attendance!: Table<Row, [string, string]>;
  marks!: Table<Row, [string, string]>;
  timetable!: Table<Row, [string, string]>;
  fees!: Table<Row, string>;
  campus!: Table<Row, string>;
  academics!: Table<Row, string>;
  meta!: Table<MetaRecord, string>;
  outbox!: Table<OutboxRow, string>;

  /** `name` is a parameter only so a test can build an ISOLATED database that
   *  still goes through this exact class: the upgrade fixture must exercise the
   *  real version list, not a hand-copied one. */
  constructor(name = 'opensrm') {
    super(name);
    SCHEMAS.forEach((stores, i) => { this.version(i + 1).stores(stores); });
    // Every record stamped before SCHEMA_VERSION was derived carries the old,
    // wrong number (1, while the schema had been 2 for a while). Rewrite the
    // mismatched `meta` records on open: a repair, never a wipe (see the upgrade
    // policy above). `meta` is the record a future migration branches on; panel
    // rows carry the same stamp but nothing reads it, and the next `writePanel`
    // re-stamps them.
    this.on('ready', (vipDb: Dexie) => {
      void vipDb.table<MetaRecord, string>('meta').toCollection()
        .modify((m) => { if (m.schemaVersion !== SCHEMA_VERSION) m.schemaVersion = SCHEMA_VERSION; })
        .catch((e: unknown) => log('schemaVersion repair failed', e));
    });
  }
}

export const db = new OpenSRMDB();

export const PANELS = Object.keys(RECORD_SCHEMA) as Panel[];

const table = (p: Panel) => db.table<Row>(p);
const log = (what: string, err?: unknown) =>
  logWarn('db', what, err instanceof Error ? err.message : (err ?? ''));

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
  // ONE transaction over both stores. Named multi-table writer #1 of 2 (the
  // other is `wipeAll`): the payload and the `last_sync` stamp that promises it
  // arrive together or not at all — two independent writes could leave a row on
  // disk whose timestamp the `meta` record never learned.
  const commit = () =>
    db.transaction('rw', [panel, 'meta'], async () => {
      await io.put(panel, row);
      await db.meta.update(rec.netid, (m) => {
        if (m) m.last_sync[panel] = row.fetchedAt;
      });
    });
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
    // ONE transaction over every store. These used to be a bare Promise.all of
    // independent deletes: each one committed on its own, so a failure part-way
    // left some stores cleared and others not, with nothing recording which.
    // Named multi-table writer #2 of 2 (the other is `writePanel`).
    //
    // `outbox` is in this list on purpose. It holds a tag the student TYPED, so
    // a logout that left it behind would replay that write under whoever signs
    // in next on a shared device — the queue would become a cross-account leak.
    const tables: string[] = [...PANELS, 'meta', 'outbox'];
    if (netid === undefined) {
      await db.transaction('rw', tables, () => Promise.all(tables.map((t) => db.table(t).clear())));
    } else {
      await db.transaction('rw', tables, () =>
        Promise.all([
          ...PANELS.map((p) => table(p).where('netid').equals(netid).delete()),
          db.meta.delete(netid),
          db.outbox.where('netid').equals(netid).delete(),
        ]),
      );
    }
  } catch (e) {
    log('wipe failed', e);
  }
}
