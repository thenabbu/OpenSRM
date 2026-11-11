import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  __resetInstall,
  canInstall,
  promptInstall,
  watchForInstallAvailability,
} from './install';

/**
 * P8.3 — install affordance.
 *
 * `beforeinstallprompt` is single-use: if the capture did not call
 * preventDefault(), or if the deferred event is not cleared after one prompt,
 * the button is dead while `canInstall()` still says it works. Both are
 * asserted here.
 */

function firePrompt(opts: { outcome: 'accepted' | 'dismissed' } = { outcome: 'accepted' }) {
  const e = new Event('beforeinstallprompt', { cancelable: true });
  const prompt = vi.fn().mockResolvedValue(undefined);
  const userChoice = Promise.resolve({ outcome: opts.outcome });
  Object.assign(e, { prompt, userChoice });
  window.dispatchEvent(e);
  return { e, prompt, userChoice };
}

afterEach(() => {
  __resetInstall();
});

describe('install affordance', () => {
  it('captures the prompt, cancels the browser default, and reports canInstall', () => {
    __resetInstall();
    expect(canInstall()).toBe(false);

    const { e } = firePrompt();
    expect(e.defaultPrevented).toBe(true);
    expect(canInstall()).toBe(true);
  });

  it('notifies availability subscribers when the prompt is captured', () => {
    __resetInstall();
    const onAvailable = vi.fn();
    watchForInstallAvailability(onAvailable);
    expect(onAvailable).not.toHaveBeenCalled();

    firePrompt();
    expect(onAvailable).toHaveBeenCalledTimes(1);
  });

  it('prompts once and clears the deferred event (a dismissed prompt cannot be retried)', async () => {
    __resetInstall();
    const { prompt } = firePrompt({ outcome: 'dismissed' });
    watchForInstallAvailability();

    await expect(promptInstall()).resolves.toBe(false);
    expect(prompt).toHaveBeenCalledTimes(1);
    expect(canInstall()).toBe(false);
    await expect(promptInstall()).resolves.toBe(false);
  });

  it('hides itself after appinstalled, even with a prompt still captured', async () => {
    __resetInstall();
    firePrompt();
    watchForInstallAvailability();
    expect(canInstall()).toBe(true);

    window.dispatchEvent(new Event('appinstalled'));
    expect(canInstall()).toBe(false);
    await expect(promptInstall()).resolves.toBe(false);
  });

  it('promptInstall is a no-op before any prompt has been captured', async () => {
    __resetInstall();
    watchForInstallAvailability();
    await expect(promptInstall()).resolves.toBe(false);
  });
});
