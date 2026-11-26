import { beforeEach, describe, expect, it, vi } from 'vitest';
import { STALE_ATTR, showStale, removeStale } from './stale';

/**
 * P7.2 — staleness caption.
 *
 * The caption is the only thing telling a user that the rows they see came
 * from IndexedDB at 09:12 rather than live from the portal. Two properties
 * matter and both are asserted here: it appears with the right age, and it
 * disappears when the data is fresh (an "as of" label on live data is a lie).
 */

const NOW = Date.parse('2026-11-09T12:00:00Z') / 1000;

function mount() {
  const el = document.createElement('div');
  el.setAttribute('data-island', 'fees');
  document.body.appendChild(el);
  return el;
}

beforeEach(() => { document.body.innerHTML = ''; });

describe('P7.2 staleness caption', () => {
  it('labels a stale mount with its age, as a sibling of the mount', () => {
    const el = mount();
    const span = showStale(el, NOW - 2 * 3600, NOW);      // 2 h old
    expect(span).not.toBeNull();
    expect(span!.textContent).toBe('as of 2h ago');
    // sibling, not child: the island replaces its own children on re-mount
    expect(span!.parentElement).not.toBe(el);
    expect(el.parentElement!.querySelector(`[${STALE_ATTR}]`)).toBe(span);
  });

  it('is polite for screen readers (announces on change, no interruption)', () => {
    const el = mount();
    const span = showStale(el, NOW - 3 * 3600, NOW)!;
    expect(span.getAttribute('aria-live')).toBe('polite');
  });

  it('renders NOTHING when the payload is fresh', () => {
    const el = mount();
    expect(showStale(el, NOW - 30, NOW)).toBeNull();      // 30 s: inside FRESH_S
    expect(document.querySelector(`[${STALE_ATTR}]`)).toBeNull();
    // positive control: the same call one hour older DOES render
    expect(showStale(el, NOW - 3600, NOW)).not.toBeNull();
  });

  it('replaces an existing caption rather than stacking duplicates', () => {
    const el = mount();
    showStale(el, NOW - 3600, NOW);
    showStale(el, NOW - 7200, NOW);                        // re-labelled
    const all = document.querySelectorAll(`[${STALE_ATTR}]`);
    expect(all).toHaveLength(1);
    expect(all[0].textContent).toBe('as of 2h ago');
  });

  it('removes the caption when fresh data arrives', () => {
    const el = mount();
    showStale(el, NOW - 3600, NOW);
    expect(document.querySelector(`[${STALE_ATTR}]`)).not.toBeNull();
    removeStale(el);
    expect(document.querySelector(`[${STALE_ATTR}]`)).toBeNull();
  });

  it('never invents an age for a missing timestamp', () => {
    // epoch 0 means "present but unknown age", not "0 seconds ago"
    const el = mount();
    const span = showStale(el, 0, NOW);
    expect(span).not.toBeNull();
    expect(span!.textContent).not.toContain('as of 0');
  });

  /**
   * REGRESSION (found 2026-11-09): every test above passes SECONDS, but the
   * only production caller — main.ts:147 — passes `outcome.fetchedAt`, which
   * load.ts writes as `Date.now()`. ageCaption subtracts it from a seconds
   * clock, so the difference came out negative, read as "fresh", and every
   * stale panel silently rendered NO caption. The suite was green throughout.
   * These two pin the real call shape.
   */
  describe('with the production argument shape (milliseconds)', () => {
    it('renders the caption when fetchedAt is in ms', () => {
      const el = mount();
      const span = showStale(el, (NOW - 2 * 3600) * 1000, NOW);   // ms, as load.ts writes
      expect(span).not.toBeNull();
      expect(span!.textContent).toBe('as of 2h ago');
    });

    it('a mount cached 6h ago is labelled, not silently treated as fresh', () => {
      const el = mount();
      const span = showStale(el, (NOW - 6 * 3600) * 1000, NOW);
      expect(span).not.toBeNull();
      expect(span!.textContent).toContain('6h ago');
    });
  });

  /**
   * REGRESSION (found 2026-11-09): removeStale used to scan the whole parent
   * for `[data-island-stale]`, which finds the FIRST caption in the panel —
   * so refreshing island B deleted island A's caption. It must only touch the
   * caption that sits immediately after its own mount.
   */
  it('removing one mount\'s caption leaves another mount\'s caption alone', () => {
    const a = mount();
    const b = document.createElement('div');
    b.setAttribute('data-island', 'campus');
    document.body.appendChild(b);

    showStale(a, (NOW - 2 * 3600) * 1000, NOW);
    showStale(b, (NOW - 3 * 3600) * 1000, NOW);
    expect(document.querySelectorAll(`[${STALE_ATTR}]`)).toHaveLength(2);

    removeStale(b);                                   // only B refreshes
    const left = document.querySelectorAll(`[${STALE_ATTR}]`);
    expect(left).toHaveLength(1);
    expect(left[0].textContent).toBe('as of 2h ago'); // A's caption survives
  });
});
