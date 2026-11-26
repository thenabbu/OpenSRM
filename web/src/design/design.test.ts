import { describe, expect, it } from 'vitest';
import { badge, button, cn, text, tint } from './index';
import { SERVER_TINTS, TINTS } from './tokens';

// Table-driven against the exact strings the legacy templates emit, so a helper
// that drifts from the app fails here rather than shipping an unstyled element.
describe('button()', () => {
  const VARIANTS = [
    ['ghost', 'btn btn-ghost btn-sm'], // home.html:91
    ['primary', 'btn btn-primary btn-sm'], // home.html:266
    ['accent', 'btn btn-accent btn-sm'], // home.html:316
    ['error', 'btn btn-error btn-sm'], // home.html:299
    ['outline', 'btn btn-outline btn-sm'], // settings.html:305
  ] as const;

  it.each(VARIANTS)('variant %s', (variant, expected) => {
    expect(button({ variant })).toBe(expected);
  });

  it.each([
    ['xs', 'btn btn-ghost btn-xs'], // profile.html:12
    ['sm', 'btn btn-ghost btn-sm'],
    ['lg', 'btn btn-ghost btn-lg'], // login.html:108
    ['square', 'btn btn-ghost btn-square min-h-11 w-11 h-11'], // home.html:132
    ['squareSm', 'btn btn-ghost btn-square'], // attendance.html:205
  ] as const)('size %s', (size, expected) => {
    expect(button({ size })).toBe(expected);
  });

  it('defaults to ghost + sm and appends extra classes last', () => {
    expect(button()).toBe('btn btn-ghost btn-sm');
    expect(button({ variant: 'primary', size: 'lg', class: 'w-full' })).toBe(
      'btn btn-primary btn-lg w-full',
    );
  });
});

describe('badge()', () => {
  it.each([
    ['neutral', 'badge badge-sm'], // settings.html:222
    ['error', 'badge badge-error badge-sm'], // today.html:8
    ['warning', 'badge badge-warning badge-sm'], // week.html:8
    ['outline', 'badge badge-outline badge-sm'], // campus.html:233
  ] as const)('variant %s', (variant, expected) => {
    expect(badge(variant)).toBe(expected);
  });

  it('composes softness', () => {
    expect(badge('warning', { softness: 'soft' })).toBe('badge badge-soft badge-warning badge-sm');
  });
});

describe('tint()', () => {
  it.each([
    ['red', 'mz mz--red'], // attendance.py:300 -> attendance.html:244
    ['warn', 'mz mz--warn'],
    ['gray', 'mz'], // .mz base rule IS the gray fill
  ] as const)('%s', (t, expected) => {
    expect(tint(t)).toBe(expected);
  });

  // The full server set, asserted exactly: a NEW tint emitted by
  // app/views/attendance.py with no mapping here fails this test.
  it('covers exactly the tints the server emits', () => {
    expect([...SERVER_TINTS].sort()).toEqual(['gray', 'red', 'warn']);
    expect(Object.keys(TINTS).sort()).toEqual([...SERVER_TINTS].sort());
  });
});

describe('text()', () => {
  it.each([
    ['base', 'text-base-content'],
    ['80', 'text-base-content/80'],
    ['70', 'text-base-content/70'],
    ['60', 'text-base-content/60'],
    ['50', 'text-base-content/50'],
    ['30', 'text-base-content/30'],
  ] as const)('tone %s', (tone, expected) => {
    expect(text(tone)).toBe(expected);
  });
});

describe('the vocabulary is closed at compile time', () => {
  // @ts-expect-error — 'purple' is not a button variant
  const notAVariant = () => button({ variant: 'purple' });
  // @ts-expect-error — server emits red/warn/gray, never amber
  const notATint = () => tint('amber');
  // @ts-expect-error — /40 is not in the text scale the app uses
  const notATone = () => text('40');

  it('rejects them only in the type system, still returns a plain string', () => {
    // The functions above are deliberately never called: if @ts-expect-error
    // stops being an error, `tsc --noEmit` fails and this file never runs green.
    expect([notAVariant, notATint, notATone].every((f) => typeof f === 'function')).toBe(true);
  });
});

describe('cn()', () => {
  it('joins truthy values and drops falsy ones', () => {
    expect(cn('a', false, 'b', null, undefined, 'c')).toBe('a b c');
    expect(cn()).toBe('');
    expect(cn(false && 'x', 'y')).toBe('y');
    expect(cn('a', '', 'b')).toBe('a b');
  });
});
