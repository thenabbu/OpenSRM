import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import type { ToolsProps } from './contract';

// The fixture is the shape app/views/tools_island.py:props() emits for
// app/views/timetable.py:_tools_entries rows. Two rows so order is provable;
// hints are long enough to exercise the single-line clip class.
// No @testing-library/preact dep — same harness as campus.test.ts.
const PROPS: ToolsProps = {
  rows: [
    { slug: 'academics', label: 'Academics', hint: 'Grades, credits and semester GPA', tab: 'academics' },
    { slug: 'fees', label: 'Fees', hint: 'Outstanding dues, receipts and paid history', tab: 'fees' },
  ],
};

let pageId = 0;
/**
 * Server markup mirroring tools.html:206-222: the mount node is the <ul>
 * itself, so the island must return the <ul> and nothing around it. The card
 * and heading above it are template chrome the island never touches.
 */
const page = (props: unknown = PROPS, id = `island-tools-${++pageId}`) => `
  <div class="card bg-base-200 border border-base-300">
    <div class="card-body p-4">
      <h2 class="text-base font-semibold mb-3">Tools</h2>
      <ul id="list" class="flex flex-col gap-2" data-island="tools" data-props="#${id}">
        <li><a href="/academics">SERVER PAINT: Academics</a></li>
      </ul>
    </div>
  </div>
  <script type="application/json" id="${id}">${JSON.stringify(props)}</script>`;

const LOG: string[] = [];
beforeEach(async () => {
  LOG.length = 0;
  document.body.innerHTML = '';
  (await import('../../main')).__resetWarnOnce();
  vi.spyOn(console, 'warn').mockImplementation((m: unknown) => { LOG.push(String(m)); });
});

const mount = () => document.querySelector<HTMLElement>('[data-island="tools"]')!;
const NOW = Date.parse('2026-11-09T10:20:00Z') / 1000;
const hydrate = async (props?: unknown, id?: string) => {
  document.body.innerHTML = page(props, id);
  return hydrateAll(document.body, NOW);
};

describe('tools island', () => {
  it('hydrates: the mount is one <ul>, marked data-hydrated', async () => {
    await hydrate();
    expect(mount().hasAttribute('data-hydrated')).toBe(true);
    // No wrapper crept in: the mount's children are the rows themselves.
    expect([...mount().children].every((n) => n.tagName === 'LI')).toBe(true);
  });

  it('paints one row per registry entry: link, label, hint, chevron', async () => {
    await hydrate();
    const links = [...mount().querySelectorAll('li > a')] as HTMLAnchorElement[];
    expect(links).toHaveLength(2);
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/academics', '/fees']);
    expect(links.map((a) => a.textContent)).toEqual([
      'AcademicsGrades, credits and semester GPA',
      'FeesOutstanding dues, receipts and paid history',
    ]);
    expect(links[0].querySelector('.text-sm.font-semibold')!.textContent).toBe('Academics');
    expect(links[0].querySelector('.text-xs')!.textContent).toBe('Grades, credits and semester GPA');
  });

  it('keeps the template row hooks: data-tool-tab + data-tool-slug', async () => {
    await hydrate();
    const links = [...mount().querySelectorAll('a')];
    expect(links.map((a) => a.dataset.toolTab)).toEqual(['academics', 'fees']);
    expect(links.map((a) => a.dataset.toolSlug)).toEqual(['academics', 'fees']);
  });

  it('row order follows props order (server order is the only order)', async () => {
    await hydrate();
    const labels = [...mount().querySelectorAll('.text-sm.font-semibold')].map((n) => n.textContent);
    expect(labels).toEqual(PROPS.rows.map((r) => r.label));
  });

  it('the chevron is decorative: aria-hidden, not a second label', async () => {
    await hydrate();
    for (const svg of mount().querySelectorAll('svg')) {
      expect(svg.getAttribute('aria-hidden')).toBe('true');
    }
  });

  it('the server paint is replaced, not appended to (no duplicate rows)', async () => {
    await hydrate();
    expect(mount().textContent).not.toContain('SERVER PAINT');
    expect(mount().querySelectorAll('li')).toHaveLength(2);
  });

  it('a failing island leaves the server children untouched', async () => {
    const { mountBounded } = await import('../../main');
    const el = document.createElement('ul');
    el.innerHTML = '<li><a href="/academics">SERVER PAINT: Academics</a></li>';
    const before = el.innerHTML;
    const Boom = (): never => { throw new Error('boom'); };
    const ok = mountBounded('tools', Boom as never, el, PROPS, Date.now());
    expect(ok).toBe(false);
    expect(el.innerHTML).toBe(before);
    expect(el.hasAttribute('data-hydrated')).toBe(false);
    expect(LOG.join(' ')).toContain('server markup kept');
  });

  it('invalid props (row missing its tab) render nothing and keep the server markup', async () => {
    document.body.innerHTML = page({ rows: [{ slug: 'x', label: 'X', hint: 'h' }] });
    const before = mount().innerHTML;
    await hydrateAll(document.body, NOW);
    expect(mount().innerHTML).toBe(before);
    expect(mount().hasAttribute('data-hydrated')).toBe(false);
  });

  it('empty rows list paints an empty <ul>, not a crash', async () => {
    await hydrate({ rows: [] });
    expect(mount().hasAttribute('data-hydrated')).toBe(true);
    expect(mount().children).toHaveLength(0);
  });
});
