import 'fake-indexeddb/auto';
import { it } from 'vitest';
import { loadPanel } from './data/load';
import { propsFromCache, hasIslandProjection } from './data/props';
import { db, writePanel, readPanel } from './db';

const PAYLOAD = { ok: true, data: { courses: [{
  code: 'X', description: 'D', attended: 20, max_hours: 30, pct_disp: '66.6', fill: 66.67,
  t75: 23, skip_now: -1, attend_now: 3, tint: 'red', margin: -3, label: 'x', nudge: '', pole: false,
}] } };

it('probe', async () => {
  (globalThis as any).fetch = async () => new Response(JSON.stringify(PAYLOAD), { status: 200 });
  console.log('hasProjection attendance', hasIslandProjection('attendance'));
  const out = await loadPanel('attendance', { netid: 'zz1', groupKey: '' });
  console.log('outcome', JSON.stringify(out).slice(0, 300));
  console.log('direct', JSON.stringify(propsFromCache('attendance', (out as any).data)).slice(0, 300));
  const rd = await readPanel('attendance', 'zz1', '');
  console.log('readPanel', JSON.stringify(rd).slice(0, 200));
  console.log('fromCache(read)', JSON.stringify(propsFromCache('attendance', rd)).slice(0, 200));
});
