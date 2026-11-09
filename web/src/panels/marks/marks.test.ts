import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import type { MarksProps } from './contract';

// The fixture is the shape app/views/marks_island.py:props() emits for the
// three states that matter on this page: a normal subject, the single weakest
// subject (outlier -> the page's one accent), and a component with a nested
// IE row. No @testing-library/preact dep — the existing harness (main.ts's
// hydrateAll on jsdom) is the unit under test, same as main.test.ts.
const PROPS: MarksProps = {
  subjects: [
    {
      code: '21CSS201T', title: 'Computer Organization And Architecture',
      scored_disp: '32.5', max_disp: '50', pct: 65, outlier: true,
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
      max_disp: '10', pct: 90, outlier: false,
      components: [],   // -> "No assessment data"
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
const cards = () => Array.from(mount().querySelectorAll(':scope > .rounded-box'));

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
    expect(cards()).toHaveLength(2);
  });

  it('subject rows match the view model, in order, with the one accent', async () => {
    document.body.innerHTML = page();
    await hydrateAll(document, Date.now() / 1000);
    const [weak, strong] = cards();
    expect(weak.querySelector('.font-mono.text-xs')!.textContent).toBe('21CSS201T');
    expect(weak.querySelector('h3')!.textContent).toBe('Computer Organization And Architecture');
    expect(weak.textContent).toContain('32.5/50');
    // exactly one text-secondary on the page, on the outlier (§2.7)
    const pct = weak.querySelector('.text-lg')!;
    expect(pct.textContent).toBe('65%');
    expect(pct.className).toContain('text-secondary');
    expect(document.querySelectorAll('.text-secondary')).toHaveLength(1);
    expect(strong.querySelector('h3')!.textContent).toBe('Advanced Programming Practice');
    expect(strong.querySelector('.text-lg')!.className).not.toContain('text-secondary');
  });

  it('component breakdown: chip, date, score, tag form and the nested IE row', async () => {
    document.body.innerHTML = page();
    await hydrateAll(document, Date.now() / 1000);
    const weak = cards()[0];
    const chips = Array.from(weak.querySelectorAll('.rounded-full')).map((e) => e.textContent);
    expect(chips).toEqual(['FT-I', 'FT-II', 'IE-1']);
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
