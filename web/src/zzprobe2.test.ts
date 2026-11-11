import 'fake-indexeddb/auto';
import { expect, it, vi } from 'vitest';
import { setNetid, sessionGroupKey } from './session/session';
import { wipeAll } from './db';

const COURSE = { code: 'C', description: 'D', attended: 20, max_hours: 30, pct_disp: '66.6',
  fill: 66.67, t75: 23, skip_now: -1, attend_now: 3, tint: 'red', margin: -3, label: 'x', nudge: '', pole: false };
const PAYLOAD = { ok: true, data: { courses: [COURSE] } };

it('probe', async () => {
  await wipeAll();
  setNetid('zz7111');
  console.log('GROUPKEY', JSON.stringify(sessionGroupKey()), 'NETID', JSON.stringify((await import('./session/session')).currentNetid?.() ?? 'n/a'));
  vi.spyOn(console, 'warn').mockImplementation((...a: unknown[]) => { console.log('WARN', ...a); });
  document.body.innerHTML = '<div><span data-island="attendance">rows</span></div>';
  const el = document.querySelector<HTMLElement>('[data-island="attendance"]')!;
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(PAYLOAD), { status: 200 })));
  vi.resetModules();
  const { hydrateIsland } = await import('./main');
  await hydrateIsland(el, Date.now() / 1000);
  console.log('AFTER mountedAt=', el.dataset.mountedAt, 'children', el.children.length);
  expect(1).toBe(1);
});
