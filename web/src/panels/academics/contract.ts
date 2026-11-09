import { z } from 'zod';

// The academics tab's rows, as app/views/academics_island.py:props() emits them.
//
// Every number that has a display form arrives ALREADY FORMATTED
// (academics.py owns CGPA rounding, the 'x/y credits earned' string and each
// meter's `fill`): the island prints strings, it never re-derives a figure.
//
// `provisional` / `revaluation` are deliberately NOT in the payload. The view
// model hardcodes them to [] (academics.py:_semesters_view), so shipping
// z.unknown() rows would be shipping a shape nobody has ever seen. If a
// non-empty list ever appears, add the field here and in academics_island.py
// together — the template's fallback keeps painting it until then.

export const acadRow = z.object({
  code: z.string(),
  title: z.string(),
  grade: z.string(),
  completed: z.boolean(),
  tint_o: z.boolean(),
  tint_f: z.boolean(),
});

/** A course row also carries the completion month and attempt count. */
export const courseRow = acadRow.extend({
  month: z.string(),
  attempts: z.number().int(),
});

export const sem = z.object({
  sem: z.number().int(),
  label: z.string(),
  credits: z.number().int(),
  sgpa: z.string(),
  rows: z.array(acadRow),
});

export const cat = z.object({
  name: z.string(),
  req: z.number().int(),
  acq: z.number().int(),
  pct: z.number(),
  done: z.boolean(),
  fill: z.string(),
  n: z.number().int(),
  n_pending: z.number().int(),
  pending: z.array(courseRow),
  completed: z.array(courseRow),
});

export const academicsProps = z.object({
  cgpa: z
    .object({
      value: z.string(),
      credits_disp: z.string(),
      sems: z.array(sem),
    })
    .nullable(),
  courses: z
    .object({
      overall: z.object({ acq: z.number().int(), req: z.number().int() }),
      pending: z.number().int(),
      total: z.number().int(),
      cats: z.array(cat),
    })
    .nullable(),
});

export type AcadRow = z.infer<typeof acadRow>;
export type CourseRow = z.infer<typeof courseRow>;
export type Sem = z.infer<typeof sem>;
export type Cat = z.infer<typeof cat>;
export type AcademicsProps = z.infer<typeof academicsProps>;
