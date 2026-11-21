import '../tailwind.css';
import { createElement, render } from 'preact';
import type { ComponentType, VNode } from 'preact';
import { isIslandName, schemas } from './islands/contract';
import type { HostProps, IslandName } from './islands/contract';
import { loadPanel } from './data/load';
import { refreshProps, triggerRefresh, bindRefreshButtons, renderSyncCaptions } from './data/refresh';
import { showError } from './data/errorToast';
import { showStale, removeStale } from './data/stale';
import { showFailure, removeFailure } from './data/failure';
import { hasIslandProjection, propsFromCache } from './data/props';
import { bootstrapSessionOffline, currentNetid, sessionGroupKey, wireLogoutLink } from './session';
import { warmShells } from './session/shell';
import { mountBanner } from './pwa/banner';
import { startOutbox, queueWrite } from './data/outbox';
import { bindCopyTargets } from './data/copy';
import { bindAttView } from './data/attView';
import { bindTimetableEditor } from './data/timetableEditor';
import { autoRefreshIfStale, bindAvatarOffscreen, bindFeedbackModal } from './data/background';
import {
  bindDeleteAccount,
  bindDetailsDismiss,
  bindTagSave,
  startScopePoll,
} from './data/userActions';
import {
  applyGroupDefaults,
  bindItemBeacon,
  bindOfflineBanner,
  bindScrollIndicator,
  registerServiceWorker,
} from './data/pageChrome';
import { bindPullToRefresh } from './data/pullToRefresh';
import { bindSoftNav } from './nav/softNav';
import { warn as logWarn } from './log';

/**
 * Lazy component per island name (contract §Mount rules 1). Add one line here
 * per island; nothing else in this file changes.
 */
const registry: Record<IslandName, () => Promise<ComponentType<HostProps>>> = {
  'sync-age': () => import('./islands/sync-age').then((m) => m.default as ComponentType<HostProps>),
  academics: () => import('./panels/academics/AcademicsPanel').then((m) => m.default as ComponentType<HostProps>),
  attendance: () =>
    import('./panels/attendance/AttendancePanel').then((m) => m.default as ComponentType<HostProps>),
  campus: () => import('./panels/campus/CampusPanel').then((m) => m.default as ComponentType<HostProps>),
  dashboard: () =>
    import('./panels/dashboard/DashboardPanel').then((m) => m.default as ComponentType<HostProps>),
  fees: () => import('./panels/fees/FeesPanel').then((m) => m.default as ComponentType<HostProps>),
  marks: () => import('./panels/marks/MarksPanel').then((m) => m.default as ComponentType<HostProps>),
  settings: () => import('./panels/settings/SettingsPanel').then((m) => m.default as ComponentType<HostProps>),
  timetable: () => import('./panels/timetable/TimetablePanel').then((m) => m.default as ComponentType<HostProps>),
  tools: () => import('./panels/tools/ToolsPanel').then((m) => m.default as ComponentType<HostProps>),
};

export const diag = {
  warned: [] as string[],
  warn(msg: string, extra?: unknown): void {
    this.warned.push(msg);
    logWarn('island', msg, extra ?? '');
    // Also on window: the offline DUT runs in a real browser and has no other
    // way to see why an island declined to paint.
    try {
      const w = window as unknown as { __osrmDiag?: string[] };
      (w.__osrmDiag ||= []).push(msg);
    } catch {
      // not a browser context (unit tests) — the array above is enough.
    }
  },
};
const warnedUnknown = new Set<string>();
const warnedProps = new Set<string>();

/**
 * Props for a mount point. Contract shape: `data-props="#island-<name>"` names
 * an inert `<script type="application/json" id="island-<name>">` block; one
 * block serves every mount point of that island on the page (a <span> cannot
 * contain the block, so it sits beside the navbars). Plain JSON in the
 * attribute is accepted too (the demo/test form). Anything else => undefined,
 * which the schema rejects => render nothing.
 */
export function readProps(el: HTMLElement): unknown {
  const ref = el.dataset.props;
  if (!ref) return undefined;
  if (ref.startsWith('#')) {
    const block = document.getElementById(ref.slice(1));
    if (!block) return undefined;
    try { return JSON.parse(block.textContent ?? ''); } catch { return undefined; }
  }
  if (ref.startsWith('{')) {
    try { return JSON.parse(ref); } catch { return undefined; }
  }
  return undefined;
}

/**
 * Error boundary (contract §Mount rules 3). Preact has no built-in one, so the
 * island's render is guarded: a throw discards the island and restores the
 * server's child nodes, leaving *this* element exactly as it arrived. Callers
 * (and hydrateAll's Promise.all) never see the exception.
 */
function mountBounded(name: string, Comp: ComponentType<HostProps>, el: HTMLElement,
                     props: unknown, now: number): boolean {
  const saved = Array.from(el.childNodes);
  try {
    // createElement, not JSX: this module is .ts (the bootstrap, with the CSS
    // import Vite needs); islands stay .tsx.
    // Preact's render() APPENDS into a container that already has children; it
    // does not clear them. The server's markup is still in the mount, so an
    // island painting fewer nodes than the server painted (an empty list, say)
    // left the stale children behind - duplicated content in production. The
    // snapshot `saved` is still what the catch restores on a throw.
    el.replaceChildren();
    render(createElement(Comp, { el, props, now } as HostProps) as VNode<HostProps>, el);
    // Islands paint their OWN nodes, so anything the page armed by querying the
    // server's markup once at load is now watching a detached element: gaze.js's
    // driver and dash.js's avatar IntersectionObserver both do exactly that, and
    // the dashboard island replaced the avatar they were bound to. Both re-arm on
    // this event and are idempotent, so the extra dispatch is free.
    document.dispatchEvent(new CustomEvent('osrm:island-mounted', { detail: name }));
    return true;
  } catch (err) {
    el.replaceChildren(...saved);
    diag.warn(`"${name}" failed to render; server markup kept`, err);
    return false;
  }
}

// Exported for the isolation test: the boundary is the unit under test.
// Testing it through mounted() would require mocking a dynamic import, which
// vitest does not reliably intercept.
export { mountBounded };


// Test-only: each test simulates a fresh page load, so the warn-once sets must
// start empty. Production never calls this.
export function __resetWarnOnce(): void {
  warnedUnknown.clear();
  warnedProps.clear();
}

/**
 * Mounts Preact has already rendered into. Rendering the SAME element twice is
 *  not idempotent: the second render goes into a container Preact already owns,
 *  and the result alternates between 0 and N children — which is exactly what a
 *  flaky "offline paints sometimes" DUT was showing. */
const claimed = new WeakSet<HTMLElement>();

/** element -> what mounted it, so a sync can repaint THAT island from its own
 *  feed without re-deriving its component from the DOM. Only mounted islands
 *  enter this map: an island that declined to paint (invalid props, no store,
 *  a throw) keeps the server's markup and must not be repainted from nothing. */
const mountedAt = new WeakMap<HTMLElement, { name: IslandName; Comp: ComponentType<HostProps> }>();

/** mountBounded + remember the pairing. */
function mountIsland(
  name: IslandName,
  Comp: ComponentType<HostProps>,
  el: HTMLElement,
  props: unknown,
  now: number,
): boolean {
  const ok = mountBounded(name, Comp, el, props, now);
  if (ok) mountedAt.set(el, { name, Comp });
  return ok;
}

export async function hydrateIsland(el: HTMLElement, now: number): Promise<void> {
  const name = el.dataset.island ?? '';
  if (claimed.has(el)) return;               // already hydrated this load
  claimed.add(el);                           // claim BEFORE any await: two boots
  // overlapping (the bootstrap plus a re-run) would otherwise both pass the
  // check above. Both branches below mount through this point, so this is the
  // only guard: mountBounded into a container Preact already owns reconciles the
  // second tree against the first and leaves 0 children.
  if (!isIslandName(name)) {
    if (!warnedUnknown.has(name)) {          // log once, never throw
      warnedUnknown.add(name);
      diag.warn(`unknown island "${name}" — skipped`);
    }
    return;
  }
  const parsed = schemas[name].safeParse(readProps(el));   // Zod at the trust boundary
  let Comp: ComponentType<HostProps>;
  try {
    Comp = await registry[name]();
  } catch (err) {
    diag.warn(`could not load island "${name}"`, err);
    return;
  }

  // ── P7.1 read path ────────────────────────────────────────────────────
  // Two ways in, one rule: the SERVER PAINT is the first paint whenever it is
  // valid. The cache only ever takes over when the page arrived with no props
  // (a shell) — re-rendering over good server markup would be a flash for
  // nothing, and on a slow response a strictly worse paint than what the user
  // already had.
  if (parsed.success) {
    // The server paint is authoritative: mount it and STOP. Falling through to
    // the cache branch re-entered mountBounded on the same element, and because
    // Preact renders on a microtask the two renders interleaved — the first
    // painted 8 rows, the second reconciled against it and left 0. Measured
    // exactly as ["children=8","children=0"] on one element.
    //
    // P7.11: this IS the "fresh network data" case — the props came from the
    // server on this response — so the stale caption from an earlier
    // cache-served mount of this element dies here. Keeping the cleanup down
    // there was the whole bug: this branch returns, so it never reached it.
    removeStale(el);
    mountIsland(name, Comp, el, parsed.data, now);
    // Persist what the server just gave us. Without this the online path never
    // wrote anything to IndexedDB, so the NEXT visit had no cached payload to
    // paint from — measured: after a full online load of /attendance Dexie held
    // {academics:0, attendance:0, ..., meta:1} while the page showed 8 rows.
    // That is why offline painted 0 rows: not a read bug, a NEVER-WRITTEN bug.
    //
    // Fire-and-forget on purpose: this must not delay or re-render the paint
    // that just happened, and a failed write (private mode, quota) must not
    // break the page. loadPanel/writePanel already log their own failures.
    if (hasIslandProjection(name)) {
      const owner = currentNetid();
      if (owner) {
        void loadPanel(name, { netid: owner, groupKey: sessionGroupKey() }).catch(() => {
          /* cache write is best-effort; the paint already succeeded */
        });
      }
    }
    return;
  }
  if (!warnedProps.has(name)) {
    warnedProps.add(name);
    diag.warn(`"${name}" invalid props — trying the cache`, parsed.error.issues);
  }

  // Cache → network. `loadPanel` never rejects and never returns unvalidated
  // data, so a failed load (offline, 401, bad payload) lands here as `ok:false`
  // and this function simply leaves whatever is on screen alone: the server
  // paint if it mounted, nothing otherwise. A throw inside Preact is caught by
  // mountBounded, which restores the pre-render children either way.
  const netid = currentNetid();
  // Silent on purpose: no netid / no projection are NORMAL states (an anonymous
  // page, an island with no store) — not faults. Warning here broke the marks
  // island's "hydration logs nothing" contract, and a console warning per island
  // per load is noise, not diagnosis. The interesting failures (a cache that
  // reads but cannot project) log from data/props.ts instead.
  if (!netid) return;                        // no owner => cache nothing, reuse nothing
  if (!hasIslandProjection(name)) return;    // panel has no cached feed

  const outcome = await loadPanel(name, { netid, groupKey: sessionGroupKey() });
  if (!outcome.ok) {
    // P7.3: the screen is still untouched — but a blank panel is not an answer
    // when the student is logged out or offline with nothing saved. `showFailure`
    // picks the affordance from the reason; `invalid`/`http` paint nothing.
    showFailure(el, outcome);
    return;
  }
  removeFailure(el);                         // a good load clears any earlier message
  // This is where the old guard went wrong. It read
  //   if (parsed.success && outcome.source === 'network') { removeStale(el); return; }
  // and that can never be true: every `parsed.success` mount already returned at
  // :155, so by here it is always false. `removeStale` therefore never ran on ANY
  // path, and a shell that served its rows from the store fell straight past it.
  const props = propsFromCache(name, outcome.data);
  if (!props) return;                        // projection refused the shape: keep the paint
  // No per-branch guard here: `claimed` claimed this element at the top of the
  // function. The old one keyed on el.dataset.mountedAt, which the SERVER's own
  // markup can carry — and the server-paint branch above sets no marker at all,
  // so that element re-mounted on the second boot.
  //
  // The caption on screen is a lie the moment we paint again: either the rows
  // just came off the wire (fresh — any age label is wrong) or they came from
  // the store, and `showStale` below re-labels them with their true age. This
  // runs on the SERVER-paint path too (:154) for the same reason.
  removeStale(el);
  mountIsland(name, Comp, el, props, now);
  el.dataset.mountedAt = outcome.source;     // informational (the gate reads it)
  // P7.2: label a cache-served mount with its age, so "what we had earlier"
  // never reads as "live". One helper for every island (data/stale.ts).
  showStale(el, outcome.fetchedAt, now);
}

export async function hydrateAll(root: ParentNode, now: number): Promise<void> {

  // SEQUENTIAL. Nine concurrent dynamic imports on a cold profile (and on a cold
  // service worker) race each other: the browser's connection budget is small and
  // a chunk arriving late rejects with "Failed to fetch dynamically imported
  // module", which leaves that island showing the server paint or nothing at all.
  // That intermittency is what made this DUT pass one run and fail the next.
  // Hydration is not latency-critical — the server paint is already on screen.
  for (const el of Array.from(root.querySelectorAll<HTMLElement>('[data-island]'))) {
    await hydrateIsland(el, now);
  }
}

/**
 * Repaint every mounted island from its live `/api` slice — the sync path
 * (dash.js calls `window.__osrmRefreshData`, see below).
 *
 * THIS is what makes a sync preserve scroll, focus, open <details> and the
 * attendance view: rendering into a container Preact already owns RECONCILES
 * against the previous tree, so only the text/attribute nodes that actually
 * changed are written. Every other node is the same object it was before the
 * sync, so the browser has nothing to clamp scrollY against.
 *
 * Sequential on purpose (same reason hydrateAll is): the page is already
 * painted, the feeds are small, and N concurrent fetches on a phone is how
 * chunks start rejecting. One island failing leaves the others working and its
 * own paint untouched — the old markup swap had no such middle ground.
 */
export async function refreshIslands(root: ParentNode, now: number): Promise<void> {
  const netid = currentNetid();
  for (const el of Array.from(root.querySelectorAll<HTMLElement>('[data-island]'))) {
    const at = mountedAt.get(el);
    if (!at) continue;                       // never painted: the server's markup stands
    const props = await refreshProps(at.name, {
      netid: netid ?? '',
      groupKey: sessionGroupKey(),
    });
    if (!props) continue;                    // no feed, or the answer failed validation
    try {
      render(createElement(at.Comp, { el, props, now } as HostProps), el);
      // fresh numbers carry no age caption, and a repaint can add rows the
      // page-level handlers stamp (copy targets), so re-arm them.
      removeStale(el);
      document.dispatchEvent(new CustomEvent('osrm:island-mounted', { detail: at.name }));
    } catch (err) {
      diag.warn(`"${at.name}" failed to repaint; previous paint kept`, err);
    }
  }
}

// Bootstrap: the entry is a deferred module, so the document is parsed here.
//
// P7.1: adopt the netid BEFORE hydrating — every cache read and the logout wipe
// key on it, and <body data-netid> is the only place the server publishes it.
// Async boot: on a real page this resolves immediately from <body data-netid>;
// on a SHELL (offline, or served by the service worker) that attribute is
// deliberately absent, so it falls back to the netid remembered in Dexie.
// Hydration MUST wait for it — an island hydrating with no netid reads the
// cache with no key and paints nothing, which is the "offline shows an empty
// panel" bug in miniature.
void (async () => {
  await bootstrapSessionOffline(document);
  await hydrateAll(document, Date.now() / 1000);
})();

// NOT chained behind hydrateAll. Islands hydrate against the network, and a slow
// or stalled island would hold the shell warm back indefinitely — which is
// exactly what happened: the shells were never cached because this line never
// ran. Warming is independent of hydration in both directions (it fetches
// /shell/<panel>, not the islands), so it starts on its own.
// It is NOT unconditional though: warmShells bails without a netid, so the
// signed-out pages (login) issue no /shell/* at all.
void warmShells();


// Logout: the href stays as the no-JS path; this only gets the netid-scoped
// IndexedDB wipe done first (capped, so a hung wipe cannot block the link).
wireLogoutLink(document);

// P7.4: replay any write the student made while offline, then keep doing it
// every time the link returns. Independent of hydration on purpose — a queued
// tag must go out even if an island never mounts, and it must not delay paint.
// The caption is attached to the marks panel when that panel is on the page
// (the only panel that can queue anything today).
void (async () => {
  const el = document.querySelector<HTMLElement>('[data-island="marks"]');
  // dash.js is a plain <script> and cannot import the bundle, so it reaches the
  // queue through this one hook (the same shape as __osrmDiag). Absent until
  // this module runs — dash.js treats a missing hook as "queue unavailable" and
  // keeps its existing failure toast.
  //
  // W5.4c: bindTagSave defers a transport failure into the same hook, and it
  // may run BEFORE this assignment (the binders are bound synchronously below,
  // this is inside an async IIFE). The hook is published first, then the
  // outbox is started, so neither path can see a half-built object.
  const w = window as unknown as { __osrmOutbox?: unknown };
  w.__osrmOutbox = { queueWrite, startOutbox: () => startOutbox(el) };
  await startOutbox(el);
  // `online` fires once per reconnect; drainOutbox is bounded and idempotent,
  // so a burst of events costs at most one empty pass each.
  window.addEventListener('online', () => {
    void startOutbox(el);
  });
})();

// W5.1b: a sync repaints DATA, not markup. dash.js is a plain <script> and
// cannot import this bundle, so it reaches the repaint through this one hook —
// the same shape as __osrmOutbox. Until this module runs the hook is absent and
// a sync leaves the page alone; that degradation is deliberate, because the
// alternative (fetching the route's HTML again to change one number) is the
// cost this task exists to delete.
(window as unknown as { __osrmRefreshData?: () => Promise<void> }).__osrmRefreshData =
  () => refreshIslands(document, Date.now() / 1000);

// W5.2a: the refresh primitive and the error toast live in web/src/data now
// (refresh.ts, errorToast.ts) instead of dash.js, which three files used to
// reach into. They are classic <script>s, so they come through these bridges —
// same seam as __osrmOutbox above. (W5.4: dash.js is deleted, so the
// PREACT_ISLANDS=0 duplicate binder those paragraphs described no longer
// exists; the markers and their `if (!…)` guards stay because they make each
// binder idempotent, which is what a double-injected entrypoint would need.)
//
// The [data-refresh] buttons are bound HERE: one binder, or a single click
// starts two syncs.
//
// __osrmSyncCaption is the caption painter (the replacement for the deleted
// dash.js `renderSyncLines` global): it re-formats every `.sync-line` from its
// own `data-ts`, which the e2e bar needs to drive the age buckets it asserts.
const bridge = window as unknown as {
  __osrmShowError?: (msg: string) => void;
  __osrmRevalidate?: (quiet?: boolean) => Promise<void>;
  __osrmSyncCaption?: () => void;
};
bridge.__osrmShowError = showError;
bridge.__osrmRevalidate = triggerRefresh;
bridge.__osrmSyncCaption = renderSyncCaptions;
bindRefreshButtons();

// W5.2b: the copy cluster. Bound BEFORE hydration on purpose — it registers the
// `osrm:island-mounted` listener that re-stamps copy targets, and listening
// late would miss the first mount, which is the one that repaints them.
bindCopyTargets(document);

// W5.2c: the attendance view toggle. Bound once, here, like the copy cluster —
// the two buttons are server-rendered and never repainted, so no re-arm is
// needed; the restore-on-load happens inside the binder.
//
// The bridge is what tells dash.js to stand down: it keeps a PREACT_ISLANDS=0
// toggle that flips the nodes but persists nothing, and without this marker
// both binders would answer the same click.
(window as unknown as { __osrmAttView?: typeof bindAttView }).__osrmAttView = bindAttView;
bindAttView();

// W5.4a: the timetable editor. Same shape as the toggle above — but this one
// is the reason timetable.js cannot be deleted yet, so main.ts is now the only
// place that wires editing. It no-ops on every route without #tt-edit-btn
// (which includes /timetable itself under the archived default), and no bridge
// is needed: timetable.js keeps its own copy until W5.4 deletes it, and the
// two must never both bound. The bridge below is the stand-down: timetable.js
// checks it at init and skips its own listeners when the bundle is here, the
// same seam __osrmAttView gives dash.js.
(window as unknown as { __osrmTimetableEditor?: typeof bindTimetableEditor }).__osrmTimetableEditor =
  bindTimetableEditor;
bindTimetableEditor();
// Re-arm on every island mount: on a hard load of anything but /timetable the
// editor's nodes do not exist yet and the call above returns false, and the
// editor only appears when that route is swapped in. Idempotent per element (see
// the ttBound flag in timetableEditor.ts), so the extra calls are free.
// One immediate attempt, then a brief bounded retry: the nodes bindTimetableEditor
// needs are not all in the document at the instant the signal fires (the grid is
// rendered by the island from the timetable data), and it returns false unless it
// finds every one of them. 20 x 100 ms is the ceiling; the bind itself is per
// element, so a retry after success is a no-op. The `typeof document` guard is for
// unit tests, where a pending timer can outlive the jsdom environment.
const rebindTimetableEditor = (): void => {
  let tries = 0;
  const attempt = (): void => {
    if (typeof document === 'undefined') return;
    if (bindTimetableEditor() || ++tries > 20) return;
    setTimeout(attempt, 100);
  };
  attempt();
};
for (const ev of ['osrm:island-mounted', 'osrm:route-swapped'] as const) {
  document.addEventListener(ev, rebindTimetableEditor);
}

// W5.4b: page chrome — the five dash.js behaviours that belong to the page
// rather than to a panel (scroll indicator, item beacon, settings groups,
// offline banner, SW registration). Each marker below is the stand-down: the
// legacy block in dash.js checks it and skips its own copy, so until W5.4
// deletes that file neither runs twice.
//
// Ordering matters for exactly one of them: the settings-group rule arms
// `osrm:island-mounted` BEFORE hydration below can fire the first mount.
const chrome = window as unknown as {
  __osrmScrollIndicator?: typeof bindScrollIndicator;
  __osrmItemBeacon?: typeof bindItemBeacon;
  __osrmGroupDefaults?: typeof applyGroupDefaults;
  __osrmOfflineBanner?: typeof bindOfflineBanner;
  __osrmSwRegister?: typeof registerServiceWorker;
};
if (!chrome.__osrmScrollIndicator) {
  chrome.__osrmScrollIndicator = bindScrollIndicator;
  bindScrollIndicator();
}
if (!chrome.__osrmItemBeacon) {
  chrome.__osrmItemBeacon = bindItemBeacon;
  bindItemBeacon();
}
if (!chrome.__osrmGroupDefaults) {
  chrome.__osrmGroupDefaults = applyGroupDefaults;
  applyGroupDefaults();
  document.addEventListener('osrm:island-mounted', () => applyGroupDefaults());
}
if (!chrome.__osrmOfflineBanner) {
  chrome.__osrmOfflineBanner = bindOfflineBanner;
  bindOfflineBanner();
}
if (!chrome.__osrmSwRegister) {
  chrome.__osrmSwRegister = registerServiceWorker;
  registerServiceWorker();
}

// W5.4c: user actions — the four dash.js rows that are something the user DID
// (tag save, delete account, tap-away dismiss, the scope poll). Same seam as
// pageChrome above: each marker is the stand-down for its legacy block, so
// until W5.4 deletes dash.js neither copy runs twice. For the delete row that
// is not cosmetic — two binders means one confirm DELETES TWICE.
//
// Bound unconditionally, no `if (!__osrmX)` guard: main.ts is the only binder
// for these rows in the bundle, and the guard pattern pageChrome uses exists
// only because those five also have a PREACT_ISLANDS=0 copy that must win on
// the rollback path. Here the legacy copy checks the marker; it never races.
const actions = window as unknown as {
  __osrmTagSave?: typeof bindTagSave;
  __osrmDeleteAccount?: typeof bindDeleteAccount;
  __osrmDetailsDismiss?: typeof bindDetailsDismiss;
  __osrmScopePoll?: typeof startScopePoll;
};
actions.__osrmTagSave = bindTagSave;
bindTagSave();
actions.__osrmDeleteAccount = bindDeleteAccount;
bindDeleteAccount();
actions.__osrmDetailsDismiss = bindDetailsDismiss;
bindDetailsDismiss();
actions.__osrmScopePoll = startScopePoll;
// The only poll in the app: 1.5 s first, 4 s then 8 s, 150 tries max, one
// repaint on 'complete'. No-ops unless <body data-scope-sync> is stale/running.
startScopePoll();

// W5.4d: background — the three dash.js rows that run with no click: the avatar
// IO deferral, the feedback dialog's open/submit pair, and the load-time stale
// check. Same seam as above: each marker is the stand-down for its legacy block,
// so until W5.4 deletes dash.js neither copy runs twice. For the dialog that is
// not cosmetic — two document-level click handlers means one confirm POSTs
// /api/feedback/fill twice, i.e. two fills per teacher.
//
// Ordering: this block is module top-level, so it runs before the boot IIFE's
// hydrateAll() resolves (the await yields, module evaluation finishes first).
// That matters for autoRefreshIfStale: it reads the SERVER's data-ts off the
// first .sync-line, and an island repaint may rewrite it afterwards.
// dash.js read it after hydration, so this is the stricter of the two timings,
// and it is the one the DUT pins (stale rewrite -> exactly one POST).
const background = window as unknown as {
  __osrmAvatarOffscreen?: typeof bindAvatarOffscreen;
  __osrmFbModal?: typeof bindFeedbackModal;
  __osrmAutoRefresh?: typeof autoRefreshIfStale;
};
background.__osrmAvatarOffscreen = bindAvatarOffscreen;
// Arms the current avatar AND re-arms on `osrm:island-mounted`: the dashboard
// island paints its own avatar node, so an observer left on the server-rendered
// one would report on a node nobody can see.
bindAvatarOffscreen();
background.__osrmFbModal = bindFeedbackModal;
bindFeedbackModal();
background.__osrmAutoRefresh = autoRefreshIfStale;
// ONE check at load. Stale = no data-ts, or older than 10 min; skipped when the
// page has no credentials (meta can-sync=0) or the browser is offline.
autoRefreshIfStale();

// The mount entry, exposed for the same reason __osrmRefreshData is: the e2e bar
// has to be able to make an island repaint a page that is already hydrated, and
// "wait for a sync to change some data" is not a reliable trigger (an unchanged
// payload patches nothing, so Preact writes no nodes). This is refreshIslands
// itself — the exact function a sync calls — not a test double.
(window as unknown as { __osrmHydrate?: typeof hydrateAll }).__osrmHydrate = hydrateAll;
(window as unknown as { __osrmRepaint?: typeof refreshIslands }).__osrmRepaint = refreshIslands;

// P8.3: update + install banner. Independent of hydration on purpose — a
// pending update matters most exactly when an island is stuck.
mountBanner();

// W5.4e: pull-to-refresh — the four pull.js rows (gesture, excluded regions,
// dialog guard, refresh-running guard). Same seam as every block above: the
// marker below IS the stand-down, and pull.js returns before binding when it
// sees it. Two binders would fire TWO POST /api/refresh per gesture, which is
// the double-fire t_d051895a chased; test_pull_dut's delta==1 check catches it.
//
// This is also what finally cuts pull.js's last tie to dash.js: the old file
// called the GLOBAL `ref()` behind `typeof ref === "function"`, so deleting
// dash.js first made the gesture a silent no-op. The port calls triggerRefresh
// straight from refresh.ts, so either deletion order is now safe.
const pull = window as unknown as { __osrmPull?: typeof bindPullToRefresh };
pull.__osrmPull = bindPullToRefresh;
// No-ops on a fine pointer (desktop mouse), so nothing to feature-detect here.
bindPullToRefresh();

// Soft navigation: a tab tap swaps the route in place instead of reloading the
// document (see nav/softNav.ts for why). Bound LAST so the markers it looks for
// — base.html's `route:start` / `route:end` and the ids above — are all present,
// and so a soft-nav swap re-runs nothing that is about the document rather than
// the route. The chrome binders (scroll indicator, beacon, copy, pull, outbox)
// are delegated at document level and keep working across a swap; this is the
// one behaviour the swap re-runs, with the fresh island markup as its root.
bindSoftNav(document, window, {
  hydrate: (root) => hydrateAll(root, Date.now() / 1000),
});
