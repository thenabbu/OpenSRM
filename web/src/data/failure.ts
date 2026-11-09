import type { LoadFailure } from './load';

/**
 * P7.3 — typed failures, rendered.
 *
 * `loadPanel` already refuses to return anything untrusted; until now a failed
 * load just left the mount alone, which is right for `invalid` (the server
 * paint is the good copy) and wrong for everything else: a logged-out student
 * got a blank panel with no way forward, and an offline student with no cache
 * got a blank panel that looked like an empty account.
 *
 * So each reason gets exactly one affordance, chosen by the reason, never by a
 * shared error string:
 *
 *   unauthenticated → "sign in again" link to /login   (actionable)
 *   not_found       → "not available for this account" (gated panel, not an error)
 *   network  (offline, no cache) → "no offline copy"    (a state, stated)
 *   http / invalid  → nothing on screen, one log line   (server paint kept)
 *
 * `invalid` in particular paints NOTHING: the server already rendered a correct
 * panel and a banner over good data reads as an error the user caused.
 */

/** Prefix for the element attributes; also the removal selector. */
export const FAILURE_ATTR = 'data-island-failure';

/** One line per (island, reason) for the life of the page. A flapping network
 *  or a server that 500s on every retry must not become a console flood —
 *  the same rule `warnedUnknown`/`warnedProps` already follow in main.ts. */
const warned = new Set<string>();

/** Test-only: a fresh page load starts with no warns. Mirrors __resetWarnOnce. */
export function __resetFailureWarnOnce(): void {
  warned.clear();
}

/**
 * What to say, or `null` for "say nothing". Pure, so the reasons are testable
 * without a DOM — the render below is the only impure part.
 */
export function failureCopy(
  f: LoadFailure,
): { tone: 'error' | 'warn' | 'info'; text: string; action?: { href: string; label: string } } | null {
  switch (f.reason) {
    case 'unauthenticated':
      return {
        tone: 'warn',
        text: 'Your session ended, so this panel could not refresh.',
        action: { href: '/login', label: 'Sign in again' },
      };
    case 'not_found':
      return { tone: 'info', text: 'This panel is not available for your account.' };
    case 'network':
      // Deliberately does not say "check your connection": the cause can be a
      // dead server on a working connection, and the useful fact is the same.
      return { tone: 'warn', text: 'You are offline and there is no saved copy of this panel yet.' };
    case 'invalid':
    case 'http':
      // The server paint (when there is one) is better than anything we can say.
      return null;
  }
}

const TONE_CLASS: Record<'error' | 'warn' | 'info', string> = {
  error: 'text-error',
  warn: 'text-warning',
  info: 'text-base-content/60',
};

/**
 * Renders the affordance for `f` as a SIBLING of the mount and returns it (or
 * null when the reason has nothing to say). Replaces any previous one, so a
 * retry that fails differently never stacks two contradicting messages.
 *
 * Rejected props are not a failure of the read path, so this is called with
 * the load outcome only — never with a Zod error.
 */
export function showFailure(el: HTMLElement, f: LoadFailure): HTMLElement | null {
  removeFailure(el);

  // Log once per island+reason, whether or not it paints.
  const key = `${el.dataset.island ?? '?'}:${f.reason}`;
  if (!warned.has(key)) {
    warned.add(key);
    console.warn(`[island] ${key} — ${f.message}`);
  }

  const copy = failureCopy(f);
  if (!copy) return null;

  const box = document.createElement('p');
  box.setAttribute(FAILURE_ATTR, f.reason);
  box.setAttribute('role', copy.action ? 'alert' : 'status');
  box.className = `text-[11px] leading-5 mt-1 ${TONE_CLASS[copy.tone]}`;
  box.textContent = copy.text;

  if (copy.action) {
    const a = document.createElement('a');
    a.href = copy.action.href;
    a.className = 'link';
    a.textContent = copy.action.label;
    box.append(' ', a);
  }

  // Sibling, not child — same reason as the staleness caption: the island
  // replaces its own children on re-mount and would wipe this.
  el.insertAdjacentElement('afterend', box);
  return box;
}

export function removeFailure(el: HTMLElement): void {
  el.parentElement?.querySelectorAll(`[${FAILURE_ATTR}]`).forEach((n) => n.remove());
}
