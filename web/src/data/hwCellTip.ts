// ── Period-cell bubble (P / A / OD) — the affordance a phone could not have.
//
// Each grid cell shipped a `title` attribute: desktop hover only, and a
// long-press does not count as hover on any phone. So the subject behind an
// absent hour was invisible on the device most of these students use.
//
// `title` stays in the markup for the no-JS page; the first interaction on a
// cell drops it (its native bubble would paint over this one) and shows a
// single floating label instead. One label at a time: a tap on the same cell
// closes it, a tap anywhere else closes it, and any scroll closes it because
// a fixed bubble does not follow the grid.

/** The cell selector — attendance.html's `hw-c`, one per date × hour. */
const CELL = '.hw-c';

export function bindHwCellTip(doc: Document = document): void {
  let tip: HTMLElement | null = null;
  let origin: Element | null = null;

  const hide = (): void => {
    tip?.remove();
    tip = null;
    origin = null;
  };

  const show = (cell: Element): void => {
    // `data-subject` is the short name + code a person can read at a glance;
    // the full `title` sentence is the fallback for a cell with no subject.
    const text = cell.getAttribute('data-subject') || cell.getAttribute('title') || '';
    if (!text) return;
    const again = origin === cell;
    hide();
    if (again) return;                      // second tap on the same cell closes it
    cell.removeAttribute('title');

    const el = doc.createElement('div');
    el.className = 'hw-tip';
    el.setAttribute('role', 'tooltip');
    el.textContent = text;
    doc.body.appendChild(el);

    // Above the cell, centred, clamped inside the viewport: the last column
    // would otherwise push its label off the right edge.
    const box = cell.getBoundingClientRect();
    const half = el.offsetWidth / 2;
    const width = doc.defaultView?.innerWidth ?? box.right * 2 + 16;
    el.style.left = `${Math.min(Math.max(box.left + box.width / 2, half + 8), width - half - 8)}px`;
    el.style.top = `${Math.max(box.top - 8, el.offsetHeight + 8)}px`;

    tip = el;
    origin = cell;
  };

  doc.addEventListener('click', (e) => {
    const cell = e.target instanceof Element ? e.target.closest(CELL) : null;
    if (cell) show(cell);
    else hide();
  });
  doc.addEventListener('scroll', hide, { capture: true, passive: true });
}
