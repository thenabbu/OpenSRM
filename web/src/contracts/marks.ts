import { z } from 'zod';

// ── /api/marks (app/app.py:api_marks) — `{ok:true, marks:[…]}`: this endpoint
// predates the panel envelope and uses `marks`, not `data`, so makeParser does
// NOT fit. The stored json is whatever the scrape wrote (tests/_seed.py), so
// numbers may arrive as 0.0 defaults — never null.

export const MarkComponent = z.object({
  name: z.string(),
  entered: z.string(),
  scored: z.number(),
  max: z.number(),
}).strict();

export const MarkSubject = z.object({
  code: z.string(),
  title: z.string(),
  components: z.array(MarkComponent),
  scored_total: z.number(),
  max_total: z.number(),
}).strict();

export const MarksResponse = z.object({ ok: z.literal(true), marks: z.array(MarkSubject) }).strict();

/** The stored payload is the `marks` list itself (that is what the server json
 *  column holds), so the store validates against this array, not the envelope. */
export const MarksData = z.array(MarkSubject);

export type MarkComponent = z.infer<typeof MarkComponent>;
export type MarkSubject = z.infer<typeof MarkSubject>;
export type MarksPayload = z.infer<typeof MarksData>;

/** `{ok:true, marks}` parses; anything else (incl. `{ok:false}`) fails. */
export const parseMarksResponse = (json: unknown) => MarksResponse.safeParse(json);
