import { afterEach, describe, expect, it, vi } from 'vitest';
import { showError } from './errorToast';

// The toast is the only way a failed save is ever visible, so the two things
// that matter are: it writes where the markup says it does, and it takes itself
// down again. The third: a page with no toast must not throw.

const mk = (): HTMLElement => {
  document.body.innerHTML = '<div id="error-toast" class="hidden"></div>';
  return document.getElementById('error-toast') as HTMLElement;
};

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
});

describe('showError', () => {
  it('writes the message and unhides the toast', () => {
    const t = mk();
    showError('Save failed: nope');
    expect(t.textContent).toBe('Save failed: nope');
    expect(t.classList.contains('hidden')).toBe(false);
  });

  it('hides it again after 5 s (not before)', () => {
    vi.useFakeTimers();
    const t = mk();
    showError('x');
    vi.advanceTimersByTime(4999);
    expect(t.classList.contains('hidden')).toBe(false);
    vi.advanceTimersByTime(1);
    expect(t.classList.contains('hidden')).toBe(true);
  });

  it('is a no-op on a page with no toast (login) instead of throwing', () => {
    document.body.innerHTML = '';
    expect(() => showError('x')).not.toThrow();
  });
});
