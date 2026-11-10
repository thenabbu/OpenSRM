import { type FeesData } from '../contracts';
import { type CampusData, type CampusCard } from '../contracts';
import { type AcademicsData } from '../contracts';
import type { Panel } from '../db';
import type { FeesProps } from '../panels/fees/contract';
import type { CampusProps } from '../panels/campus/contract';
import type { AcademicsProps } from '../panels/academics/contract';
import { schemas } from '../islands/contract';

// ── Cache payload → island props ─────────────────────────────────────────
//
// The store holds what /api/<panel> serves (the panel_data slice); an island
// renders what its server-side `*_island.props()` emits. Those are the SAME
// numbers in two shapes, and the gap is the reason the read path could not just
// hand `out.data` to a component.
//
// So the projection is mirrored here, once per panel, and it is deliberately
// NARROW: a field the island's own schema would reject never reaches the
// component (this module re-validates with the same schema main.ts does, so a
// drift between the two throws here rather than painting half a panel).
//
// Arrays are COPIED, not re-sorted: fees.py/campus.py/academics.py own row order
// and thresholds, and re-sorting client-side is how the offline copy starts
// disagreeing with the page the user saw a minute ago.
//
// `attendance`, `marks`, `timetable` have no island yet (Phase 6 shipped five),
// so they project to nothing and stay cache-only until their island lands.

type Project = (data: unknown) => unknown;

const feesProps = (data: unknown): FeesProps => {
  const f = data as FeesData & { due?: number };
  return {
    due_disp: f.due_disp,
    // /api/fees types `level` as a bare string; the island's enum is narrower.
    // Anything the server did not mean to colour falls back to '' (uncoloured).
    level: f.level === 'text-warning' || f.level === 'text-error' ? f.level : '',
    dues: f.dues.map((d) => ({
      amt: d.amt, due: d.due, penalty: d.penalty, penalised: Boolean(d.penalised),
    })),
    paid_total: f.paid_total,
    years: f.years.map((y) => ({
      year: y.year,
      total: y.total,
      rows: y.rows.map((r) => ({ date: r.date, head: r.head, amt: r.amt })),
    })),
    ledger: f.ledger.map((e) => ({
      date: e.date, amt: e.amt, vno: e.vno, head: e.head, full: e.full,
    })),
  };
};

const campusProps = (data: unknown): CampusProps => {
  const c = data as CampusData;
  return {
    cards: c.cards.map((card: CampusCard): CampusProps['cards'][number] =>
      'kv' in card && card.kv
        ? { title: card.title, kv: card.kv.map((g) => ({ label: g.label, pairs: g.pairs })) }
        : {
            title: card.title,
            rows: ('rows' in card ? card.rows : []).map((r) => ({
              title: r.title, sub: r.sub, badge: r.badge, meta: r.meta, extras: r.extras,
            })),
          },
    ),
  };
};

const academicsProps = (data: unknown): AcademicsProps => {
  const a = data as AcademicsData;
  const cgpa = a.cgpa;
  const courses = a.courses;
  return {
    cgpa: !cgpa
      ? null
      : {
          value: cgpa.value,
          credits_disp: cgpa.credits_disp,
          sems: cgpa.sems.map((s) => ({
            sem: s.sem, label: s.label, credits: s.credits, sgpa: s.sgpa,
            // provisional/revaluation are omitted on purpose: the island's
            // schema does not carry them (see panels/academics/contract.ts).
            rows: s.rows.map((r) => ({
              code: r.code, title: r.title, grade: r.grade, completed: r.completed,
              tint_o: r.tint_o, tint_f: r.tint_f,
            })),
          })),
        },
    courses: !courses
      ? null
      : {
          overall: { acq: courses.overall.acq, req: courses.overall.req },
          pending: courses.pending,
          total: courses.total,
          cats: courses.cats.map((c) => ({
            name: c.name, req: c.req, acq: c.acq, pct: c.pct, done: Boolean(c.done),
            fill: c.fill, n: c.n, n_pending: c.n_pending,
            pending: c.pending.map((r) => ({
              code: r.code, title: r.title, grade: r.grade, completed: r.completed,
              tint_o: r.tint_o, tint_f: r.tint_f, month: r.month, attempts: r.attempts,
            })),
            completed: c.completed.map((r) => ({
              code: r.code, title: r.title, grade: r.grade, completed: r.completed,
              tint_o: r.tint_o, tint_f: r.tint_f, month: r.month, attempts: r.attempts,
            })),
          })),
        },
  };
};

/**
 * Endpoint -> island props for the four panels whose handler already returns
 * the island's own payload (panels.py calls marks_island.props(),
 * timetable_island.props(), tools_island.props() server-side, and the
 * attendance handler emits the same course rows the island reads). The
 * projection is therefore identity — reshaping here would only create a second
 * definition of the wire format that could drift from the server's.
 *
 * `propsFromCache` still runs the island's zod schema over the result, so a
 * server-side shape change is a cache MISS rather than a broken paint.
 */
/**
 * Project a cached `/api/<panel>` payload onto the island's own schema.
 *
 * The two are NOT the same object. `/api/attendance` returns the whole panel
 * slice (courses + monthly + hourwise + timetable + period + has_budgets); the
 * attendance island only wants `{courses}`. Validating the api payload against
 * the island schema therefore fails on every offline load — which read as
 * "cache miss" and painted nothing.
 *
 * `pick` names the island's top-level keys, so the projection says out loud
 * which part of the api payload the island consumes. If a key is missing it is
 * a real shape drift and we throw, rather than passing a partial object through.
 */
const asIslandProps =
  <T>(schema: { safeParse: (v: unknown) => { success: boolean; data?: T } }, pick?: readonly string[]) =>
  (data: unknown): T => {
    let candidate: unknown = data;
    if (pick) {
      const src = (data ?? {}) as Record<string, unknown>;
      const missing = pick.filter((k) => !(k in src));
      if (missing.length) throw new TypeError(`cached payload is missing ${missing.join(', ')}`);
      // Keep the KEY: the island schema is an object (`{courses: [...]}`), so
      // picking must yield `{courses: src.courses}`, not the bare array.
      candidate = Object.fromEntries(pick.map((k) => [k, src[k]]));
    }
    const parsed = schema.safeParse(candidate);
    if (!parsed.success) throw new TypeError('cache payload is not island-shaped');
    return parsed.data as T;
  };

const PROJECT = {
  fees: feesProps,
  campus: campusProps,
  academics: academicsProps,
  attendance: asIslandProps(schemas.attendance),
  marks: asIslandProps(schemas.marks),
  timetable: asIslandProps(schemas.timetable),
} satisfies Partial<Record<Panel, Project>>;

/** Island names that HAVE a projection, and therefore a cache path.
 *
 *  Absent, each for a different reason:
 *   - `sync-age` renders a clock from props, no store.
 *   - `settings` has no endpoint at all — identity data is server-rendered only,
 *     so it can never be cached offline.
 *   - `dashboard` composes several panels rather than one `/api` feed.
 *   - `tools` has no Dexie store in `RECORD_SCHEMA`, so there is nowhere to
 *     write what /api/tools/island returns. Adding the store is a schema
 *     migration, not a projection — that is why the endpoint exists but this
 *     map does not list it. */
export const hasIslandProjection = (name: string): name is keyof typeof PROJECT =>
  Object.hasOwn(PROJECT, name);

/**
 * Island-ready props from a cached payload, or `undefined` when this panel has
 * no island / no projection / the projection does not satisfy the island's own
 * schema. Never throws: a shape that drifted is a cache MISS, not a crash.
 */
export function propsFromCache(panel: Panel, data: unknown): Record<string, unknown> | undefined {
  if (!hasIslandProjection(panel)) return undefined;
  const project = PROJECT[panel];
  const schema = (schemas as Record<string, { safeParse: (v: unknown) => { success: boolean } }>)[
    panel
  ];
  if (!schema) return undefined;
  try {
    const props = project(data);
    return schema.safeParse(props).success ? (props as Record<string, unknown>) : undefined;
  } catch (e) {
    // Was a silent `return undefined`, which made an offline cache miss
    // indistinguishable from "this panel has no projection". A cache that reads
    // but cannot project is a BUG, not a normal miss — say so.
    console.warn(`[props] projection failed for ${panel}`, e instanceof Error ? e.message : e);
    return undefined;
  }
}
