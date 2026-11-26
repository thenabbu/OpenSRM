// ── Click-to-copy (W5.2b) ────────────────────────────────────────────────
// Ported out of `dash.js:158-216`. Values only — keys and labels never carry
// `data-copy`.
//
// This module owns the ATTRIBUTE CONTRACT, not just the behaviour. The island
// components already emit `data-copy` (DashboardPanel.tsx:61, FeesPanel.tsx:90,
// SettingsPanel.tsx:43/89/96) while the handler that reads it lived in dash.js,
// so an island edit could add a target that nothing ever copied and no test
// would notice. Everything a copy target needs — the value attribute, the
// a11y stamps, the handler, the re-arm — is defined here so the next island
// change has one place to look.
//
// The re-arm is not optional. A repaint replaces or rewrites the nodes it
// touches (SettingsPanel repaints the whole details block), so stamps applied
// once at load land on nodes that are then thrown away: measured as 24 targets,
// 0 wired. `bindCopyTargets` is called from main.ts after every mount and
// listens on `osrm:island-mounted` for every later repaint. It is idempotent
// per node, so re-arming costs nothing when nothing changed.

import { showError } from './errorToast';

/** Stamp on a node whose affordance attributes are already applied. */
const READY = 'data-copy-ready';
const FLASH_MS = 1200;
const TOAST_COPY_FAILED = 'Copy failed';
const TOAST_NO_CLIPBOARD = 'Clipboard unavailable';

/**
 * The affordance attributes, in one place. `setupCopyTargets` applies them to
 * nodes that arrive from the server or from an island that did not declare
 * them, and SettingsPanel spreads the same object in its JSX so a repainted
 * node carries them from its first frame instead of losing them until the
 * re-arm runs. Two spellings of the contract is how a copy target silently
 * becomes mouse-only, so there is exactly one.
 */
export const COPY_ATTRS = { title: 'Click to copy', tabindex: 0, role: 'button' } as const;

/** Every copy target on the page — the islands and the server both the emit it. */
export const COPY_SELECTOR = '[data-copy]';

/** The clipboard write, or `undefined` when the page has no Clipboard API
 *  (an insecure origin, or an old browser). Callers tell the two apart so a
 *  missing API says so instead of looking like a silent failure. */
const clipboard = (): ((text: string) => Promise<void>) | undefined => {
  const api = typeof navigator === 'undefined' ? undefined : navigator.clipboard;
  if (!api || typeof api.writeText !== 'function') return undefined;
  return (text: string) => api.writeText(text);
};

/**
 * Apply the a11y/cursor affordance to every copy target under `root`.
 *
 * A copy target is a `div`/`span`, so without these three attributes it is
 * mouse-only and a keyboard or screen-reader user cannot use it at all:
 *   * `role=button`  — announces it as actionable
 *   * `tabindex=0`   — makes it reachable with Tab
 *   * `title`        — names the affordance on hover, and for some AT
 * `cursor-copy` is the mouse equivalent. Idempotent per node: a re-arm after a
 * repaint leaves the nodes it already stamped alone.
 */
export function setupCopyTargets(root: ParentNode = document): void {
  root.querySelectorAll<HTMLElement>(COPY_SELECTOR).forEach((el) => {
    if (el.hasAttribute(READY)) return;
    el.setAttribute(READY, '1');
    if (!el.title) el.title = COPY_ATTRS.title;
    el.classList.add('cursor-copy');
    el.setAttribute('tabindex', String(COPY_ATTRS.tabindex));
    el.setAttribute('role', COPY_ATTRS.role);
  });
}

/**
 * The value a target copies: the explicit `data-copy` attribute, else the
 * element's own text. Islands pass the value explicitly because a repaint can
 * change the visible text while the value stays the same.
 *
 * `|| ` not `??`: an empty `data-copy=""` arrives as `''`, and `'' ?? text`
 * would copy nothing. The old dash.js used `||` for exactly this reason.
 */
export function copyValue(el: HTMLElement): string {
  return el.dataset.copy || (el.textContent ?? '').trim();
}

/** Briefly show "Copied!" in the target, then put its own text back. */
function flash(el: HTMLElement): void {
  const state = el as HTMLElement & { _copyTimer?: number };
  if (el.dataset.origText === undefined) el.dataset.origText = el.textContent ?? '';
  el.textContent = 'Copied!';
  el.classList.add('text-success');
  window.clearTimeout(state._copyTimer);
  state._copyTimer = window.setTimeout(() => {
    if (el.dataset.origText !== undefined) el.textContent = el.dataset.origText;
    el.classList.remove('text-success');
  }, FLASH_MS);
}

/** Copy a target's value, flashing only when the clipboard accepted it. */
export function copyTarget(el: HTMLElement): void {
  const write = clipboard();
  if (!write) return;                     // nothing to promise: no flash, no toast
  write(copyValue(el))
    .then(() => flash(el))
    // A refused write (permission denied, document not focused) is not a
    // success, so the target must not claim one.
    .catch(() => {});
}

/** `#copyEmail` (partials/widgets/profile.html): copy `data-email`, relabel the
 *  inner span, and route a failure to the page's toast. */
function copyEmailButton(btn: HTMLElement): void {
  const email = btn.dataset.email ?? '';
  const write = clipboard();
  if (!write) {
    showError(TOAST_NO_CLIPBOARD);
    return;
  }
  write(email)
    .then(() => {
      const span = btn.querySelector('span');
      if (!span) return;
      const old = span.textContent;
      span.textContent = 'Copied!';
      window.setTimeout(() => { span.textContent = old; }, FLASH_MS);
    })
    .catch(() => showError(TOAST_COPY_FAILED));
}

const closest = (target: EventTarget | null, sel: string): HTMLElement | null => {
  const el = target as HTMLElement | null;
  return el && typeof el.closest === 'function' ? el.closest<HTMLElement>(sel) : null;
};

/** The documents already bound. A second bind would double every activation —
 *  two copies per click, two keydown handlers — which is the exact failure the
 *  refresh buttons had to guard against, so it is guarded here per root. */
const bound = new WeakSet<Document>();

/**
 * Wire the copy cluster to the document: one click handler, one keydown
 * handler, and the re-arm after every island mount/repaint. Call once from the
 * bundle entry; repeat calls on the same document are no-ops.
 */
export function bindCopyTargets(root: Document = document): void {
  if (bound.has(root)) return;
  bound.add(root);
  setupCopyTargets(root);
  root.addEventListener('click', (ev) => {
    const el = closest(ev.target, COPY_SELECTOR);
    if (el) {
      copyTarget(el);
      return;
    }
    const btn = closest(ev.target, '#copyEmail');
    if (btn) copyEmailButton(btn);
  });
  // Enter/Space is what `role=button` promises, so it has to work: a stamped
  // target that only answers the mouse is a keyboard trap wearing a button role.
  root.addEventListener('keydown', (ev) => {
    const key = (ev as KeyboardEvent).key;
    if (key !== 'Enter' && key !== ' ') return;
    const el = closest(ev.target, COPY_SELECTOR);
    if (!el) return;
    ev.preventDefault();                  // Space would otherwise scroll the page
    copyTarget(el);
  });
  // An island repaint builds fresh nodes; stamp them as they arrive.
  root.addEventListener('osrm:island-mounted', () => setupCopyTargets(root));
}
