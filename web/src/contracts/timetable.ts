import { z } from 'zod';

// ── /api/timetable (app/routes_sync.py:api_get_timetable) — the CALLER's
// group's grid: `{ok, slots, subjects, group_key}`. Keys of `slots` are
// `"<Day>-<period>"` (data, so a record); group_key is null when the student
// has no group, and then slots/subjects are empty.

export const TimetableCell = z.object({
  code: z.string(),
  name: z.string(),
  location: z.string(),
}).strict();

export const TimetableSubject = z.object({
  code: z.string(),
  name: z.string(),
  credits: z.number().int(),
  custom: z.boolean(),
}).strict();

export const TimetableData = z.object({
  ok: z.literal(true),
  slots: z.record(z.string(), TimetableCell),
  subjects: z.array(TimetableSubject),
  group_key: z.string().nullable(),
}).strict();

export type TimetableCell = z.infer<typeof TimetableCell>;
export type TimetableSubject = z.infer<typeof TimetableSubject>;
export type TimetablePayload = z.infer<typeof TimetableData>;

export const parseTimetableResponse = (json: unknown) => TimetableData.safeParse(json);
