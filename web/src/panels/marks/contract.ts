import { z } from 'zod';

/**
 * Marks panel props — the JSON app/views/marks_island.py builds from the SAME
 * view model the template paints (`_marks_view`, app/views/marks.py:41).
 *
 * Field names are SERVER-named on purpose. There is no `tint` here: the page's
 * only tint is the single weakest subject's `outlier` accent (marks.py:73-78,
 * "one muted accent per screen", DESIGN.md §2.7) — a boolean, not a palette.
 */
const ieRow = z.object({
  role: z.enum(['IE-1', 'IE-2']),
  confirmed: z.boolean(),
  max_disp: z.string(),
  score_disp: z.string(),
});

export const marksProps = z.object({
  subjects: z.array(
    z.object({
      code: z.string(),
      title: z.string(),                    // already .title()'d server-side
      scored_disp: z.string(),
      max_disp: z.string(),
      pct: z.number(),
      outlier: z.boolean(),
      components: z.array(
        z.object({
          name: z.string(),
          date_disp: z.string(),            // '' when the portal had no date
          score_disp: z.string(),
          max_disp: z.string(),
          derived: z.string(),              // 'IE-1' | 'IE-2' | ''
          confirmed: z.enum(['IE-1', 'IE-2', 'none']).nullable(),
          ie: ieRow.nullable(),
        }),
      ),
    }),
  ),
});

export type MarksProps = z.infer<typeof marksProps>;
export type MarksSubject = MarksProps['subjects'][number];
export type MarksComponent = MarksSubject['components'][number];
