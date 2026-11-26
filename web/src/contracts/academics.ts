import { z } from 'zod';
import { makeParser } from './envelope';

// ── /api/academics — {cgpa, courses}. Note the real payload nests the totals
// under `courses.overall` (plus flat pending/total) — the fixture is the
// truth, not the summary that was sketched from it.

export const GradeRow = z.object({
  code: z.string(),
  completed: z.boolean(),
  grade: z.string(),
  tint_f: z.boolean(),
  tint_o: z.boolean(),
  title: z.string(),
}).strict();

/** Provisional/revaluation lists were EMPTY in every captured semester, so the
 *  element shape is unproven — `z.unknown()` is the honest type here rather
 *  than an invented row. Tighten the day a non-empty list shows up. */
export const CgpaSem = z.object({
  sem: z.number().int(),
  label: z.string(),
  credits: z.number().int(),
  sgpa: z.string(),
  provisional: z.array(z.unknown()),
  revaluation: z.array(z.unknown()),
  rows: z.array(GradeRow),
}).strict();

export const Cgpa = z.object({
  value: z.string(),
  credits_disp: z.string(),
  sems: z.array(CgpaSem),
}).strict();

export const CourseEntry = z.object({
  attempts: z.number().int(),
  code: z.string(),
  completed: z.boolean(),
  grade: z.string(),
  month: z.string(),
  tint_f: z.boolean(),
  tint_o: z.boolean(),
  title: z.string(),
}).strict();

export const CourseCategory = z.object({
  name: z.string(),
  acq: z.number().int(),
  req: z.number().int(),
  n: z.number().int(),
  n_pending: z.number().int(),
  pct: z.number(),
  done: z.boolean(),
  fill: z.string(),
  completed: z.array(CourseEntry),
  pending: z.array(CourseEntry),
}).strict();

export const AcademicsData = z.object({
  cgpa: Cgpa,
  courses: z.object({
    overall: z.object({ acq: z.number().int(), req: z.number().int() }).strict(),
    pending: z.number().int(),
    total: z.number().int(),
    cats: z.array(CourseCategory),
  }).strict(),
}).strict();

export type GradeRow = z.infer<typeof GradeRow>;
export type CgpaSem = z.infer<typeof CgpaSem>;
export type Cgpa = z.infer<typeof Cgpa>;
export type CourseEntry = z.infer<typeof CourseEntry>;
export type CourseCategory = z.infer<typeof CourseCategory>;
export type AcademicsData = z.infer<typeof AcademicsData>;

export const parseAcademicsResponse = makeParser(AcademicsData);
