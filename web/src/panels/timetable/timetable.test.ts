import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import type { TimetableProps } from './contract';

// The fixture is the shape app/views/timetable_island.py:props() emits for the
// four row states that matter: a class with an attendance tag, a break divider
// BETWEEN classes, a class with no attendance data, and an empty day. No
// @testing-library/preact dep — the existing harness (main.ts's hydrateAll on
// jsdom) is the unit under test, same as main.test.ts.
const PROPS: TimetableProps = {
  default_day: 'Tuesday',
  days: [
    {
      day: 'Monday', short: 'Mon', empty: false,
      rows: [
        { kind: 'class', start: '09:00', end: '09:50', code: '21CSS201T',
          name: 'Computer Organization', location: 'LT-204', live: false,
          sig: { cls: 'ok', num: 3 } },
        { kind: 'break', label: 'Lunch' },
        { kind: 'class', start: '13:00', end: '13:50', code: '21CSC203P',
          name: 'Advanced Programming', location: '', live: false, sig: null },
      ],
    },
    {
      day: 'Tuesday', short: 'Tue', empty: false,
      rows: [
        { kind: 'class', start: '10:00', end: '10:50', code: '21MAB201T',
          name: 'Transforms', location: 'A-12', live: true,
          sig: { cls: 'danger', num: 2 } },
      ],
    },
    { day: 'Wednesday', short: 'Wed', empty: true, rows: [] },
  ],
};

let pageId = 0;
/** Server markup: the mount with its panels already painted + the inert block. */
const page = (props: unknown = PROPS, id = `island-timetable-${++pageId}`) => `
  <section id="markup">
    <div class="panels" data-island="timetable" data-props="#${id}">
      <div class="day-panel" id="panel-Monday">SERVER PAINT</div>
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

const mount = () => document.querySelector<HTMLElement>('[data-island="timetable"]')!;
const panels = () => Array.from(mount().children) as HTMLElement[];

async function hydrate(props: unknown = PROPS): Promise<void> {
  document.body.innerHTML = page(props);
  await hydrateAll(document.body, Date.parse('2026-11-09T10:20:00Z') / 1000);
}

describe('timetable island', () => {
  it('hydrates: marks itself and paints one panel per day, in server order', async () => {
    await hydrate();
    expect(mount().getAttribute('data-hydrated')).toBe('1');
    expect(panels().map((p) => p.id)).toEqual([
      'panel-Monday', 'panel-Tuesday', 'panel-Wednesday',
    ]);
  });

  it('keeps the classes in server order', async () => {
    await hydrate();
    const codes = Array.from(panels()[0].querySelectorAll('.tt-code')).map((c) => c.textContent);
    expect(codes).toEqual(['21CSS201T', '21CSC203P']);
  });

  it('paints a break divider only between two classes, never trailing', async () => {
    await hydrate();
    const mon = panels()[0];
    const kinds = Array.from(mon.children).map((c) => c.className);
    expect(kinds).toEqual(['tt-row', 'tt-brk', 'tt-row']);
    expect(mon.querySelector('.tt-brk')!.textContent).toBe('Lunch');
    // the last class is last: no divider after it
    expect(mon.lastElementChild!.className).toBe('tt-row');
  });

  it('renders the attendance tag words and keeps the tooltip', async () => {
    await hydrate();
    const [mon, tue] = panels();
    const ok = mon.querySelector('.tt-tag--ok')!;
    expect(ok.textContent).toBe('can skip 3');
    expect(ok.getAttribute('title')).toBe('skippable, still 75%');

    const dgr = tue.querySelector('.tt-tag--danger')!;
    expect(dgr.textContent).toBe('attend 2');
    expect(dgr.getAttribute('title')).toBe('2 in a row to reach 75%');
  });

  it('falls back to the neutral tag when there is no attendance join', async () => {
    await hydrate();
    const none = panels()[0].querySelector('.tt-tag--none')!;
    expect(none.textContent).toBe('no data');
    expect(none.hasAttribute('title')).toBe(false);
  });

  it('carries the live row marker and the room chip', async () => {
    await hydrate();
    const [mon, tue] = panels();
    expect(tue.querySelector('.tt-row')!.className).toBe('tt-row tt-row--now');
    expect(mon.querySelector('.tt-row')!.className).toBe('tt-row');
    expect(mon.querySelector('.tt-chip')!.textContent).toBe('LT-204');
    // a slot with no room renders no chip
    expect(mon.querySelectorAll('.tt-row')[1].querySelector('.tt-chip')).toBeNull();
  });

  it('renders the "No classes" line for an empty day', async () => {
    await hydrate();
    const wed = panels()[2];
    expect(wed.textContent).toBe('No classes');
    expect(wed.querySelector('.tt-row')).toBeNull();
  });

  // The generic throw-isolation case lives in main.test.ts (`mountBounded`,
  // main.test.ts:134) — it is the boundary's unit, not this island's.
  it('leaves the server markup alone when the props are invalid', async () => {
    await hydrate({ days: 'nope' });
    expect(LOG.some((m) => m.includes('invalid props'))).toBe(true);
    expect(mount().children).toHaveLength(1);
    expect(mount().textContent).toContain('SERVER PAINT');
    expect(mount().hasAttribute('data-hydrated')).toBe(false);
  });
});
