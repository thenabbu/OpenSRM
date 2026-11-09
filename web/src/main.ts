import '../tailwind.css';
import { createElement, render } from 'preact';
import type { ComponentType, VNode } from 'preact';
import { isIslandName, schemas } from './islands/contract';
import type { HostProps, IslandName } from './islands/contract';
import { loadPanel } from './data/load';
import { hasIslandProjection, propsFromCache } from './data/props';
import { type StaleProps, withStale } from './islands/stale';
import { bootstrapSession, currentNetid, sessionGroupKey, wireLogoutLink } from './session';

/**
 * Lazy component per island name (contract §Mount rules 1). Add one line here
 * per island; nothing else in this file changes.
 */
const registry: Record<IslandName, () => Promise<ComponentType<HostProps>>> = {
  'sync-age': () => import('./islands/sync-age').then((m) => m.default as ComponentType<HostProps>),
  fees: () => import('./panels/fees/FeesPanel').then((m) => m.default as ComponentType<HostProps>),
  academics: () => import('./panels/academics/AcademicsPanel').then((m) => m.default as ComponentType<HostProps>),
  campus: () => import('./panels/campus/CampusPanel').then((m) => m.default as ComponentType<HostProps>),
  settings: () => import('./panels/settings/SettingsPanel').then((m) => m.default as ComponentType<HostProps>),
};

export const diag = {
  warned: [] as string[],
  warn(msg: string, extra?: unknown): void {
    this.warned.push(msg);
    console.warn(`[island] ${msg}`, extra ?? '');
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
function mountBounded(name: string, Comp: ComponentType<HostProps>,
                     el: HTMLElement, props: unknown, now: number,
                     stamp = 0, stale = false): boolean {
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
    // Every island routes through here, so wrapping HERE is what makes the
    // staleness caption "one implementation, used by every island" (P7.2).
    const Stale = withStale(Comp);
    render(createElement(Stale, { el, props, now, stamp, stale } as StaleProps) as VNode<StaleProps>, el);
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

export async function hydrateIsland(el: HTMLElement, now: number): Promise<void> {
  const name = el.dataset.island ?? '';
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
    mountBounded(name, Comp, el, parsed.data, now);
  } else if (!warnedProps.has(name)) {
    warnedProps.add(name);
    diag.warn(`"${name}" invalid props — trying the cache`, parsed.error.issues);
  }

  // Cache → network. `loadPanel` never rejects and never returns unvalidated
  // data, so a failed load (offline, 401, bad payload) lands here as `ok:false`
  // and this function simply leaves whatever is on screen alone: the server
  // paint if it mounted, nothing otherwise. A throw inside Preact is caught by
  // mountBounded, which restores the pre-render children either way.
  const netid = currentNetid();
  if (!netid) return;                        // no owner => cache nothing, reuse nothing
  if (!hasIslandProjection(name)) return;    // attendance/marks/timetable: no island yet

  const outcome = await loadPanel(name, { netid, groupKey: sessionGroupKey() });
  if (!outcome.ok) return;                   // failed load: screen untouched, by design
  // Server paint already correct and fresh: only a cache hit serves offline.
  if (parsed.success && outcome.source === 'network') return;
  const props = propsFromCache(name, outcome.data);
  if (!props) return;                        // projection refused the shape: keep the paint
  // The cache is the only source that can be old: label it with its own stamp
  // (and `outcome.stale`, which is that stamp measured against STALE_MS).
  mountBounded(name, Comp, el, props, now, outcome.fetchedAt, outcome.stale);
}

export async function hydrateAll(root: ParentNode, now: number): Promise<void> {
  await Promise.all(
    Array.from(root.querySelectorAll<HTMLElement>('[data-island]')).map((el) => hydrateIsland(el, now)),
  );
}

// Bootstrap: the entry is a deferred module, so the document is parsed here.
//
// P7.1: adopt the netid BEFORE hydrating — every cache read and the logout wipe
// key on it, and <body data-netid> is the only place the server publishes it.
bootstrapSession(document);
void hydrateAll(document, Date.now() / 1000);

// Logout: the href stays as the no-JS path; this only gets the netid-scoped
// IndexedDB wipe done first (capped, so a hung wipe cannot block the link).
wireLogoutLink(document);
