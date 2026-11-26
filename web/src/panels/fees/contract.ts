import { z } from 'zod';

// The fees tab's rows, as app/views/fees_island.py:props() emits them.
//
// Every amount is already a DISPLAY STRING (fees.py `_money`: Indian grouping,
// '2,00,000'), and every date is already formatted ('23 Nov 2026'). The island
// never reparses money or dates — '₹' + the string is the whole rule, so the
// client cannot round 3,150 into 3150 or re-format a date and disagree with
// the no-JS paint.

/** One outstanding charge (fees.py:_exam_dues), soonest deadline first. */
export const feeDue = z.object({
  /** 'Exam Fees' — the portal's own feetype, sentence-cased server-side. */
  head: z.string(),
  /** 'November-2026' — the portal's academicyear, '' when absent. */
  cycle: z.string(),
  amt: z.string(),
  /** '' | 'text-warning' | 'text-error' — fees.py's threshold, never recomputed. */
  level: z.enum(['', 'text-warning', 'text-error']),
  /** Last date at the cheap price, e.g. '23 Nov 2026'. '' when SRM gave none. */
  deadline: z.string(),
  /** First date the late fee applies, '' when it equals the deadline. */
  late_on: z.string(),
  /** The penalty DELTA in rupees ('1,000'), never the total-with-penalty. */
  late_extra: z.string(),
  /** Days from the server's IST today to `deadline`; null when there is none. */
  days_left: z.number().nullable(),
  overdue: z.boolean(),
  penalised: z.boolean(),
  /** Part-payment floor, '' when part payment is not accepted. */
  min: z.string(),
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
  /** '' => nothing owed. Server decides, island obeys. */
  due_disp: z.string(),
  /** The sum line, '' unless 2+ charges (one charge already states itself). */
  due_sum: z.string(),
  /** '' | 'text-warning' | 'text-error' for the sum line. */
  level: z.enum(['', 'text-warning', 'text-error']),
  dues: z.array(feeDue),
  years: z.array(feeYear),
  /** 2+ year groups -> each keeps its own header row. */
  multi_year: z.boolean(),
  /** The single year, shown as a label on the heading; '' when multi_year. */
  year_label: z.string(),
  /** '' when there are no fee rows. */
  paid_total: z.string(),
  ledger: z.array(feeReceipt),
});

export type FeeDue = z.infer<typeof feeDue>;
export type FeeYear = z.infer<typeof feeYear>;
export type FeeReceipt = z.infer<typeof feeReceipt>;
export type FeesProps = z.infer<typeof feesProps>;
