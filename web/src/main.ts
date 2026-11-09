import '../tailwind.css';
import { createElement, render } from 'preact';
import type { ComponentType, VNode } from 'preact';
import { isIslandName, schemas } from './islands/contract';
import type { HostProps, IslandName } from './islands/contract';
import { wireLogoutLink } from './session';

/**
 * Lazy component per island name (contract §Mount rules 1). Add one line here
 * per island; nothing else in this file changes.
 */
const registry: Record<IslandName, () => Promise<ComponentType<HostProps>>> = {
  'sync-age': () => import('./islands/sync-age').then((m) => m.default as ComponentType<HostProps>),
  dashboard: () =>
    import('./panels/dashboard/DashboardPanel').then((m) => m.default as ComponentType<HostProps>),
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
function mountBounded(name: string, Comp: ComponentType<HostProps>, el: HTMLElement,
                     props: unknown, now: number): boolean {
  const saved = Array.from(el.childNodes);
  try {
    // createElement, not JSX: this module is .ts (the bootstrap, with the CSS
    // import Vite needs); islands stay .tsx.
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
  if (!parsed.success) {
    if (!warnedProps.has(name)) {
      warnedProps.add(name);
      diag.warn(`"${name}" invalid props — rendering nothing`, parsed.error.issues);
    }
    return;
  }
  let Comp: ComponentType<HostProps>;
  try {
    Comp = await registry[name]();
  } catch (err) {
    diag.warn(`could not load island "${name}"`, err);
    return;
  }
  mountBounded(name, Comp, el, parsed.data, now);
}

export async function hydrateAll(root: ParentNode, now: number): Promise<void> {
  await Promise.all(
    Array.from(root.querySelectorAll<HTMLElement>('[data-island]')).map((el) => hydrateIsland(el, now)),
  );
}

// Bootstrap: the entry is a deferred module, so the document is parsed here.
void hydrateAll(document, Date.now() / 1000);

// Logout: the href stays as the no-JS path; this only gets the netid-scoped
// IndexedDB wipe done first (capped, so a hung wipe cannot block the link).
wireLogoutLink(document);
