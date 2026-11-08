import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { db, PANELS, readMeta, wipeAll, writeMeta, writePanel } from '../db';
import { currentNetid, onLogout, setNetid, WIPE_CAP_MS, wireLogoutLink } from './session';

const A = 'zz1111';
const B = 'zz2222';
// Minimal rows: these tests own the WIPE, not payload validation.
const P = {} as never;

const LOG: string[] = [];
beforeEach(async () => {
  LOG.length = 0;
  setNetid(undefined);
  vi.spyOn(console, 'warn').mockImplementation((m: unknown) => void LOG.push(String(m)));
});
afterEach(async () => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  await wipeAll();
});

const nothing = { attendance: 0, marks: 0, timetable: 0, fees: 0, campus: 0, academics: 0, meta: 0 };
const oneEach = { attendance: 1, marks: 1, timetable: 1, fees: 1, campus: 1, academics: 1, meta: 1 };

/** Rows held per store FOR `netid`. `null` only when every store is empty —
 *  the shape makes "wiped" and "never written" distinguishable. */
async function rowsFor(netid: string): Promise<Record<string, number> | null> {
  const out: Record<string, number> = {};
  for (const p of PANELS) out[p] = await db.table(p).where('netid').equals(netid).count();
  out.meta = (await readMeta(netid)) ? 1 : 0;
  const total = Object.values(out).reduce((a, b) => a + b, 0);
  return total === 0 ? null : out;
}

/** Both students cached, in every store, plus their meta rows. */
async function seedBoth(): Promise<void> {
  for (const n of [A, B]) {
    await writePanel('attendance', { netid: n, groupKey: 'g1', payload: P });
    await writePanel('marks', { netid: n, groupKey: 'g1', payload: [] as never });
    await writePanel('timetable', { netid: n, groupKey: 'g1', payload: P });
    await writePanel('fees', { netid: n, payload: P });
    await writePanel('campus', { netid: n, payload: P });
    await writePanel('academics', { netid: n, payload: P });
    await writeMeta({ netid: n, last_sync: { fees: 1 }, schemaVersion: 1, flags: {} });
  }
}

describe('session scope', () => {
  it('currentNetid() reports what the bootstrap set', () => {
    expect(currentNetid()).toBeUndefined();
    setNetid(B);
    expect(currentNetid()).toBe(B);
    setNetid('');
    expect(currentNetid()).toBeUndefined(); // '' is not an account
  });
});

describe('logout wipe is netid-scoped', () => {
  it('wipes every store for the current netid', async () => {
    setNetid(A);
    await seedBoth();
    // POSITIVE CONTROL: A was cached in all seven stores before the logout.
    expect(await rowsFor(A)).toEqual(oneEach);

    const navigated: string[] = [];
    await onLogout('/login', { navigate: (u) => void navigated.push(u) });

    expect(await rowsFor(A)).toBeNull();
    expect(navigated).toHaveLength(1);
    expect(navigated[0]).toMatch(/\/login$/);
  });

  it("does NOT wipe another student's records on the same device", async () => {
    setNetid(A);
    await seedBoth();
    // POSITIVE CONTROL for the "did not happen" half below: B really was
    // cached. Without this, "B survived" would also hold on an empty DB.
    expect(await rowsFor(B)).toEqual(oneEach);

    await onLogout('/login', { navigate: () => {} });

    // POSITIVE CONTROL the wipe actually ran against the current netid:
    expect(await rowsFor(A)).toBeNull();
    // Same device, same stores, B still whole — the assertion the row owns.
    expect(await rowsFor(B)).toEqual(oneEach);
    expect(await db.attendance.get([B, 'g1'])).toBeDefined();
    expect(await db.attendance.get([A, 'g1'])).toBeUndefined();
  });

  it('is idempotent: a second logout does not throw', async () => {
    setNetid(A);
    await seedBoth();
    // POSITIVE CONTROL: the first call had something to delete and deleted it.
    expect(await rowsFor(A)).toEqual(oneEach);
    await expect(onLogout('/login', { navigate: () => {} })).resolves.toMatch(/\/login$/);
    expect(await rowsFor(A)).toBeNull();

    const navigated: string[] = [];
    await expect(onLogout('/login', { navigate: (u) => void navigated.push(u) })).resolves.toMatch(
      /\/login$/,
    );
    expect(navigated).toHaveLength(1); // still navigates, second time through
    expect(await rowsFor(A)).toBeNull();
    expect(await rowsFor(B)).toEqual(oneEach); // and still did not touch B
  });
});

describe('logout survives a hostile storage stack', () => {
  it('IndexedDB unavailable: onLogout still resolves and navigation is attempted', async () => {
    setNetid(A);
    await seedBoth();
    // POSITIVE CONTROL: on a healthy stack A's rows are gone after a logout —
    // so the private-mode case below is the SAME call, not a weaker one.
    expect(await rowsFor(A)).toEqual(oneEach);

    // Safari private mode / denied storage: touching the factory throws.
    vi.stubGlobal('indexedDB', {
      databases() {
        throw new Error('SecurityError: indexedDB unavailable (private mode)');
      },
    });

    const navigated: string[] = [];
    let done = false;
    const p = onLogout('/login', { navigate: (u) => void navigated.push(u) }).then((u) => {
      done = true;
      return u;
    });
    await expect(p).resolves.toMatch(/\/login$/);
    // With the factory zapped, nothing can be checked through Dexie — so assert
    // the outcome the caller sees: logout completed and navigation was asked for.
    expect(done).toBe(true);
    expect(navigated).toHaveLength(1);
    // POSITIVE CONTROL: the guard fired. Without this the test would also pass
    // if wipeAll silently returned early for some unrelated reason.
    expect(LOG.join()).toContain('no usable IndexedDB');
  });

  it('a hanging wipe still lets the caller proceed once the cap expires', async () => {
    setNetid(A);
    await seedBoth();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    // The wipe itself hangs forever: the cap, not the wipe, must be what
    // unblocks logout.
    const never = vi.spyOn(db.table('attendance'), 'where').mockImplementation(
      () => ({ equals: () => ({ delete: () => new Promise<void>(() => {}) }) }) as never,
    );

    const navigated: string[] = [];
    let done = false;
    const p = onLogout('/login', { navigate: (u) => void navigated.push(u) }).then((u) => {
      done = true;
      return u;
    });

    await vi.advanceTimersByTimeAsync(WIPE_CAP_MS - 1);
    // POSITIVE CONTROL that the timer is what unblocks it: one ms short, it is
    // still blocked, so `done` is not true all along.
    expect(never).toHaveBeenCalled();
    expect(done).toBe(false);
    expect(navigated).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    await expect(p).resolves.toMatch(/\/login$/);
    expect(done).toBe(true);
    expect(navigated).toHaveLength(1);
    never.mockRestore();
  });
});

describe('the logout link', () => {
  it('intercepts a plain click, leaves a modified click alone, and still navigates', async () => {
    setNetid(A);
    await seedBoth();
    // A fresh element per test: the wiring queries at bind time, so nothing
    // left over from another test's document can share this listener.
    const link = document.createElement('a');
    link.href = '/logout';
    link.textContent = 'Log out';
    document.body.append(link);
    const navigated: string[] = [];
    const unbind = wireLogoutLink(document, (u) => void navigated.push(u));

    // POSITIVE CONTROL: A is cached before the click, so "wiped after" means
    // something.
    expect(await rowsFor(A)).toEqual(oneEach);

    // Modified click ("open in new tab") is the browser's: not prevented, not wiped.
    link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ctrlKey: true }));
    expect(await rowsFor(A)).toEqual(oneEach);
    expect(navigated).toHaveLength(0);

    // Plain click: the handler owns it (so the browser does not navigate on
    // its own), wipes, then navigates to the link's own href.
    const plain = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    link.dispatchEvent(plain);
    expect(plain.defaultPrevented).toBe(true);
    await vi.waitFor(() => expect(navigated).toHaveLength(1));
    expect(navigated[0]).toMatch(/\/logout$/);
    expect(await rowsFor(A)).toBeNull();

    unbind();
    link.remove();
  });
});
