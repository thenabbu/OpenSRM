import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import type { FeesProps } from './contract';

// The fixture is the shape app/views/fees_island.py:props() emits, including
// its awkward cases: a charge already penalised, a charge with a late fee but
// none applied yet, a charge with no deadline at all, and a receipt with no
// narration head and no voucher number.
// W4.3: stays on the bespoke harness — hydrateAll over server markup IS the unit
// under test (RTL's render() mounts a component, it cannot drive that), same as main.test.ts.
const PROPS: FeesProps = {
  due_disp: '8,650',
  due_sum: '8,650',
  level: 'text-warning',
  dues: [
    {
      head: 'Exam Fees', cycle: 'November-2026', amt: '3,150', level: 'text-warning',
      deadline: '23 Nov 2026', late_on: '24 Nov 2026', late_extra: '1,000',
      days_left: 3, overdue: false, penalised: false, min: '',
    },
    {
      head: 'Hostel Fees', cycle: '', amt: '5,000', level: 'text-warning',
      deadline: '', late_on: '1 Oct 2026', late_extra: '500',
      days_left: null, overdue: false, penalised: true, min: '',
    },
  ],
  years: [
    {
      year: '2026', total: '1,00,000',
      rows: [
        { date: '12 Jul 2026', head: 'Semester fee', amt: '75,000' },
        { date: '1 Aug 2026', head: 'Exam fee', amt: '25,000' },
      ],
    },
    { year: '2025', total: '1,00,000', rows: [{ date: '12 Jul 2025', head: 'Semester fee', amt: '1,00,000' }] },
  ],
  multi_year: true,
  year_label: '',
  paid_total: '2,00,000',
  ledger: [
    { date: '2 Aug 2026', amt: '25,000', vno: 'RC-77', head: 'Exam fee', full: 'Exam fee paid through online' },
    { date: '13 Jul 2026', amt: '75,000', vno: '', head: '', full: '' },
  ],
};

let pageId = 0;
/** Server markup: the mount with its rows already painted + the inert block. */
const page = (props: unknown = PROPS, id = `island-fees-${++pageId}`) => `
  <section id="markup">
    <div id="tab-fees" role="tabpanel" data-island="fees" data-props="#${id}">
      <div class="bg-base-200">SERVER PAINT: ₹3,150</div>
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
    // Owed sum · charge cards · pay line · Paid card · receipts
    expect(kids().map((k) => k.tagName)).toEqual(['DIV', 'DIV', 'P', 'DIV', 'DETAILS']);
  });

  it('prints the server-formatted amount verbatim, never a reparsed one', async () => {
    await hydrate();
    // the 2+ charge sum line, not a number the island added up
    expect(kids()[0].querySelector('.font-mono')!.textContent).toBe('₹8,650');
    // and the display string survives all the way through — Indian grouping
    // and its comma placement are the server's, not the client's
    const head = kids()[3];
    expect(head.textContent).toContain('Paid');
    // last .font-mono in the header ROW is the total (the first is the year
    // label; the rows below carry their own amounts)
    expect([...head.firstElementChild!.querySelectorAll('.font-mono')].pop()!.textContent)
      .toBe('₹2,00,000');
  });

  it('keeps the server threshold class on the number', async () => {
    await hydrate();
    expect(kids()[0].querySelector('.font-mono')!.className).toContain('text-warning');
  });

  it('drops the sum line when there is only one charge (it would be a dup)', async () => {
    await hydrate({ ...PROPS, due_sum: '', dues: [PROPS.dues[0]] });
    // no sum line, so the first child is the charge card itself
    expect(kids()[0].children[0].textContent).toContain('Exam Fees');
    expect(mount().textContent).not.toContain('Owed');
  });

  it('drops every charge block when nothing is owed and says so once', async () => {
    // Zero dues: fees.py sends due_disp='', due_sum='' and no rows, so the page
    // opens at Paid — with one plain sentence, never an empty gap.
    await hydrate({ ...PROPS, due_disp: '', due_sum: '', level: '', dues: [], ledger: [] });
    expect(mount().textContent).not.toContain('Pay through the SRM portal.');
    expect(mount().textContent).toContain('Nothing due.');
    // the sentence, then the Paid card (no receipts: PROPS.ledger was emptied)
    expect(kids().map((k) => k.tagName)).toEqual(['P', 'DIV']);
    expect(kids()[0].textContent).toBe('Nothing due.');
    const card = kids()[1];
    expect(card.className).toContain('rounded-box');
    expect([...card.firstElementChild!.querySelectorAll('.font-mono')].pop()!.textContent)
      .toBe('₹2,00,000');
  });

  it('names each charge and states its deadline, late-fee and no-deadline cases', async () => {
    await hydrate();
    const cards = Array.from(kids()[1].children) as HTMLElement[];
    expect(cards).toHaveLength(2);
    // charge 1: named, cycle, deadline, days-left, up-coming late fee
    expect(cards[0].textContent).toContain('Exam Fees');
    expect(cards[0].textContent).toContain('November-2026');
    expect(cards[0].textContent).toContain('by 23 Nov 2026');
    expect(cards[0].textContent).toContain('3 days left');
    expect(cards[0].textContent).toContain('Late fee ₹1,000 from 24 Nov 2026');
    // charge 2: no deadline from SRM, and the penalty already applied
    expect(cards[1].textContent).toContain('no due date from SRM yet');
    expect(cards[1].textContent).toContain('Late fee ₹500 applied');
    expect(cards[1].textContent).not.toContain('days left');
  });

  it('marks an overdue charge in words, not colour alone', async () => {
    await hydrate({
      ...PROPS,
      dues: [{ ...PROPS.dues[0], days_left: -4, overdue: true, deadline: '23 Nov 2026' }],
    });
    const card = kids()[1].children[0] as HTMLElement;
    expect(card.textContent).toContain('overdue');
    expect(card.textContent).toContain('was due 23 Nov 2026');
    expect(card.textContent).not.toContain('days left');
    expect(card.textContent).toContain('Late fee ₹1,000 applied');
  });

  it('keeps year headers only when there are 2+ years', async () => {
    await hydrate();
    const years = Array.from(kids()[3].querySelectorAll('section'));
    expect(years).toHaveLength(2);
    expect(years[0].querySelector('h2')!.textContent).toBe('2026');
    expect(
      Array.from(years[0].querySelectorAll('.grid')).map((r) => r.children[1].textContent),
    ).toEqual(['Semester fee', 'Exam fee']);
  });

  it('moves the single year onto the heading instead of a duplicate header row', async () => {
    await hydrate({
      ...PROPS,
      multi_year: false,
      year_label: '2026',
      years: [{ year: '2026', total: '1,00,000', rows: PROPS.years[0].rows }],
    });
    const head = kids()[3];
    expect(head.textContent).toContain('Paid');
    expect(head.textContent).toContain('2026');
    // the year header row is gone: no h2 anywhere inside the Paid card
    expect(head.querySelector('h2')).toBeNull();
    // ...and the total appears once, on the heading, exactly as it did before
    // [0] is the year label on the heading, [1] the total
    expect(head.querySelectorAll('.font-mono')[1].textContent).toBe('₹2,00,000');
    expect(head.className).toContain('rounded-box');
  });

  it('paints receipts with the divider only between them, and the voucher only when present', async () => {
    await hydrate();
    const box = kids()[4];
    expect(box.querySelector('summary')!.textContent).toContain('Payment receipts');
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
