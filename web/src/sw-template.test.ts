import { describe, expect, it, vi } from 'vitest';
// Vite's `?raw` hands over the shipped source itself (no fs, no path games).
import TEMPLATE from './sw-template.js?raw';

/**
 * The service worker's install decision — the half of "never a silent swap" that
 * lives in the worker, not in the page.
 *
 * `web/src/sw-template.js` is a classic worker source (no types, no test
 * harness), so the handler bodies are extracted from the source and EXECUTED
 * against a fake `self`. That is what makes this a behaviour test rather than a
 * grep: reverting the guard leaves a handler that calls skipWaiting() on an
 * update, and the "waits" case below goes red.
 *
 * Why it matters: `skipWaiting()` on an update activates the new worker and
 * claims the clients while the page is still running the previous bundle, and
 * the `activate` cache wipe then deletes the caches that page is fetching from.
 * The banner that follows cannot undo that — it reports it.
 */

const SRC = TEMPLATE;

/** The `{ ... }` body of `self.addEventListener('<event>', ...)`, brace-matched. */
function listenerBody(event: string): string {
  const at = SRC.indexOf(`self.addEventListener('${event}',`);
  if (at < 0) throw new Error(`sw-template.js has no '${event}' listener`);
  const open = SRC.indexOf('{', SRC.indexOf('=>', at));
  if (open < 0) throw new Error(`unnamed listener for '${event}'`);
  let depth = 0;
  for (let i = open; i < SRC.length; i++) {
    if (SRC[i] === '{') depth++;
    else if (SRC[i] === '}' && --depth === 0) return SRC.slice(open + 1, i);
  }
  throw new Error(`unbalanced '${event}' handler`);
}

/** Run a handler body against a fake worker global; returns its skipWaiting spy. */
function run(event: string, active: unknown, data?: unknown) {
  const self = { registration: { active }, skipWaiting: vi.fn() };
  // eslint-disable-next-line no-new-func -- the point is to execute the shipped source
  new Function('self', 'event', listenerBody(event))(self, { data });
  return self.skipWaiting;
}

describe('sw-template install', () => {
  it('takes over at once on a FIRST install (because the gate measured it)', () => {
    expect(run('install', null)).toHaveBeenCalledTimes(1);
  });

  it('WAITS on an update instead of claiming a running page', () => {
    // `registration.active` is the outgoing worker exactly during an update.
    expect(run('install', { state: 'activated' })).not.toHaveBeenCalled();
  });
});

describe('sw-template SKIP_WAITING', () => {
  it('promotes the waiting worker when the page asks for it', () => {
    expect(run('message', {}, { type: 'SKIP_WAITING' })).toHaveBeenCalledTimes(1);
  });

  it('ignores any other message', () => {
    expect(run('message', {}, { type: 'SOMETHING_ELSE' })).not.toHaveBeenCalled();
    expect(run('message', {}, undefined)).not.toHaveBeenCalled();
  });
});
