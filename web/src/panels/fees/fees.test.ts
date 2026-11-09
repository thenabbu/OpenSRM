import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import type { FeesProps } from './contract';

// The fixture is the shape app/views/fees_island.py:props() emits, including
// its three awkward cases: a penalised charge, a charge with a penalty date but
// none applied, and a receipt with no narration head and no voucher number.
// No @testing-library/preact dep — the existing harness (main.ts's hydrateAll on
// jsdom) is the unit under test, same as main.test.ts.
const PROPS: FeesProps = {
  due_disp: '3,150.00',
  level: 'text-warning',
  dues: [
    { amt: '3,150.00', due: '25-11-2026', penalty: '24-11-2026', penalised: false },
    { amt: '500.00', due: '', penalty: '01-10-2026', penalised: true },
  ],
  paid_total: '200,000.00',
  years: [
    {
      year: '2026', total: '100,000.00',
      rows: [
        { date: '2026-07-12', head: 'Semester fee', amt: '75,000.00' },
        { date: '2026-08-01', head: 'Exam fee', amt: '25,000.00' },
      ],
    },
    { year: '2025', total: '100,000.00', rows: [{ date: '2025-07-12', head: 'Semester fee', amt: '100,000.00' }] },
  ],
  ledger: [
    { date: '2026-08-02', amt: '25,000.00', vno: 'RC-77', head: 'Exam fee', full: 'Exam fee paid through online' },
    { date: '2026-07-13', amt: '75,000.00', vno: '', head: '', full: '' },
  ],
};

let pageId = 0;
/** Server markup: the mount with its rows already painted + the inert block. */
const page = (props: unknown = PROPS, id = `island-fees-${++pageId}`) => `
  <section id="markup">
    <div id="tab-fees" role="tabpanel" data-island="fees" data-props="#${id}">
      <div class="bg-base-200">SERVER PAINT: ₹3,150.00</div>
    </div>
    <script type="application/json" id="${id}">${JSON.stringify(props)}</script>
  </section>`;

const LOG: string[] = [];
beforeEach(async () => {
  LOG.length = 0;
  document.body.innerHTML = '';
  (await import('../../main')).__resetWarnOnce();
  vi.spyOn(console, 'warn').mockImplementation((m: unknown) => { LOG.push(String(m)); });
});

const mount = () => document.querySelector<HTMLElement>('[data-island="fees"]')!;
const kids = () => Array.from(mount().children) as HTMLElement[];

async function hydrate(props: unknown = PROPS): Promise<void> {
  document.body.innerHTML = page(props);
  await hydrateAll(document.body, Date.parse('2026-11-09T10:20:00Z') / 1000);
}

describe('fees island', () => {
  it('hydrates: marks itself and repaints the blocks in server order', async () => {
    await hydrate();
    expect(mount().getAttribute('data-hydrated')).toBe('1');
    // hero · dues card · Paid header · year list · receipts
    expect(kids().map((k) => k.tagName)).toEqual(['DIV', 'DIV', 'DIV', 'DIV', 'DETAILS']);
  });

  it('prints the server-formatted amount verbatim, never a reparsed one', async () => {
    await hydrate();
    const hero = kids()[0];
    expect(hero.querySelector('.font-mono')!.textContent).toBe('₹3,150.00');
    // and the display string is untouched all the way through — a group total
    // and a row amount keep their grouping commas
    expect(kids()[3].textContent).toContain('₹100,000.00');
  });

  it('keeps the server threshold class on the hero', async () => {
    await hydrate();
    expect(kids()[0].querySelector('.font-mono')!.className).toContain('text-warning');
  });

  it('drops the hero entirely when nothing is owed', async () => {
    // Zero dues: fees.py sends due_disp='' and no rows, so the page opens at
    // Paid — there is no hero node at all, and no gap where it would have been.
    await hydrate({ ...PROPS, due_disp: '', level: '', dues: [], ledger: [] });
    expect(mount().textContent).not.toContain('Outstanding dues');
    expect(kids().map((k) => k.tagName)).toEqual(['DIV', 'DIV']);
    expect(kids()[0].textContent).toContain('Paid');
    expect(kids()[0].querySelector('.font-mono')!.textContent).toBe('₹200,000.00');
  });

  it('renders both penalty states and the no-deadline wording', async () => {
    await hydrate();
    const dues = kids()[1];
    const lines = Array.from(dues.children[0].children) as HTMLElement[];
    expect(lines[0].textContent).toContain('Due 25-11-2026');
    expect(lines[0].textContent).toContain('penalty after 24-11-2026');
    expect(lines[0].textContent).not.toContain('penalty applied');
    expect(lines[1].textContent).toContain('Outstanding');
    expect(lines[1].textContent).toContain('penalty applied');
  });

  it('keeps year groups and their rows in server order', async () => {
    await hydrate();
    const years = kids()[3];
    expect(Array.from(years.children).map((s) => s.tagName)).toEqual(['SECTION', 'SECTION']);
    expect(years.children[0].querySelector('h2')!.textContent).toBe('2026');
    expect(
      Array.from(years.children[0].querySelectorAll('.grid')).map((r) => r.children[2].textContent),
    ).toEqual(['Semester fee', 'Exam fee']);
  });

  it('paints receipts with the divider only between them, and the voucher only when present', async () => {
    await hydrate();
    const box = kids()[4];
    expect(box.querySelector('summary')!.textContent).toContain('(2)');
    const rcpts = Array.from(box.querySelectorAll('.fees-rcpt')) as HTMLElement[];
    expect(rcpts).toHaveLength(2);
    expect(rcpts[0].className).not.toContain('border-t');
    expect(rcpts[1].className).toContain('border-t');
    expect(rcpts[0].querySelector('[data-copy]')!.getAttribute('data-copy')).toBe('RC-77');
    expect(rcpts[1].querySelector('[data-copy]')).toBeNull();
    // no narration body on the second receipt: no paragraph at all
    expect(rcpts[1].querySelector('p')).toBeNull();
  });

  // The generic throw-isolation case lives in main.test.ts (`mountBounded`) —
  // it is the boundary's unit, not this island's.
  it('leaves the server markup alone when the props are invalid', async () => {
    await hydrate({ dues: 'nope' });
    expect(LOG.some((m) => m.includes('invalid props'))).toBe(true);
    expect(mount().children).toHaveLength(1);
    expect(mount().textContent).toContain('SERVER PAINT');
    expect(mount().hasAttribute('data-hydrated')).toBe(false);
  });
});
