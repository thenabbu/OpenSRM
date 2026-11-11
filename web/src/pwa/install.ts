/**
 * P8.3 — "install app" affordance.
 *
 * `beforeinstallprompt` is a late, one-shot event: the browser fires it on its
 * own schedule and `preventDefault()` + a later `prompt()` is the ONLY way to
 * turn it into a clickable install. So it must be captured once, early, and
 * held — a listener attached after the event has fired never runs at all.
 * Hence: capture at module load into a module-local `deferred`, and let callers
 * subscribe for "now it is available" rather than polling.
 *
 * `appinstalled` fires after any successful install (including one made from
 * the browser's own menu), so it is the honest signal to hide the affordance —
 * `canInstall()` alone would keep claiming true until the next prompt fires.
 */

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

const PROMPT = 'beforeinstallprompt';
const INSTALLED = 'appinstalled';

let deferred: InstallPromptEvent | null = null;
let installed = false;
const listeners = new Set<() => void>();

/**
 * Attach the one-shot capture. Idempotent: calling it from several modules (or
 * on every route) must not stack duplicate listeners, because the first one to
 * call `preventDefault()` already consumed the event.
 */
let wired = false;
export function watchForInstallAvailability(onAvailable?: () => void): () => void {
  if (onAvailable) listeners.add(onAvailable);

  if (!wired && typeof window !== 'undefined') {
    wired = true;

    window.addEventListener(PROMPT, (e: Event) => {
      // Without this the browser shows its own mini-infobar and `prompt()`
      // later resolves as dismissed — the event is single-use.
      e.preventDefault();
      deferred = e as InstallPromptEvent;
      listeners.forEach((fn) => fn());
    });

    window.addEventListener(INSTALLED, () => {
      installed = true;
      deferred = null;
      listeners.forEach((fn) => fn());
    });
  }

  return () => {
    if (onAvailable) listeners.delete(onAvailable);
  };
}

/** True once the browser has offered a prompt and no install has happened yet. */
export function canInstall(): boolean {
  return !installed && deferred !== null;
}

/**
 * Shows the browser's install dialog. Resolves to whether the user accepted.
 *
 * The event is cleared unconditionally: `beforeinstallprompt` fires only once
 * per install, so a dismissed prompt can never be re-prompted. Keeping it would
 * leave `canInstall()` true with a dead button behind it.
 */
export async function promptInstall(): Promise<boolean> {
  const e = deferred;
  if (installed || !e) return false;
  deferred = null;
  try {
    await e.prompt();
    const choice = await e.userChoice;
    return choice.outcome === 'accepted';
  } catch {
    // A prompt already used / no longer valid throws. The affordance is gone
    // either way; an exception here must not break the surrounding page.
    return false;
  }
}

/** Test-only: a fresh page load starts with nothing captured. */
export function __resetInstall(): void {
  deferred = null;
  installed = false;
  wired = false;
  listeners.clear();
}
