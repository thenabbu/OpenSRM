import { afterEach, describe, expect, it, vi } from 'vitest';
import { __resetInstall, canInstall, promptInstall, watchForInstallAvailability } from './install';

/**
 * P8.3 — install affordance.
 *
 * `beforeinstallprompt` is single-use: if the capture did not call
 * preventDefault(), or if the deferred event is not cleared after one prompt,
 * the button is dead while `canInstall()` still says it works. Both are
 * asserted here.
 *
 * Note: `watchForInstallAvailability` wires the listeners ONCE per page (module
 * state, reset by `__resetInstall`). A test that fires the event before the
 * first wiring call is testing nothing, so every case wires first.
 */

function firePrompt(opts: { outcome: 'accepted' | 'dismissed' } = { outcome: 'accepted' }) {
  const e = new Event('beforeinstallprompt', { cancelable: true });
  const prompt = vi.fn().mockResolvedValue(undefined);
  const userChoice = Promise.resolve({ outcome: opts.outcome });
  Object.assign(e, { prompt, userChoice });
  window.dispatchEvent(e);
  return { e, prompt };
}

/** Fresh module state + the one-shot capture wired, which is the page's real order. */
function boot() {
  __resetInstall();
  const onAvailable = vi.fn();
  watchForInstallAvailability(onAvailable);
  return onAvailable;
}

afterEach(() => {
  __resetInstall();
});

describe('install affordance', () => {
  it('captures the prompt, cancels the browser default, and reports canInstall', () => {
    boot();
    expect(canInstall()).toBe(false);

    const { e } = firePrompt();
    expect(e.defaultPrevented).toBe(true);
    expect(canInstall()).toBe(true);
  });

  it('notifies availability subscribers when the prompt is captured', () => {
    const onAvailable = boot();
    expect(onAvailable).not.toHaveBeenCalled();

    firePrompt();
    expect(onAvailable).toHaveBeenCalledTimes(1);
  });

  it('prompts once and clears the deferred event (a dismissed prompt cannot be retried)', async () => {
    boot();
    const { prompt } = firePrompt({ outcome: 'dismissed' });

    await expect(promptInstall()).resolves.toBe(false);
    expect(prompt).toHaveBeenCalledTimes(1);
    expect(canInstall()).toBe(false);
    await expect(promptInstall()).resolves.toBe(false);
  });

  it('hides itself after appinstalled, even with a prompt still captured', async () => {
    boot();
    firePrompt();
    expect(canInstall()).toBe(true);

    window.dispatchEvent(new Event('appinstalled'));
    expect(canInstall()).toBe(false);
    await expect(promptInstall()).resolves.toBe(false);
  });

  it('promptInstall is a no-op before any prompt has been captured', async () => {
    boot();
    await expect(promptInstall()).resolves.toBe(false);
  });

  it('a prompt gone stale (browser throws) reports false instead of breaking the page', async () => {
    boot();
    const e = new Event('beforeinstallprompt', { cancelable: true });
    Object.assign(e, {
      prompt: vi.fn().mockRejectedValue(new Error('already prompted')),
      userChoice: Promise.resolve({ outcome: 'dismissed' }),
    });
    window.dispatchEvent(e);

    await expect(promptInstall()).resolves.toBe(false);
    expect(canInstall()).toBe(false);
  });
});
