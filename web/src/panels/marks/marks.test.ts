import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import type { MarksProps } from './contract';

// The fixture is the shape app/views/marks_island.py:props() emits for the
// three states that matter on this page: a normal subject, the single weakest
// subject (outlier -> the page's one accent), and a component with a nested
// IE row. W4.3: stays on the bespoke harness — hydrateAll over server markup is
// the unit under test; RTL's render() cannot drive it, same as main.test.ts.
const PROPS: MarksProps = {
  subjects: [
    {
      code: '21CSS201T', title: 'Computer Organization And Architecture',
      scored_disp: '32.5', max_disp: '50', head_disp: '32.5/50', sub_disp: '',
      grade: '', internal: false, pct: 65, pct_disp: '65.0', outlier: true,
      components: [
        { name: 'FT-I', date_disp: '04 Sep', score_disp: '8.5', max_disp: '15',
          derived: 'IE-1', confirmed: null,
          ie: { role: 'IE-1', confirmed: false, max_disp: '50', score_disp: '28.33' } },
        { name: 'FT-II', date_disp: '', score_disp: '24', max_disp: '35',
          derived: '', confirmed: 'none', ie: null },
      ],
    },
    {
      code: '21CSC203P', title: 'Advanced Programming Practice', scored_disp: '9',
      max_disp: '10', head_disp: '9/10', sub_disp: '', grade: '', internal: false,
      pct: 90, pct_disp: '90.0', outlier: false,
      components: [],   // -> "No assessment data"
    },
    {
      // internal-only course: /100 total -> the GRADE leads, the total is the sub-line
      code: '21LEM201T', title: 'Professional Ethics', scored_disp: '91', max_disp: '100',
      head_disp: 'A+', sub_disp: '91/100', grade: 'A+', internal: true,
      pct: 91, pct_disp: '91.0', outlier: false, components: [],
    },
  ],
};

let pageId = 0;
/** Server markup: the mount with its children already painted + the inert block. */
const page = (props: unknown = PROPS, id = `island-marks-${++pageId}`) => `
  <section id="markup">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3" data-island="marks" data-props="#${id}">
      <div class="bg-base-200">SERVER PAINT</div>
    </div>
    <script type="application/json" id="${id}">${JSON.stringify(props)}</script>
  </section>`;

const LOG: string[] = [];
beforeEach(async () => {
  LOG.length = 0;
  (await import('../../main')).__resetWarnOnce();
  vi.spyOn(console, 'warn').mockImplementation((m: unknown) => { LOG.push(String(m)); });
});

const mount = () => document.querySelector<HTMLElement>('[data-island="marks"]')!;
// direct card children of the grid the island returns (MarksPanel.tsx)
const cards = () => Array.from(mount().children) as HTMLElement[];

describe('P6.3 marks island', () => {
  it('no-JS: server markup stands, nothing hydrated', () => {
    document.body.innerHTML = page();
    expect(mount().textContent).toContain('SERVER PAINT');
    expect(mount().hasAttribute('data-hydrated')).toBe(false);
  });

  it('hydrates: marker set, server children replaced by the islands cards', async () => {
    document.body.innerHTML = page();
    await hydrateAll(document, Date.now() / 1000);
    expect(mount().getAttribute('data-hydrated')).toBe('1');
    expect(LOG).toEqual([]);
    expect(mount().textContent).not.toContain('SERVER PAINT');
    expect(cards()).toHaveLength(3);
  });

  it('subject rows match the view model, in order, with the one accent', async () => {
    document.body.innerHTML = page();
    await hydrateAll(document, Date.now() / 1000);
    const [weak, strong] = cards();
    expect(weak.querySelector('.font-mono.text-xs')!.textContent).toBe('21CSS201T');
    expect(weak.querySelector('h3')!.textContent).toBe('Computer Organization And Architecture');
    expect(weak.textContent).toContain('32.5/50');
    // exactly one text-secondary on the page, on the outlier (§2.7)
    const head = weak.querySelector('.text-lg')!;
    expect(head.textContent).toBe('32.5/50');   // scored/max, never a percentage
    expect(head.className).toContain('text-secondary');
    expect(document.querySelectorAll('.text-secondary')).toHaveLength(1);
    expect(strong.querySelector('h3')!.textContent).toBe('Advanced Programming Practice');
    expect(strong.querySelector('.text-lg')!.className).not.toContain('text-secondary');
    // internal-only: grade headline + scored/100 sub-line, no percentage anywhere
    const internal = cards()[2];
    expect(internal.querySelector('.text-lg')!.textContent).toBe('A+');
    expect(internal.textContent).toContain('91/100');
    expect(internal.textContent).not.toContain('%');
  });

  it('component breakdown: chip, date, score, tag form and the nested IE row', async () => {
    document.body.innerHTML = page();
    await hydrateAll(document, Date.now() / 1000);
    const weak = cards()[0];
    // Chips only: `h-5 rounded-full` is the chip fill (marks.html, DESIGN §4.13).
    // `span` excludes the tag summary button (a `<summary>`) and its sr-only label.
    const chips = Array.from(weak.querySelectorAll('span.h-5.rounded-full')).map((e) => e.textContent);
    // DOM order follows the component: FT-I, then its nested IE row, then FT-II.
    expect(chips).toEqual(['FT-I', 'IE-1', 'FT-II']);
    expect(weak.textContent).toContain('04 Sep');
    expect(weak.textContent).toContain('8.5/15');
    expect(weak.textContent).toContain('28.33/50');
    expect(weak.textContent).toContain('derived');
    // the no-date chip renders no date span; an unconfirmed/certain tag reads right
    expect(weak.textContent).toContain('Derived IE-1 · not confirmed yet');
    expect(weak.textContent).toContain('Derived none · confirmed neither');
    expect(weak.querySelector('form[action="/marks/tag"] input[name="component"]')).toBeTruthy();
    expect(weak.querySelector('details')!.id).toBe('tag-21CSS201T-FT-I');
  });

  it('empty component list renders the neutral fallback, not a blank card', async () => {
    document.body.innerHTML = page();
    await hydrateAll(document, Date.now() / 1000);
    expect(cards()[1].textContent).toContain('No assessment data');
  });

  it('fallback: a bad payload keeps the server markup', async () => {
    document.body.innerHTML = page({ subjects: [{ code: 1 }] });
    await hydrateAll(document, Date.now() / 1000);
    expect(mount().hasAttribute('data-hydrated')).toBe(false);
    expect(mount().textContent).toContain('SERVER PAINT');
    expect(LOG.join('\n')).toContain('invalid props');
  });
});
