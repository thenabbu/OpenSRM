import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mountBanner } from './banner';
import { __resetInstall } from './install';

/**
 * P8.3 — the banner is the USER-VISIBLE half of the update flow.
 *
 * `update.test.ts` covers the event wiring underneath it: which lifecycle event
 * counts as "a new version". It asserts nothing about what a student meets, so a
 * banner that never painted, painted the wrong words, or offered a button that
 * did nothing would keep that suite green. That is what this file covers — a
 * visible control, with words on it, that the user can actually click.
 */

function fakeSW() {
  const target = new EventTarget();
  const sw = {
    controller: null as unknown,
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    fire: (type: string) => target.dispatchEvent(new Event(type)),
  };
  Object.defineProperty(navigator, 'serviceWorker', { value: sw, configurable: true });
  return sw;
}

const bannerEl = (): HTMLElement => {
  const el = document.getElementById('pwa-banner');
  if (!el) throw new Error('banner was never mounted into <body>');
  return el;
};
const shown = (el: HTMLElement): boolean => !el.classList.contains('hidden');
const labels = (el: HTMLElement): string[] =>
  Array.from(el.querySelectorAll('button')).map((b) => (b.textContent || '').trim());
const click = (el: HTMLElement, label: string): void => {
  const btn = Array.from(el.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === label);
  if (!btn) throw new Error(`no "${label}" button; banner offers: ${labels(el).join(' | ')}`);
  btn.click();
};

const realLocation = Object.getOwnPropertyDescriptor(window, 'location');

beforeEach(() => {
  document.body.replaceChildren();
  sessionStorage.clear();
  __resetInstall();
  Object.defineProperty(navigator, 'serviceWorker', { value: undefined, configurable: true });
});
afterEach(() => {
  document.body.replaceChildren();
  // jsdom's Location is not spy-able (`Cannot redefine property: reload`), so the
  // reload test swaps the whole object; put the real one back for the next test.
  if (realLocation) Object.defineProperty(window, 'location', realLocation);
  vi.restoreAllMocks();
});

describe('update banner', () => {
  it('is invisible on a normal load, then appears with a Reload button', () => {
    const sw = fakeSW();
    sw.controller = { scriptURL: '/static/sw.js' };        // page already controlled
    mountBanner();

    // Positive control: the element exists but the user sees nothing yet.
    expect(shown(bannerEl())).toBe(false);

    sw.controller = { scriptURL: '/static/sw.js' };        // a new worker claimed
    sw.fire('controllerchange');

    const el = bannerEl();
    expect(shown(el)).toBe(true);
    expect(el.textContent).toContain('A new version of openSRM is ready.');
    expect(labels(el)).toContain('Reload');
  });

  it('never tells a first-time visitor to reload the page they just opened', () => {
    const sw = fakeSW();                                   // controller === null
    mountBanner();

    sw.controller = { scriptURL: '/static/sw.js' };
    sw.fire('controllerchange');

    expect(shown(bannerEl())).toBe(false);
  });

  it('clicking Reload reloads the page exactly once', () => {
    const sw = fakeSW();
    sw.controller = { scriptURL: '/static/sw.js', postMessage: vi.fn() };
    const reload = vi.fn();
    Object.defineProperty(window, 'location', { value: { reload }, configurable: true });
    mountBanner();

    sw.controller = { scriptURL: '/static/sw.js', postMessage: vi.fn() };
    sw.fire('controllerchange');
    click(bannerEl(), 'Reload');

    // Reload is armed by the click and fires when the worker actually takes over.
    expect(reload).not.toHaveBeenCalled();
    sw.fire('controllerchange');
    expect(reload).toHaveBeenCalledTimes(1);

    sw.fire('controllerchange');                            // must not reload again
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('dismiss hides the banner and keeps it away for the session', () => {
    const sw = fakeSW();
    sw.controller = { scriptURL: '/static/sw.js' };
    mountBanner();

    sw.controller = { scriptURL: '/static/sw.js' };
    sw.fire('controllerchange');
    click(bannerEl(), '✕');

    expect(shown(bannerEl())).toBe(false);
    expect(sessionStorage.getItem('pwa-banner-dismissed')).toBe('1');

    sw.fire('controllerchange');                            // a later fire must stay quiet
    expect(shown(bannerEl())).toBe(false);
  });
});
