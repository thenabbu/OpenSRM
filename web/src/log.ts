/**
 * W4.2 — the one place the client talks to the console.
 *
 * WHY a module instead of `console.warn` at the call site: a warning that only
 * ever appears in a devtools pane is a developer aid, and on a student's phone
 * it is noise nobody reads. Prod is therefore SILENT, and `LOG_ENABLED` below is
 * the single switch that decides — Vite inlines `import.meta.env.DEV` at build
 * time, so a production bundle carries no console call at all.
 *
 * The scope prefix STAYS (`[outbox]`, `[props]`, …): that prefix is how a bug
 * report gets grepped back to a module. Diagnostics that are not FOR the console
 * stay at their call sites — `diag.warn` still pushes to `window.__osrmDiag`,
 * and `data/failure.ts` still rate-limits one line per island+reason. This owns
 * the developer-facing half only.
 *
 * Pinned by tests/e2e/route_paint.py: zero console output of any type on all
 * nine routes, in the prod build (leg 2 of scripts/offline_proof.sh).
 */
export const LOG_ENABLED: boolean = import.meta.env.DEV;

/** `warn('outbox', 'could not read the queue')` → `[outbox] could not read the queue` */
export function warn(scope: string, msg: string, extra?: unknown): void {
  if (!LOG_ENABLED) return;
  if (extra === undefined) console.warn(`[${scope}] ${msg}`);
  else console.warn(`[${scope}] ${msg}`, extra);
}
