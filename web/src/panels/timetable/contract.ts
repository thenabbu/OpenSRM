import { z } from 'zod';

// The timetable grid, as app/views/timetable_island.py:props() emits it.
//
// Row order and day order are decided SERVER-side (Python's _tt_grid +
// DAY_ORDER) and travel on the wire untouched: the island must paint the no-JS
// markup's exact order, so it never sorts, filters or reorders.

export const ttSig = z.object({
  cls: z.enum(['danger', 'warn', 'ok']),
  num: z.number().int().nonnegative(),
});

export type TtSig = z.infer<typeof ttSig>;

/** A rendered class row (timetable.py:441-465). */
export const ttRow = z.object({
  kind: z.literal('class'),
  start: z.string(),
  end: z.string(),
  code: z.string(),
  name: z.string(),
  location: z.string(),
  /** `tt-row--now` — the server already decided "now" at render time. */
  live: z.boolean(),
  /** null => the neutral "no data" tag (timetable.py:461). */
  sig: ttSig.nullable(),
});

/** A dashed break rule BETWEEN two rendered classes (timetable.py:431). */
export const ttBreak = z.object({
  kind: z.literal('break'),
  label: z.string(),
});

export const ttDay = z.object({
  day: z.string(),
  short: z.string(),
  rows: z.array(z.union([ttRow, ttBreak])),
  /** "No classes" fallback row for an empty day (timetable.py:468). */
  empty: z.boolean(),
});

export const timetableProps = z.object({
  days: z.array(ttDay),
  default_day: z.string(),
});

export type TtRow = z.infer<typeof ttRow>;
export type TtBreak = z.infer<typeof ttBreak>;
export type TtDay = z.infer<typeof ttDay>;
export type TimetableProps = z.infer<typeof timetableProps>;
