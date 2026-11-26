import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAll } from '../../main';
import { db, readPanel, wipeAll, writePanel } from '../../db';
import { bootstrapSession, setNetid } from '../../session';
import type { FeesData } from '../../contracts';
import { FeesData as FeesSchema } from '../../contracts';
import type { FeesProps } from './contract';

// ── P7.1 acceptance: the island renders from the CACHE when the page has no
// props, and the seed's server paint survives a load that fails.
//
// Both halves need their positive control (standing rule 5). Every "nothing
// happened" assertion below is paired with a seed that proves the machinery
// was live: the row really is in IndexedDB, the server paint really is in the
// mount, the fetch really was called.

const NETID = 'zz1111';
const SCHEMA = 'zz2222'; // a DIFFERENT student's rows, to prove scoping

/** Exactly what /api/fees serves (vm["fees"]) — the store holds this shape. */
const API: FeesData = {
  due: 3150,
  due_disp: '3,150.00',
  level: 'text-warning',
  dues: [{ amt: '3,150.00', due: '25-11-2026', penalty: '24-11-2026', penalised: false }],
  paid_total: '200,000.00',
  years: [
    {
      year: '2026',
      total: '100,000.00',
      rows: [{ date: '2026-07-12', head: 'Semester fee', amt: '75,000.00' }],
    },
  ],
  ledger: [
    { date: '2026-08-02', amt: '25,000.00', vno: 'RC-77', head: 'Exam fee', full: 'Exam fee paid online' },
  ],
};
// Positive control for the fixture itself: if this ever fails, the constant
// above drifted from the schema and every assertion below is meaningless.
expect(FeesSchema.safeParse(API).success).toBe(true);

/** What the island renders from the CACHE. Distinct from API on purpose. */
const CACHED: FeesData = {
  ...API,
  due: 999,
  due_disp: '999.00',
  dues: [{ amt: '999.00', due: '01-12-2026', penalty: '', penalised: false }],
  years: [],
  ledger: [],
};

let pageId = 0;

/** The offline shell: the mount exists, its props block is EMPTY, and the
 *  server's first paint is in the mount. */
const shell = (paint = 'SERVER PAINT: ₹3,150.00', props: unknown = '') => {
  const id = `island-fees-${++pageId}`;
  return `
    <div id="tab-fees" role="tabpanel" data-island="fees" data-props="#${id}">
      <div class="bg-base-200">${paint}</div>
    </div>
    <script type="application/json" id="${id}">${JSON.stringify(props)}</script>`;
};

const mount = () => document.querySelector<HTMLElement>('[data-island="fees"]')!;
const LOG: string[] = [];

beforeEach(async () => {
  LOG.length = 0;
  document.body.innerHTML = '';
  document.body.dataset.netid = NETID;      // the server's <body data-netid>
  setNetid(undefined);
  (await import('../../main')).__resetWarnOnce();
  vi.spyOn(console, 'warn').mockImplementation((m: unknown) => void LOG.push(String(m)));
});

afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete document.body.dataset.netid;
  setNetid(undefined);
  await wipeAll();
});

/** Offline: every fetch rejects the way a dead network does. */
const offline = () => vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline'); }));

const seed = (row: unknown, netid = NETID) =>
  writePanel('fees', { netid, payload: row as never, fetchedAt: Date.now() - 1000 });

const hydrate = async () => {
  bootstrapSession(document);
  await hydrateAll(document.body, Date.now() / 1000);
};

describe('P7.1 — props empty, cache has a row: the cache renders', () => {
  it('renders the cached fees rows, not the server paint', async () => {
    await seed(CACHED);
    // POSITIVE CONTROL: the row really is in the store under this netid.
    expect(await readPanel('fees', NETID)).toEqual(CACHED);

    offline();
    document.body.innerHTML = shell();
    // POSITIVE CONTROL: the server paint is really there to be replaced.
    expect(mount().textContent).toContain('SERVER PAINT');

    await hydrate();

    expect(mount().getAttribute('data-hydrated')).toBe('1');
    // The cached number, the one the class above made up — no other source
    // on this page carries '999.00'.
    expect(mount().textContent).toContain('₹999.00');
    expect(mount().textContent).toContain('01-12-2026');
    expect(mount().textContent).not.toContain('SERVER PAINT');
    // And it did NOT silently render the API fixture instead.
    expect(mount().textContent).not.toContain('3,150.00');
  });

  it('never reads another student\'s cached rows', async () => {
    await seed(CACHED, SCHEMA);
    // POSITIVE CONTROL: the OTHER student's row exists and would render if the
    // cache were keyed wrong.
    expect(await readPanel('fees', SCHEMA)).toEqual(CACHED);
    expect(await db.fees.count()).toBe(1);

    offline();
    document.body.innerHTML = shell('SERVER PAINT: mine');
    await hydrate();

    expect(mount().textContent).toContain('SERVER PAINT: mine');
    expect(mount().textContent).not.toContain('999.00');
  });
});

describe('P7.1 — no cache and a network error: the server paint survives', () => {
  it('leaves the server paint untouched when the load fails', async () => {
    // POSITIVE CONTROL: the store is empty, so a cache pass is impossible.
    expect(await db.fees.count()).toBe(0);

    const fetcher = vi.fn(async () => { throw new TypeError('offline'); });
    vi.stubGlobal('fetch', fetcher);
    document.body.innerHTML = shell();

    await hydrate();

    expect(mount().textContent).toContain('SERVER PAINT: ₹3,150.00');
    expect(mount().getAttribute('data-hydrated')).toBeNull();
    // POSITIVE CONTROL: the load path really RAN and really failed — otherwise
    // "paint survived" would also pass with the read path deleted.
    expect(fetcher).toHaveBeenCalled();
    expect(LOG.join()).toContain('invalid props');
  });

  it('keeps the paint when the network returns an invalid payload', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ ok: true, data: { nope: 1 } }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    document.body.innerHTML = shell('SERVER PAINT: intact');

    await hydrate();

    expect(mount().textContent).toContain('SERVER PAINT: intact');
    expect(fetcher).toHaveBeenCalled();
  });
});

describe('P7.1 — valid server props are the first paint', () => {
  it('does not re-render over good props when the network answers', async () => {
    const props: FeesProps = {
      due_disp: '3,150.00',
      level: 'text-warning',
      dues: [{ amt: '3,150.00', due: '25-11-2026', penalty: '', penalised: false }],
      paid_total: '',
      years: [],
      ledger: [],
    };
    vi.stubGlobal('fetch', vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, data: API }), { status: 200 })));

    document.body.innerHTML = shell('SERVER PAINT: props win', props);
    await hydrate();

    expect(mount().getAttribute('data-hydrated')).toBe('1');
    // The island rendered the PROPS, whose paid_total is '' (no "Paid" header),
    // while API carries 200,000.00 and a year group. A cache/network merge over
    // the props would have added that header.
    expect(mount().textContent).toContain('₹3,150.00');
    expect(mount().textContent).not.toContain('Paid');
  });
});

describe('P7.1 — no netid means no cache access at all', () => {
  it('skips the read path entirely when <body> carries no data-netid', async () => {
    await seed(CACHED);
    // POSITIVE CONTROL: the row IS there — but with no owner it must not be used.
    expect(await readPanel('fees', NETID)).toEqual(CACHED);

    delete document.body.dataset.netid;
    const fetcher = vi.fn(async () => { throw new TypeError('offline'); });
    vi.stubGlobal('fetch', fetcher);
    document.body.innerHTML = shell('SERVER PAINT: anonymous');
    await hydrate();

    expect(mount().textContent).toContain('SERVER PAINT: anonymous');
    expect(mount().textContent).not.toContain('999.00');
    expect(fetcher).not.toHaveBeenCalled();
  });
});
