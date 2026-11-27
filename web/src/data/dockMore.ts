// ── Dock "More" sheet ───────────────────────────────────────────────────────
//
// The phone dock has five slots; the middle one toggles a sheet that grows up
// over the page with the destinations that do not fit (fees, academics, the
// campus surfaces, settings). The sheet is server-rendered in base.html, so
// this module owns exactly three things: the open/closed state, the ARIA
// wiring, and closing it when the person does something that means "nevermind".
//
// Why this is JS at all: `aria-expanded` on the trigger, the `inert` on the
// closed sheet (so its rows leave the tab order), and the escape/tap-away/
// route-change closes. The height animation itself is pure CSS (grid-template-
// rows 0fr -> 1fr in tailwind.css) — nothing here measures a height.
//
// Why a marker: dash.js is the PREACT_ISLANDS=0 fallback and must stand down
// when the bundle is present, the same seam __osrmAttView uses.

export const SHEET_ID = 'dock-more-sheet';
export const TRIGGER_ID = 'dock-more-btn';
/** Set once bound; dash.js checks it before binding its own copy. */
export const MARKER = '__osrmDockMore';

/** Open state is an attribute, not a class: `[data-open]` is what the CSS
 *  transition keys on, and a class named `open` would collide with the
 *  includes-tap-away handler that matches `details[open]`. */
export function setOpen(sheet: HTMLElement, trigger: HTMLElement, open: boolean): void {
  if (open) sheet.setAttribute('data-open', '');
  else sheet.removeAttribute('data-open');
  trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
  // inert, not hidden: `hidden` would be display:none and cancel the
  // transition. inert removes the rows from the a11y tree and the tab order,
  // which is what closed actually means.
  const inner = sheet.firstElementChild as HTMLElement | null;
  if (inner) inner.toggleAttribute('inert', !open);
}

export function isOpen(sheet: HTMLElement): boolean {
  return sheet.hasAttribute('data-open');
}

/**
 * Bind the trigger. Returns false when this document has no dock (desktop,
 * or a route rendered without base.html's chrome) so callers can skip.
 *
 * Idempotent per document: a second call re-uses the existing listeners
 * rather than stacking a second toggle, which would open and immediately
 * close the sheet on one tap.
 */
export function bindDockMore(doc: Document = document): boolean {
  const win = doc.defaultView;
  const sheet = doc.getElementById(SHEET_ID);
  const trigger = doc.getElementById(TRIGGER_ID);
  if (!sheet || !trigger) return false;
  if ((win as unknown as Record<string, unknown> | null)?.[MARKER]) return true;

  // Start closed, whatever the markup said: the sheet must never be open on
  // a fresh load (a soft-nav swap keeps it, so state is per-document).
  setOpen(sheet, trigger, false);

  const toggle = (): void => setOpen(sheet, trigger, !isOpen(sheet));
  const close = (): void => setOpen(sheet, trigger, false);

  trigger.addEventListener('click', (e) => {
    e.preventDefault();
    toggle();
  });

  // Escape closes and returns focus to the trigger — a keyboard user who
  // opened the sheet cannot otherwise get out without tabbing past every row.
  doc.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !isOpen(sheet)) return;
    close();
    trigger.focus();
  });

  // Tap-away: anything outside the sheet AND outside the trigger closes it.
  // The trigger is excluded so its own click is not counted as "away" (it
  // would toggle open then immediately closed).
  doc.addEventListener('click', (e) => {
    if (!isOpen(sheet)) return;
    const t = e.target as Node | null;
    if (!t || sheet.contains(t) || trigger.contains(t)) return;
    close();
  });

  // A row tap navigates, so close on the way out — otherwise the sheet is
  // still open behind the next soft-swapped route, with stale aria state.
  sheet.addEventListener('click', (e) => {
    const row = (e.target as Element | null)?.closest?.('a');
    if (row) close();
  });

  // The dock survives a soft navigation, but the page under it changes and a
  // sheet left open would cover the new route's first paint.
  doc.addEventListener('osrm:route-swapped', close);

  (win as unknown as Record<string, unknown>)[MARKER] = bindDockMore;
  return true;
}
