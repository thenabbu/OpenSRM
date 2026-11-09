import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import type { SettingsProps } from './contract';

// The fixture is the shape app/views/settings_island.py:props() emits for a
// filled portal: identity header + three groups (Academic carries the wide
// Institution cell, Contact carries the prose Address — the two behaviours the
// template branches on). No @testing-library/preact dep — same harness as
// campus.test.ts / fees.test.ts.
const PROPS: SettingsProps = {
  personal: {
    name: 'Aarav Mehta',
    program: 'B.Tech CSE (Cloud Computing)',
    groups: [
      {
        title: 'Academic',
        items: [
          { key: 'Register No.', value: 'RA2511028030033', wide: false, mono: true },
          { key: 'Institution', value: 'SRMIST Delhi-NCR', wide: true, mono: true },
        ],
      },
      {
        title: 'Personal',
        items: [{ key: 'Blood Group', value: 'O+', wide: false, mono: true }],
      },
      {
        title: 'Contact',
        items: [
          { key: 'Address', value: 'Flat 4, Sector 62', wide: true, mono: false },
          { key: 'Pincode', value: '201309', wide: false, mono: true },
        ],
      },
    ],
  },
  count: 7,
};

let pageId = 0;
/** Server markup: the mount IS #personal-details, painted + the inert block. */
const page = (props: unknown = PROPS, id = `island-settings-${++pageId}`) => `
  <section id="markup">
    <div class="flex flex-col gap-3">
      <div class="collapse" id="personal-details" data-island="settings" data-props="#${id}">
        <div class="collapse-content">SERVER PAINT: Aarav Mehta</div>
      </div>
      <a href="/logout" id="logout-row"><span>Log out</span></a>
      <div class="card" id="push-card">Notifications</div>
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

const mount = () => document.querySelector<HTMLElement>('[data-island="settings"]')!;
const NOW = Date.parse('2026-11-09T10:20:00Z') / 1000;
const hydrate = async () => { document.body.innerHTML = page(); return hydrateAll(document.body, NOW); };

describe('settings island', () => {
  it('hydrates: sets data-hydrated on the mount and keeps the id', async () => {
    await hydrate();
    expect(mount().hasAttribute('data-hydrated')).toBe(true);
    expect(mount().id).toBe('personal-details');
    // no nesting: the outer collapse is the mount's own content, and each group
    // is one child collapse of it (3 groups in the fixture) — never an extra level
    expect(mount().firstElementChild!.classList.contains('collapse')).toBe(true);
    expect(mount().querySelectorAll('.collapse').length).toBe(4); // the mount + 3 groups
    expect(mount().querySelectorAll('.collapse-content').length).toBe(4);
  });

  it('paints the identity header and the count badge the server counted', async () => {
    await hydrate();
    expect(mount().querySelector('.text-lg.font-semibold')!.textContent).toBe('Aarav Mehta');
    expect(mount().textContent).toContain('B.Tech CSE (Cloud Computing)');
    expect(mount().querySelector('.collapse-title .badge')!.textContent).toBe('7');
    expect(mount().querySelector('.collapse-title')!.textContent).toContain('Personal details');
  });

  it('group order follows props order, each with its own item count', async () => {
    await hydrate();
    const titles = [...mount().querySelectorAll('.collapse-title')].map((n) => n.textContent);
    expect(titles).toEqual([
      'Personal details7', 'Academic2', 'Personal1', 'Contact2',
    ]);
  });

  it('wide keys span both columns; Address is prose, every other value mono', async () => {
    await hydrate();
    const groups = [...mount().querySelectorAll('.collapse')] as HTMLElement[];
    const academic = groups[1];
    const cells = [...academic.querySelectorAll('.collapse-content > div > div')] as HTMLElement[];
    expect(cells[0].className).toBe('');
    expect(cells[1].className).toBe('sm:col-span-2');
    const contact = groups[3];
    const addr = contact.querySelector('[data-copy="Flat 4, Sector 62"]')!;
    expect(addr.className).toBe('text-sm break-words');
    const pin = contact.querySelector('[data-copy="201309"]')!;
    expect(pin.className).toBe('text-sm font-mono break-words');
  });

  it('empty personal renders the same "No personal details available." alert, no badge', async () => {
    document.body.innerHTML = page({ personal: null, count: 0 });
    await hydrateAll(document.body, NOW);
    expect(mount().querySelector('.alert.alert-info')!.textContent).toBe(
      'No personal details available.',
    );
    expect(mount().querySelector('.badge')).toBeNull();
    expect(mount().hasAttribute('data-hydrated')).toBe(true);
  });

  it('never re-wires logout: the /logout row and the push card are untouched siblings', async () => {
    document.body.innerHTML = page();
    const before = document.getElementById('push-card')!.outerHTML;
    await hydrateAll(document.body, NOW);
    expect(document.getElementById('push-card')!.outerHTML).toBe(before);
    expect(document.querySelector('#logout-row')!.getAttribute('href')).toBe('/logout');
  });

  it('a failing island leaves the server children untouched', async () => {
    const { mountBounded } = await import('../../main');
    const el = document.createElement('div');
    el.innerHTML = '<div class="collapse-content">SERVER PAINT: Aarav Mehta</div>';
    const before = el.innerHTML;
    const Boom = (): never => { throw new Error('boom'); };
    const ok = mountBounded('settings', Boom as never, el, PROPS, Date.now());
    expect(ok).toBe(false);
    expect(el.innerHTML).toBe(before);
    expect(el.hasAttribute('data-hydrated')).toBe(false);
    expect(LOG.join(' ')).toContain('server markup kept');
  });

  it('invalid props (missing count) render nothing and keep the server markup', async () => {
    document.body.innerHTML = page({ personal: null });
    const before = mount().innerHTML;
    await hydrateAll(document.body, NOW);
    expect(mount().innerHTML).toBe(before);
    expect(mount().hasAttribute('data-hydrated')).toBe(false);
  });
});
