import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import { readPanel, wipeAll, writePanel } from '../../db';
import { bootstrapSession, setNetid } from '../../session';
import type { FeesData } from '../../contracts';
import { ageCaption } from '../../lib/syncAge';
import { STALE_ATTR } from '../../islands/stale';

// ── P7.2 acceptance: a STALE cached copy is labelled with its age, a fresh one
// is not, and the label comes from syncAge (break it, this goes red).
//
// Standing rule 5: the "fresh renders no caption" case carries a positive
// control — the same shell, same seed, only the age differs — so a page that
// simply never renders the caption cannot pass this file.

const NETID = 'zz1111';
const HOUR = 3600_000;
const STALE_MS = 6 * HOUR;

const API: FeesData = {
  due: 3150,
  due_disp: '3,150.00',
  level: 'text-warning',
  dues: [{ amt: '3,150.00', due: '25-11-2026', penalty: '24-11-2026', penalised: false }],
  paid_total: '200,000.00',
  years: [{ year: '2026', total: '100,000.00', rows: [{ date: '2026-07-12', head: 'Semester fee', amt: '75,000.00' }] }],
  ledger: [{ date: '2026-08-02', amt: '25,000.00', vno: 'RC-77', head: 'Exam fee', full: 'Exam fee paid online' }],
};
const CACHED: FeesData = { ...API, due: 999, due_disp: '999.00', dues: [], years: [], ledger: [] };

let pageId = 0;
const shell = () => {
  const id = `island-fees-${++pageId}`;
  return `<div id="tab-fees" role="tabpanel" data-island="fees" data-props="#${id}">
      <div class="bg-base-200">SERVER PAINT</div></div>
    <script type="application/json" id="${id}"></script>`;
};
const mount = () => document.querySelector<HTMLElement>('[data-island="fees"]')!;
/** The caption, wherever main.ts put it — by its own attribute, not by shape. */
const caption = () => mount().querySelector<HTMLElement>(`[${STALE_ATTR}]`);
const offline = () => vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline'); }));

/** Seed the cache `ageMs` old, then hydrate the offline shell. `fetchedAt` is
 *  read straight from the row, so the age is exact, not approximated. */
async function hydrateWithAge(ageMs: number): Promise<void> {
  await writePanel('fees', { netid: NETID, payload: CACHED as never, fetchedAt: Date.now() - ageMs });
  // POSITIVE CONTROL: the row is really there, with really that stamp.
  expect(await readPanel('fees', NETID)).toEqual(CACHED);
  offline();
  document.body.innerHTML = shell();
  bootstrapSession(document);
  await hydrateAll(document.body, Date.now() / 1000);
  expect(mount().getAttribute('data-hydrated')).toBe('1');   // the cache really rendered
}

beforeEach(async () => {
  document.body.innerHTML = '';
  document.body.dataset.netid = NETID;
  setNetid(undefined);
  (await import('../../main')).__resetWarnOnce();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete document.body.dataset.netid;
  setNetid(undefined);
  await wipeAll();
});

describe('P7.2 — a stale cached panel is labelled', () => {
  it('renders "as of Nh ago" for a cache older than STALE_MS', async () => {
    await hydrateWithAge(7 * HOUR);
    const c = caption();
    expect(c).not.toBeNull();
    expect(c!.textContent).toBe('as of 7h ago');
    // The cached data (999.00), not the server's paint: the label rides the
    // paint it describes.
    expect(mount().textContent).toContain('₹999.00');
  });

  it('announces politely and stays a sibling, not a wrapper', async () => {
    await hydrateWithAge(7 * HOUR);
    const c = caption()!;
    expect(c.getAttribute('aria-live')).toBe('polite');
    // The island's own children are still direct children of the mount (the
    // P6.3 rule): the caption is one more child, never a box around them.
    expect(c.parentElement).toBe(mount());
    expect(mount().querySelector('#tab-fees')).toBeNull();
  });

  it('says nothing for a cache inside the window — with a positive control', async () => {
    await hydrateWithAge(1 * HOUR);
    expect(caption()).toBeNull();
    expect(mount().textContent).toContain('₹999.00');   // same path, same paint
  });
});

describe('P7.2 — the age comes from syncAge', () => {
  it('a bucket change in syncAge moves the caption', async () => {
    // The unit-under-test, spelled out: whatever syncAge caps a 7h age at is
    // what the caption must carry. Break syncAge and both halves go red.
    expect(ageCaption(Date.now() / 1000 - 7 * 3600, Date.now() / 1000)).toBe('(7h ago)');
    await hydrateWithAge(7 * HOUR);
    expect(caption()!.textContent).toBe('as of 7h ago');
  });

  it('labels a row with no stamp rather than claiming it is fresh', async () => {
    // fetchedAt 0 => "Never synced" in syncAge => the caption cannot say an age.
    await writePanel('fees', { netid: NETID, payload: CACHED as never, fetchedAt: 0 });
    expect(await readPanel('fees', NETID)).toEqual(CACHED);
    offline();
    document.body.innerHTML = shell();
    bootstrapSession(document);
    await hydrateAll(document.body, Date.now() / 1000);
    const c = caption();
    expect(c).not.toBeNull();
    expect(c!.textContent).toBe('showing a saved copy that may be out of date');
  });
});

// Guard against the constant drifting out of this file.
expect(STALE_MS).toBe(6 * HOUR);
