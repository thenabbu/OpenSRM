import { z } from 'zod';

/**
 * Attendance panel props — the JSON the server already computes in
 * app/views/attendance.py `_course_view` (the meter-row half only) and ships in
 * `<script type="application/json" id="island-attendance">`.
 *
 * Every field is SERVER-named on purpose: `tint` is red|warn|gray (the server's
 * own vocabulary, attendance.py:300), never amber/green. A field the server sets
 * to None (no classes held → pct_disp None) is never shipped: the template skips
 * those rows entirely (`{% if c.pct_disp is not none %}`), so the island does too.
 */
export const attendanceProps = z.object({
  courses: z.array(
    z.object({
      code: z.string(),
      description: z.string(),
      attended: z.number().int().nonnegative(),
      max_hours: z.number().int().nonnegative(),
      pct_disp: z.string(),                    // exact truncated "dd.d"
      fill: z.number().min(0).max(100),        // attended/max_hours * 100
      t75: z.number().int().nonnegative(),     // ceil(75% of max_hours)
      skip_now: z.number().int(),              // null on the server when NaC; 0 is a real value
      attend_now: z.number().int().nullable(),
      tint: z.enum(['red', 'warn', 'gray']),
      margin: z.number().int(),                // +skip / 0 / -attend
      label: z.string(),                       // the role="img" aria-label, built server-side
      nudge: z.string(),                       // '', nudL, nudR, nud2L, nud2R
      pole: z.boolean(),
    }),
  ),
});

export type AttendanceProps = z.infer<typeof attendanceProps>;
export type AttendanceCourse = AttendanceProps['courses'][number];
