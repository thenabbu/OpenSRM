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

/** `settings` has no /api endpoint (its props come from merge_personal, not a
 *  panel_data slice) so there is nothing to restore offline yet. */
const PROJECT = {
  fees: feesProps,
  campus: campusProps,
  academics: academicsProps,
} satisfies Partial<Record<Panel, Project>>;

/** Island names that HAVE a projection. `sync-age`/`settings` are absent (no
 *  store behind them), and so are attendance/marks/timetable — their islands do
 *  not exist yet. Narrowing through this is what lets main.ts pass an island
 *  name where `loadPanel` wants a `Panel`, instead of casting. */
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
  } catch {
    return undefined;
  }
}
