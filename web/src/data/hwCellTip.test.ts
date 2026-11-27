import { beforeEach, describe, expect, it } from 'vitest';
import { bindHwCellTip } from './hwCellTip';

// The four things that would each make the bubble useless, and nothing else:
//   1. a tap on a cell opens ONE label carrying the subject, and the native
//      `title` is gone (otherwise both paint at once);
//   2. a tap anywhere else closes it — including on the page background;
//   3. a second tap on the same cell closes it (a toggle, not a trap);
//   4. a cell with no subject falls back to the full title sentence instead
//      of opening an empty bubble.

const page = (): Document => {
  const doc = document.implementation.createHTMLDocument('attendance');
  doc.body.innerHTML = `
    <div class="hw-c hw-c-a" title="Monday · 28 Sep 2026 · h1 · absent · DATA STRUCTURES (21CSC201J)"
         data-subject="DATA STRUCTURES (21CSC201J)">A</div>
    <div class="hw-c" title="No class scheduled · h2" data-subject="">P</div>
    <p id="elsewhere">elsewhere</p>`;
  bindHwCellTip(doc);
  return doc;
};

const cells = (doc: Document) => doc.querySelectorAll('.hw-c');
const tips = (doc: Document) => doc.querySelectorAll('.hw-tip');
// An inert document (createHTMLDocument) has no defaultView, so events are
// built on the global window and dispatched onto its nodes — same event,
// same path through the delegated listener.
const tap = (_doc: Document, el: Element): void => {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
};

describe('bindHwCellTip', () => {
  let doc: Document;
  beforeEach(() => {
    doc = page();
  });

  it('opens one label with the subject and drops the native title', () => {
    const cell = cells(doc)[0];
    tap(doc, cell);
    expect(tips(doc).length).toBe(1);
    expect(tips(doc)[0].textContent).toBe('DATA STRUCTURES (21CSC201J)');
    expect(tips(doc)[0].getAttribute('role')).toBe('tooltip');
    expect(cell.hasAttribute('title')).toBe(false);
  });

  it('closes on a tap anywhere else', () => {
    tap(doc, cells(doc)[0]);
    tap(doc, doc.getElementById('elsewhere')!);
    expect(tips(doc).length).toBe(0);
  });

  it('closes when the same cell is tapped again', () => {
    const cell = cells(doc)[0];
    tap(doc, cell);
    tap(doc, cell);
    expect(tips(doc).length).toBe(0);
  });

  it('never stacks two labels, and moves between cells', () => {
    tap(doc, cells(doc)[0]);
    tap(doc, cells(doc)[1]);
    expect(tips(doc).length).toBe(1);
    expect(tips(doc)[0].textContent).toBe('No class scheduled · h2'); // title fallback
  });

  it('closes on scroll', () => {
    tap(doc, cells(doc)[0]);
    doc.dispatchEvent(new Event('scroll'));
    expect(tips(doc).length).toBe(0);
  });
});
