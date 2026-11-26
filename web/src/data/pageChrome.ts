// ── Page chrome (W5.4b) — five dash.js behaviours that are about the PAGE,
//    not about any one panel, ported into the bundle.
//
// Rows this module owns (matrix names, so a future grep finds them):
//   dash-scroll-indicator  → bindScrollIndicator   (html.is-scrolling)
//   dash-item-beacon       → bindItemBeacon        (POST /api/track/tab)
//   dash-settings-groups   → applyGroupDefaults    (#personal-details groups)
//   dash-offline-banner    → bindOfflineBanner     (#offline-banner)
//   dash-sw-register       → registerServiceWorker (/static/sw.js, scope '/')
//
// Why this is ONE file and not five: they share exactly one property — every
// one of them is bound once per document at boot and none of them renders. Five
// files would be five imports in main.ts for five listeners.
//
// Nothing here persists. W5.4b's card said to reuse `web/src/data/local.ts`;
// that module does not exist in this tree, and none of these five rows writes
// to storage, so there is nothing to route through it. The persisted rows
// (attView, the timetable editor) own their own stores.
//
// STAND-DOWN: dash.js stays as the PREACT_ISLANDS=0 fallback until W5.4 deletes
// it, so each binder publishes a `window.__osrm*` marker and the legacy block
// checks it. Same seam as __osrmAttView / __osrmTimetableEditor — without it
// both copies listen and one click beacons twice.

// ─ 1. Scroll indicator ────────────────────────────────────────────────────
/** How long `is-scrolling` outlives the last scroll event (dash.js used 1200). */
export const SCROLL_LINGER_MS = 1200;
export const SCROLL_CLASS = 'is-scrolling';

/** The value a `window.__osrmScrollIndicator` marker holds once bound. */
export function bindScrollIndicator(
  doc: Document = document,
  win: Window = window,
): void {
  const root = doc.documentElement;
  let timer: ReturnType<typeof setTimeout> | undefined;
  win.addEventListener(
    'scroll',
    () => {
      root.classList.add(SCROLL_CLASS);
      clearTimeout(timer);
      timer = setTimeout(() => root.classList.remove(SCROLL_CLASS), SCROLL_LINGER_MS);
    },
    { passive: true },
  );
}

// ─ 2. Item beacon ─────────────────────────────────────────────────────────
/**
 * Which tab each tracked item belongs to — the body of the beacon.
 *
 * The islands EMIT `data-track-item` but cannot know this mapping, and the
 * server keeps the closed vocabulary of valid names (an unknown item is dropped
 * server-side, so a stale attribute can never mint a new label). An item that is
 * missing here falls back to 'dashboard', which is what dash.js did.
 */
export const ITEM_TAB: Readonly<Record<string, string>> = {
  'attendance-graph': 'attendance',
  'attendance-table': 'attendance',
  'attendance-sort': 'attendance',
  'timetable-day': 'timetable',
  'timetable-subject': 'timetable',
  'marks-component': 'marks',
  'marks-semester': 'marks',
  'fees-breakdown': 'fees',
  'academics-transcript': 'academics',
  'academics-credits': 'academics',
  'tools-feedback': 'tools',
  'tools-push': 'tools',
  'profile-card': 'dashboard',
  'sync-button': 'dashboard',
  'settings-device': 'settings',
};

export const TRACK_URL = '/api/track/tab';

/**
 * One delegated listener, fire-and-forget with keepalive. Telemetry must never
 * break a click: the whole body is wrapped and the fetch is `.catch`ed, which
 * is the behaviour the matrix's proof asserts ("throw inside fetch and the
 * click still performs its normal action").
 */
export function bindItemBeacon(
  doc: Document = document,
  doFetch: typeof fetch | undefined = typeof fetch === 'function' ? fetch : undefined,
): void {
  doc.addEventListener(
    'click',
    (ev) => {
      try {
        const target = ev.target as Element | null;
        const el = target?.closest?.('[data-track-item]');
        if (!el || !doFetch) return;
        const item = el.getAttribute('data-track-item');
        if (!item) return;
        doFetch(TRACK_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tab: ITEM_TAB[item] ?? 'dashboard', item }),
          keepalive: true,
          credentials: 'same-origin',
        }).catch(() => {});
      } catch {
        // a beacon failure is never a click failure
      }
    },
    { passive: true },
  );
}

// ─ 3. Settings groups ─────────────────────────────────────────────────────
/** The desktop breakpoint the group rule flips at (Tailwind `sm`). */
export const GROUP_WIDE_QUERY = '(min-width: 640px)';

/**
 * Open every personal-details group at >=640 px, only the first below it.
 *
 * Called at load AND on `osrm:island-mounted`, because settings.html:84 is both
 * `#personal-details` and the settings island's mount: the repaint ships the
 * inputs unchecked and would otherwise undo this.
 *
 * Two details that are load-bearing, both learned the hard way in dash.js:
 *   * the selector walks `.collapse-content > .flex.flex-col` because after
 *     hydration the island's block is a SECOND `#personal-details`, and a plain
 *     `#personal-details .collapse input` would also match the ROW's own toggle
 *     — opening a row the user never opened;
 *   * each input is stamped `data-group-default` so a re-arm never overwrites a
 *     toggle the user made, and a breakpoint rotation keeps their choice.
 */
export function applyGroupDefaults(
  doc: Document = document,
  win: Window = window,
): void {
  const wrap = doc.querySelector('#personal-details .collapse-content > .flex.flex-col');
  if (!wrap) return;
  // matchMedia is absent in jsdom and in very old engines. W5.4b's port is the
  // first code to call it from an `osrm:island-mounted` listener, so a missing
  // API would now throw once per mount instead of only at load — and this
  // listener must never break a mount. Absent API => keep the mobile rule.
  const mm = win.matchMedia;
  const wide = typeof mm === 'function' ? mm.call(win, GROUP_WIDE_QUERY).matches : false;
  Array.prototype.forEach.call(
    wrap.querySelectorAll('.collapse > input'),
    (g: HTMLInputElement, i: number) => {
      if (g.dataset.groupDefault) return;
      g.dataset.groupDefault = '1';
      g.checked = wide || i === 0;
    },
  );
}

// ─ 4. Offline banner ──────────────────────────────────────────────────────
/** The exact daisyUI class list dash.js applied; `''` is the cleared state. */
export const BANNER_CLASSES =
  'alert alert-soft alert-warning fixed bottom-0 left-0 right-0 z-50 rounded-none';
export const BANNER_TEXT = 'You are offline \u2014 showing cached data';

/** Paint the banner for the current connectivity, then follow online/offline. */
export function bindOfflineBanner(doc: Document = document, win: Window = window): void {
  const el = doc.getElementById('offline-banner');
  if (!el) return;
  const paint = (offline: boolean): void => {
    el.className = offline ? BANNER_CLASSES : '';
    el.textContent = offline ? BANNER_TEXT : '';
  };
  // A page that LOADS offline never fires `offline` — the event only marks a
  // transition — so seed from the current state. dash.js missed this window.
  paint(win.navigator?.onLine === false);
  win.addEventListener('online', () => paint(false));
  win.addEventListener('offline', () => paint(true));
}

// ─ 5. Service worker registration ─────────────────────────────────────────
export const SW_URL = '/static/sw.js';
export const SW_SCOPE = '/';

/**
 * Register the worker on every route except /login, which login.js already
 * covers — registering there twice would be two register() calls for one
 * worker.
 *
 * This row is on W7's ground (offline), so the port is deliberately a literal
 * copy of dash.js:272-274: same URL, same scope, same swallow of the rejection
 * (a failed registration on an insecure origin must not throw into boot). It is
 * called from main.ts, which runs on every page the bundle ships to.
 */
export function registerServiceWorker(win: Window = window): void {
  const sw = win.navigator?.serviceWorker;
  if (!sw) return;
  if (win.location?.pathname === '/login') return;
  sw.register(SW_URL, { scope: SW_SCOPE }).catch(() => {});
}
