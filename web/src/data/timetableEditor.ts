// ── The timetable editor — ported out of `app/static/timetable.js` (W5.4a).
//
// Structural note, same as attView.ts: the MARKUP stays server-rendered
// (app/templates/timetable.html). This module owns behaviour only. It does
// render two containers — `#tt-palette` and `#tt-grid-body` — but only because
// the template ships them EMPTY on purpose (timetable.html:36,38) and the
// classic script was what filled them. That is unchanged: the grid is data,
// not template, and cannot exist until /api/timetable answers.
//
// PERSISTENCE IS NOT localStorage. `timetable.js` never wrote to a store; it
// POSTs the whole slot map to `/api/timetable` on Save. So this module keeps a
// working copy in memory and there is no storage helper to reuse — there is no
// `web/src/data/local.ts` in the tree, and inventing one to wrap a POST would
// create a second persistence path, which is the bug this port exists to
// avoid. Save is the only writer, exactly as before.
//
// The editor is ARCHIVED by default (`TIMETABLE_EDITOR=archived`,
// app/views/timetable.py:59): #tt-edit-btn does not render and POST 403s
// unless the env flips it. Every binder here returns early on a page without
// the editor, so a normal visitor pays nothing.

/** One class slot. `period` is the grid column, 1-7 (0 is a break, never editable). */
export interface TtSlot {
  code: string;
  name: string;
}

/** A palette entry — a course the student can drop into a slot. */
export interface TtSubject extends TtSlot {
  credits?: number;
  custom?: boolean;
}

/** `{ 'Monday-3': {code,name} }`, keyed exactly as the API expects. */
export type TtSlots = Record<string, TtSlot>;

/** The grid's columns. Copied from timetable.js:33-44 — server and client must
 *  agree on which periods are classes, or a drop lands in a break. */
export const CLASS_PERIODS: readonly { period: number; start: string; end: string }[] = [
  { period: 1, start: '09:30', end: '10:20' },
  { period: 2, start: '10:20', end: '11:10' },
  { period: 3, start: '11:20', end: '12:10' },
  { period: 4, start: '12:10', end: '13:00' },
  { period: 5, start: '14:10', end: '15:00' },
  { period: 6, start: '15:00', end: '15:50' },
  { period: 7, start: '16:00', end: '16:50' },
];

export const DAYS: readonly string[] = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];

/** ids, in one place. */
const NODES = {
  view: 'tab-timetable-view',
  editor: 'tt-editor',
  editBtn: 'tt-edit-btn',
  saveBtn: 'tt-save-btn',
  cancelBtn: 'tt-cancel-btn',
  addBtn: 'tt-add-subject-btn',
  palette: 'tt-palette',
  grid: 'tt-grid-body',
  historyList: 'tt-history-list',
  historyCount: 'tt-history-count',
  modal: 'add-subject-modal',
  code: 'subj-code',
  name: 'subj-name',
  confirm: 'subj-confirm-btn',
} as const;

declare global {
  interface Window {
    /** W5.2a error toast, published by main.ts. Absent without the bundle. */
    __osrmShowError?: (msg: string) => void;
    /** W5.1b in-place repaint, published by main.ts. Absent without the bundle. */
    __osrmRefreshData?: () => Promise<void>;
    /** Set by `bindTimetableEditor` itself, on a real bind. The e2e suite reads
     *  it to prove the BUNDLE bound the editor — without it, an unbound bundle
     *  is invisible because timetable.js binds the very same ids. */
    __osrmTimetableEditorBound?: boolean;
  }
}

/** The editor's whole working state. */
export interface TtEditor {
  /** Group the save writes into — null until /api/timetable answers. */
  groupKey: string | null;
  subjects: TtSubject[];
  slots: TtSlots;
  /** Set by any mutation; cleared by save and by close. */
  dirty: boolean;
}

/** A fresh editor over an API payload. */
export function readEditor(
  data: {
    group_key?: string | null;
    subjects?: TtSubject[];
    slots?: Record<string, TtSlot | null>;
  } | null,
): TtEditor {
  const slots: TtSlots = {};
  for (const [k, v] of Object.entries(data?.slots ?? {})) {
    // The API returns null for an empty slot; only a coded one is a placement.
    if (v && v.code) slots[k] = { code: v.code, name: v.name };
  }
  return {
    groupKey: data?.group_key ?? null,
    subjects: [...(data?.subjects ?? [])],
    slots,
    dirty: false,
  };
}

/** Immutable place. Returns the SAME object when the slot already holds it, so
 *  a redundant drop does not mark the editor dirty. */
export function placeSlot(e: TtEditor, key: string, s: TtSlot): TtEditor {
  const prev = e.slots[key];
  if (prev && prev.code === s.code && prev.name === s.name) return e;
  return { ...e, slots: { ...e.slots, [key]: { code: s.code, name: s.name } }, dirty: true };
}

/** Clear a slot. A no-op on an already-empty slot is NOT dirty. */
export function clearSlot(e: TtEditor, key: string): TtEditor {
  if (!e.slots[key]) return e;
  const slots = { ...e.slots };
  delete slots[key];
  return { ...e, slots, dirty: true };
}

/** Register a subject, or rename one already in the roster. Returns the same
 *  object for a blank submission (the confirm button is not disabled). */
export function addSubject(e: TtEditor, rawCode: string, rawName: string): TtEditor {
  const code = rawCode.trim().toUpperCase();
  const name = rawName.trim();
  if (!code || !name) return e;
  const i = e.subjects.findIndex((s) => s.code === code);
  if (i >= 0) {
    if (e.subjects[i]!.name === name) return e;
    const subjects = [...e.subjects];
    subjects[i] = { ...subjects[i]!, name };
    return { ...e, subjects, dirty: true };
  }
  return {
    ...e,
    subjects: [...e.subjects, { code, name, credits: 0, custom: true }],
    dirty: true,
  };
}

/** The POST body. `custom` subjects are the only ones the server can persist as
 *  new rows — the official ones already exist (timetable.js:345). */
export function saveBody(e: TtEditor): { slots: TtSlots; custom_subjects: TtSubject[] } {
  return { slots: e.slots, custom_subjects: e.subjects.filter((s) => s.custom) };
}

/** Element helper. Text only, never innerHTML — every value here is
 *  student-controlled (timetable.js:68 says the same, for the same reason). */
function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

/**
 * Paint ONE cell. Exported separately from `applyGrid` so a row-level test can
 * assert a single placement without building a whole grid.
 */
export function applyCell(
  cell: HTMLElement,
  e: TtEditor,
  key: string,
  onClear: () => void,
  onDrop: (s: TtSlot) => void,
): void {
  const placed = e.slots[key];
  cell.classList.toggle('tt-cell-filled', !!placed);
  cell.replaceChildren();
  if (placed) {
    cell.append(el('span', 'cell-code', placed.code));
    const rm = el('button', 'cell-remove', '\u00d7');
    rm.type = 'button';
    rm.dataset.key = key;
    rm.setAttribute('aria-label', `Clear ${placed.code} from ${key.replace('-', ' period ')}`);
    rm.addEventListener('click', onClear);
    cell.append(rm);
  }
  cell.addEventListener('dragover', (ev) => {
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
    cell.classList.add('tt-cell-hover');
  });
  cell.addEventListener('dragleave', () => cell.classList.remove('tt-cell-hover'));
  cell.addEventListener('drop', (ev) => {
    ev.preventDefault();
    cell.classList.remove('tt-cell-hover');
    const raw = ev.dataTransfer?.getData('text/plain');
    if (!raw) return;
    try {
      const s = JSON.parse(raw) as TtSlot;
      if (s && s.code) onDrop(s);
    } catch {
      // a foreign drag (a file, a link) — not ours, ignore it
    }
  });
}

/** Paint the palette. Called on open and after every add-subject. */
export function applyPalette(
  palette: HTMLElement,
  e: TtEditor,
  onPick: (s: TtSubject) => void,
): void {
  palette.replaceChildren();
  for (const s of e.subjects) {
    const block = el('div', 'tt-subject-block');
    block.draggable = true;
    block.dataset.code = s.code;
    block.dataset.name = s.name;
    // A tap/Enter pick is the keyboard AND touch path. HTML5 drag is
    // mouse-only, which is exactly why timetable.js needed drag-drop-touch
    // (the tt-touch-drag row). One click handler does that job with no
    // vendored library, and it is what a screen reader can activate.
    block.tabIndex = 0;
    block.setAttribute('role', 'button');
    block.setAttribute('aria-label', `Place ${s.code}`);
    block.append(el('span', 'tt-subject-code', s.code), el('span', 'tt-subject-name', s.name));
    block.addEventListener('dragstart', (ev) => {
      ev.dataTransfer?.setData('text/plain', JSON.stringify({ code: s.code, name: s.name }));
      if (ev.dataTransfer) ev.dataTransfer.effectAllowed = 'copy';
      block.classList.add('dragging');
    });
    block.addEventListener('dragend', () => block.classList.remove('dragging'));
    block.addEventListener('click', () => onPick(s));
    block.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        onPick(s);
      }
    });
    palette.append(block);
  }
}

/** Paint the whole grid: a header row of times, then one row per day. */
export function applyGrid(
  grid: HTMLElement,
  e: TtEditor,
  handlers: {
    onClear: (key: string) => void;
    onDrop: (key: string, s: TtSlot) => void;
    onSelect: (key: string) => void;
  },
): void {
  grid.replaceChildren();
  const header = el('div', 'tt-grid-header');
  header.append(el('div'));
  for (const p of CLASS_PERIODS) {
    const h = el('div', 'tt-grid-time', p.start);
    h.title = `${p.start} - ${p.end}`;
    header.append(h);
  }
  grid.append(header);

  for (const day of DAYS) {
    const row = el('div', 'tt-grid-row');
    row.append(el('div', 'tt-grid-day', day.slice(0, 3)));
    for (const p of CLASS_PERIODS) {
      const key = `${day}-${p.period}`;
      const cell = el('div', 'tt-grid-cell');
      cell.dataset.day = day;
      cell.dataset.period = String(p.period);
      cell.dataset.key = key;
      applyCell(cell, e, key, () => handlers.onClear(key), (s) => handlers.onDrop(key, s));
      cell.addEventListener('click', (ev) => {
        if ((ev.target as HTMLElement).closest('.cell-remove')) return;
        handlers.onSelect(key);
      });
      row.append(cell);
    }
    grid.append(row);
  }
}

/** Relative time for the audit log (timetable.js:162-169). */
export function relTime(ts: number, now = Date.now()): string {
  const s = Math.floor(now / 1000) - ts;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 604800) return `${Math.floor(s / 86400)}d ago`;
  return new Date(ts * 1000).toLocaleDateString([], { day: '2-digit', month: 'short' });
}

const DAY_ABBR: Record<string, string> = {
  Monday: 'Mon',
  Tuesday: 'Tue',
  Wednesday: 'Wed',
  Thursday: 'Thu',
  Friday: 'Fri',
};

export interface TtChange {
  day?: string;
  period?: number;
  action?: string;
  from?: TtSlot | null;
  to?: TtSlot | null;
}

/** One terse symbol line (timetable.js:148-154). */
export function chLine(ch: TtChange): string {
  const where = `${DAY_ABBR[ch.day ?? ''] ?? ch.day ?? ''} P${ch.period ?? ''}`;
  const code = (s?: TtSlot | null) => (s ? s.code || '?' : '');
  if (ch.action === 'added') return `${where}: +${code(ch.to)}`;
  if (ch.action === 'removed') return `${where}: -${code(ch.from)}`;
  return `${where}: ${code(ch.from)} \u2192 ${code(ch.to)}`;
}

/** The same line in full words, for `title=` (timetable.js:155-161). */
export function chFull(ch: TtChange): string {
  const lab = (s?: TtSlot | null) => (s ? `${s.code || ''}${s.name ? ` ${s.name}` : ''}` : 'empty');
  const where = `${ch.day ?? ''} P${ch.period ?? ''}`;
  if (ch.action === 'added') return `${where} \u00b7 added ${lab(ch.to)}`;
  if (ch.action === 'removed') return `${where} \u00b7 removed ${lab(ch.from)}`;
  return `${where} \u00b7 changed ${lab(ch.from)} \u2192 ${lab(ch.to)}`;
}

/**
 * Paint the audit log. Text nodes only — every field is another student's
 * name or a code (timetable.js:68 makes the same point).
 */
export function applyHistory(
  list: HTMLElement | null,
  count: HTMLElement | null,
  entries: { name?: string; netid?: string; at: number; changes?: TtChange[] }[],
  now = Date.now(),
): void {
  if (!list) return;
  if (count) count.textContent = String(entries.length);
  list.replaceChildren();
  if (!entries.length) {
    list.append(el('p', 'text-base-content/60', 'No edits recorded yet.'));
    return;
  }
  for (const e of entries) {
    const item = el('div', 'py-2 border-b border-base-300 last:border-b-0');
    const head = el('div', 'flex justify-between items-baseline gap-2');
    const who = el('span', 'text-sm font-medium', e.name || e.netid || '');
    if (e.name && e.netid) {
      who.append(el('span', 'font-mono text-xs text-base-content/60 ml-1', e.netid));
    }
    const when = el('span', 'text-xs text-base-content/60 shrink-0', relTime(e.at, now));
    when.title = new Date(e.at * 1000).toLocaleString();
    head.append(who, when);
    item.append(head);

    const box = el('div', 'text-xs text-base-content/60 mt-0.5 space-y-0.5');
    const chs = e.changes ?? [];
    chs.forEach((ch, i) => {
      const line = el('div', i >= 3 ? 'tt-h hidden' : '', chLine(ch));
      line.title = chFull(ch);
      box.append(line);
    });
    if (chs.length > 3) {
      const rest = chs.length - 3;
      const tog = el('div', 'cursor-pointer', `+${rest} more`);
      tog.title = 'show all changes';
      tog.addEventListener('click', () => {
        const hid = box.querySelectorAll<HTMLElement>('.tt-h');
        const wasCollapsed = hid[0]?.classList.contains('hidden') ?? false;
        hid.forEach((n) => n.classList.toggle('hidden', !wasCollapsed));
        tog.textContent = wasCollapsed ? 'show less' : `+${rest} more`;
      });
      box.append(tog);
    }
    item.append(box);
    list.append(item);
  }
}

/**
 * Bind the whole editor. Bound once from `main.ts`, like `bindAttView`.
 *
 * Returns false on a page with no editor (the archived default, or any route
 * that is not /timetable), so the caller — and the test — can tell "nothing to
 * wire" from "wired but broken".
 */
export function bindTimetableEditor(doc: Document = document): boolean {
  const editBtn = doc.getElementById(NODES.editBtn);
  const editor = doc.getElementById(NODES.editor);
  const grid = doc.getElementById(NODES.grid);
  const palette = doc.getElementById(NODES.palette);
  if (!editBtn || !editor || !grid || !palette) return false;
  // Bound per ELEMENT, not per page. A soft navigation (nav/softNav.ts) swaps the
  // timetable panel in and the island re-renders it, so the nodes this would bind
  // are new ones — while the previous call's `__osrmTimetableEditorBound` marker
  // still says "bound". The dataset flag is the truth: it travels with the node,
  // so a re-render rebinds and a repeated call on the same markup does nothing.
  if (editBtn.dataset.ttBound) return true;
  editBtn.dataset.ttBound = '1';

  const q = (id: string) => doc.getElementById(id);
  const hiddenIds = [NODES.saveBtn, NODES.cancelBtn, NODES.addBtn] as const;

  let state = readEditor(null);
  /** The slot a palette tap lands in. Clicking a cell arms it. */
  let selected: string | null = null;

  const markSelected = () => {
    grid.querySelectorAll('.tt-cell-sel').forEach((n) => n.classList.remove('tt-cell-sel'));
    if (selected) grid.querySelector<HTMLElement>(`[data-key="${selected}"]`)?.classList.add('tt-cell-sel');
  };

  const paint = () => {
    applyPalette(palette, state, (s) => {
      if (!selected) return;
      state = placeSlot(state, selected, { code: s.code, name: s.name });
      paint();
    });
    applyGrid(grid, state, {
      onClear: (key) => {
        state = clearSlot(state, key);
        paint();
      },
      onDrop: (key, s) => {
        state = placeSlot(state, key, s);
        paint();
      },
      onSelect: (key) => {
        selected = key;
        markSelected();
      },
    });
    // applyGrid rebuilt the nodes, so the selection class has to go back on.
    markSelected();
  };

  const setEditorOpen = (open: boolean) => {
    const view = q(NODES.view);
    if (view) view.style.display = open ? 'none' : '';
    editBtn.style.display = open ? 'none' : '';
    editor.style.display = open ? 'block' : 'none';
    for (const id of hiddenIds) q(id)?.classList.toggle('hidden', !open);
  };

  const openEditor = async () => {
    setEditorOpen(true);
    try {
      const r = await fetch('/api/timetable', { credentials: 'same-origin' });
      if (r.redirected) {
        location.href = '/login';
        return;
      }
      const data = await r.json();
      if (!data.ok) return;
      state = readEditor(data);
      selected = null;
      paint();
    } catch {
      // the grid stays empty; Save is guarded on groupKey and says why
    }
  };

  const closeEditor = () => {
    setEditorOpen(false);
    state = readEditor(null);
    selected = null;
  };

  const save = async () => {
    if (!state.groupKey) {
      window.__osrmShowError?.('No timetable group found. Login again to create one.');
      return;
    }
    try {
      const r = await fetch('/api/timetable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(saveBody(state)),
      });
      if (r.redirected) {
        location.href = '/login';
        return;
      }
      const data = await r.json();
      if (!data.ok) {
        window.__osrmShowError?.(`Save failed: ${data.error || 'unknown error'}`);
        return;
      }
      closeEditor();
      // Same contract as timetable.js:342: repaint in place, and reload only
      // when the bundle never ran (so there is no bridge to call).
      if (window.__osrmRefreshData) void window.__osrmRefreshData();
      else location.reload();
    } catch (err) {
      window.__osrmShowError?.(`Save failed: ${(err as Error).message}`);
    }
  };

  const openAddSubject = () => {
    const modal = q(NODES.modal) as HTMLDialogElement | null;
    const codeIn = q(NODES.code) as HTMLInputElement | null;
    if (!modal || !codeIn) return;
    codeIn.value = '';
    const nameIn = q(NODES.name) as HTMLInputElement | null;
    if (nameIn) nameIn.value = '';
    modal.showModal();
    codeIn.focus();
  };

  editBtn.addEventListener('click', () => void openEditor());
  q(NODES.saveBtn)?.addEventListener('click', () => void save());
  q(NODES.cancelBtn)?.addEventListener('click', closeEditor);
  q(NODES.addBtn)?.addEventListener('click', openAddSubject);

  // timetable.js re-bound the confirm button on every open (:335) and tore it
  // down on close (:331) to stop the listeners stacking. One listener bound
  // once does the same job without the bookkeeping.
  const codeEl = q(NODES.code) as HTMLInputElement | null;
  const nameEl = q(NODES.name) as HTMLInputElement | null;
  q(NODES.confirm)?.addEventListener('click', () => {
    const before = state;
    state = addSubject(state, codeEl?.value ?? '', nameEl?.value ?? '');
    if (state === before) return; // blank or unchanged — leave the modal open
    (q(NODES.modal) as HTMLDialogElement | null)?.close();
    paint();
  });

  // ── edit history ───────────────────────────────────────────────────────
  const histList = q(NODES.historyList);
  if (histList) {
    fetch('/api/timetable/history', { credentials: 'same-origin' })
      .then((r) => (r.redirected ? null : r.json()))
      .then((data) => {
        const entries = (data && data.ok && data.entries) || [];
        applyHistory(histList, q(NODES.historyCount), entries);
      })
      .catch(() => {
        histList.replaceChildren(el('p', 'text-base-content/60', 'Could not load edit history.'));
      });
  }

  window.__osrmTimetableEditorBound = true;
  return true;
}
