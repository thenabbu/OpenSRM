// ── The ONE error surface (W5.2a) ────────────────────────────────────────
// Ported out of `dash.js:1-8`. The node is server-rendered on every route
// (#error-toast, partials/theme.html), so this module owns behaviour only — no
// markup, no mount step.
//
// Why it moved: timetable.js wrote its save errors through a function that only
// existed while dash.js happened to be on the page. A missing global is a
// silent no-op, so "Save failed" could vanish with nothing in the console. The
// caller could not tell "the toast was written" from "the helper was never
// defined", and deleting dash.js (W5.4) would have made that permanent.
const TOAST_ID = 'error-toast';
const HIDE_AFTER_MS = 5000;

/** Write `msg` into the page's toast and hide it again after 5 s. */
export function showError(msg: string): void {
  const t = document.getElementById(TOAST_ID);
  if (!t) return;                 // a page without a toast (login): nothing to say it with
  t.textContent = msg;
  t.classList.remove('hidden');
  window.setTimeout(() => t.classList.add('hidden'), HIDE_AFTER_MS);
}
