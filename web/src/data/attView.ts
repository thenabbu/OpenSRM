// ── Attendance view toggle (graph ↔ table) — ported out of `dash.js:165-185`
//    (W5.2c).
//
// Structural note, because it decides the shape of this file: the two toggle
// buttons sit in the Subjects header (attendance.html:8,13) and BOTH toggled
// nodes straddle the island — `#att-graph` is above the mount point (:21) and
// `#att-table` is inside it (:58). So the attendance island cannot own this
// state without moving markup, and the toggle must also work with islands OFF
// (amendment A2). State therefore lives here, in the bundle, and reaches the
// page through the DOM the server already rendered — option (b) of W5.2c, not
// (a). Nothing in attendance.html moved.
//
// Two behaviours that look like polish and are not:
//   * visibility is the `hidden` ATTRIBUTE only. The golden capture and the
//     a11y assertions read the attribute; a Tailwind class would leave
//     `table.hidden === false` on a table the user cannot see.
//   * the localStorage read is guarded. Private-mode Safari THROWS on access,
//     and an unguarded read turns the whole toggle into a dead button there.

/** The two views, and the key the previous implementation already used. */
export type AttView = 'graph' | 'table';
export const ATT_VIEW_KEY = 'attView';

/** ids, in one place: dash.js and this module must never name them differently. */
const NODES = {
  graph: 'att-graph',
  table: 'att-table',
  graphBtn: 'att-view-graph',
  tableBtn: 'att-view-table',
} as const;

/**
 * The persisted view, or `graph` when there is nothing saved, the saved value
 * is not one of the two views, or the store is unavailable (private mode,
 * storage disabled, no `window.localStorage` in a worker). Never throws.
 */
export function readAttView(store?: Storage): AttView {
  try {
    const s = store ?? globalThis.localStorage;
    return s?.getItem(ATT_VIEW_KEY) === 'table' ? 'table' : 'graph';
  } catch {
    return 'graph';
  }
}

/** Persist the view. A refused write is not worth a toast: the toggle already
 *  worked for this page load, and only the next reload loses the choice. */
export function writeAttView(view: AttView, store?: Storage): void {
  try {
    (store ?? globalThis.localStorage)?.setItem(ATT_VIEW_KEY, view);
  } catch {
    // private mode / quota — the current page keeps the view it just applied.
  }
}

/**
 * Apply a view to the four nodes. Returns false when the page has no toggle
 * (every route except /attendance), so the caller can skip wiring.
 */
export function applyAttView(view: AttView, doc: Document = document): boolean {
  const graph = doc.getElementById(NODES.graph);
  const table = doc.getElementById(NODES.table);
  const graphBtn = doc.getElementById(NODES.graphBtn);
  const tableBtn = doc.getElementById(NODES.tableBtn);
  if (!graph || !table || !graphBtn || !tableBtn) return false;

  const isTable = view === 'table';
  table.hidden = !isTable;
  graph.hidden = isTable;
  tableBtn.setAttribute('aria-pressed', isTable ? 'true' : 'false');
  graphBtn.setAttribute('aria-pressed', isTable ? 'false' : 'true');
  tableBtn.classList.toggle('btn-active', isTable);
  graphBtn.classList.toggle('btn-active', !isTable);
  return true;
}

/**
 * Restore the saved view on load and write it on every click. Bound from
 * main.ts, once per document.
 *
 * `store` is a parameter and not a hard-coded `localStorage` on purpose: the
 * click handlers need the same store the restore read from, and a test has to
 * be able to supply one (a module that reads the global and writes a private
 * copy is two stores pretending to be one).
 */
export function bindAttView(doc: Document = document, store?: Storage): void {
  if (!applyAttView(readAttView(store), doc)) return;
  doc.getElementById(NODES.graphBtn)?.addEventListener('click', () => {
    applyAttView('graph', doc);
    writeAttView('graph', store);
  });
  doc.getElementById(NODES.tableBtn)?.addEventListener('click', () => {
    applyAttView('table', doc);
    writeAttView('table', store);
  });
}
