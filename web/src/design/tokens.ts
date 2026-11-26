// Closed vocabulary of the daisyUI / Tailwind classes the app really uses.
//
// DERIVED, not invented. Every entry below was collected by grepping the legacy
// templates; each line carries the file:line it came from (branch
// feat/preact-migration). If you need a class that is not here, add it WITH its
// grep evidence — a helper that could emit an unseen class is exactly the
// silent missing style this module exists to prevent.
//
// Kept apart from index.ts so the vocabulary can be diffed against a fresh grep
// without reading the helper bodies.

export const BUTTON_VARIANTS = {
  // app/templates/home.html:91 `btn btn-ghost btn-sm tab-active` (138 occurrences)
  ghost: 'btn-ghost',
  // app/templates/home.html:266 `btn btn-primary btn-sm min-h-11`
  primary: 'btn-primary',
  // app/templates/home.html:316 `btn btn-accent btn-sm`
  accent: 'btn-accent',
  // app/templates/home.html:299 `btn btn-error btn-sm min-h-11 text-base-content`
  error: 'btn-error',
  // app/templates/settings.html:305 `btn btn-outline btn-sm`
  outline: 'btn-outline',
} as const;

export const BUTTON_SIZES = {
  // app/templates/partials/widgets/profile.html:12 `btn btn-ghost btn-xs px-0 min-h-6`
  xs: 'btn-xs',
  // 155 occurrences across app/templates — the app's default button size
  sm: 'btn-sm',
  // app/templates/login.html:108 `btn btn-accent btn-lg w-full mt-2 sm:mt-5`
  lg: 'btn-lg',
  // app/templates/home.html:132 `btn btn-ghost btn-square min-h-11 w-11 h-11`
  // (17 occurrences). Carries the touch target itself: every square button in
  // the app pins the 44px minimum, so composing a bare btn-square would render
  // a 32px target. That is why this is a size, not a shape.
  square: 'btn-square min-h-11 w-11 h-11',
  // app/templates/attendance.html:205 `btn btn-sm btn-square join-item` inside
  // the view join — sized per-item, so it must NOT inherit the 44px pin.
  squareSm: 'btn-square',
} as const;

export const BADGE_VARIANTS = {
  // app/templates/settings.html:222 `badge badge-sm` (default tone)
  neutral: '',
  // app/templates/partials/widgets/today.html:8 `badge badge-error badge-sm`
  error: 'badge-error',
  // app/templates/partials/widgets/week.html:8 `badge badge-soft badge-warning badge-sm`
  warning: 'badge-warning',
  // app/templates/campus.html:233 `badge badge-outline badge-sm text-base-content/60`
  outline: 'badge-outline',
  // NOT in the app yet: success / info. Add them here (with a grep) the moment
  // a template emits one; until then a component using them should not compile.
} as const;

export const BADGE_SOFTNESS = {
  // default: `badge badge-error badge-sm` (today.html:8)
  solid: '',
  // `badge badge-soft badge-*`: every informational badge is soft (week.html:8)
  soft: 'badge-soft',
} as const;

export const BADGE_SIZES = {
  // 12 occurrences of badge-sm; the only size the app emits
  sm: 'badge-sm',
} as const;

// app/views/attendance.py:300 — the ONLY producer of a domain tint:
//   "red" if pct < 75 else ("warn" if skip == 0 else "gray")
// Consumed by app/templates/attendance.html:244, which maps it to the fill's
// `mz--*` modifier (app/static/timetable.css:195-196). These are the SERVER's
// names: `warn` is orange (oklch 63% 0.115 68) and `gray` is comfortable — do
// not rename them to amber/green, that would miss every live payload.
export const TINTS = {
  red: 'mz--red',
  warn: 'mz--warn',
  gray: '', // the .mz base rule (timetable.css:194) already IS the gray fill
} as const;

// The base fill element every tint sits on (attendance.html:244 `class="mz"`).
export const TINT_BASE = 'mz';

// 255 occurrences of text-base-content{/opacity} across app/templates. /90
// never appears; the closed scale is 30/50/60/70/80 plus the full-strength form.
export const TEXT_TONES = {
  base: 'text-base-content',
  '80': 'text-base-content/80',
  '70': 'text-base-content/70',
  '60': 'text-base-content/60',
  '50': 'text-base-content/50',
  '30': 'text-base-content/30',
} as const;

export type ButtonVariant = keyof typeof BUTTON_VARIANTS;
export type ButtonSize = keyof typeof BUTTON_SIZES;
export type BadgeVariant = keyof typeof BADGE_VARIANTS;
export type BadgeSoftness = keyof typeof BADGE_SOFTNESS;
export type BadgeSize = keyof typeof BADGE_SIZES;
export type Tint = keyof typeof TINTS;
export type TextTone = keyof typeof TEXT_TONES;

// The complete tint set the server can emit, as a value a test can assert.
export const SERVER_TINTS: readonly Tint[] = ['red', 'warn', 'gray'];
