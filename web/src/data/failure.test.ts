import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadFailure } from './load';
import {
  FAILURE_ATTR,
  __resetFailureWarnOnce,
  failureCopy,
  removeFailure,
  showFailure,
} from './failure';

/**
 * P7.3 — typed failures in the UI.
 *
 * The point of these tests is that the reasons stay DISTINGUISHABLE. A single
 * shared "something went wrong" banner would pass a naive test ("a message
 * appeared") while making the card's acceptance criteria false, so every case
 * below asserts the affordance AND that it is not the other kinds': the
 * unauthenticated case must not read like the offline one, and the two silent
 * reasons must not paint at all.
 */

const fail = (reason: LoadFailure['reason'], extra: Partial<LoadFailure> = {}): LoadFailure =>
  ({ ok: false, reason, message: `msg:${reason}`, ...extra }) as LoadFailure;

function mount(name = 'fees') {
  const el = document.createElement('div');
  el.setAttribute('data-island', name);
  document.body.appendChild(el);
  return el;
}

const box = () => document.querySelector(`[${FAILURE_ATTR}]`);

beforeEach(() => {
  document.body.innerHTML = '';
  __resetFailureWarnOnce();
  vi.restoreAllMocks();
});

describe('P7.3 failureCopy — one meaning per reason', () => {
  it('gives every reason its own copy (no reason shares another\'s message)', () => {
    const reasons = ['unauthenticated', 'not_found', 'network'] as const;
    const texts = reasons.map((r) => failureCopy(fail(r))?.text);
    expect(new Set(texts).size).toBe(3);
  });

  it('unauthenticated offers a way forward, not a dead end', () => {
    const c = failureCopy(fail('unauthenticated', { status: 401 }))!;
    expect(c.action).toEqual({ href: '/login', label: 'Sign in again' });
  });

  it('network says there is no offline copy, and names neither "try again" nor a retry button', () => {
    const c = failureCopy(fail('network'))!;
    expect(c.text).toContain('no saved copy');
    expect(c.action).toBeUndefined();
  });

  it('keeps server paint for invalid and http (no copy at all)', () => {
    expect(failureCopy(fail('invalid'))).toBeNull();
    expect(failureCopy(fail('http', { status: 503 }))).toBeNull();
  });
});

describe('P7.3 showFailure — rendering', () => {
  it('unauthenticated paints a sign-in link as a SIBLING of the mount', () => {
    const el = mount();
    const p = showFailure(el, fail('unauthenticated', { status: 401 }))!;
    expect(p).not.toBeNull();
    expect(p.textContent).toContain('Sign in again');
    const a = p.querySelector('a')!;
    expect(a.getAttribute('href')).toBe('/login');
    // sibling: the island replaces its own children on re-mount
    expect(p.parentElement).not.toBe(el);
    expect(el.parentElement!.querySelector(`[${FAILURE_ATTR}]`)).toBe(p);
  });

  it('offline with no cache states it explicitly, with no link', () => {
    const el = mount();
    const p = showFailure(el, fail('network'))!;
    expect(p.textContent).toContain('no saved copy');
    expect(p.querySelector('a')).toBeNull();
  });

  it('invalid renders NOTHING (server paint is kept) but logs exactly once', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const el = mount();
    expect(showFailure(el, fail('invalid'))).toBeNull();
    expect(box()).toBeNull();
    showFailure(el, fail('invalid'));
    showFailure(el, fail('invalid'));
    const mine = warn.mock.calls.filter((c) => String(c[0]).includes('fees:invalid'));
    expect(mine).toHaveLength(1);           // logged once, never a flood

    // positive control: the SAME call with a reason that paints does not stay silent
    expect(showFailure(el, fail('unauthenticated'))).not.toBeNull();
  });

  it('http renders nothing but still logs once', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const el = mount();
    expect(showFailure(el, fail('http', { status: 500 }))).toBeNull();
    expect(box()).toBeNull();
    expect(warn.mock.calls.filter((c) => String(c[0]).includes('fees:http'))).toHaveLength(1);
  });

  it('logs once per island, so two islands each say their piece', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    showFailure(mount('fees'), fail('invalid'));
    showFailure(mount('campus'), fail('invalid'));
    expect(warn.mock.calls.filter((c) => String(c[0]).includes(':invalid'))).toHaveLength(2);
  });

  it('a retry failing differently replaces the old affordance instead of stacking', () => {
    const el = mount();
    showFailure(el, fail('network'));
    showFailure(el, fail('unauthenticated', { status: 401 }));
    const all = document.querySelectorAll(`[${FAILURE_ATTR}]`);
    expect(all).toHaveLength(1);
    expect(all[0].getAttribute(FAILURE_ATTR)).toBe('unauthenticated');
  });

  it('is announced to assistive tech (alert for actions, status for states)', () => {
    expect(showFailure(mount('fees'), fail('unauthenticated'))!.getAttribute('role')).toBe('alert');
    expect(showFailure(mount('campus'), fail('network'))!.getAttribute('role')).toBe('status');
  });

  it('removes cleanly once a load succeeds', () => {
    const el = mount();
    showFailure(el, fail('network'));
    expect(box()).not.toBeNull();
    removeFailure(el);
    expect(box()).toBeNull();
  });
});

describe('P7.3 a generic error path cannot satisfy the specific kinds', () => {
  // Positive control for the whole card: if someone replaces the switch with
  // one shared message, these assertions go red on copy, action and silence.
  it('a single shared message would fail every one of these', () => {
    const shared = { tone: 'error' as const, text: 'Something went wrong.' };

    const unauth = failureCopy(fail('unauthenticated'))!;
    expect(unauth).not.toEqual(shared);
    expect(unauth.action?.href).toBe('/login');

    const offline = failureCopy(fail('network'))!;
    expect(offline).not.toEqual(shared);
    expect(offline.text).toContain('no saved copy');

    // the silent kinds must stay silent; a generic banner paints over good paint
    expect(failureCopy(fail('invalid'))).toBeNull();
    expect(failureCopy(fail('http', { status: 500 }))).toBeNull();
  });
});
