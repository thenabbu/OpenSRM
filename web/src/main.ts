import '../tailwind.css';
import { createElement, render } from 'preact';
import type { ComponentType, VNode } from 'preact';
import { isIslandName, schemas } from './islands/contract';
import type { HostProps, IslandName } from './islands/contract';
import { loadPanel } from './data/load';
import { showStale, removeStale } from './data/stale';
import { showFailure, removeFailure } from './data/failure';
import { hasIslandProjection, propsFromCache } from './data/props';
import { bootstrapSessionOffline, currentNetid, sessionGroupKey, wireLogoutLink } from './session';
import { warmShells } from './session/shell';
import { mountBanner } from './pwa/banner';

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
    console.warn(`[island] ${msg}`, extra ?? '');
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

/** Mounts Preact has already rendered into. Rendering the SAME element twice is
 *  not idempotent: the second render goes into a container Preact already owns,
 *  and the result alternates between 0 and N children — which is exactly what a
 *  flaky "offline paints sometimes" DUT was showing. */
const claimed = new WeakSet<HTMLElement>();

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
    mountBounded(name, Comp, el, parsed.data, now);
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
  mountBounded(name, Comp, el, props, now);
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
void warmShells();


// Logout: the href stays as the no-JS path; this only gets the netid-scoped
// IndexedDB wipe done first (capped, so a hung wipe cannot block the link).
wireLogoutLink(document);

// P8.3: update + install banner. Independent of hydration on purpose — a
// pending update matters most exactly when an island is stuck.
mountBanner();
