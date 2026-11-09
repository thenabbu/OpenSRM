import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import type { AcademicsProps } from './contract';

// The fixture is the shape app/views/academics_island.py:props() emits, cut
// down to what the assertions need: two semesters (newest first) and two
// categories, one of them empty (the "No subjects listed" branch) and one
// finished (done = the success fill + ", complete" in the aria-label).
// No @testing-library/preact dep — the existing harness (main.ts's hydrateAll
// on jsdom) is the unit under test, same as fees.test.ts.
const PROPS: AcademicsProps = {
  cgpa: {
    value: '9.40',
    credits_disp: '43/163 credits earned',
    sems: [
      {
        sem: 2, label: 'MAY 2026', credits: 21, sgpa: '9.33',
        rows: [
          { code: '21CSC101T', title: 'Object Oriented Design And Programming', grade: 'O', completed: true, tint_o: true, tint_f: false },
          { code: '21CYM101T', title: 'Environmental Science', grade: 'A+', completed: true, tint_o: false, tint_f: false },
        ],
      },
      {
        sem: 1, label: 'DEC 2025', credits: 22, sgpa: '9.45',
        rows: [
          { code: '21MAB199T', title: 'Failed Subject', grade: 'F', completed: false, tint_o: false, tint_f: true },
        ],
      },
    ],
  },
  courses: {
    overall: { acq: 43, req: 163 },
    pending: 52,
    total: 63,
    cats: [
      {
        name: 'Basic Science Courses (B)', req: 32, acq: 20, pct: 62.5, done: false,
        fill: 'width:62.5%', n: 2, n_pending: 1,
        pending: [{ code: '21BTB101T', title: 'Applied Biology', grade: '-', completed: false, tint_o: false, tint_f: false, month: '', attempts: 0 }],
        completed: [{ code: '21CYB101J', title: 'Chemistry', grade: 'A+', completed: true, tint_o: false, tint_f: false, month: 'DEC-2025', attempts: 1 }],
      },
      {
        name: 'Open Elective Courses (O)', req: 9, acq: 9, pct: 100, done: true,
        fill: 'width:100.0%;background:var(--color-success)', n: 0, n_pending: 0,
        pending: [], completed: [],
      },
    ],
  },
};

let pageId = 0;
/** Server markup: the mount with its cards already painted + the inert block. */
const page = (props: unknown = PROPS, id = `island-academics-${++pageId}`) => `
  <section id="markup">
    <div id="tab-academics" role="tabpanel" data-island="academics" data-props="#${id}">
      <div class="flex flex-col gap-3"><div class="bg-base-200">SERVER PAINT: 9.40</div></div>
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

const mount = () => document.querySelector<HTMLElement>('[data-island="academics"]')!;
const stack = () => mount().firstElementChild as HTMLElement;
const cards = () => Array.from(stack().children) as HTMLElement[];
const sems = () => Array.from(mount().querySelectorAll('.acad-sem')) as HTMLElement[];
const cats = () => Array.from(mount().querySelectorAll('.acad-cat')) as HTMLElement[];

async function hydrate(props: unknown = PROPS): Promise<void> {
  document.body.innerHTML = page(props);
  await hydrateAll(document.body, Date.parse('2026-11-09T10:20:00Z') / 1000);
}

describe('academics island', () => {
  it('hydrates: marks itself and paints CGPA card then credits card', async () => {
    await hydrate();
    expect(mount().getAttribute('data-hydrated')).toBe('1');
    expect(cards().map((k) => k.tagName)).toEqual(['DIV', 'DIV']);
    expect(cards()[0].textContent).toContain('CGPA');
    expect(cards()[1].textContent).toContain('Credits & subjects');
  });

  it('prints the server CGPA and credits strings verbatim', async () => {
    await hydrate();
    expect(cards()[0].textContent).toContain('9.40');
    expect(cards()[0].textContent).toContain('43/163 credits earned');
    // overall pair and the pending sentence keep their server numbers
    expect(cards()[1].textContent).toContain('43/163');
    expect(cards()[1].textContent).toContain('52 of 63 subjects pending');
  });

  it('keeps the server semester order (newest first) and label', async () => {
    await hydrate();
    expect(sems().map((d) => d.textContent!.match(/Semester (\d)/)![1])).toEqual(['2', '1']);
    expect(sems()[0].textContent).toContain('MAY 2026');
    expect(sems()[0].textContent).toContain('SGPA 9.33');
    expect(sems()[0].textContent).toContain('21 cr');
  });

  it('carries the grade tints: O is acad-g-o, F is acad-g-f, plain A+ is neither', async () => {
    await hydrate();
    const pills = Array.from(sems()[0].querySelectorAll('li > span:last-child')) as HTMLElement[];
    expect(pills[0].className).toContain('acad-g-o');
    expect(pills[0].textContent).toBe('O');
    expect(pills[1].className).not.toContain('acad-g');
    const fail = sems()[1].querySelector('li > span:last-child') as HTMLElement;
    expect(fail.className).toContain('acad-g-f');
  });

  it('renders the fail grade letter even though it is tinted (never colour alone)', async () => {
    await hydrate();
    expect(sems()[1].textContent).toContain('F');
  });

  it('orders category rows PENDING first, completed last', async () => {
    await hydrate();
    const titles = (Array.from(cats()[0].querySelectorAll('li')) as HTMLElement[])
      .map((li) => li.textContent!);
    expect(titles).toHaveLength(2);
    expect(titles[0]).toContain('Applied Biology');
    expect(titles[1]).toContain('Chemistry');
    // the completed row keeps its month and attempt count
    expect(titles[1]).toContain('DEC-2025');
    expect(titles[1]).toContain('1 attempts');
  });

  it('keeps the meter fill from the server and the aria-label the template had', async () => {
    await hydrate();
    const meter = cats()[0].querySelector('.meter') as HTMLElement;
    expect(meter.getAttribute('role')).toBe('img');
    expect(meter.getAttribute('aria-label')).toBe('Basic Science Courses (B): 20 of 32 credits');
    // the style string rides through untouched (jsdom only adds the ';')
    expect((meter.querySelector('.mz') as HTMLElement).getAttribute('style')).toContain('width: 62.5%');
    const done = cats()[1].querySelector('.meter') as HTMLElement;
    expect(done.getAttribute('aria-label')).toContain(', complete');
  });

  it('shows the empty-category line when a category has no subjects', async () => {
    await hydrate();
    expect(cats()[1].textContent).toContain('No subjects listed for this category.');
  });

  it('drops the CGPA card entirely when the server section is null', async () => {
    await hydrate({ ...PROPS, cgpa: null });
    expect(cards()).toHaveLength(1);
    expect(stack().textContent).toContain('Credits & subjects');
    expect(stack().textContent).not.toContain('CGPA');
  });

  it('falls back to the server markup when the props are invalid', async () => {
    document.body.innerHTML = page({ ...PROPS, cgpa: { value: 9.4, credits_disp: '', sems: [] } });
    await hydrateAll(document.body, 0);
    // schema rejected => nothing hydrated, original children untouched
    expect(mount().getAttribute('data-hydrated')).toBeNull();
    expect(mount().textContent).toContain('SERVER PAINT: 9.40');
  });
});
