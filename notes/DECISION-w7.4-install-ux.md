# W7.4 — install UX: what was already there, what was missing, what was decided

Card t_d55b7dc4, plan ask at `RECOVERY_PLAN.md:209`:

> `beforeinstallprompt`; iOS Safari instruction sheet (Share → Add to Home Screen);
> Windows/Edge `shortcuts`; `display_override` considered and the decision
> recorded; standalone safe-area insets.

Measured on branch `feat/preact-migration` at 27bf659 (the W7.3b merge), not on the
card's stated base cc57dac, because W7.2/W7.3/W7.3b all landed after it.

## Verdict per ask

| ask | verdict | evidence |
|---|---|---|
| `beforeinstallprompt` | **already met** (no change) | `web/src/pwa/install.ts:43` captures the event at module load and `:46` calls `preventDefault()`, which is what makes a later `prompt()` possible; `:79` `promptInstall()` consumes it once and clears it unconditionally (`:82`). Firing the event twice is covered by `install.test.ts`. |
| iOS Safari instruction sheet | **gap — closed here** | Safari never fires `beforeinstallprompt`, so before this change every iPhone and iPad got an install affordance that could never appear. The only iOS wording in the repo was `app/static/push.js:106`, and that is the *push* hint, not the install path. |
| Windows/Edge `shortcuts` | **gap — closed here** | `app/static/manifest.json` had zero `shortcuts`. |
| `display_override` | **considered, decision = no** (see below) | absent from the manifest, and that stays true on purpose. |
| standalone safe-area insets | **already met** (no change) | `viewport-fit=cover` + real `env()` rules, both named below. |

## What shipped

**iOS install wording** — `web/src/pwa/banner.ts:35` (`iosNeedsInstallInstructions()`)
and `:104`. The banner already owned the install slot for every browser that has a
prompt event; on iOS that slot painted nothing at all. It now carries the instruction
instead of a dead button:

> Install openSRM: tap Share, then Add to Home Screen.

Gate is `iOS user agent AND not already installed`; `navigator.standalone === true`
is the iOS-only signal for "running from the Home Screen", which is the one state
where the instruction is noise. No new CSS classes (the banner's existing class list
is reused, so nothing new for Tailwind to generate) and no template change: the
banner is built in JS, which is the only route under `script-src 'self'`.

`web/src/pwa/banner.test.ts` gains 4 tests: the wording appears on an iPhone, stays
quiet on an iPhone already installed, stays quiet on a non-iOS user agent, and its
dismissal survives a remount. Break-proved both conditions: deleting the paint block
turns 2 red, deleting `&& !standalone` turns 1 red, restored = 8 green.

**`shortcuts`** — three entries in `app/static/manifest.json`: Attendance
(`/attendance`), Marks (`/marks`), Timetable (`/timetable`), each with the existing
`/static/icon-192.png`. Rationale: these are the three tabs a student opens without
looking, the manifest already ships the icon, and Chromium-on-Windows (plus Android's
long-press menu) renders them in the jump list for free. No new file, no new asset.

## Decisions

**`display_override` — NO.** The field exists to request a *different* window mode
than `display`: `window-controls-overlay` (title bar merged into the page),
`tabbed`, `minimal-ui`. This app wants exactly `standalone` on every platform, and
`display_override: ["standalone"]` changes nothing a browser does while adding a
second source of truth for the same value. It would only become real work if the
design asked for a custom title bar or a tabbed shell — neither is in the plan.
Recorded here so the next reader does not re-litigate it.

**Safe-area — met, and this is the rule that proves it.** `viewport-fit=cover` is
set on both entry templates (`app/templates/base.html:2`, `app/templates/login.html:5`);
without it every `env(safe-area-inset-*)` resolves to 0, so the meta tag alone is
the half that does nothing. The insets are then actually consumed:

- `app/static/app.css`, selector `.dock`:
  `height:calc(4rem + env(safe-area-inset-bottom)); padding-bottom:env(safe-area-inset-bottom)`
  — the fixed bottom dock, which is where the iOS home indicator overlaps.
- `app/static/app.css`, selector `.h-\[env\(safe-area-inset-bottom\)\]{height:env(safe-area-inset-bottom)}`
  — the arbitrary-value spacer used by `base.html:198` and `login.html:129`, so the
  last card is not hidden under the dock.
- Inline, because they are computed with a constant:
  `base.html:78` and `:120` `padding-top:calc(0.5rem + env(safe-area-inset-top))`
  (both fixed navbars — the notch), `base.html:149`
  `padding-bottom:env(safe-area-inset-bottom)` (the dock again, belt and braces).

## Ceilings worth knowing

- The iOS instruction is per session, matching the update notice's dismissal
  (`sessionStorage`); a student who ignores it sees it again next session. Making it
  once-ever would need a second storage key, and it is one line in `banner.ts` when
  that becomes annoying.
- Detection is a user-agent test, not a capability test: iPadOS reports a desktop
  user agent in "Request Desktop Site" mode, where the instruction would not appear.
  There is no reliable capability signal for "iOS Safari" — this is the same
  trade-off `app/static/push.js:21` already makes for push.
- Shortcuts are not asserted by `check_icons.py`: it validates `icons`, and adding a
  manifest-key check there would also have to decide what a valid shortcut is. The
  served bytes are golden-captured (`tests/golden/v3/api/static_manifest.json.json`),
  so a shortcut that disappears still fails CI.

## Traps this card hit, and what caught them

**The word "menu" in a code comment is 9 KB of CSS.** Tailwind scans every file in
`web/src`, comments included. The first draft of the iOS comment said "the Share
*menu* is the only install path", which is also a daisyUI component name, so the
build emitted the whole `.menu` component: `app/static/app.css` went
**163,806 B -> 173,100 B** (+9,294 B) for a change that adds no markup. Caught by
`gates.sh`'s existing `committed app.css is current` check, not by review. The
comment now says "Share sheet" and names the hazard so the next writer does not
re-introduce it. Nothing new was needed: the gate that exists is the gate that
works.

**Golden re-capture: 3 files, and the screens deliberately were not committed.**
`app/static/manifest.json` (shortcuts) and the rebuilt worker move
`tests/golden/v3/api/static_manifest.json.json`, `api/static_sw.js.json` and
`metrics.json` (manifest 2161 -> 2923 B, gzip 467 -> 613). The 27 screen PNGs also
differ on this host, and that is *not* this change: `capture_golden.py --check`
compares no PNGs by default (`--no-screens`, added because "PNG bytes encode the
host's font stack"), and every non-PNG capture — 76 KB of HTML, 62 KB of JS,
913 KB of API bodies, `dom nodes page=342 panels=2077` — is byte-identical to the
committed goldens at the same tree. Reverting just the PNGs leaves
`bash scripts/capture_golden.sh --check --no-screens` green, which is the check CI
runs.

**The card's base was stale and rebasing onto it needed care.** The card measured
cc57dac; W7.2, W7.3, W7.3b and W7.3c all landed after it, so this branch sits on
5811da1. Copying the whole old `banner.ts` onto the new base silently deleted
W7.3c's `refreshOnVisible()` call — visible only in the diff, and it would have
looked like a passing change because nothing tests that call's absence. The branch
re-applies this card's delta instead, so W7.3c's worker guard and visibility poll
are intact.

## 2026-11-26 — the install card was the annoyance, not the affordance

Reported on `dev`: the install popup is "very annoying and persistent". Measured
cause, not a guess:

| what the user met | why |
|---|---|
| the popup on a **desktop** | `mountBanner` painted it whenever `beforeinstallprompt` fired, and Chromium fires that on desktop Edge/Chrome too |
| the popup again on **every session** | dismissal was `sessionStorage`, and it shared ONE key with the update notice |
| no way back after dismissing | the cross was the end of the road: nothing replaced it |
| a popup that did not look like the app | `alert alert-info` + `btn-ghost`: a flat strip, not the `bg-base-200` + border card every other surface uses |

**What it is now** (`web/src/pwa/banner.ts`):

- **Phone only.** `isPhone()` = `(pointer: coarse) and (hover: none)` — the
  `hover` half is what keeps a touchscreen laptop out. No card on a desktop.
- **Only when not installed.** `isInstalled()` = `display-mode: standalone` OR
  iOS `navigator.standalone`, checked in addition to `canInstall()`, because a
  user who installed from the browser menu fires no event we can see.
- **A card, not a strip** (DESIGN §2.3, §4.7): app icon, `text-sm font-semibold`
  title, `text-xs /60` body, one `btn-accent` action (white = the one emphasis
  action, §0.5), 44px close (§5). Offset is
  `calc(4rem + env(safe-area-inset-bottom) + 1rem)`, so the notched-phone home
  indicator cannot push the dock into the card.
- **One answer per device.** The cross writes `pwa-install-dismissed` to
  **localStorage** (per device, not per session) and hands the job to an install
  icon button in the phone navbar (`#mobile-navbar .navbar-end`, added in
  `base.html`). The update notice keeps its own session key — a later version is
  a new message.
- **No dead buttons.** The card shows the Install action only while the browser
  still holds the prompt. Refused, or absent (iOS, iPadOS reporting a Mac UA),
  repaints as the manual route: Share → Add to Home Screen, or the browser menu.

**Evidence** — `banner.test.ts` (14 tests; break-proved: dropping the phone gate
turns 1 red, dropping the installed gate 1, dropping the persist write 2,
dropping the navbar handoff 2) and a Playwright DUT at iPhone 13 / Pixel 7 /
1280×900 (25 checks): card above the dock with a 16px gap, 44×44 targets, no card
on desktop, card absent after reload, navbar button present after reload.

**Ceiling:** logout wipes localStorage (`session.ts`), so a logout/login cycle
shows the card once more. That wipe is a privacy property, not a bug — the card
is one line of code to re-add if it ever matters.
