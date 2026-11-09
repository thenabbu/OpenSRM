import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import { dashboardProps } from './contract';

// Exactly what app/templates/home.html renders into the card grid for one
// student: the six widgets with their guards satisfied — EXCEPT `ticker`, whose
// widget is the one the fallback test below hides. Written by hand from the
// partials (today.html, week.html, attendance.html, marks.html, exams.html,
// teachers.html) so it is a real fixture, not the island's own output.
const PROPS = {
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
    expect(el.querySelectorAll('.wbox')).toHaveLength(5);        // week, budgets, marks, exams, teachers
    expect(text(el)).toContain('This week');
    expect(text(el)).toContain('2 days absent');
    expect(text(el)).toContain('Computer Organization And Architecture');
    expect(text(el)).toContain('-4');
    expect(text(el)).toContain('18/20');
    expect(text(el)).toContain('First exam in');
    expect(text(el)).toContain('Dr. Priyanka Gupta');
    expect(text(el)).toContain('Auto-fill mid-sem feedback');
  });

  it('rendered text matches the server markup fixture (no drift)', async () => {
    // Same inputs, no ticker: the hydrated text must equal the server's for
    // the one widget both paint verbatim — plus the widgets the SSR omitted
    // must all still be present, so nothing is silently dropped.
    document.body.innerHTML = newPage();
    await hydrateAll(document, Date.now() / 1000);
    expect(text(grid())).toContain('days absent');
    expect(text(grid())).toContain('3 hrs lost');
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
