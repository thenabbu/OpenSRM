import { canInstall, isInstalled, isPhone, promptInstall, watchForInstallAvailability } from './install';
import { applyUpdate, refreshOnVisible, watchForUpdate } from './update';

/**
 * P8.3 — the install card and the update notice.
 *
 * One container, two jobs, and they are NOT the same message class:
 *  - the install card is a prompt. It appears on a phone only, once per device
 *    (localStorage), and the cross turns it into a navbar button instead of
 *    bringing it back next session — a nag the user already answered is noise.
 *  - the update notice is a transient state. It stays session-scoped, because a
 *    later version is a new message worth showing again.
 *
 * Built as plain DOM, mounted into <body> from the bundle entry: the project CSP
 * is `script-src 'self'` (no inline scripts, no eval), so creating the node in
 * JS is the only route that needs no template change on the ten pages.
 *
 * daisyUI tokens only (DESIGN.md §0.1, §2.3, §4.7): container = `bg-base-200` +
 * `border border-base-300` + `rounded-box`, the one emphasis action is
 * `btn-accent` (white), everything else is `btn-ghost`. No shadow (§6).
 */

const ID = 'pwa-banner';
const NAV_ID = 'pwa-install-btn';
const ICON = '/static/icon-192.png';
// Update notice: per session. A later version is a new message.
const UPDATE_KEY = 'pwa-banner-dismissed';
// Install card: per DEVICE. The cross is the user answering "no" to this card
// forever; the navbar button is what keeps the way back reachable.
const INSTALL_KEY = 'pwa-install-dismissed';

const read = (store: () => Storage | undefined, key: string): boolean => {
  try { return store()?.getItem(key) === '1'; } catch { return false; }
};
const write = (store: () => Storage | undefined, key: string): void => {
  try { store()?.setItem(key, '1'); } catch { /* private mode: stay quiet */ }
};

const updateDismissed = (): boolean => read(() => sessionStorage, UPDATE_KEY);
const installAnswered = (): boolean => read(() => localStorage, INSTALL_KEY);

/**
 * iOS has no install API at all: Safari never fires `beforeinstallprompt`, so an
 * Install button with nothing behind it would be a dead control. The Share sheet
 * is the only install path there, so the card carries words instead.
 *
 * Kept free of daisyUI class words on purpose: Tailwind scans this file, so a
 * plain English word that is also a component name emits kilobytes of CSS.
 */
function iosNeedsInstallInstructions(): boolean {
  if (typeof navigator === 'undefined') return false;
  const standalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return /iPad|iPhone|iPod/.test(navigator.userAgent || '') && !standalone;
}

function host(): HTMLElement {
  const existing = document.getElementById(ID);
  if (existing) return existing;
  const el = document.createElement('div');
  el.id = ID;
  // `bottom-20` is the fallback; the inline calc is the real value: the dock is
  // 4rem PLUS the iOS home-indicator inset, so a bare 5rem would sit inside the
  // dock on a notched phone. 1rem on top = the app's smallest gap (§5 ladder).
  el.className = 'fixed bottom-20 left-4 right-4 z-40 mx-auto max-w-sm hidden';
  el.style.bottom = 'calc(4rem + env(safe-area-inset-bottom) + 1rem)';
  document.body.appendChild(el);
  return el;
}

function closeButton(onClick: () => void): HTMLButtonElement {
  const close = document.createElement('button');
  close.type = 'button';
  // 44px: DESIGN §5's phone tap floor, same as the mobile navbar's icons.
  close.className = 'btn btn-ghost btn-square h-11 w-11 shrink-0';
  close.setAttribute('aria-label', 'Dismiss');
  close.textContent = '✕';
  close.addEventListener('click', onClick);
  return close;
}

/** The update notice: a neutral alert strip, session-dismissed (§4.7). */
function paintUpdate(el: HTMLElement): void {
  if (updateDismissed()) return;

  const box = document.createElement('div');
  box.className = 'alert alert-soft alert-info text-sm gap-2';

  const label = document.createElement('span');
  label.className = 'flex-1';
  label.textContent = 'A new version of openSRM is ready.';

  const reload = document.createElement('button');
  reload.type = 'button';
  reload.className = 'btn btn-ghost btn-sm';
  reload.textContent = 'Reload';
  reload.addEventListener('click', () => applyUpdate());

  const close = closeButton(() => {
    el.classList.add('hidden');
    write(() => sessionStorage, UPDATE_KEY);
  });
  close.className = 'btn btn-ghost btn-square btn-sm h-11 w-11 shrink-0';

  box.append(label, reload, close);
  el.replaceChildren(box);
  el.classList.remove('hidden');
}

/**
 * The install card. Phone only, once per device, and honest about what the
 * browser can actually do: if no prompt is held, the copy names the manual
 * route instead of showing a button that cannot fire.
 */
function paintInstall(el: HTMLElement, force = false): void {
  if (isInstalled() || !isPhone()) return;
  if (!force && installAnswered()) return;

  const card = document.createElement('div');
  card.className = 'card bg-base-200 border border-base-300 rounded-box p-4 gap-3';

  const head = document.createElement('div');
  head.className = 'flex items-start gap-3';

  const icon = document.createElement('img');
  icon.src = ICON;
  icon.alt = '';
  icon.width = 40;
  icon.height = 40;
  icon.className = 'h-10 w-10 shrink-0 rounded-box border border-base-300';

  const copy = document.createElement('div');
  copy.className = 'min-w-0 flex-1';
  const title = document.createElement('p');
  title.className = 'text-sm font-semibold';
  title.textContent = 'Install OpenSRM';
  const body = document.createElement('p');
  body.className = 'mt-1 text-xs leading-5 text-base-content/60';
  copy.append(title, body);

  const installable = canInstall();
  body.textContent = installable
    ? 'Full screen, works offline, one tap from your home screen.'
    : iosNeedsInstallInstructions()
      ? 'Tap Share, then Add to Home Screen.'
      : 'Open your browser menu and choose "Install app" or "Add to Home screen".';

  const close = closeButton(() => {
    el.classList.add('hidden');
    write(() => localStorage, INSTALL_KEY);
    showNavButton();
  });
  // The 44px target is bigger than its glyph: pull it back into the corner so it
  // reads as part of the card's padding, not as a stray element (DESIGN §5).
  close.classList.add('-mr-2', '-mt-2');
  head.append(icon, copy, close);
  card.append(head);

  if (installable) {
    const go = document.createElement('button');
    go.type = 'button';
    // One emphasis action per screen (DESIGN §0.5): white accent, 44px tall.
    go.className = 'btn btn-accent btn-sm min-h-11 w-full';
    go.textContent = 'Install app';
    go.addEventListener('click', () => {
      void promptInstall().then((ok) => {
        // Accepted: the app is installing, both affordances are done.
        // Refused or unavailable: repaint as the manual route, never a dead button.
        if (ok) { clearInstall(); return; }
        paintInstall(el, true);
      });
    });
    card.append(go);
  }

  el.replaceChildren(card);
  el.classList.remove('hidden');
}

/** Post-install (or after an accepted prompt): nothing left to offer. */
function clearInstall(): void {
  document.getElementById(ID)?.classList.add('hidden');
  document.getElementById(NAV_ID)?.remove();
}

/**
 * The dismissed card's replacement: one icon button in the phone navbar, next to
 * the settings gear. Server markup cannot carry it (the state is per device and
 * only known in JS), and `#mobile-navbar` is outside soft navigation's
 * route:start/route:end swap, so one insert survives every tab change.
 */
function showNavButton(): void {
  if (isInstalled() || !isPhone() || document.getElementById(NAV_ID)) return;
  const end = document.querySelector<HTMLElement>('#mobile-navbar .navbar-end')
    ?? document.getElementById('mobile-navbar');
  if (!end) return;                       // login page: no navbar, nothing to add to

  const btn = document.createElement('button');
  btn.id = NAV_ID;
  btn.type = 'button';
  btn.className = 'btn btn-ghost btn-square min-h-11 w-11 h-11';
  btn.setAttribute('aria-label', 'Install app');
  btn.title = 'Install app';
  btn.innerHTML =
    '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">'
    + '<path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"/></svg>';
  btn.addEventListener('click', () => { void onNavInstall(); });
  end.insertBefore(btn, end.firstChild);
}

/** Navbar button: the real prompt when the browser still holds one, else the card. */
async function onNavInstall(): Promise<void> {
  if (canInstall()) {
    const ok = await promptInstall();
    if (ok) { clearInstall(); return; }
  }
  paintInstall(host(), true);
}

export function mountBanner(): void {
  if (typeof document === 'undefined' || !document.body) return;
  const el = host();

  watchForUpdate(() => paintUpdate(el));

  // Look for a new worker when the tab comes back into view. Mounted here, with
  // the watcher above, because the notification it can produce is this banner:
  // the poll forces `registration.update()`, the update installs, waits, and
  // `watchForUpdate` turns that into the notice.
  refreshOnVisible();

  // `beforeinstallprompt` fires on the browser's own schedule — often after this
  // module has mounted, and never at all on iOS.
  watchForInstallAvailability(() => {
    if (canInstall()) paintInstall(el);
  });
  // The event may already have fired before this mount (install.ts captures it
  // at module load), and iOS never fires one: both still deserve the card.
  if (canInstall() || iosNeedsInstallInstructions()) paintInstall(el);

  // Answered on an earlier visit: the way back is the navbar button, not the card.
  if (installAnswered()) showNavButton();

  // Installed from the browser's own menu: neither affordance applies.
  if (isInstalled()) clearInstall();
}
