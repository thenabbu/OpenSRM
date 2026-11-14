import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { db, wipeAll } from '../db/db';
import {
  drainOutbox, io, MAX_ATTEMPTS, OUTBOX_ATTR, OUTBOX_ROUTES,
  pendingWrites, queueWrite, startOutbox,
} from './outbox';

/**
 * P7.4 — deferred writes survive being offline.
 *
 * The property under test is exactly the one the brief names: a tag queued
 * while `navigator.onLine === false` must make ZERO network calls, then make
 * EXACTLY ONE when the link returns, and the row is gone afterwards. A queue
 * that never drains passes the first half and fails the second, which is why
 * the call count is asserted and not just the row count.
 */

const NETID = 'zz7777';
const FORM = { code: '21CSS201T', component: 'CAT-1', role: 'IE-1' };
const CALLS: string[] = [];
let online = false;

const jsonResponse = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

beforeEach(() => {
  CALLS.length = 0;
  online = false;
  document.body.innerHTML = '';
  // Stub the two impure edges: the link state and the POST itself. The counter
  // lives on the real fetch path `send()` uses, so "one network call" is
  // measured through the production code, not a helper the test defines.
  io.online = () => online;
  io.post = async (url: string, body: FormData) => {
    CALLS.push(url);
    expect(body.get('code')).toBe('21CSS201T');
    expect(body.get('component')).toBe('CAT-1');
    return jsonResponse({ ok: true });
  };
});

afterEach(async () => {
  vi.restoreAllMocks();
  await wipeAll();
});

describe('P7.4 write queue survives being offline', () => {
  it('enqueues offline, replays EXACTLY ONE call on return, and clears the row', async () => {
    await queueWrite(NETID, 'tag', FORM);
    expect(await db.outbox.count()).toBe(1);

    // Offline: a drain attempt must not touch the network at all.
    const off = await drainOutbox();
    expect(CALLS).toHaveLength(0);
    expect(off.sent).toBe(0);
    expect(await db.outbox.count()).toBe(1); // still queued

    online = true;
    const on = await drainOutbox();
    expect(CALLS).toEqual(['/marks/tag']);
    expect(on.sent).toBe(1);
    expect(await db.outbox.count()).toBe(0);
  });

  it('does not replay twice — an emptied queue stays empty', async () => {
    await queueWrite(NETID, 'tag', FORM);
    online = true;
    await drainOutbox();
    await drainOutbox();
    expect(CALLS).toHaveLength(1);
  });

  it('last-write-wins per subject+component: re-tagging offline sends ONE write, the LAST choice', async () => {
    await queueWrite(NETID, 'tag', { ...FORM, role: 'IE-1' });
    await queueWrite(NETID, 'tag', { ...FORM, role: 'IE-2' }); // same code+component
    expect(await db.outbox.count()).toBe(1); // replaced, not appended
    expect((await pendingWrites(NETID))[0]?.form.role).toBe('IE-2');

    online = true;
    await drainOutbox();
    expect(CALLS).toHaveLength(1); // one write, not two
  });

  it('keeps a different component as a second row (the grain is not the whole subject)', async () => {
    await queueWrite(NETID, 'tag', FORM);
    await queueWrite(NETID, 'tag', { ...FORM, component: 'CAT-2' });
    expect(await db.outbox.count()).toBe(2);
  });

  it('keeps the row on a network error and drops it only past MAX_ATTEMPTS', async () => {
    await queueWrite(NETID, 'tag', FORM);
    online = true;
    io.post = async () => {
      CALLS.push('boom');
      throw new Error('net down');
    };

    const first = await drainOutbox();
    expect(first.failed).toBe(1);
    expect(first.dropped).toBe(0); // still retriable
    expect(await db.outbox.count()).toBe(1);

    for (let i = 1; i < MAX_ATTEMPTS; i++) await drainOutbox();
    expect(CALLS).toHaveLength(MAX_ATTEMPTS); // bounded, not infinite
    expect(await db.outbox.count()).toBe(0);
    expect(await pendingWrites()).toHaveLength(0);
  });

  it('drops a {ok:false} body within the same bound — the endpoint said no', async () => {
    await queueWrite(NETID, 'tag', FORM);
    online = true;
    io.post = async () => jsonResponse({ ok: false, error: 'Component not found' });
    for (let i = 0; i < MAX_ATTEMPTS; i++) await drainOutbox();
    expect(await db.outbox.count()).toBe(0);
  });

  it('starts offline, paints the queued count, and clears the message once drained', async () => {
    const el = document.createElement('div');
    document.body.appendChild(el);
    await queueWrite(NETID, 'tag', FORM);

    await startOutbox(el);
    const span = el.parentElement?.querySelector(`[${OUTBOX_ATTR}]`);
    expect(span?.textContent).toBe('1 change is saved and will be sent when you are back online.');

    online = true;
    await startOutbox(el);
    expect(CALLS).toHaveLength(1);
    expect(el.parentElement?.querySelector(`[${OUTBOX_ATTR}]`)).toBeNull();
  });
});

describe('the queue may never carry auth or lifecycle routes', () => {
  it('declares /marks/tag and nothing else', () => {
    expect(Object.values(OUTBOX_ROUTES)).toEqual(['/marks/tag']);
  });
});

describe('logout must not leave a typed write behind', () => {
  it('wipeAll(netid) removes that student\'s queued writes', async () => {
    await queueWrite(NETID, 'tag', FORM);
    await queueWrite('zz8888', 'tag', FORM);
    expect(await db.outbox.count()).toBe(2);

    await wipeAll(NETID);
    // Only the other account's row survives: a queued tag replayed under the
    // next session is a cross-account leak on a shared device.
    expect(await pendingWrites()).toHaveLength(1);
    expect((await pendingWrites())[0]?.netid).toBe('zz8888');
  });

  it('wipeAll() with no netid clears the queue entirely', async () => {
    await queueWrite(NETID, 'tag', FORM);
    await wipeAll();
    expect(await db.outbox.count()).toBe(0);
  });
});
