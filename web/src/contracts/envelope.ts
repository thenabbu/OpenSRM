import { z } from 'zod';

// ── The panel API envelope (app/blueprints/panels.py) ────────────────────
// Success `{ok:true, data:{…}}` · failure `{ok:false, error:"…"}` + an HTTP
// status. Both branches are closed objects: an unknown top-level key is a
// contract change and fails, never rides through.

export const ErrorEnvelope = z.object({
  ok: z.literal(false),
  error: z.string(),
}).strict();

export type ErrorEnvelope = z.infer<typeof ErrorEnvelope>;

/** Why a parse failed — never a throw. `reason` is the joined zod path+message. */
export type ParseFailure = { ok: false; reason: string };

export type ParseResult<T> = { ok: true; data: T } | ParseFailure;

/** `{ok:false, error}` from the server → its user-facing message. */
const failureOf = (json: unknown): string | undefined => {
  const envelope = ErrorEnvelope.safeParse(json);
  return envelope.success ? envelope.data.error : undefined;
};

const format = (err: z.ZodError): string =>
  err.issues.map((i) => `${i.path.join('.') || '(root)'}: ${i.message}`).join('; ');

/**
 * The one parser shape, shared by all four panels: success branch → the
 * domain schema, failure branch → `{ok:false, reason}`. Anything else
 * (wrong envelope, wrong type, missing key, extra key) is a failure too —
 * an unparseable response is never a success with holes in it.
 *
 * Typed against a plain `{ ok: true; data: T }` rather than zod's inferred
 * object: zod v4 loses the member types when the schema is passed through a
 * generic, and the one cast below is the cheapest honest fix.
 */
export function makeParser<S extends z.ZodType>(schema: S) {
  const ok = z.object({ ok: z.literal(true), data: schema }).strict();
  return (json: unknown): ParseResult<z.output<S>> => {
    const error = failureOf(json);
    if (error !== undefined) return { ok: false, reason: error };
    const parsed = ok.safeParse(json);
    if (!parsed.success) return { ok: false, reason: format(parsed.error) };
    return { ok: true, data: (parsed.data as { data: z.output<S> }).data };
  };
}
