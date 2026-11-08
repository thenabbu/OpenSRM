// Typed bridge between TypeScript and the daisyUI class strings the app uses.
// Every helper returns `string` but only ever composes from the closed sets in
// tokens.ts, so an unknown variant is a compile error instead of a silently
// unstyled element.
import {
  BADGE_SIZES,
  BADGE_SOFTNESS,
  BADGE_VARIANTS,
  BUTTON_SIZES,
  BUTTON_VARIANTS,
  TEXT_TONES,
  TINT_BASE,
  TINTS,
  type BadgeSize,
  type BadgeSoftness,
  type BadgeVariant,
  type ButtonSize,
  type ButtonVariant,
  type TextTone,
  type Tint,
} from './tokens';
import { cn } from './cn';

export interface ButtonOptions {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Extra utilities that are not part of the token vocabulary (e.g. 'w-full'). */
  class?: string;
}

// Mirrors `btn btn-ghost btn-sm` (home.html:91).
export function button({ variant = 'ghost', size = 'sm', class: extra }: ButtonOptions = {}): string {
  return cn('btn', BUTTON_VARIANTS[variant], BUTTON_SIZES[size], extra);
}

export interface BadgeOptions {
  softness?: BadgeSoftness;
  size?: BadgeSize;
  class?: string;
}

// Mirrors `badge badge-soft badge-warning badge-sm` (week.html:8).
export function badge(
  variant: BadgeVariant = 'neutral',
  { softness = 'solid', size = 'sm', class: extra }: BadgeOptions = {},
): string {
  return cn('badge', BADGE_SOFTNESS[softness], BADGE_VARIANTS[variant], BADGE_SIZES[size], extra);
}

// Mirror of attendance.html:244 — the fill element plus its server-driven tint.
export function tint(t: Tint): string {
  return cn(TINT_BASE, TINTS[t]);
}

// Mirrors `text-base-content/60` et al.
export function text(tone: TextTone = 'base', extra?: string): string {
  return cn(TEXT_TONES[tone], extra);
}

export { cn } from './cn';
export * from './tokens';
