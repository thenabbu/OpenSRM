import { canInstall, promptInstall, watchForInstallAvailability } from './install';
import { applyUpdate, refreshOnVisible, watchForUpdate } from './update';

/**
 * P8.3 — the update / install banner.
 *
 * One element for both jobs, mounted into <body> from the bundle entry. No
 * template change: partials/theme.html already loads the module on all 10
 * pages, and the project CSP is `script-src 'self'` (no inline scripts, no
 * eval), so creating the node in JS is the only route.
 *
 * Rendered as a plain DOM build rather than a Preact island: it is chrome
 * around the shell, not data, and it must appear on a page whose server markup
 * is already correct — an island would need a mount point in every template.
 *
 * daisyUI classes only (alert + btn + btn-sm), all already compiled into
 * app.css, so no CSS change and no stale-stylesheet risk.
 */

const ID = 'pwa-banner';
const DISMISSED_KEY = 'pwa-banner-dismissed';
// One dismissal silences the UPDATE notice for the session. `sessionStorage`
// (not localStorage): a later version is a new message worth showing again.
const dismissed = (): boolean => {
  try { return sessionStorage.getItem(DISMISSED_KEY) === '1'; } catch { return false; }
};

/**
 * iOS has no install API at all: Safari never fires `beforeinstallprompt`, so
 * the Install button below is unreachable on every iPhone and iPad — the Share
 * sheet is the only install path. `navigator.standalone` is the iOS-only signal
 * for "already running from the Home Screen", the one state where the
 * instruction must stay quiet.
 *
 * Kept free of daisyUI class words on purpose: Tailwind scans this file, so a
 * plain English word that is also a component name emits kilobytes of CSS.
 */
function iosNeedsInstallInstructions(): boolean {
  if (typeof navigator === 'undefined') return false;
  const standalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return /iPad|iPhone|iPod/.test(navigator.userAgent || '') && !standalone;
}

function banner(): HTMLElement {
  const existing = document.getElementById(ID);
  if (existing) return existing;
  const el = document.createElement('div');
  el.id = ID;
  el.className = 'alert alert-info fixed bottom-20 left-4 right-4 z-50 mx-auto max-w-md text-sm shadow-lg hidden';
  document.body.appendChild(el);
  return el;
}

function paint(el: HTMLElement, text: string, actions: Array<[string, () => void]>): void {
  if (dismissed()) return;
  const frag = document.createDocumentFragment();
  const label = document.createElement('span');
  label.className = 'flex-1';
  label.textContent = text;
  frag.append(label);

  for (const [name, onClick] of actions) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-sm btn-ghost';
    btn.textContent = name;
    btn.addEventListener('click', onClick);
    frag.append(btn);
  }

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'btn btn-sm btn-circle btn-ghost';
  close.setAttribute('aria-label', 'Dismiss');
  close.textContent = '✕';
  close.addEventListener('click', () => {
    el.classList.add('hidden');
    try { sessionStorage.setItem(DISMISSED_KEY, '1'); } catch { /* private mode */ }
  });
  frag.append(close);

  // One message at a time: the update notice is the actionable one and would
  // otherwise be stacked under an install notice.
  el.replaceChildren(frag);
  el.classList.remove('hidden');
}

export function mountBanner(): void {
  if (typeof document === 'undefined' || !document.body) return;
  const el = banner();

  watchForUpdate(() => {
    paint(el, 'A new version of openSRM is ready.', [['Reload', () => applyUpdate()]]);
  });

  // Look for a new worker when the tab comes back into view. Mounted here, with
  // the watcher above, because the notification it can produce is this banner:
  // the poll forces `registration.update()`, the update installs, waits, and
  // `watchForUpdate` turns that into the notice.
  refreshOnVisible();

  // The install affordance appears whenever the browser gets round to firing
  // `beforeinstallprompt` — which can be after this module has mounted.
  watchForInstallAvailability(() => {
    if (!canInstall()) return;
    paint(el, 'Install openSRM for offline access.', [
      ['Install app', () => void promptInstall()],
    ]);
  });

  // iOS: the same slot, as words instead of a button, because there is no event
  // to wait for. Same session dismissal as the other two notices.
  if (iosNeedsInstallInstructions()) {
    paint(el, 'Install openSRM: tap Share, then Add to Home Screen.', []);
  }
}
