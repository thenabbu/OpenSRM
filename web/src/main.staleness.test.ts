import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { wipeAll, writePanel } from './db';
import { STALE_ATTR, showStale } from './data/stale';

// P7.11 — the dead cache branch, and the staleness cleanup it starved.
//
// main.ts used to read, just above the mount:
//
//   if (parsed.success && outcome.source === 'network') {
//     removeStale(el); return;
//   }
//
// Every `parsed.success` mount already returned ~30 lines earlier, so that
// condition is false on the only path that reaches it: `removeStale` was never
// called on ANY path, and the branch below it — the one that serves a shell
// from the store — was the only mount a shell ever got.
//
// Assertions are on the observable caption, never on "removeStale was called":
// the bug the user sees is a lie on screen, and the age label is the lie.
//
// The attendance island only needs its chunk to load (its row DOM wants layout
// jsdom does not do), so these check mount + caption, which is the whole of
// what the branch controls.

const NETID = 'zz7111';
const COURSE = {
  code: '21CSS201T', description: 'COMPUTER ORGANIZATION', attended: 20, max_hours: 30,
  pct_disp: '66.6', fill: 66.67, t75: 23, skip_now: -1, attend_now: 3,
  tint: 'red' as const, margin: -3, label: 'x', nudge: '', pole: false,
};
const PAYLOAD = { ok: true, data: { courses: [COURSE] } };
const HOUR_MS = 3600_000;

/** A shell: an island mount point with no `data-props` to read. */
const shell = (): HTMLElement => {
  document.body.innerHTML = '<div><span data-island="attendance">rows</span></div>';
  return document.querySelector<HTMLElement>('[data-island="attendance"]')!;
};

const captionOf = (el: HTMLElement) =>
  el.nextElementSibling?.hasAttribute(STALE_ATTR) ? el.nextElementSibling : null;

let hydrateIsland: (el: HTMLElement, now: number) => Promise<void>;
beforeEach(async () => {
  await wipeAll();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  // A fresh page load: `claimed` (and the netid) live in the modules, so each
  // test needs its own. `resetModules` gives `main` a NEW `session` instance —
  // setting the netid on a session module imported above therefore hands
  // hydrateIsland an undefined owner and it returns before reading the cache.
  // The netid has to be adopted through the same instance `main` closes over.
  vi.resetModules();
  ({ hydrateIsland } = await import('./main'));
  (await import('./session/session')).setNetid(NETID);
});
afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  (await import('./session/session')).setNetid(undefined);
  await wipeAll();
});

describe('P7.11 painting again clears the caption the old mount left', () => {
  it('network-served shell: the rows are fresh, so the old "2h ago" is gone', async () => {
    const el = shell();
    // What an earlier cache-served mount left behind.
    expect(showStale(el, Date.now() - 2 * HOUR_MS, Date.now() / 1000)).not.toBeNull();
    expect(captionOf(el)?.textContent).toBe('as of 2h ago');

    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(PAYLOAD), { status: 200 })));

    await hydrateIsland(el, Date.now() / 1000);

    // No `mountedAt` here on purpose: the shell mount writes `outcome.source`,
    // and a padlock on THAT would only prove the branch ran, not that the
    // branch is right. The caption is the bug.
    expect(captionOf(el)).toBeNull();             // the lie is gone
  });

  it('cache-served shell: the old caption is RE-labelled, not stacked', async () => {
    // An hour-old row — older than FRESH_S (300s), so it must keep a caption.
    // The cleanup therefore cannot just delete every caption: showStale has to
    // re-add the true age, and only one caption may be left behind.
    await writePanel('attendance', {
      netid: NETID, groupKey: '', payload: PAYLOAD.data, fetchedAt: Date.now() - HOUR_MS,
    });
    const el = shell();
    showStale(el, Date.now() - 2 * HOUR_MS, Date.now() / 1000); // the previous mount's label
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));

    await hydrateIsland(el, Date.now() / 1000);

    expect(el.dataset.mountedAt).toBe('cache');               // mounted off the store
    expect(captionOf(el)?.textContent).toBe('as of 1h ago');  // the true age, not the old lie
    expect(el.parentElement!.querySelectorAll(`[${STALE_ATTR}]`)).toHaveLength(1);
  });
});
