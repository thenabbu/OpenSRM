import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import type { CampusProps } from './contract';

// The fixture is the shape app/views/campus_island.py:props() emits, with BOTH
// card shapes the union allows: the kv card (hostel + transport, two groups so
// the first-vs-rest border rule is exercised) and a rows card carrying a badge,
// a meta line and extras (the "Details" disclosure).
// No @testing-library/preact dep — same harness as fees.test.ts / academics.test.ts.
const PROPS: CampusProps = {
  cards: [
    {
      title: 'Placement',
      rows: [
        {
          title: 'Software Engineer Intern', sub: 'Acme Corp', badge: 'Open',
          meta: '2026-11-01 \xb7 25,000',
          extras: [['Location', 'Remote'], ['Cgpa', '7.0']],
        },
        { title: 'Data Analyst', sub: '', badge: '', meta: '', extras: [] },
      ],
    },
    {
      title: 'Hostel & transport',
      kv: [
        { label: 'Hostel', pairs: [['Room no', 'A-214'], ['Block', 'Nilgiri']] },
        { label: 'Transport', pairs: [['Route', 'R-14'], ['Stop', 'Sector 62']] },
      ],
    },
  ],
};

let pageId = 0;
/** Server markup: the mount node itself with cards painted + the inert block. */
const page = (props: unknown = PROPS, id = `island-campus-${++pageId}`) => `
  <section id="markup">
    <div id="tab-campus" role="tabpanel" data-island="campus" data-props="#${id}">
      <div class="flex flex-col gap-3"><div class="card">SERVER PAINT: Acme Corp</div></div>
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

const mount = () => document.querySelector<HTMLElement>('[data-island="campus"]')!;
const stack = () => mount().firstElementChild as HTMLElement;
const NOW = Date.parse('2026-11-09T10:20:00Z') / 1000;
const hydrate = async () => { document.body.innerHTML = page(); return hydrateAll(document.body, NOW); };

describe('campus island', () => {
  it('hydrates: sets data-hydrated and paints every card', async () => {
    await hydrate();
    expect(mount().hasAttribute('data-hydrated')).toBe(true);
    const titles = [...mount().querySelectorAll('h3')].map((h) => h.textContent);
    expect(titles).toEqual(['Placement', 'Hostel & transport']);
  });

  it('rows card renders title, badge, sub, meta and the extras disclosure', async () => {
    await hydrate();
    const first = mount().querySelectorAll('.card')[0] as HTMLElement;
    expect(first.querySelector('.text-sm.font-semibold')!.textContent).toBe('Software Engineer Intern');
    expect(first.querySelector('.badge')!.textContent).toBe('Open');
    expect(first.textContent).toContain('Acme Corp');
    expect(first.textContent).toContain('2026-11-01 \xb7 25,000');
    const dt = [...first.querySelectorAll('summary + dl dt')].map((n) => n.textContent);
    expect(dt).toEqual(['Location', 'Cgpa']);
    expect(first.querySelectorAll('details')).toHaveLength(1);
  });

  it('a row with no badge/sub/meta/extras paints bare (no empty nodes)', async () => {
    await hydrate();
    const rows = mount().querySelectorAll('.card')[0].querySelectorAll('.flex.flex-col.gap-1.py-2');
    const bare = rows[1] as HTMLElement;
    expect(bare.textContent).toBe('Data Analyst');
    expect(bare.querySelectorAll('.badge, p, details')).toHaveLength(0);
  });

  it('kv card renders each group: label, then mono pairs, first group without a top rule', async () => {
    await hydrate();
    const kvCard = mount().querySelectorAll('.card')[1] as HTMLElement;
    const groups = [...kvCard.querySelectorAll(':scope > .card-body > div')] as HTMLElement[];
    expect(groups).toHaveLength(2);
    expect(groups[0].className).not.toContain('border-t');
    expect(groups[1].className).toContain('border-t');
    expect(groups[0].querySelector('p')!.textContent).toBe('Hostel');
    const vals = [...groups[0].querySelectorAll('.font-mono')].map((n) => n.textContent);
    expect(vals).toEqual(['A-214', 'Nilgiri']);
    expect(groups[1].textContent).toContain('Sector 62');
  });

  it('card order follows props order (server order is the only order)', async () => {
    await hydrate();
    const h3 = [...mount().querySelectorAll('h3')].map((h) => h.textContent);
    expect(h3).toEqual(PROPS.cards.map((c) => c.title));
  });

  it('a failing island leaves the server children untouched', async () => {
    const { mountBounded } = await import('../../main');
    const el = document.createElement('div');
    el.innerHTML = '<div class="card">SERVER PAINT: Acme Corp</div>';
    const before = el.innerHTML;
    const Boom = (): never => { throw new Error('boom'); };
    const ok = mountBounded('campus', Boom as never, el, PROPS, Date.now());
    expect(ok).toBe(false);
    expect(el.innerHTML).toBe(before);
    expect(el.hasAttribute('data-hydrated')).toBe(false);
    expect(LOG.join(' ')).toContain('server markup kept');
  });

  it('invalid props (card with neither shape) render nothing and keep the server markup', async () => {
    document.body.innerHTML = page({ cards: [{ title: 'Nope' }] });
    const before = mount().innerHTML;
    await hydrateAll(document.body, NOW);
    expect(mount().innerHTML).toBe(before);
    expect(mount().hasAttribute('data-hydrated')).toBe(false);
  });

  it('empty cards list paints an empty stack, not a crash', async () => {
    document.body.innerHTML = page({ cards: [] });
    await hydrateAll(document.body, NOW);
    expect(mount().hasAttribute('data-hydrated')).toBe(true);
    expect(stack().children).toHaveLength(0);
  });
});
