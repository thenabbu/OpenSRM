import { z } from 'zod';

/**
 * Dashboard widget props — `<script type="application/json" id="island-dashboard">`,
 * built by app/views/dashboard_island.py from the SAME dicts the partials read.
 *
 * Every self-hiding widget keeps its server "nothing" as a null/empty value, and
 * the panel renders nothing for it — exactly the partial's `{% if %}` guard.
 */
const classRow = z.object({
  start: z.string(),
  end: z.string(),
  code: z.string(),
  name: z.string(),
});

const markRow = z.object({
  code: z.string(),
  name: z.string(),
  date: z.string(),
});

const examRow = z.object({
  code: z.string(),
  name_disp: z.string(),
  short: z.string(),
  day: z.string(),
  dow: z.string(),
  session_disp: z.string(),
  slot: z.string().nullish(),
  hall: z.string().nullish(),
  seat: z.string().nullish(),
});

/**
 * profile.html — the identity box, which the partial renders unconditionally
 * (no `{% if %}`), so it is required here too.
 *
 * `avatar` is the `blobatar` Jinja filter's own SVG for this netid, serialised
 * by the server. One generator, two renderings: the island paints the identical
 * markup the partial did, so `.blobatar-gaze` / `.mo-root` (what gaze.js and the
 * low-tier CSS key on) exist whichever path painted the box.
 */
const profileProps = z.object({
  netid: z.string(),
  name: z.string(),
  email: z.string(),
  reg_no: z.string(),
  avatar: z.string(),
});

export const dashboardProps = z.object({
  profile: profileProps,
  ticker: z
    .object({
      state: z.enum(['now', 'up', 'done']),
      prev: classRow.nullable(),
      now: classRow.nullable(),
      next: classRow.nullable(),
    })
    .nullable(),
  week: z.object({
    days: z.number(),
    hours: z.number(),
    dates: z.array(z.object({ date: z.string(), hours: z.number() })),
    marks: z.array(markRow),
    today_absent: z.boolean(),
  }),
  /** [name, signed value, risk] — teachers.py `{% for name, val, risk in budgets %}`. */
  budgets: z.array(z.tuple([z.string(), z.string(), z.number().int()])),
  marks: z.array(
    z.object({
      code: z.string(),
      scored: z.string(),
      max: z.string(),
      stale: z.boolean(),
      recent: z.boolean(),
      entered: z.string(),
    }),
  ),
  exams: z
    .object({
      rows: z.array(examRow),
      label: z.string(),
      days_until: z.number().int(),
      source: z.string(),
    })
    .nullable(),
  teachers: z.array(
    z.object({
      code: z.string(),
      name: z.string(),
      staff: z.array(z.object({ name: z.string(), mode: z.string(), ini: z.string() })),
    }),
  ),
  fb_plan: z.boolean(),
});

export type DashboardProps = z.infer<typeof dashboardProps>;
