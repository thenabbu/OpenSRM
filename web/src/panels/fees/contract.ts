import { z } from 'zod';

// The fees tab's rows, as app/views/fees_island.py:props() emits them.
//
// Every amount is already a DISPLAY STRING (fees.py `_money`: '200,000.00').
// The island never reparses money — '₹' + the string is the whole rule, so the
// client cannot round 3150.00 into 3150 and disagree with the no-JS paint.

/** One outstanding charge (fees.py:_exam_dues — already sorted by due date). */
export const feeDue = z.object({
  amt: z.string(),
  due: z.string(),
  penalty: z.string(),
  penalised: z.boolean(),
});

/** One paid row inside a year group (fees.py:_fees_view `years`). */
export const feeYearRow = z.object({
  head: z.string(),
  amt: z.string(),
  date: z.string(),
});

export const feeYear = z.object({
  year: z.string(),
  rows: z.array(feeYearRow),
  total: z.string(),
});

/** One receipt (fees.py:_fees_view `ledger`, newest voucherdate first). */
export const feeReceipt = z.object({
  date: z.string(),
  amt: z.string(),
  vno: z.string(),
  head: z.string(),
  full: z.string(),
});

export const feesProps = z.object({
  /** '' => the hero is absent (zero dues). Server decides, island obeys. */
  due_disp: z.string(),
  /** '' | 'text-warning' | 'text-error' — fees.py's threshold, never recomputed. */
  level: z.enum(['', 'text-warning', 'text-error']),
  dues: z.array(feeDue),
  years: z.array(feeYear),
  /** '' when there are no fee rows (fees.py). */
  paid_total: z.string(),
  ledger: z.array(feeReceipt),
});

export type FeeDue = z.infer<typeof feeDue>;
export type FeeYear = z.infer<typeof feeYear>;
export type FeeReceipt = z.infer<typeof feeReceipt>;
export type FeesProps = z.infer<typeof feesProps>;
