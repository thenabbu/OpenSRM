import { z } from 'zod';
import { makeParser } from './envelope';

// ── /api/fees — vm["fees"]. Money is PRE-FORMATTED strings on every row
// (`"3,150.00"`); only `due` is a number, because the page compares it.

export const FeeDue = z.object({
  amt: z.string(),
  due: z.string(),
  penalised: z.boolean(),
  penalty: z.string(),
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
  dues: z.array(FeeDue),
  ledger: z.array(FeeLedgerRow),
  level: z.string(),
  paid_total: z.string(),
  years: z.array(FeeYear),
}).strict();

export type FeeDue = z.infer<typeof FeeDue>;
export type FeeLedgerRow = z.infer<typeof FeeLedgerRow>;
export type FeeYear = z.infer<typeof FeeYear>;
export type FeesData = z.infer<typeof FeesData>;

export const parseFeesResponse = makeParser(FeesData);
