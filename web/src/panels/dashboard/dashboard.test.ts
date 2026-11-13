import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import { dashboardProps } from './contract';

// Exactly what app/templates/home.html renders into the card grid for one
// student: the six widgets with their guards satisfied — EXCEPT `ticker`, whose
// widget is the one the fallback test below hides. Written by hand from the
// partials (today.html, week.html, attendance.html, marks.html, exams.html,
// teachers.html) so it is a real fixture, not the island's own output.
const PROPS = {
  // profile.html renders unconditionally — the box hydration used to delete.
  profile: {
    netid: 'zz9999',
    name: 'Test Student',
    email: 'zz9999@srmist.edu.in',
    reg_no: 'RA2500000000',
    avatar:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="64" height="64"><g class="mo-root mo-always"></g></svg>',
  },
  ticker: null as null,
  week: {
    days: 2,
    hours: 3,
    dates: [{ date: '2026-11-03', hours: 2 }, { date: '2026-11-05', hours: 1 }],
    marks: [{ code: '21CSS201T', name: 'Quiz 1', date: '04 Nov' }],
    today_absent: false,
  },
  budgets: [
    ['Computer Organization And Architecture', '-4', 0],
    ['Cloud Computing', '+2', 2],
    ['Discrete Mathematics', '0', 1],
  ],
  marks: [
    { code: '21CSS201T', scored: '18', max: '20', stale: false, recent: true, entered: '04 Nov 2026' },
    { code: '21CSC302J', scored: '12', max: '20', stale: true, recent: false, entered: '' },
  ],
  exams: {
    label: 'Dec 2026',
    days_until: 12,
    source: 'Official',
    rows: [
      { code: '21CSS201T', name_disp: 'Computer Organization', short: '12 Dec', day: '12', dow: 'Sat',
        session_disp: 'FN', slot: 'A', hall: 'M-201', seat: '41' },
    ],
  },
  teachers: [
    { code: '21CSS201T', name: 'Computer Organization', staff: [{ name: 'Dr. Priyanka Gupta', mode: 'Theory', ini: 'PG' }] },
  ],
  fb_plan: true,
};

const BLOCK = (p = PROPS, id = 'island-dashboard') =>
  `<script type="application/json" id="${id}">${JSON.stringify(p)}</script>`;

/** The server's own grid — the mount point's children, and the no-JS paint. */
const SSR = `
<div class="wbox rounded-box p-4">
  <div class="wlabel">This week</div>
  <div class="text-sm"><strong>2</strong> days absent &middot; 3 hrs lost</div>
  <div class="flex flex-wrap gap-1.5 mt-2">
    <span class="badge badge-soft badge-warning badge-sm font-mono" title="2 hrs">2026-</span>
  </div>
  <div class="mt-3 pt-3 border-t border-base-300">
    <div class="text-[11px] uppercase tracking-wider text-base-content/50 mb-1">marks added</div>
    <div class="flex items-baseline justify-between gap-2 py-0.5 text-xs">
      <span class="shrink-0 font-mono text-base-content/60">21CSS201T</span>
      <span class="min-w-0 truncate text-base-content/80">Quiz 1</span>
      <span class="shrink-0 font-mono text-base-content/50">04 Nov</span>
    </div>
  </div>
</div>`;

let pageId = 0;
const newPage = (p = PROPS) => {
  const id = `island-dashboard-${++pageId}`;
  return `<div data-island="dashboard" data-props="#${id}">${SSR}</div>${BLOCK(p, id)}`;
};

const grid = () => document.querySelector<HTMLElement>('[data-island="dashboard"]')!;

const LOG: string[] = [];
beforeEach(async () => {
  LOG.length = 0;
  (await import('../../main')).__resetWarnOnce();
  vi.spyOn(console, 'warn').mockImplementation((msg: unknown) => { LOG.push(String(msg)); });
});

/** Visible text of the whole grid, whitespace-collapsed: what a reader sees. */
const text = (el: HTMLElement) => el.textContent?.replace(/\s+/g, ' ').trim() ?? '';

describe('P6.2 dashboard island', () => {
  it('props the server builds satisfy the contract', () => {
    expect(dashboardProps.safeParse(PROPS).success).toBe(true);
  });

  it('the server markup is correct with no JS', () => {
    document.body.innerHTML = newPage();
    expect(grid().hasAttribute('data-hydrated')).toBe(false);
    expect(text(grid())).toContain('days absent');
  });

  it('hydration happened and painted every non-empty widget', async () => {
    document.body.innerHTML = newPage();
    await hydrateAll(document, Date.now() / 1000);
    const el = grid();
    expect(el.getAttribute('data-hydrated')).toBe('1');
    // one widget per rendered section, in partial order
    expect(el.querySelectorAll('.wbox')).toHaveLength(6);        // profile, week, budgets, marks, exams, teachers
    expect(text(el)).toContain('This week');
    expect(text(el)).toContain('2 days absent');
    expect(text(el)).toContain('Computer Organization And Architecture');
    expect(text(el)).toContain('-4');
    expect(text(el)).toContain('18/20');
    // risk-first order IS the view (attendance widget comment, teachers.py:61).
    // Scoped to the attendance widget: the unscoped `.widget-scroll li` here
    // used to pass only because the island rendered attendance BEFORE exams —
    // the server's LAYOUT puts exams in the `assess` card ahead of `people`,
    // so a global query returns an exam row first. That divergence is what
    // W2.6 fixed; the ordering claim under test is the widget's own.
    const att = Array.from(el.querySelectorAll<HTMLElement>('.wbox')).find((w) => text(w).includes('to 75%'))!;
    const rows = Array.from(att.querySelectorAll('.widget-scroll li')).map((n) => n.querySelector('span')!.textContent);
    expect(rows[0]).toBe('Computer Organization And Architecture');
    expect(text(el)).toContain('First exam in');
    expect(text(el)).toContain('Dr. Priyanka Gupta');
    expect(text(el)).toContain('Auto-fill mid-sem feedback');
  });

  it('the profile widget survives hydration (P6.2b regression)', async () => {
    // The bug: hydration replaced the grid's children with six widgets and the
    // identity box vanished after first paint. These three selectors are what
    // gaze.js, dash.js and three e2e DUTs key on, so they are the assertion.
    document.body.innerHTML = newPage();
    await hydrateAll(document, Date.now() / 1000);
    const el = grid();
    const av = el.querySelector('.avatar > div');
    expect(av?.classList.contains('blobatar-gaze')).toBe(true);
    expect(av?.getAttribute('data-morph')).toBe('ignore');
    expect(av?.querySelector('.mo-root')).not.toBeNull();
    const btn = el.querySelector('#copyEmail');
    expect(btn?.getAttribute('data-email')).toBe('zz9999@srmist.edu.in');
    expect(el.querySelector('[data-copy="RA2500000000"]')).not.toBeNull();
    expect(text(el)).toContain('Test Student');
    // the box comes FIRST: LAYOUT's day card is [profile, today, week]
    expect(el.querySelector('.wbox')).toBe(av?.closest('.wbox'));
  });

  it('every widget sits in the server\'s card > card-body tree (W2.6 regression)', async () => {
    // home.html:234-237 wraps each card's widgets as `.card > .card-body >
    // .wbox`, and home.html:227-232 states the hydration contract: "replaces
    // this element's children with the same tree". It did not — the island
    // emitted six bare wboxes, so the grid cell was gone (feedback card
    // collapsed to 58x64), `box.closest('.card')` was null (scope-profile DUT
    // threw) and home.html's `.card-body > .wbox` flex rules had no parent.
    //
    // LAYOUT is THREE cards for seven widgets — day [profile, today, week],
    // assess [marks, exams], people [attendance, teachers] — so the counts are
    // 3, not one per widget. Pinned against the server's own paint:
    // tests/golden/dom/dashboard.html has 3 `card bg-base-200` divs and 3
    // `card-body` divs (its 6 wboxes differ only because the fixture has no
    // ticker, which the PROPS above also omit).
    document.body.innerHTML = newPage();
    await hydrateAll(document, Date.now() / 1000);
    const el = grid();
    const cards = Array.from(el.querySelectorAll<HTMLElement>('.card'));
    expect(cards).toHaveLength(3);
    expect(el.querySelectorAll('.card-body')).toHaveLength(3);
    for (const c of cards) {
      // exactly one card-body, a DIRECT child — not any descendant
      expect(Array.from(c.children).filter((n) => n.classList.contains('card-body'))).toHaveLength(1);
    }
    // no widget is left outside a card-body
    const wboxes = Array.from(el.querySelectorAll<HTMLElement>('.wbox'));
    expect(wboxes).toHaveLength(6); // profile, week, budgets, marks, exams, teachers
    for (const w of wboxes) expect(w.parentElement?.closest('.card-body')).not.toBeNull();
    // and the spans are LAYOUT's, so each card keeps its grid cell
    expect(cards[0].className).toContain('lg:col-span-4');
    expect(cards[0].className).toContain('lg:row-span-2');
    expect(cards[1].className).toContain('lg:col-span-8');
    expect(cards[1].className).toContain('lg:max-h-[calc((100dvh-94px)*0.65)]');
    // people is a `cols: 2` card: the widgets ride one inner grid
    expect(cards[2].querySelector('.card-body > div.grid')).not.toBeNull();
  });

  it('a card whose widgets are all empty emits no orphan shell', async () => {
    // layout.py's `when` rule, mirrored: the route drops a card when every one
    // of its guard vars is empty, so the island must drop it too — an empty
    // `.card` is a visible grid cell with nothing in it.
    document.body.innerHTML = newPage({ ...PROPS, budgets: [], teachers: [], marks: [], exams: null });
    await hydrateAll(document, Date.now() / 1000);
    const el = grid();
    expect(el.querySelectorAll('.card')).toHaveLength(1);  // `day` only
    expect(el.querySelectorAll('.card-body')).toHaveLength(1);
    expect(el.querySelectorAll('.wbox')).toHaveLength(2);  // profile + week
  });

  it('rendered text matches the server markup fixture (no drift)', async () => {
    // Same inputs, no ticker: the hydrated text must equal the server's for
    // the one widget both paint verbatim — plus the widgets the SSR omitted
    // must all still be present, so nothing is silently dropped.
    document.body.innerHTML = newPage();
    await hydrateAll(document, Date.now() / 1000);
    expect(text(grid())).toContain('days absent');
    expect(text(grid())).toContain('3 hrs lost');
    // the week chips keep their token mapping (BADGE_VARIANTS.warning, week.html:8)
    const chip = grid().querySelector('.badge-warning');
    expect(chip).not.toBeNull();
    expect(chip!.className).toContain('badge-soft');
  });

  it('an empty widget self-hides exactly as the partial does', async () => {
    // ticker:null (no classes) + no budgets + no exams => those three are gone
    document.body.innerHTML = newPage({ ...PROPS, budgets: [], exams: null });
    await hydrateAll(document, Date.now() / 1000);
    const t = text(grid());
    expect(t).not.toContain('to 75%');       // attendance widget absent
    expect(t).not.toContain('End sem exams'); // exams widget absent
    expect(t).toContain('This week');         // week is unconditional in its partial
  });

  it('the CTA is absent when there is no feedback plan', async () => {
    document.body.innerHTML = newPage({ ...PROPS, fb_plan: false });
    await hydrateAll(document, Date.now() / 1000);
    expect(text(grid())).not.toContain('Auto-fill mid-sem feedback');
  });

  it('invalid props leave the server markup untouched', async () => {
    // `budgets` must be [string, string, number] triples — a bare string is a
    // trust-boundary violation, so the schema must reject the whole payload.
    document.body.innerHTML = newPage({ ...PROPS, budgets: ['not-a-tuple'] });
    await hydrateAll(document, Date.now() / 1000);
    const el = grid();
    expect(el.hasAttribute('data-hydrated')).toBe(false);
    expect(text(el)).toContain('days absent');   // server paint survived
    expect(LOG.join('\n')).toContain('invalid props');
  });

  it('an island that throws keeps the original children', async () => {
    // Same boundary as P4.1 (main.test.ts): a render throw restores the server's
    // nodes. Forced by poisoning the mount element's own setAttribute, which
    // DashboardPanel calls first — a throw from inside the component's body.
    document.body.innerHTML = newPage();
    const el = grid();
    const before = Array.from(el.childNodes);
    vi.spyOn(el, 'setAttribute').mockImplementation(() => { throw new Error('boom'); });
    await hydrateAll(document, Date.now() / 1000);
    expect(Array.from(el.childNodes)).toEqual(before);
    expect(text(el)).toContain('days absent');
    expect(LOG.join('\n')).toContain('failed to render');
  });
});
