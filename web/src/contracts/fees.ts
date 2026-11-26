import { z } from 'zod';
import { makeParser } from './envelope';

// ── /api/fees — vm["fees"], the whole view model (`_fees_view`). Money and
// dates are PRE-FORMATTED strings on every row (`"2,00,000"`, `"23 Nov 2026"`);
// `due` stays a number and `days_left` stays a number-or-null because the page
// compares them.

/** '' | 'text-warning' | 'text-error' — fees.py:_level, never recomputed. */
const Level = z.enum(['', 'text-warning', 'text-error']);

export const FeeDue = z.object({
  head: z.string(),
  cycle: z.string(),
  amt: z.string(),
  level: Level,
  deadline: z.string(),
  late_on: z.string(),
  late_extra: z.string(),
  days_left: z.number().nullable(),
  overdue: z.boolean(),
  penalised: z.boolean(),
  min: z.string(),
}).strict();

export const FeeLedgerRow = z.object({
  amt: z.string(),
  date: z.string(),
  full: z.string(),
  head: z.string(),
  vno: z.string(),
}).strict();

export const FeeYear = z.object({
  rows: z.array(z.object({ amt: z.string(), date: z.string(), head: z.string() }).strict()),
  total: z.string(),
  year: z.string(),
}).strict();

export const FeesData = z.object({
  due: z.number(),
  due_disp: z.string(),
  due_sum: z.string(),
  dues: z.array(FeeDue),
  ledger: z.array(FeeLedgerRow),
  level: Level,
  multi_year: z.boolean(),
  paid_total: z.string(),
  year_label: z.string(),
  years: z.array(FeeYear),
}).strict();

export type FeeDue = z.infer<typeof FeeDue>;
export type FeeLedgerRow = z.infer<typeof FeeLedgerRow>;
export type FeeYear = z.infer<typeof FeeYear>;
export type FeesData = z.infer<typeof FeesData>;

export const parseFeesResponse = makeParser(FeesData);
