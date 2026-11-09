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
});
