import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  CLASS_PERIODS,
  DAYS,
  addSubject,
  applyCell,
  applyGrid,
  applyHistory,
  chFull,
  chLine,
  clearSlot,
  placeSlot,
  readEditor,
  relTime,
  saveBody,
  bindTimetableEditor,
} from './timetableEditor';
import type { TtEditor, TtSlot } from './timetableEditor';

// W5.4a ported the timetable EDITOR out of app/static/timetable.js. One
// describe per matrix row, because those rows are the exit condition for
// deleting that file. A row that regresses here is a row W5.4 cannot delete.

const S = (code: string, name = code): TtSlot => ({ code, name });

/** jsdom ships no DataTransfer. DragEvent only ever calls getData/setData on
 *  it, so a Map is the whole contract. */
class FakeDT {
  readonly store = new Map<string, string>();
  dropEffect = 'none';
  effectAllowed = 'none';
  setData(t: string, v: string) { this.store.set(t, v); }
  getData(t: string) { return this.store.get(t) ?? ''; }
}
const dtWith = (v: string) => {
  const d = new FakeDT();
  d.setData('text/plain', v);
  return d as unknown as DataTransfer;
};

/** jsdom has no DragEvent either. The handler only reads `dataTransfer`, so a
 *  plain Event carrying that field IS the event it sees. */
const dropEvent = (dataTransfer: DataTransfer) => {
  const ev = new Event('drop', { bubbles: true, cancelable: true });
  Object.defineProperty(ev, 'dataTransfer', { value: dataTransfer });
  return ev;
};

/** A payload shaped like GET /api/timetable — note the null empty slot. */
const payload = () => ({
  ok: true,
  group_key: 'G1',
  subjects: [{ code: 'A', name: 'Alpha' }, { code: 'B', name: 'Beta' }],
  slots: { 'Monday-1': S('A', 'Alpha'), 'Tuesday-2': null },
});

const doc = (): Document => {
  const d = document.implementation.createHTMLDocument('timetable');
  d.body.innerHTML = `
    <div id="tab-timetable-view"><p>panels</p></div>
    <button id="tt-edit-btn">Edit</button>
    <div id="tt-editor" style="display:none">
      <button id="tt-save-btn" class="hidden">Save</button>
      <button id="tt-cancel-btn" class="hidden">Cancel</button>
      <button id="tt-add-subject-btn" class="hidden">+ Add</button>
      <div id="tt-palette"></div>
      <div id="tt-grid-body"></div>
    </div>
    <dialog id="add-subject-modal">
      <input id="subj-code"><input id="subj-name">
      <button id="subj-confirm-btn">Add</button>
    </dialog>`;
  return d;
};

const cellFor = (root: HTMLElement, key: string) =>
  root.querySelector<HTMLElement>(`[data-key="${key}"]`)!;

describe('readEditor / persistence shape (tt-save)', () => {
  it('treats a null slot as empty and a coded slot as a placement', () => {
    const e = readEditor(payload());
    expect(e.groupKey).toBe('G1');
    expect(e.slots['Monday-1']).toEqual({ code: 'A', name: 'Alpha' });
    expect(e.slots['Tuesday-2']).toBeUndefined();
    expect(e.dirty).toBe(false); // nothing changed yet
  });

  it('sends only custom subjects — official ones already exist server-side', () => {
    let e: TtEditor = readEditor(payload());
    e = addSubject(e, 'zz9001', 'Mine');
    const body = saveBody(e);
    expect(body.custom_subjects.map((s) => s.code)).toEqual(['ZZ9001']);
    expect(body.slots['Monday-1']).toEqual({ code: 'A', name: 'Alpha' });
  });

  it('a null payload is an empty editor, not a crash', () => {
    expect(readEditor(null)).toEqual({ groupKey: null, subjects: [], slots: {}, dirty: false });
  });
});

describe('selection + place + clear + dirty (tt-open-editor, tt-cell-drop, tt-cell-remove)', () => {
  const base = () => readEditor(payload());

  it('place marks dirty and lands in the slot', () => {
    const e = placeSlot(base(), 'Wednesday-3', S('B', 'Beta'));
    expect(e.slots['Wednesday-3']).toEqual({ code: 'B', name: 'Beta' });
    expect(e.dirty).toBe(true);
  });

  it('placing the SAME value again is not a change (same object, still clean)', () => {
    const e0 = base();
    const e1 = placeSlot(e0, 'Monday-1', S('A', 'Alpha'));
    expect(e1).toBe(e0);
    expect(e1.dirty).toBe(false);
  });

  it('clear removes the slot and marks dirty', () => {
    const e = clearSlot(base(), 'Monday-1');
    expect(e.slots['Monday-1']).toBeUndefined();
    expect(e.dirty).toBe(true);
  });

  it('clearing an EMPTY slot is not a change', () => {
    const e0 = base();
    expect(clearSlot(e0, 'Thursday-5')).toBe(e0);
  });

  it('mutations never touch the input object (immutable)', () => {
    const e0 = base();
    placeSlot(e0, 'Friday-7', S('C'));
    clearSlot(e0, 'Monday-1');
    expect(Object.keys(e0.slots)).toEqual(['Monday-1']);
    expect(e0.dirty).toBe(false);
  });
});

describe('add subject (tt-add-subject)', () => {
  it('uppercases the code, trims, and marks it custom', () => {
    const e = addSubject(readEditor(payload()), '  zz9001 ', ' My Subject ');
    expect(e.subjects.at(-1)).toEqual({ code: 'ZZ9001', name: 'My Subject', credits: 0, custom: true });
    expect(e.dirty).toBe(true);
  });

  it('an existing code RENAMES instead of duplicating', () => {
    const e = addSubject(readEditor(payload()), 'a', 'Alpha Renamed');
    expect(e.subjects.filter((s) => s.code === 'A')).toHaveLength(1);
    expect(e.subjects.find((s) => s.code === 'A')!.name).toBe('Alpha Renamed');
  });

  it('blank code or name is refused — the confirm button is not disabled', () => {
    const e0 = readEditor(payload());
    expect(addSubject(e0, '', 'Name')).toBe(e0);
    expect(addSubject(e0, 'CODE', '   ')).toBe(e0);
  });
});

describe('grid render (tt-palette-drag, tt-cell-drop, tt-cell-remove)', () => {
  it('paints a header per class period and a row per day', () => {
    const grid = document.createElement('div');
    applyGrid(grid, readEditor(payload()), { onClear: vi.fn(), onDrop: vi.fn(), onSelect: vi.fn() });
    expect(grid.querySelectorAll('.tt-grid-row')).toHaveLength(DAYS.length);
    expect(grid.querySelectorAll('.tt-grid-header .tt-grid-time')).toHaveLength(CLASS_PERIODS.length);
    expect(grid.querySelectorAll('.tt-grid-cell')).toHaveLength(DAYS.length * CLASS_PERIODS.length);
    // periods are the class ones only — no break column with a 0
    expect(CLASS_PERIODS.map((p) => p.period)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it('a filled cell shows the code and a remove button that clears it', () => {
    const grid = document.createElement('div');
    const onClear = vi.fn();
    applyGrid(grid, readEditor(payload()), { onClear, onDrop: vi.fn(), onSelect: vi.fn() });
    const cell = cellFor(grid, 'Monday-1');
    expect(cell.classList.contains('tt-cell-filled')).toBe(true);
    expect(cell.querySelector('.cell-code')!.textContent).toBe('A');
    cell.querySelector<HTMLElement>('.cell-remove')!.click();
    expect(onClear).toHaveBeenCalledWith('Monday-1');
  });

  it('a drop from another subject JSON lands in that slot', () => {
    const cell = document.createElement('div');
    const onDrop = vi.fn();
    applyCell(cell, readEditor(payload()), 'Friday-2', vi.fn(), onDrop);
    cell.dispatchEvent(dropEvent(dtWith(JSON.stringify({ code: 'B', name: 'Beta' }))));
    expect(onDrop).toHaveBeenCalledWith({ code: 'B', name: 'Beta' });
  });

  it('a foreign drop (not our JSON) is ignored, not thrown', () => {
    const cell = document.createElement('div');
    const onDrop = vi.fn();
    applyCell(cell, readEditor(payload()), 'Friday-2', vi.fn(), onDrop);
    expect(() =>
      cell.dispatchEvent(dropEvent(dtWith('not json'))),
    ).not.toThrow();
    expect(onDrop).not.toHaveBeenCalled();
  });

  it('an empty cell renders no remove button', () => {
    const cell = document.createElement('div');
    applyCell(cell, readEditor(payload()), 'Friday-2', vi.fn(), vi.fn());
    expect(cell.querySelector('.cell-remove')).toBeNull();
  });
});

describe('touch/keyboard path (tt-touch-drag)', () => {
  it('a palette tap places into the armed slot, Enter too', async () => {
    // The MobileDragDrop polyfill existed because HTML5 drag is mouse-only.
    // The port replaces it with activation that works on every pointer.
    const d = doc();
    const grid = d.getElementById('tt-grid-body')!;
    const palette = d.getElementById('tt-palette')!;
    const { applyPalette } = await import('./timetableEditor');

    let picked: TtSlot | null = null;
    applyPalette(palette, readEditor(payload()), (s) => (picked = s));
    const block = palette.querySelector<HTMLElement>('.tt-subject-block')!;
    expect(block.tabIndex).toBe(0);
    expect(block.getAttribute('role')).toBe('button');

    block.click();
    expect(picked).toEqual({ code: 'A', name: 'Alpha' });

    picked = null;
    block.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(picked).toEqual({ code: 'A', name: 'Alpha' });

    picked = null;
    block.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    expect(picked).toEqual({ code: 'A', name: 'Alpha' });
    expect(grid).toBeTruthy();
  });
});

describe('edit history (tt-edit-history)', () => {
  it('renders text, collapses past three changes, and toggles them open', () => {
    const list = document.createElement('div');
    const count = document.createElement('span');
    const at = Math.floor(Date.now() / 1000) - 90;
    applyHistory(list, count, [
      {
        name: 'Navya', netid: 'ng2776', at,
        changes: [1, 2, 3, 4, 5].map((p) => ({ day: 'Monday', period: p, action: 'added', to: S('A') })),
      },
    ]);
    expect(count.textContent).toBe('1');
    expect(list.textContent).toContain('Navya');
    expect(list.querySelectorAll('.tt-h').length).toBe(2); // 5 changes, 3 shown
    const tog = list.querySelector<HTMLElement>('.cursor-pointer')!;
    expect(tog.textContent).toBe('+2 more');
    tog.click();
    expect(list.querySelectorAll('.tt-h.hidden').length).toBe(0);
    expect(tog.textContent).toBe('show less');
  });

  it('an empty log says so instead of rendering nothing', () => {
    const list = document.createElement('div');
    applyHistory(list, document.createElement('span'), []);
    expect(list.textContent).toContain('No edits recorded yet');
  });

  it('formats changes and relative time like the original', () => {
    expect(chLine({ day: 'Monday', period: 3, action: 'added', to: S('A') })).toBe('Mon P3: +A');
    expect(chLine({ day: 'Monday', period: 3, action: 'removed', from: S('A') })).toBe('Mon P3: -A');
    expect(chLine({ day: 'Monday', period: 3, from: S('A'), to: S('B') })).toBe('Mon P3: A → B');
    expect(chFull({ day: 'Monday', period: 3, action: 'removed', from: S('A', 'Alpha') }))
      .toBe('Monday P3 · removed A Alpha');
    const now = 1_000_000_000_000;
    expect(relTime(now / 1000 - 10, now)).toBe('just now');
    expect(relTime(now / 1000 - 120, now)).toBe('2m ago');
    expect(relTime(now / 1000 - 7200, now)).toBe('2h ago');
    expect(relTime(now / 1000 - 172800, now)).toBe('2d ago');
  });
});

describe('bindTimetableEditor (tt-open-editor, tt-close-editor, tt-save)', () => {
  let d: Document;

  beforeEach(() => {
    d = doc();
    vi.restoreAllMocks();
  });

  it('returns false on a page with no editor (the archived default)', () => {
    expect(bindTimetableEditor(document.implementation.createHTMLDocument('x'))).toBe(false);
  });

  it('open reveals the editor, hides the panels and un-hides the actions', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ redirected: false, json: async () => payload() })));
    bindTimetableEditor(d);
    d.getElementById('tt-edit-btn')!.click();
    await vi.waitFor(() => expect(d.querySelectorAll('.tt-grid-cell').length).toBeGreaterThan(0));

    expect((d.getElementById('tt-editor') as HTMLElement).style.display).toBe('block');
    expect((d.getElementById('tab-timetable-view') as HTMLElement).style.display).toBe('none');
    for (const id of ['tt-save-btn', 'tt-cancel-btn', 'tt-add-subject-btn']) {
      expect(d.getElementById(id)!.classList.contains('hidden')).toBe(false);
    }
    // the palette came from the API, and the grid already shows the placement
    expect(d.querySelectorAll('.tt-subject-block').length).toBe(2);
    expect(cellFor(d.getElementById('tt-grid-body')!, 'Monday-1').classList.contains('tt-cell-filled')).toBe(true);
  });

  it('cancel closes and discards the working copy', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ redirected: false, json: async () => payload() })));
    bindTimetableEditor(d);
    d.getElementById('tt-edit-btn')!.click();
    await vi.waitFor(() => expect(d.querySelectorAll('.tt-grid-cell').length).toBeGreaterThan(0));
    d.getElementById('tt-cancel-btn')!.click();
    expect((d.getElementById('tt-editor') as HTMLElement).style.display).toBe('none');
    expect(d.getElementById('tt-save-btn')!.classList.contains('hidden')).toBe(true);
  });

  it('click a cell, then a subject, and SAVE posts the slot (the whole point)', async () => {
    const calls: { url: string; body?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body as string | undefined });
      return { redirected: false, json: async () => payload() };
    }));
    const refresh = vi.fn(async () => {});
    (window as unknown as { __osrmRefreshData?: () => Promise<void> }).__osrmRefreshData = refresh;

    bindTimetableEditor(d);
    d.getElementById('tt-edit-btn')!.click();
    await vi.waitFor(() => expect(d.querySelectorAll('.tt-grid-cell').length).toBeGreaterThan(0));

    cellFor(d.getElementById('tt-grid-body')!, 'Wednesday-4').click(); // arm
    const block = [...d.querySelectorAll<HTMLElement>('.tt-subject-block')]
      .find((b) => b.dataset.code === 'B')!;
    block.click();                                                     // place
    expect(cellFor(d.getElementById('tt-grid-body')!, 'Wednesday-4')
      .querySelector('.cell-code')!.textContent).toBe('B');

    d.getElementById('tt-save-btn')!.click();
    await vi.waitFor(() => expect(calls.some((c) => c.body)).toBe(true));

    const post = calls.find((c) => c.body)!;
    const body = JSON.parse(post.body!);
    expect(body.slots['Wednesday-4']).toEqual({ code: 'B', name: 'Beta' });
    expect(body.slots['Monday-1']).toEqual({ code: 'A', name: 'Alpha' });
    await vi.waitFor(() => expect(refresh).toHaveBeenCalled()); // repaint, no reload
  });

  it('save with no groupKey toasts instead of POSTing', async () => {
    const fetchSpy = vi.fn(async () => ({
      redirected: false,
      json: async () => ({ ...payload(), group_key: null }),
    }));
    vi.stubGlobal('fetch', fetchSpy);
    const showError = vi.fn();
    (window as unknown as { __osrmShowError?: (m: string) => void }).__osrmShowError = showError;

    bindTimetableEditor(d);
    d.getElementById('tt-edit-btn')!.click();
    await vi.waitFor(() => expect(d.querySelectorAll('.tt-grid-cell').length).toBeGreaterThan(0));
    d.getElementById('tt-save-btn')!.click();
    await vi.waitFor(() => expect(showError).toHaveBeenCalled());
    expect(showError.mock.calls[0]![0]).toContain('No timetable group found');
    const posts = fetchSpy.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === 'POST',
    );
    expect(posts).toHaveLength(0); // the GET happened; no write was attempted
  });

  it('a failed save toasts the server reason and keeps the editor open', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) =>
      init?.body
        ? { redirected: false, json: async () => ({ ok: false, error: 'quota' }) }
        : { redirected: false, json: async () => payload() },
    ));
    const showError = vi.fn();
    (window as unknown as { __osrmShowError?: (m: string) => void }).__osrmShowError = showError;

    bindTimetableEditor(d);
    d.getElementById('tt-edit-btn')!.click();
    await vi.waitFor(() => expect(d.querySelectorAll('.tt-grid-cell').length).toBeGreaterThan(0));
    d.getElementById('tt-save-btn')!.click();
    await vi.waitFor(() => expect(showError).toHaveBeenCalled());
    expect(showError.mock.calls[0]![0]).toBe('Save failed: quota');
    expect((d.getElementById('tt-editor') as HTMLElement).style.display).toBe('block');
  });

  it('a remove button on a filled cell clears it in the DOM', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ redirected: false, json: async () => payload() })));
    bindTimetableEditor(d);
    d.getElementById('tt-edit-btn')!.click();
    await vi.waitFor(() => expect(d.querySelectorAll('.tt-grid-cell').length).toBeGreaterThan(0));

    const grid = d.getElementById('tt-grid-body')!;
    cellFor(grid, 'Monday-1').querySelector<HTMLElement>('.cell-remove')!.click();
    expect(cellFor(grid, 'Monday-1').classList.contains('tt-cell-filled')).toBe(false);
    expect(cellFor(grid, 'Monday-1').querySelector('.cell-remove')).toBeNull();
  });
});
