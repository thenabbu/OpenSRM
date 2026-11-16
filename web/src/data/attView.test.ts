import { beforeEach, describe, expect, it } from 'vitest';
import { ATT_VIEW_KEY, applyAttView, bindAttView, readAttView, writeAttView } from './attView';

// W5.2c ported the attendance toggle out of dash.js. The five things that would
// each break it silently, and nothing else:
//   1. the default is graph, and an unknown saved value is not trusted;
//   2. a click flips BOTH nodes and the aria/btn-active pairing on BOTH buttons;
//   3. visibility is the `hidden` ATTRIBUTE (never a class — the golden capture
//      and the a11y assertions read the attribute);
//   4. the saved value SURVIVES A RELOAD — a fresh DOM, same store;
//   5. a throwing localStorage (private-mode Safari) does not kill the toggle.

/** A reload: same store, brand-new document as the server would render it. */
const page = (): Document => {
  const doc = document.implementation.createHTMLDocument('attendance');
  doc.body.innerHTML = `
    <button id="att-view-graph" class="btn btn-square btn-active" aria-pressed="true"></button>
    <button id="att-view-table" class="btn btn-square" aria-pressed="false"></button>
    <div id="att-graph"></div>
    <div id="att-table" hidden></div>`;
  return doc;
};

const state = (doc: Document) => {
  const q = (id: string) => doc.getElementById(id) as HTMLElement;
  return {
    graphHidden: q('att-graph').hidden,
    tableHidden: q('att-table').hidden,
    graphPressed: q('att-view-graph').getAttribute('aria-pressed'),
    tablePressed: q('att-view-table').getAttribute('aria-pressed'),
    graphActive: q('att-view-graph').classList.contains('btn-active'),
    tableActive: q('att-view-table').classList.contains('btn-active'),
  };
};

/** A `Storage` stand-in. `throwing` models private-mode Safari. */
const store = (initial: Record<string, string> = {}, throwing = false): Storage => {
  const map = new Map(Object.entries(initial));
  const boom = () => {
    if (throwing) throw new DOMException('denied', 'SecurityError');
  };
  return {
    get length() { boom(); return map.size; },
    clear: () => { boom(); map.clear(); },
    getItem: (k: string) => { boom(); return map.get(k) ?? null; },
    key: (i: number) => { boom(); return [...map.keys()][i] ?? null; },
    removeItem: (k: string) => { boom(); map.delete(k); },
    setItem: (k: string, v: string) => { boom(); map.set(k, v); },
  } as Storage;
};

let ls: Storage;
beforeEach(() => { ls = store(); });

describe('attView read/write', () => {
  it('defaults to graph when nothing is saved', () => {
    expect(readAttView(ls)).toBe('graph');
  });

  it('round-trips both views', () => {
    writeAttView('table', ls);
    expect(ls.getItem(ATT_VIEW_KEY)).toBe('table');
    expect(readAttView(ls)).toBe('table');
    writeAttView('graph', ls);
    expect(readAttView(ls)).toBe('graph');
  });

  it('ignores a saved value that is not a view', () => {
    ls.setItem(ATT_VIEW_KEY, 'sideways');
    expect(readAttView(ls)).toBe('graph');
  });

  it('survives a throwing store on both read and write', () => {
    const dead = store({}, true);
    expect(readAttView(dead)).toBe('graph');
    expect(() => writeAttView('table', dead)).not.toThrow();
  });
});

describe('applyAttView', () => {
  it('flips both nodes to table, and the aria/btn-active pairing with them', () => {
    const doc = page();
    expect(applyAttView('table', doc)).toBe(true);
    expect(state(doc)).toEqual({
      graphHidden: true,
      tableHidden: false,
      graphPressed: 'false',
      tablePressed: 'true',
      graphActive: false,
      tableActive: true,
    });
  });

  it('flips both nodes back to graph', () => {
    const doc = page();
    applyAttView('table', doc);
    applyAttView('graph', doc);
    expect(state(doc)).toEqual({
      graphHidden: false,
      tableHidden: true,
      graphPressed: 'true',
      tablePressed: 'false',
      graphActive: true,
      tableActive: false,
    });
  });

  it('says "no toggle here" on a page without the nodes', () => {
    const doc = document.implementation.createHTMLDocument('dashboard');
    doc.body.innerHTML = '<div id="other"></div>';
    expect(applyAttView('table', doc)).toBe(false);
  });
});

describe('bindAttView', () => {
  it('restores the saved view on load and writes the click', () => {
    ls.setItem(ATT_VIEW_KEY, 'table');
    const doc = page();
    bindAttView(doc, ls);
    expect(doc.getElementById('att-table')?.hidden).toBe(false);
    expect(doc.getElementById('att-graph')?.hidden).toBe(true);

    (doc.getElementById('att-view-graph') as HTMLElement).click();
    expect(ls.getItem(ATT_VIEW_KEY)).toBe('graph');
    expect(doc.getElementById('att-graph')?.hidden).toBe(false);
    expect(doc.getElementById('att-table')?.hidden).toBe(true);
  });

  it('a click on table survives a RELOAD (fresh document, same store)', () => {
    const first = page();
    bindAttView(first, ls);
    (first.getElementById('att-view-table') as HTMLElement).click();
    expect(ls.getItem(ATT_VIEW_KEY)).toBe('table');

    const afterReload = page();          // the server's markup again: graph shown
    expect(state(afterReload).tableHidden).toBe(true);
    bindAttView(afterReload, ls);            // …and the saved view wins on load
    const s = state(afterReload);
    expect(s.tableHidden).toBe(false);
    expect(s.graphHidden).toBe(true);
    expect(s.tablePressed).toBe('true');
    expect(s.graphActive).toBe(false);
  });

  it('is a no-op on a page without the toggle', () => {
    const doc = document.implementation.createHTMLDocument('dashboard');
    expect(() => bindAttView(doc)).not.toThrow();
  });
});
