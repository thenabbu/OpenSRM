import { attendanceProps } from '../panels/attendance/contract';
import { z } from 'zod';
import { makeParser } from './envelope';

// ── /api/attendance — vm courses + monthly + hourwise + timetable + period.
// Nullable fields are the SERVER's own nulls (app/views/attendance.py):
//   pct_disp/fill/margin are null only when max_hours is 0 (nothing held),
//   skip_now vs attend_now are mutually exclusive, and `stop` is
//   `date.isoformat()` — or null when the course has no exam date.

export const AttendanceCourse = z.object({
  code: z.string(),
  description: z.string(),
  max_hours: z.number().int(),
  attended: z.number().int(),
  pct: z.number(),
  pct_disp: z.string().nullable(),
  fill: z.number().nullable(),
  t75: z.number().int(),
  skip_now: z.number().int().nullable(),
  attend_now: z.number().int().nullable(),
  tint: z.string(),
  margin: z.number().int().nullable(),
  bunk_line: z.string(),
  stop: z.string().nullable(),
  days_left_90: z.number().int().nullable(),
  days_left_exam: z.number().int().nullable(),
  m90: z.number().nullable(),
  m_end: z.number().nullable(),
  w: z.number().int(),
}).strict();

export const AttendanceMonthly = z.object({
  abs_rows: z.array(z.object({ date: z.string(), hours: z.string() }).strict()),
  absent: z.string(),
  bar: z.string().nullable(),
  label: z.string(),
  ml: z.string(),
  month: z.string(),
  od_absent: z.string(),
  od_present: z.string(),
  pct: z.number(),
  pct_disp: z.string(),
  present: z.string(),
}).strict();

export const HourCell = z.object({
  code: z.string().nullable(),
  n: z.number().int(),
  state: z.enum(['P', 'A', 'OD']).nullable(),
  subject: z.string().nullable(),
  title: z.string(),
}).strict();

export const HourwiseMonth = z.object({
  a: z.number().int(),
  od: z.number().int(),
  p: z.number().int(),
  pct: z.number().nullable(),
  label: z.string(),
  side: z.string(),
  days: z.array(
    z.object({
      date: z.string(),
      dow: z.string(),
      full: z.string(),
      cells: z.array(HourCell),
    }).strict(),
  ),
}).strict();

export const Hourwise = z.object({
  full: z.string(),
  ts: z.number().int(),
  hours: z.array(z.number().int()),
  months: z.array(HourwiseMonth),
}).strict();

/** day → period → slot. `attendance` is a COURSE VIEW (the same shape as a
 *  course row) or null when the slot has no matching course. */
export const TimetableSlot = z.object({
  code: z.string(),
  name: z.string(),
  location: z.string(),
  attendance: AttendanceCourse.nullable(),
}).strict();

/** day/period keys are DATA (they change with the student's timetable), so this
 *  is the ONE dynamic-key container — the leaf slot is closed, the keys are not. */
export const Timetable = z.record(z.string(), z.record(z.string(), TimetableSlot));

export const AttendanceData = z.object({
  courses: z.array(AttendanceCourse),
  monthly: z.array(AttendanceMonthly),
  hourwise: Hourwise.nullable(),
  timetable: Timetable,
  period: z.object({ from: z.string(), to: z.string() }).strict().nullable(),
  has_budgets: z.boolean(),
}).strict();

export type AttendanceCourse = z.infer<typeof AttendanceCourse>;
export type AttendanceMonthly = z.infer<typeof AttendanceMonthly>;
export type HourCell = z.infer<typeof HourCell>;
export type HourwiseMonth = z.infer<typeof HourwiseMonth>;
export type Hourwise = z.infer<typeof Hourwise>;
export type TimetableSlot = z.infer<typeof TimetableSlot>;
export type Timetable = z.infer<typeof Timetable>;
export type AttendanceData = z.infer<typeof AttendanceData>;

export const parseAttendanceResponse = makeParser(AttendanceData);

/** The attendance ISLAND's payload — /api/attendance/island.
 *
 *  Distinct from AttendanceData on purpose: that is the /api/attendance panel
 *  slice with its `.strict()` schema. The island needs only the courses, each
 *  carrying the derived label/nudge/pole the island paints. */
export const parseAttendanceIslandResponse = makeParser(attendanceProps);
