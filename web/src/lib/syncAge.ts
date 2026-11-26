/** Client mirror of app/views/sync_age.py's caption() — KEEP IN STEP.
 *  The server renders the caption for first paint; this re-ages it after
 *  hydration (dash.js's 60s setInterval is retired by this island). */
export const FRESH_S = 300;

export function ageCaption(ts: number, nowS: number): string {
  const diff = ts ? Math.floor(nowS) - ts : 0;
  if (!ts) return 'Never synced';
  if (diff < FRESH_S) return '';
  if (diff < 3600) return `(${Math.floor(diff / 60)}m ago)`;
  if (diff < 86400) return `(${Math.floor(diff / 3600)}h ago)`;
  return `(${Math.floor(diff / 86400)}d ago)`;
}
