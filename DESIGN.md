# OpenSRM design system

> **Audience: coding agents.** Read this whole file before you change any template, stylesheet, or UI class in this repo.
>
> The `openSRM` theme is unusual: its `primary` color is **black**, and its surfaces are stacked the opposite way to daisyUI's docs. Your defaults will produce invisible buttons, wrong cards, and off-palette colors.
>
> When this file and your memory of daisyUI disagree, **this file wins**.

**Contents:** 0 Quick rules · 1 Look and feel · 2 Color · 3 Typography · 4 Components · 5 Layout and responsive · 6 Depth · 7 States and motion · 8 Copy · 9 Do and don't · 10 Implementation constraints · 11 Workflow and checklist · 12 Known drift · Appendix

---

## 0. Quick rules

1. **Tokens only.** Every color is a daisyUI/Tailwind token class (`bg-base-200`, `text-success`, `border-base-300`) or a CSS variable (`var(--color-success)`). Never write a hex, `rgb()`, `oklch()`, or a Tailwind palette class (`bg-gray-800`, `text-green-400`, `bg-black`, `text-white`).
2. **Grayscale is structure, color is meaning.** Green/amber/red = attendance health. Blue = information. Pink = one rare highlight. Nothing is colored just to look nice.
3. **The surface stack is inverted.** Page `bg-base-100` → containers `bg-base-200` (*darker* than the page) → lines `border-base-300` (lighter). Every container gets `border border-base-300`; the surface steps alone are almost invisible (§2.3).
4. **`primary` is black. Never use it for emphasis.** It is invisible as text, border, ring, link, checkbox, or progress. White emphasis is `accent` / `base-content` (§2.4).
5. **Button ladder.** One `btn-accent` (white) hero action per screen. `btn-primary` (black) is the standard solid button. `btn-outline` secondary. `btn-ghost` tertiary (§4.2).
6. **Status color follows the attendance thresholds.** ≥ 75% `success`, 65–74.9% `warning`, < 65% `error`. Never use these three for decoration, categories, or branding (§2.6).
7. **Never color alone.** Every status color sits next to a number, a word, or an icon.
8. **Dim text with `text-base-content/60`; `/50` is the floor.** Never `opacity-*`, never `text-gray-*`, never below `/50` for text people must read (§2.5).
9. **Borders, not shadows.** No gradients, glows, blur, glassmorphism, hover-lift, or colored shadows (§6).
10. **Data is monospace.** Course codes, percentages, times, counts, dates, NetIDs → `font-mono`. Everything else uses the default sans (§3).
11. **daisyUI 5 only.** `input-bordered`, `form-control`, and `label-text` do not exist in v5. Use `fieldset`, `floating-label`, `input`, `label`.
12. **Pre-compiled CSS, strict CSP.** Tailwind (pinned CLI) + daisyUI are compiled ahead of time into `app/static/app.css` (committed; CI fails if it is stale vs the templates — §10.16). No runtime CDN, no inline `<script>`, no other CDNs, no web fonts. After editing anything in `app/static/`, bump `CACHE_NAME` in `sw.js` (§10).

### Cheat sheet: what am I styling?

| I'm styling… | Use |
|---|---|
| Page background | `bg-base-100 text-base-content` on `<body>` |
| Card, navbar, modal, table header, accordion | `bg-base-200 border border-base-300` |
| Divider, border, progress track, avatar bg | `border-base-300` / `bg-base-300` |
| Raised strip inside a card | `bg-base-300/50` (widget fill `.wbox` is the /60 step, §4.17) |
| Body / heading text | inherit (`text-base-content`) |
| Description, caption | `text-base-content/60` · footnote floor `text-base-content/50` |
| Good / at-risk / bad number | `text-success` / `text-warning` / `text-error` (by threshold) |
| Status progress bar | `progress progress-success` / `-warning` / `-error` (monthly rows; subjects use §4.15 meters) |
| Hero button (one per screen) | `btn btn-accent` |
| Standard button | `btn btn-primary hover:bg-base-300 focus-visible:outline-accent` |
| Selected pill | `bg-accent text-accent-content` |
| Selected navbar tab | `theme.html` rule `.navbar [role=tab][aria-selected=true]` tint (§4.9) |
| Neutral notice | `alert alert-soft alert-info` |
| The one rare highlight | `badge badge-secondary` (pink) |
| Code, %, time, count, date | add `font-mono` |

---

## 1. Look and feel

OpenSRM is a self-hosted, mobile-first PWA that shows an SRM student their attendance, timetable, and personal details. People open it on a phone between classes to answer three questions: *Am I safe? Can I skip this one? What's next?*

The look comes from the pixel wordmark logo: stark black and white. Near-black surfaces, white text, hairline borders, no ornament. Calm, dense, data-first, slightly terminal-like. It should feel like an instrument panel, not a marketing page: nothing is on screen unless it helps someone read a number or take an action.

It is a **single dark theme** (`data-theme="openSRM"`). There is no light mode, no theme switcher, and no `dark:` variants.

Anatomy of the dashboard:

```text
┌────────────────────────────────────────────────────┐
│ navbar   bg-base-200 · border-b border-base-300 · sticky
│ logo | name     [Dashboard][Attendance]…[Settings]  [Refresh] (5m ago)
│                ← role=tab, selected = §4.9 tint     ← caption only once ≥5m old
├────────────────────────────────────────────────────┤   page: bg-base-100
│  main px-2 lg:px-4 py-5 pb-24 lg:pb-5             │   full-width on Dashboard only
│  ┌─ grid grid-cols-1 lg:grid-cols-12 gap-6 ──────────────────────────┐
│  │ day  span 4 · row-span 2   │ assess span 8      │  §4.17 engine  │
│  │   profile · today · week   │   marks · exams    │                │
│  │   notices                  │ people span 8      │                │
│  │                            │   attendance ·     │                │
│  │                            │   teachers         │                │
│  └────────────────────────────┴────────────────────┘                │
│  attendance · timetable · marks · personal panels:                  │
│  each its own `max-w-3xl mx-auto` tabpanel                          │
└────────────────────────────────────────────────────┘
```

---

## 2. Color

### 2.1 How the theme reaches the page

The theme is authored as a daisyUI 5 custom theme (Appendix A), but the runtime theme is **not built in the browser**. It ships as plain CSS variables under `html[data-theme="openSRM"]` in the shared partial `app/templates/partials/theme.html`, included by both `login.html` and `dashboard.html` (the compiled `app.css` supplies daisyUI component layer around it — §10.16). Do not use `@plugin "daisyui/theme"` in runtime files; it only works inside the pinned build.

### 2.2 Tokens and roles

| Token | Value (oklch) | ≈ sRGB hex\* | Role |
|---|---|---|---|
| `base-100` | 20% 0 0 | `#161616` | **Page background** (`<body>`, tab panels) |
| `base-200` | 14% 0 0 | `#090909` | **Containers:** navbar, cards, modal box, table header, accordions |
| `base-300` | 26% 0 0 | `#242424` | **Lines and wells:** borders, dividers, progress tracks, avatar bg, inset fills |
| `base-content` | 100% 0 0 | `#ffffff` | **Text and icons** (dim with `/60`, `/50`) |
| `primary` / `-content` | 0% 0 0 / 100% 0 0 | `#000000` / `#ffffff` | Fill of `btn-primary` **only** |
| `accent` / `-content` | 100% 0 0 / 0% 0 0 | `#ffffff` / `#000000` | **White emphasis:** hero CTA, selected pill, checked state. `accent-content` is the theme's black text |
| `secondary` / `-content` | 65% .241 354 / 97% .014 343 | `#f43098` / `#fcf2f8` | Pink highlight, rare (§2.7) |
| `neutral` / `-content` | 26% 0 0 / 98% 0 0 | `#242424` / `#f8f8f8` | Same value as `base-300`; rarely needed |
| `success` | 76% .177 163 | `#00d390` | Attendance ≥ 75%, class "Now", saved |
| `warning` | 68% .162 76 | `#d08700` | Attendance 65–74.9%, breaks, offline, hours missed |
| `error` | 57% .245 27 | `#e50006` | Attendance < 65%, failures, destructive |
| `info` | 58% .158 242 | `#0082ce` | Neutral information only |

\*Hex values are sRGB approximations (several of these oklch colors sit outside sRGB). Use them only where CSS variables cannot reach: `<meta name="theme-color">`, `manifest.json`, canvas or exported SVG. In CSS and HTML always use the token.

Shape tokens: `--radius-selector/field/box` = `0.5rem` · `--size-selector/field` = `0.25rem` (control height = size × 10, so `btn` is 40px, `btn-sm` 32px, `btn-lg` 48px) · `--border` = `1px` · `--depth` = `1` · `--noise` = `0`.

### 2.3 The surface stack (inverted vs daisyUI docs)

```text
page         bg-base-100     #161616   lightest surface
└ container  bg-base-200     #090909   darker "well": cards, navbar, modal, table header
  └ line     border-base-300 #242424   lighter hairline around every container
```

daisyUI's docs and the theme-generator preview put cards on `base-100` over a `base-200` page. **This app does the reverse.** Follow the app, not the generator preview.

- The steps are tiny (contrast 1.10:1 between `base-200` and `base-100`, 1.28:1 between `base-300` and `base-200`), so the 1px `border-base-300` is what actually draws the edge. A container without its border looks smudged.
- Inputs inside a card keep daisyUI's default fill (`base-100`), so they sit *lighter* than the card.
- A raised strip inside a card is `bg-base-300/50` (see the Personal Details section headers); the §4.17 widget fill `.wbox` is the next step up, `base-300/60`. Nest at most two levels: page → container → sub-surface. Never card-in-card-in-card.

### 2.4 `primary` is black: the trap

`primary` is `oklch(0% 0 0)`. On this UI's surfaces it measures 1.05–1.35:1, so it is invisible as anything except the fill of a button that has a white label. daisyUI defaults assume `primary` is a brand color, so it is the class agents reach for to add emphasis. Don't.

| You want | Use | Never (invisible here) |
|---|---|---|
| Standard solid button | `btn btn-primary` + hover/focus fixes (§4.2) | |
| The one hero action | `btn btn-accent` | `btn-primary` |
| Selected / active pill | `bg-accent text-accent-content` | `bg-primary`, `border-primary` |
| Active tab | `.navbar [role=tab][aria-selected=true]` tint in `theme.html` (§4.9) | daisyUI `.btn-active` (see §10.11 — a 5% black fill is a no-op here), `text-primary`, `border-primary` on a tab |
| Input focus ring | daisyUI default (2px `base-content` outline). **Add nothing.** | `input-primary`, `focus:input-primary`, `focus:ring-primary` |
| Checked checkbox / radio / toggle | `checkbox-accent`, `radio-accent`, `toggle-accent` | `*-primary` |
| Link | `link` (inherits color), `link-hover`, or `link-accent` | `link-primary`, `text-primary` |
| Progress, ring, spinner | status token if it encodes status; else `progress-accent` or default `currentColor` | `progress-primary`, `text-primary` on a spinner or radial |
| Tinted highlight | `bg-base-content/5`; `bg-success/10` for status only | `bg-primary/10` (a tint of black is nothing) |

Two more consequences of a black `primary` (both checked against daisyUI 5.7.42 source):

- `btn-primary` gets **no hover feedback**. daisyUI darkens the fill on hover, and black cannot get darker.
- `btn-primary`'s focus outline is drawn in the button's own color, so keyboard focus is **black on near-black**.

### 2.5 Text hierarchy = opacity of `base-content`

| Level | Class | Contrast on `base-200` | Use |
|---|---|---|---|
| Primary | `text-base-content` (default) | 19.9:1 | Headings, values, body |
| Secondary | `text-base-content/60` | 7.3:1 | Descriptions, sublines, labels |
| Tertiary (floor) | `text-base-content/50` | 5.3:1 | Captions, footnotes, help text. The lowest allowed for text people must read |
| Faint | `text-base-content/40` | 3.7:1 | Fails AA for small text. **Legacy only** (netid, stat rows). Don't use for new text |

Dim with the color modifier, not `opacity-*` (which also fades borders and children). Icons follow the text they sit beside.

### 2.6 Status colors

Thresholds live in `app/views/attendance.py` (re-exported by `app.app`): `ATTENDANCE_TARGET = 0.75`, `ATTENDANCE_WARN = 0.65`; `_status_for_pct()` returns `"ok"`, `"warn"`, or `"danger"`.

| `status` | Range | Token | Note |
|---|---|---|---|
| `ok` | ≥ 75% | `success` | |
| `warn` | 65% to < 75% | `warning` | |
| `danger` | < 65% | `error` | The Python value is `danger`; the CSS token is `error` |

Template pattern, as used today (the compiled build cannot see class names created at render time — any dynamic family must be safelisted in `app/static/safelist/classes.html`, §10.16; never build class names from user data):

```jinja
text-{{ 'success' if c.status == 'ok' else 'warning' if c.status == 'warn' else 'error' }}
```

| Other meaning | Token |
|---|---|
| Class happening now (`Now`) | `success` |
| Class starting soon (`Soon`) | `accent` (white) |
| Break, offline banner, hours-missed badge | `warning` |
| Absent-days count, failed request, destructive action | `error` |
| Saved / confirmed | `success` |
| Neutral notice ("No personal details available.") | `info` |
| Done for today, no timetable, off | gray only (`base-content/50`), no hue |

Rules:

- Status color appears on **at most three parts of one card** (left border, the number, the bar). Don't tint the whole card.
- Never use green/amber/red for decoration, categories, or brand, for example to color-code subjects. Tell subjects apart by mono code and position, not hue.
- Never color alone. Keep the number ("82.5%"), the sentence ("Can miss 3 more classes…"), or an icon next to the color.

### 2.7 Secondary (pink) and info (blue)

- **Pink `secondary` is used exactly once in the shipped UI: the single outlier percentage on the Marks tab (§4.13).** Treat it as the single accent-of-attention: at most one element per screen (a "New" badge, a feature dot, one chart series). Never for status, links, buttons, or container borders/backgrounds. When unsure, leave it out.
- **Blue `info`** is for neutral notices only (`alert-info`, `alert-soft alert-info`, tooltips). It is not a link color and not an accent.

### 2.8 Contrast facts to design around

Approximate ratios, computed from sRGB-clipped values. WCAG AA is 4.5:1 for small text, 3:1 for large text and UI shapes.

- **Surfaces barely separate:** `base-200`↔`base-100` 1.10, `base-300`↔`base-100` 1.17, `base-300`↔`base-200` 1.28. Always add the border.
- **Status colors as text on `base-200`:** success 10.2, warning 6.8, secondary 5.4, info 4.8, **error 4.1**. On `base-100`: 9.2 / 6.2 / 4.9 / 4.4 / **3.7**. Error is the weakest: use it at `text-sm` or larger, on `base-200`, with wording or an icon. Never as a small paragraph.
- **Solid fill with its own `-content` label:** primary 21, accent 21, neutral 14.6, error 4.4, info 3.8, secondary 3.4, **warning 2.8**, **success 1.9**. The theme's pale `success-content` on bright green is nearly unreadable.

So for badges, buttons, and banners that carry small text:

| Status | Best treatment | Why |
|---|---|---|
| success | `badge-soft` / `btn-soft` / `alert-soft`, **or** solid + `text-accent-content` | soft ≈ 8:1; black on green 10.7:1; default label 1.9:1 |
| warning | `-soft`, **or** solid + `text-accent-content` | soft ≈ 5.4–6.1:1; black on amber 7.2:1; default label 2.8:1 |
| error | solid + `text-base-content` label (measured 4.9:1 — the default `-content` label lands 4.4:1, under AA) | `-soft` is weaker (≈ 3.6–4.0:1) |
| info | solid + `text-accent-content`, or soft | black 5.1:1; default 3.8:1; soft ≈ 4.0–4.5:1 |
| secondary | solid + `text-accent-content` | black 5.7:1; default 3.4:1 |

---

## 3. Typography

- **Families:** the system stack only. Default sans (Tailwind `font-sans`) for text, `font-mono` for data. There are no web fonts; the CSP blocks them (§10). `timetable.css` uses the generic `monospace` stack (an earlier `IBM Plex Mono` mention was never loaded and has been removed).
- **Scale in use:** `text-xs` 12px (meta, captions, stat rows) · `text-sm` 14px (body, values, controls) · `text-base` 16px (section headings, card titles). Nothing larger inside the dashboard — except the §4.17 widget exceptions: `.wlabel` at 11px (floor, labels only) and the `today` ticker's running-class start time at 22px (the one hero figure, `font-mono font-bold tabular-nums`).
- **Weights:** 400 body · 500 `font-medium` (field labels, status lines) · 600 `font-semibold` (section headings, names; `btn` is 600 by default) · 700 `font-bold` (percentages only).
- **Mono is for data:** course codes, percentages, times, counts, dates, NetID. Never for sentences.
- **Case:** sentence case for new copy. Uppercase micro-labels exist in exactly two places: the Personal Details list (`text-xs uppercase tracking-wide`) and the dashboard widget labels (`.wlabel`, §4.17); do not spread them further. Portal data arrives in ALL CAPS, so course names are shown with `capitalize`.
- **Alignment:** left-aligned. Centered text appears only on the login screen (card note, status line) and the timetable break dividers. Keep lines under ~70 characters.

---

## 4. Components

Copy the nearest recipe here or the nearest existing markup in `dashboard.html`. Do not invent new component shapes.

### 4.1 Container

```html
<div class="card bg-base-200 border border-base-300">
  <div class="card-body p-4 gap-2"> … </div>   <!-- p-5 for the hero card, p-0 for list cards -->
</div>
```

### 4.2 Buttons

| Role | Classes | Notes |
|---|---|---|
| Hero action (max one per screen) | `btn btn-accent btn-lg w-full` | White fill, black label. Login "Sign in" |
| Standard solid | `btn btn-primary btn-sm hover:bg-base-300 focus-visible:outline-accent` | Black fill, white label. The two extra classes are required because `primary` is black (§2.4) |
| Secondary | `btn btn-outline btn-sm` | Transparent, `base-content` outline |
| Tertiary / toolbar | `btn btn-ghost btn-sm` | Add `text-base-content/60` for quiet ones |
| Confirm / save | `btn btn-success btn-sm text-accent-content` | Forces black label; the default label is 1.9:1 (§2.8) |
| Destructive | `btn btn-error btn-sm text-base-content` | Pair with a confirm step; the label override is what clears 4.5:1 (§2.8) |
| Icon only | `btn btn-ghost btn-sm btn-square` + `aria-label` | Inline SVG inside |

At most one solid button per row; the rest are `btn-outline` or `btn-ghost`. Labels are verb-first ("Edit timetable", "Save").

### 4.3 Status card (one per course) — RETIRED for attendance (§4.15)

> Superseded on the Attendance tab by the §4.15 meter row (2026-10). Kept below as the historical reference — `_bunk_line` still produces this sentence and it may appear in other surfaces.

```html
<div class="card bg-base-200 border border-base-300 border-l-3 border-l-success">
  <div class="card-body p-4 gap-2">
    <div class="flex justify-between items-baseline gap-2">
      <span class="font-mono text-xs text-base-content/60">21CSC101T</span>
      <span class="font-mono font-bold text-success">82.5%</span>
    </div>
    <h3 class="text-sm capitalize leading-snug">Course description</h3>
    <progress class="progress progress-success" value="82.5" max="100"></progress>
    <div class="flex gap-3 font-mono text-xs text-base-content/50 flex-wrap">
      <span>33 attended</span><span>7 absent</span><span>40 total</span>
    </div>
    <p class="text-xs text-base-content/50 border-t border-base-300 pt-2">Can miss 3 more classes and stay above 75%</p>
  </div>
</div>
```

The grid that holds them: `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3`. (Existing stat rows use `/40`; use `/50` in new work.)

### 4.4 Hero metric (overall attendance) — RETIRED (§4.15)

> The overall strip was removed with the §4.15 redesign: no aggregate anywhere (no overall %, no overall bunk line). Kept below for the radial-progress idiom only.

```html
<div class="flex items-center gap-5">
  <div class="radial-progress text-success" style="--value:82; --size:5rem; --thickness:6px;" role="progressbar">
    <span class="text-base-content font-bold text-sm">82%</span>   <!-- keep text-base-content, or the number turns green -->
  </div>
  <div class="flex-1 min-w-0">
    <h2 class="card-title text-base">Overall attendance</h2>
    <p class="text-sm text-base-content/60">320 of 390 hours attended</p>
    <p class="text-sm font-medium text-success">Can miss 3 more classes and stay above 75%</p>
  </div>
</div>
```

### 4.5 Badges

```html
<span class="badge badge-sm badge-soft badge-warning">2 hr</span>   <!-- success/warning: soft (§2.8) -->
<span class="badge badge-sm badge-error">3 days</span>              <!-- error: solid -->
```

### 4.6 Form field (daisyUI 5 idiom)

Two idioms, both daisyUI 5. **Floating label + leading icon** is the login form:

```html
<label class="floating-label w-full" for="netid">
  <svg class="pointer-events-none absolute start-3 top-1/2 z-10 h-5 w-5 -translate-y-1/2 opacity-50" …></svg>
  <input type="text" id="netid" class="input input-lg w-full text-base ps-10"
         placeholder="NetID / SRM email" autocomplete="username webauthn"
         autocapitalize="off" autocorrect="off" spellcheck="false">
  <span>NetID / Email</span>
</label>
```

`fieldset` + `fieldset-legend` stays the idiom for grouped fields (the subject editor modal).

- The icon needs `z-10`: `.input` is itself `position: relative` and comes after the
  icon in DOM order, so without it the input's background paints over the icon.
- `text-base` on inputs — anything smaller triggers mobile-Safari's focus zoom.
- `input-lg` (48px fields) so controls clear the ~44px touch-target floor.
- Inputs are bordered by default in v5. Focus is daisyUI's white 2px ring; do not override it.
- Invalid: add `input-error` and a `text-sm text-error` sentence below saying what to fix.
- Password toggle: `relative` wrapper around the label, input gets `pe-12`, button is
  `absolute end-1 top-1/2 -translate-y-1/2 btn btn-ghost btn-sm btn-square h-11 w-11` with
  `aria-label`. Keep the button OUTSIDE the `<label>` or it joins the input's accessible name.
- The Caps Lock hint row under the password field is always reserved (`h-4`), so showing
  it never shifts the layout.

### 4.7 Alerts and banners

```html
<div class="alert alert-soft alert-info">No personal details available.</div>

<!-- offline banner -->
<div class="alert alert-soft alert-warning fixed bottom-0 left-0 right-0 z-50 rounded-none pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
  You are offline — showing cached data
</div>
```

### 4.8 Modal and loading

```html
<dialog id="feedback-modal" class="modal">
  <div class="modal-box bg-base-200 border border-base-300 flex flex-col gap-3">
    <h3 class="text-lg font-semibold">Feedback — before you submit</h3>
    <p class="text-sm text-base-content/70">Read the list, then confirm.</p>
    <div class="modal-action">
      <button class="btn btn-primary">Confirm</button>
    </div>
  </div>
</dialog>
```

`modal-box` defaults to `base-100`; the app overrides it to `base-200` to match every other container. Keep that.

Page-level **data refresh never uses a blocking modal** (§7, §10.16 rule 3):
the refresh icon spins and the content updates in place; a submit button
disables itself and reports status inline (or via the toast) instead of
freezing the screen behind a dialog.

### 4.9 Tables, lists, accordions, tabs

```html
<!-- table -->
<div class="overflow-x-auto border border-base-300 rounded-box">
  <table class="table table-sm table-pin-rows">
    <thead><tr class="bg-base-200"><th>Month</th><th>Present</th><th>%</th></tr></thead>
    <tbody><tr><td>Sep</td><td>18</td><td class="font-mono font-bold">92%</td></tr></tbody>
  </table>
</div>

<!-- identity card + grouped detail list (Settings → Personal details row) -->
<div class="flex flex-col gap-3">
  <div class="card bg-base-200 border border-base-300">
    <div class="card-body p-4">
      <div class="text-lg font-semibold" data-copy="…">Student Name</div>
      <div class="text-sm font-mono text-base-content/60 break-words mt-1" data-copy="…">Program…</div>
    </div>
  </div>
  <div class="collapse collapse-arrow bg-base-200 border border-base-300">
    <input type="checkbox" />
    <div class="collapse-title text-sm font-semibold flex items-center justify-between gap-2">
      <span>Academic</span><span class="badge badge-sm">6</span>  <!-- count = fields present -->
    </div>
    <div class="collapse-content">
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-2">
        <div class="sm:col-span-2">   <!-- full-width for long values (Address, Institution) -->
          <div class="text-xs uppercase tracking-wide text-base-content/50">Label</div>
          <div class="text-sm font-mono break-words" data-copy="…">value</div>
        </div>
      </div>
    </div>
  </div>
</div>
```

- **Detail panel spacing ladder:** label→value `0` (attached) < row gap `gap-2` 8px < card stack `gap-3` 12px — asserted by `tests/e2e/test_personal.py`.
- **Responsive default state:** `dash.js` checks every group at ≥640px (dense fact-sheet scan) and opens only the first group below (compact lookup). `checkbox`, not `radio`, so groups toggle independently; `radio name=…` remains the one-open-at-a-time recipe.
- **Accordion:** `collapse collapse-arrow bg-base-200 border border-base-300` — title `text-sm font-semibold`, count as a badge on the right.
- **Tabs:** `tabs tabs-border mb-5` containing `tab` buttons with `role="tab"`; the active one adds `tab-active`.
- **Navbar tabs (the dashboard's real navigation):** plain `btn btn-ghost btn-sm` buttons in the
  navbar's `role="tablist"`; `dash.js` moves `aria-selected` on click. The *selected* fill is a rule
  in `partials/theme.html`, not a class:

  ```css
  .navbar [role="tab"][aria-selected="true"] {
    position: relative;
    background-color: color-mix(in oklab, var(--color-base-content) 10%, transparent);
  }
  .navbar [role="tab"][aria-selected="true"]::after {
    content: ""; position: absolute; width: auto;   /* width is load-bearing, see §10.11 */
    left: 0.5rem; right: 0.5rem; bottom: 2px; height: 2px; background: currentColor;
  }
  ```

  It has to be a rule because daisyUI's own active state is a no-op here — see §10.11. Measured:
  selected vs navbar = **1.25:1** (the same step as `base-300` over `base-200`, §2.3), unselected =
  **1.00:1**. The mobile dock does not need it: `.dock-active` draws a `currentColor` underline bar.

### 4.10 Icons and avatar

- Icons are **inline SVG**, Heroicons outline style: `fill="none" stroke="currentColor"`, stroke width 1.5–2, `w-4 h-4` (in buttons) or `w-5 h-5`. Never fixed fill colors, never emoji, never an icon font or library (CSP).
- Avatar: `avatar` → `div.bg-base-300.w-9.rounded-full` holding an `<img>` (blobatar via the local `/avatar/<name>` route; CSP `img-src 'self' data:` allows no remote image hosts).
- Wordmark (`logo-rect.png`, a hard-cornered 1500×500 bitmap): the navbar copies take `rounded-sm` (4px) so the corners don't read as a cut-out against the bar. Measured: 4px on an `h-8` logo is 12.5% of its height — visible, still a corner. `rounded-box` (0.5rem = 8px) was tried first and reads as **over-curled** at `h-8`/`h-6` (25% of the height), so the box token is NOT the logo's radius; keep the wordmark at 4px.

### 4.11 Timetable (server-rendered, `tt-*` classes)

`timetable_html()` in `app.py` emits the markup and `app/static/timetable.css` styles it. That file already uses `var(--color-*)` tokens throughout. When you touch a rule, keep it token-based:

```css
/* v2.7.0: one solid card per class on [72px mono time | name + code/room/tag] */
.tt-row           { background: var(--color-base-200); border-radius: 10px;
                    padding: 14px 18px; }
.tt-row--now      { border-color: color-mix(in oklab, var(--color-success) 45%, transparent);
                    background: color-mix(in oklab, var(--color-success) 7%, var(--color-base-200)); }
.tt-tag--warn     { background: oklch(78% 0.115 68 / .18); color: oklch(78% 0.115 68); }
.tt-tag--danger   { background: oklch(72% 0.135 25 / .18); color: oklch(72% 0.135 25); }
```

Meaning map: live class = `tt-row--now` success tint (the hero states it in words — no chip, one state, one indicator) · comfortable / zero-margin / must-attend = the `.tt-tag` three tiers (number always beside the word, never colour alone) · selected day pill = `base-content` fill with `base-100` text · break = dashed `base-content/30` rules · the subject NAME is the row's primary line, the course code its 12px mono subline · the piece that stays a rule: **a tag's hue is lifted toward white on dark surfaces** — the raw status tokens measure 3.8:1 and 3.0:1 against `base-200` and fail AA for 11px text, so tag tiers use 78%/72% lightness (7.2:1 / 5.9:1). Never reuse `.att-pos`/`.att-neg` values on a dark surface for the same reason.

### 4.12 End-sem schedule card (dashboard)

`_exams_view()` builds the view model (`day`, `dow`, `short`, `name_disp`, month-range `label`, `source`); the card renders only when exams exist — **empty = hidden, by design** (no empty-state text, unlike sibling cards). The header caveat is a **dynamic source badge** (Oct 2026: the portal published official dates): `Official` when every row carries a clock `slot` (from the iden=126 Exam Time Table), `Official + est.` on a mixed view, `Estimated` when rows come from the ScribeInner leak alone. Same `badge-outline badge-sm text-base-content/60` styling as the old static `Provisional` pill (7.15:1, subtle-but-present). Row metadata carries the clock slot when present, plus the room allotment when the portal publishes it (`Hall … · Seat …`, hidden until then — the ETT table leaves those cells blank until ~1 day before each exam): `{{ e.code }} · {{ e.session_disp }}{% if e.slot %} · {{ e.slot }}{% endif %}{% if e.hall %} · Hall {{ e.hall }}{% if e.seat %} · Seat {{ e.seat }}{% endif %}{% endif %}`. Sessions display as the portal's own `AN`/`FN` codes — students' native notation — never expanded. The iden=126 parser is **header-driven** (column positions resolved from the header row's labels, unknown columns ignored, `None` on drifted-but-present tables so stored rows are preserved rather than wiped); hall/seat publication and the estimate→official transition fire **one-shot Web Push events** (at-most-once per device via `push_sent_log` claims, 12 h delivery TTL).

```jinja
<!-- mobile: one landmark (day stamp) + one bright line (name) per row -->
<li class="flex items-start gap-3">
  <span class="w-9 shrink-0 text-center sm:hidden">
    <span class="block font-mono text-[17px] font-semibold leading-none tabular-nums text-base-content">{{ e.day }}</span>
    <span class="block mt-1 text-[11px] uppercase tracking-wider text-base-content/60">{{ e.dow }}</span>
  </span>
  <span class="min-w-0 flex-1 sm:hidden">
    <span class="block text-sm leading-snug text-base-content">{{ e.name_disp }}</span>
    <span class="block mt-0.5 font-mono text-xs text-base-content/60">{{ e.code }} · {{ e.session_disp }}{% if e.slot %} · {{ e.slot }}{% endif %}{% if e.hall %} · Hall {{ e.hall }}{% if e.seat %} · Seat {{ e.seat }}{% endif %}{% endif %}</span>
  </span>
  <!-- desktop: one dense line via sm: switches, zero JS -->
  <span class="hidden sm:flex sm:w-full sm:items-baseline sm:justify-between sm:gap-4">
    <span class="min-w-0 truncate text-sm"><span class="font-mono text-base-content/60">{{ e.code }}</span> <span class="text-base-content">{{ e.name_disp }}</span></span>
    <span class="shrink-0 font-mono text-xs text-base-content/60">{{ e.short }} · {{ e.session_disp }}{% if e.slot %} · {{ e.slot }}{% endif %}{% if e.hall %} · Hall {{ e.hall }}{% if e.seat %} · Seat {{ e.seat }}{% endif %}{% endif %}</span>
  </span>
</li>
```

- **Rows:** `space-y-3 sm:space-y-2`, no dividers — density comes from grouping, not rules (§ B2 / §6). The day stamp is the only 17px/600 element; name is the only `text-base-content` line; everything else `/60` (§2.5 ladder).
- **Names** are title-cased in `_exams_view()` (`name_disp`); storage keeps the portal's ALL-CAPS `name`.
- **Chip** is the default `badge-soft` — same as the marks pills (§2.7: no decorative hue). Measured soft ≈14:1 here; `badge-info` soft measured **4.07:1 on this surface (fails)** — see §10 for the override trap. The source caveat lives in the header as `badge-outline badge-sm text-base-content/60` (7.15:1, subtle-but-present) — formerly a static `Provisional` pill, now the dynamic `{{ exams.source }}` badge (Official / Official + est. / Estimated). Unlike `badge-info`, outline badges carry no explicit color rule, so `/60` does apply.
- **Verify after any row change:** a contrast probe on the rendered page (canvas-normalized colors composited over the real card bg) and geometry assertions at 393×851 + 1280×900 (one stamp x, one name x, no overlap, no h-overflow, source badge in the header, card bottom above the fixed dock).

### 4.13 Internal marks card (Marks tab)

`_marks_view()` builds the view model: title-cased `title`, `scored_disp`/`max_disp` (`16.2/20` — maxima whole, scores with trailing zeroes stripped), neutral `pct` + one `outlier`, components sorted by **name** with `date_disp` (`04 Sep`, junk passes through), and per component `derived` / `confirmed` / `ie` (converted paper marks). `_marks_summary()` returns **every subject** for the dashboard glance as `code scored/max` chips (e.g. `21MAB206T 13.4/20` — the values as last synced, risk-first order weakest first; **no `%`** on the glance) — there is **no aggregate/overall number anywhere** (brief). A row preserved from an earlier sync (empty fetch, B6) carries `stale=True` and its chip renders faint (`opacity-60` + a `title`, never colour alone).

```jinja
<div class="grid grid-cols-1 md:grid-cols-2 gap-3">  <!-- default stretch: side-by-side cards share one height; content stays top-pinned (block flow) -->
  <div class="bg-base-200 border border-base-300 rounded-box p-4">
    <div class="flex items-baseline justify-between gap-2">
      <span class="font-mono text-xs text-base-content/60">21CSS201T</span>
      <span class="font-mono font-bold text-lg tabular-nums">81.0%</span>  <!-- + text-secondary once, if outlier -->
    </div>
    <h3 class="text-sm font-semibold leading-snug">Computer Organization And Architecture</h3>
    <div class="font-mono text-xs text-base-content/50 tabular-nums mb-2">16.2/20</div>
    <div class="border-t border-base-300 pt-2">
      <div class="py-1">
        <div class="flex items-center gap-2">
          <span class="inline-flex items-center justify-center w-14 h-5 shrink-0 rounded-full bg-base-300 text-base-content/70 font-mono text-xs">FT-II</span>
          <span class="text-xs font-mono text-base-content/50">09 Sep</span>
          <span class="font-mono text-xs tabular-nums ml-auto">11.7/15</span>
          <details class="relative shrink-0"><summary>{/* pencil, 24px target */}</summary>
            <form method="post" action="/marks/tag" class="absolute end-0 top-full mt-1 z-10 w-60 bg-base-200 border border-base-300 rounded-box p-3 flex flex-col gap-2">…</form>
          </details>
        </div>
        <div class="flex items-center gap-2 ps-6 mt-0.5">   <!-- nested IE row: 24px indent -->
          <span class="…chip…">IE-1</span>
          <span class="text-xs text-base-content/50">derived</span>
          <span class="font-mono text-xs tabular-nums ml-auto">39/50</span>
        </div>
      </div>
    </div>
  </div>
</div>
```

Rules specific to this card:

- **Numbers are neutral.** No status hue on any number — at most ONE `text-secondary`, on the unique lowest subject and only below the 75 target (§2.7). Green/amber/red stay attendance-only (§2.6).
- **No overall %, no per-component %.** Per-subject `%` + `scored/max` only. Maxima print whole (`/15`, never `/15.00`); scores strip trailing zeroes (`16.2`, `5` — never `16.20`/`5.00`); every figure is `font-mono tabular-nums`. Subject names are title-cased in Python (CSS `capitalize` cannot downcase ALL-CAPS portal data).
- **The component chip is a hand-rolled span, not a `.badge`:** daisyUI badges cannot lose their 1px border (§10.9) and this chip must be solid-fill, borderless. Fixed `w-14` (56px = the widest name, `FML-I`) so `FT-II` can never shift the date column. Fill `bg-base-300`, label `text-base-content/70`.
- **Dates** are `04 Sep`, muted `/50`, `text-xs` (12px floor).
- **IE rows** nest under the component they derive from (`ps-6` indent), labelled `derived` or `confirmed`, with marks converted to the paper total (IE-1 → `/50`, IE-2 → `/60`). The portal never labels IEs; `_derive_ie()` guesses `/15` (theory) or `/10` (practical code), and a stored tag always wins.
- **Tag form = `<details>` + `<form method="post" action="/marks/tag">`** — the form itself needs no JS; the only script involved is the outside-click light-dismiss handler in `dash.js` (one `details[open]` guard — and the reason this release bumps the SW cache). The server keys the tag `year|branch|section|course|component` (no semester, no netid): one student's confirmation applies to the whole class and is persisted for the GPA predictor.
- **Verify with** `tests/e2e/test_marks_dut.py` (53 checks at 393×851 + 1280×900: uniform chips, date x-alignment, one accent, contrast, uniform row heights + top-pinned content, tooltip on hover, glance marks/max chips, outside-click dismiss, tag round-trip).

### 4.14 Timetable edit history (audit log)

Sits inside `#tab-timetable-view` under the Edit button: a §4.9 accordion (`collapse collapse-arrow bg-base-200 border border-base-300 mt-4`) whose title is `text-sm font-semibold` + a `badge badge-sm` count fed by `/api/timetable/history`. Rows are `py-2 border-b border-base-300 last:border-b-0`, kept terse on purpose: a flex head — name `text-sm font-medium` + mono netid `/60` left, **relative** time `text-xs /60` right (`title=` carries the absolute timestamp) — over change lines `text-xs /60 space-y-0.5` formatted `Mon P3: CS2011 → CS3005` (`+CODE` added, `-CODE` removed; full subject names live in `title=`, never inline). Empty state `text-base-content/60`.

- **XSS rule (audit 2026-09-27 applies here too):** every value in the payload (peer-written subject codes/names, editor name) is student-controlled — `loadHistory()` in `timetable.js` builds it with `textContent`/`createElement` only, **never `innerHTML`**.
- Server: `_tt_diff()` in `app.py` writes `timetable_edit_log` (migration v9) on POST `/api/timetable`; no-op saves are skipped, last 200 entries per group kept.

### 4.15 Attendance meter row (Subjects tab)

Replaces the old status-card grid + overall hero (§4.3/§4.4 are **retired for attendance**). One primitive per subject, all subjects in ONE `bg-base-200 border border-base-300 rounded-box p-4` card under an `h1` "Subjects" + a right-aligned two-icon view toggle (2026-10/v1.15.0: a real segmented control — `join` of `btn btn-sm btn-square` with `btn-active` on the pressed side, bordered base-200 buttons so the control reads as a control; bar-chart = graph view, clean 3-column grid icon = the plain-rows table; `aria-pressed` + `title` on both; choice persists in `localStorage.attView`; visibility via the `hidden` attribute only). Risk-first (lowest % first — server already sorts). The portal's `CL` / "CLASS IN CHARGE" row is LISTED like any subject (2026-10: students asked to see it; its hours are in the portal's own Total row — 7 subjects 289 + CL 5 = 294). It stays out of the Estimates card on its own: absent from the timetable → `w=0` → both budgets `None`. The numbers, not a sentence, carry the answer to "can I skip?".

Two label rows sandwich the meter (2026-10/v1.15.0): the **class-count line ABOVE** (`pnums`, unchanged) and the **percentage scale BELOW** (`pcts`: `0%` @0 · `75%` @tick — threshold marks only; the current % is the header `mpct` figure, `100` is the bar's end, both redundant under the bar). Splitting the two lines is what keeps the margin number and the % text from overlapping.

```html
<div class="mrow <!--nudge: nudL|nudR|nud2L|nud2R when |fill−75|<9%/<3%; pole band (dpol<9) takes NO nudge, see cluster below -->">
  <div class="mtop"><span class="mname">Course description</span><span class="mpct">62.00%</span></div>
  <div class="pnums"><span class="pn pn-now" style="left:62.0%">31</span>
    <span class="pn pn-75" style="left:75%">38</span><span class="pn pn-tot">50</span></div>
  <div class="meter" role="img" aria-label="Course, 62 percent attended, needs 26 for 75 percent">
    <i class="mz mz--red" style="width:62.0%"></i>   <!-- fill = EXACT 100·A/C, never rounded pct -->
    <i class="mhatch" style="left:62.0%;width:13.0%"></i>
    <i class="mtick"></i>                            <!-- fixed at left:75%, white -->
  </div>
  <div class="pcts"><span class="pct pct-0">0%</span><span class="pct pct-75" style="left:75%">75%</span></div>
  <div class="pconn"><i style="left:62.0%;width:13.0%"></i><span style="left:68.5%">26</span></div>
</div>
```

- **Meter grid:** `.mrows` is `repeat(auto-fit, minmax(280px, 1fr))` — bar width stays in a 270–345px band at every viewport; the old hard `min-width:768px` flip snapped bars from 650px to 345px at one pixel (the "75% mark changes width with screen size" report).
- **Pole collisions (number row only):** within 9% of the pole the row renders ONE right-anchored `attended / total` cluster (`pn-tot` carries both) with `pn-75` staying at the tick — `pn-now` and the nudges are dropped there. A fixed-px nudge can't pay for label width near the pole: the old `nudP`/`nud2P` still overlapped 13.5px at 119/120 (measured 393 + 1280), and the DUT's boundary seeds red-test the cluster. The % scale needs no collision handling: `0%` and `75%` are fixed marks 75 percentage points apart.

- **Header percentage is 2dp TRUNCATED, never rounded, and it is the ONE number.** SRM detains at <75%, so 74.9847% must read `74.98%` (the old `int(pct+0.5)` printed `75` — a student one class short saw a safe figure). `_course_view` truncates once, in integer space (`attended*10000//max_hours`, a `%d.%02d` string), and every consumer reads that same value: `pct_disp` (display), `pct` (sort key), `fill` tint and `bunk_line` (`74.98% → "Attend the next 1 class"`, never `"can miss 0"`). Do NOT truncate with `math.floor(x*100)` or string slicing — `7499/10000*100 == 7498.999…` loses a hundredth. Abbreviating the display to `62%` for tidiness re-introduces the exact bug this replaces.
- **Fill tint, FILL only:** `mz--red` = pct < 75 · `mz--warn` = pct ≥ 75 AND skip-now == 0 (orange rule — "one miss costs") · plain `mz` (grayscale) = comfortable. Track stays `--color-base-300` always. **Values are the faint approved-mockup tints — `oklch(58% 0.115 25)` / `oklch(63% 0.115 68)`** — NOT the `--color-error`/`--color-warning` theme tokens: those are full-saturation and pull the eye (attention review R1; the timetable `.tt-tag` warn/danger tiers are the dark-surface exception — see §4.11).
- **Pinned numbers:** attended @fill%, `ceil(0.75·C)` @75% (38 when C=50), total @right pole. `pnums`/`pconn` alphas are ladder steps only (50%/60% via `color-mix`); the connector's action number is `base-content` (100%) punched out on `base-200`.
- **Connector line** spans fill↔tick and carries the BARE action count (must-attend below 75, skippable above) — no words under the bar; the aria-label carries the sentence for screen readers (never "X of Y classes"). Renders **only when the count > 0** (review R3): a lone "0" on a hairline read as a bug; the orange fill already carries zero-margin.
- **Nudges** (±6px <9%, ±14px <3%) separate the `pn-now`/`pn-75` labels near the tick; they nudge AWAY from each other (`nudL`/`nud2L` when fill < 75, `nudR`/`nud2R` when fill > 75).
- **Degrade, never fake:** C=0 → no meter at all (row skipped); w=0 → budgets hidden from Estimates; no exams → Estimates endsem column `--`; unmatched/custom in the timetable → neutral "no data", NEVER a numeric 0%.
- **CSS lives in `app/static/timetable.css`** under the `/* ── Attendance meter row */` banner — every color a `var(--color-*)` token or `color-mix` ladder step; no badges, no uppercase, no gradients (the hatch is the one sanctioned pattern), one divider style, labels ≤3 words, no sentence over 8 words.
- **Estimates + Absences cards** (quiet): `.att-h` heading + `.att-n` note ("can skip: 90 working days (excl. Sat/Sun) · till {stop} (day before first endsem)" — dates derived from `_exam_stop`, never hardcoded), a `qgrid` (Subject | 90 days · N left | till D · N left) of semester budgets, and ONE merged Absences card (2026-10, v1.13.0): one `.att-month` block per month — the monthly attendance `progress` bar with that month's absence chips (`date · Nh`, `badge badge-soft badge-sm font-mono`) wrapped directly beneath it; the old standalone "Monthly breakdown" `<details>` is gone (its rows ARE the card). `date · hours` ONLY still — no subject column (daily_absent rows carry none). Months with a drill-down but no cumulative row degrade to a chip-only block.
- **Attention budget:** the meter row is attention-budget-compliant by construction — grayscale default, hue only on the fill of a deviation, numbers neutral, no aggregate anywhere (no overall %, no overall bunk line, no summed totals).

Timetable glance: **superseded in v2.7.0** — the 2px `.tt-riskbar` left rim and the `.tt-sig` number block became the single inline `.tt-tag` in the row's subline (number + word together, three tiers: neutral comfortable / warn zero-margin / danger must-attend). The hero is an icon disc plus a 16px Title-Case subject and a 12px subline carrying the code, the time and the skip phrase; there is no `tt-hero-num` stat and no left rim any more. Unmatched/custom slots render a neutral `tt-tag--none` reading "no data". Subject names are Title-Cased at render (`_title_case`: ALL-CAPS portal names only; custom mixed-case names untouched; join keys still go through `_norm_subject`).

### 4.16 Teachers card (dashboard home, faculty map)

> 2026-10/v1.16.0: the card renders through the §4.17 engine as its `teachers` widget (`.wlabel` header, `.wbox`, subject subheads, initials avatars, mode tags, `.widget-scroll` list). The `#fb-cta` button, the `#fb-modal` opt-in flow, and the plan builder below are unchanged; the old `bg-base-300/40 … p-4 sm:col-span-2` shell and the parenthesised `(Theory)/(Practical)` labels are superseded by §4.17.

Anatomy — copied from the end-sem card (§4.12): `bg-base-300/40 border border-base-300 rounded-box p-4 sm:col-span-2`; header row = `text-[11px] uppercase tracking-wider text-base-content/50` "Teachers" + one `badge-outline badge-sm` count badge; rows = subject name (`text-sm font-semibold`, title-cased) over the staff line (`text-xs text-base-content/60`, names title-cased, kind labels `(Theory)/(Practical)` at `/50` — `/40` measured 3.83:1 and fails WCAG at 12px); optional `font-mono text-xs` code chip right. Source footnote `text-xs text-base-content/70 mt-2` "From the mid-sem feedback form". Below it, when a plan exists, the *Auto-fill mid-sem feedback* CTA (`btn btn-sm btn-primary min-h-11`, 21:1) opens the opt-in explainer modal `<dialog id="fb-modal">` (daisyUI modal, same pattern as add-subject): an "Opt-in — nothing is submitted until you confirm" line, a 3-step mechanics list (every teacher gets their own form — one portal form per teacher within a subject; 5 = EXCELLENT on all 14 questions; comment "none"; live re-verify with honest skips), then the exact PER-TEACHER plan rows (subject `text-xs font-semibold` over `teacher · 5 = EXCELLENT … · comment “none”` at `/70`, `max-h-48` scrollable). The modal's *Fill feedback for N teachers* `btn btn-sm btn-primary min-h-11` is the ONLY element that writes feedback to the portal (sync harvests read-only); result line `#fb-status` inside the modal uses `text-success`/`text-error`, never color alone (counts in text), and hard failures also fire the global `#error-toast`. A `badge-neutral` "new" badge on the CTA was tried and dropped — it measured 1.35:1 on the primary button. Empty map (`{}`) -> the whole card is omitted (no empty-state block — same pattern as §4.12). Card rows live in `_faculty_view()` (app.py); the map is harvested server-side (mid-sem feedback form), never user-edited; the preview and `POST /api/feedback/fill` share ONE plan builder (`_fb_plan()`) so what the student saw IS what gets sent.

### 4.17 Dashboard card/widget engine (v1.16.0)

The Dashboard tab is generated, not hand-written. Three constants drive it: **`LAYOUT`** (card registry) and **`WIDGETS`** (id → partial + `min_w`) live in `app/views/layout.py`, **`NOTICES`** (release notices, newest first) in `app/app.py` — all three are re-exported by `app.app`. Widget partials live in `app/templates/partials/widgets/*.html`.

Engine invariants — each is a check in `tests/unit/test_layout.py`:

- **Every widget partial owns its own `.wlabel` + `.wbox`, and renders NOTHING when its data is empty.** Empty = hidden: no empty-state sentence, no placeholder (same rule as §4.12/§4.16).
- **Unknown widget ids render nothing and never 500.**
- **`when` filter:** a `LAYOUT` entry may carry `when` = a list of route-context variable names; if ALL are falsy the whole card is dropped (no orphan shells). No `when` → the card always renders.
- **`min_w` contracts** recorded per widget in `WIDGETS` (measured plateaus, px): profile 250 · today 260 · week 250 · notices 300 · marks 560 · exams 560 · attendance 300 · teachers 358.

**Grid:** `grid grid-cols-1 lg:grid-cols-12 gap-6`, and on `lg` the grid **fits the viewport exactly**: `lg:h-[calc(100dvh-104px)] lg:grid-rows-[minmax(0,auto)_minmax(0,1fr)]` — 104px = navbar (64) + main `py-5` (20+20); row 1 (marks+exams) hugs its content and row 2 (attendance+teachers) takes the rest (`1fr`), so desktop shows **no page scrollbar** at standard heights while cards stretch to fill. Row 1's hug is **capped at 65% of the grid via the card, not the track**: the assess card carries `LAYOUT["cap"]` → `lg:max-h-[calc((100dvh-104px)*0.65)]`, because max-height on the (scrollable) card-body clamps the track contribution without touching normal content — stress (14-exam load) had an uncapped `auto` row 1 size to 640px at 1024×768 and **crush row 2 to 2px** (people card gone; 41px at 1440×900). %-sized row tracks are NOT the fix: the maximize-tracks step **stretches** them to their limit (a `minmax(0,65%)` row 1 ate 65% even under normal data and starved row 2 — measured 2/20 dash_fit red). Capped, row 1 = 432/664 at 1024×768 under full load, row 2 keeps ≥35%−26px (164px at 1366×640, the smallest desktop tested). Normal data (row 1 ≈ 287px) never reaches the cap. Residue (a longer exam list, a heavy day column) scrolls INSIDE the card: cards get `lg:overflow-hidden`, `card-body` gets `lg:min-h-0 lg:overflow-y-auto`. Equal `1fr` rows were rejected by measurement: row 2 starved by 93px while row 1 idled with 100px of slack at 1280×900. **The 104px is a pinned literal**: if the navbar or main padding ever changes height, `tests/e2e/test_dash_fit.py` fails on `gridH == innerH − navH − padTop − padB` before anyone notices a drifting gap (its red run: gridH=754 vs expected=796). Mobile (<lg) keeps natural stacked flow — page scrolling on a phone is intended, and `test_dash_fit` pins that too (`scrollHeight > clientHeight` at 393). The 24px gutter is the top of the ranked gap ladder (§5). `LAYOUT` spans: **day** = `span 4` + `row_span 2` (profile, today, week, notices) · **assess** = `span 8` (marks, exams) · **people** = `span 8` (attendance, teachers). A `LAYOUT` entry may carry **`cols: 2`** — that card's widget row is then a two-up grid (`grid-cols-1 sm:grid-cols-2 gap-3`, so it collapses to a stack below `sm`); the people card uses it (attendance | teachers side-by-side), cards without it stack their widgets vertically. Card shell is §4.1 with `card-body p-4 gap-3`, so the dashboard's tiers read **8 (label gap) < 12 (widget gap) < 16 (card pad) < 24 (grid gutter)**.

**Where the CSS lives:** the widget rules ship in `dashboard.html`'s inline `<style>` block (`style-src 'unsafe-inline'`, §10.2). Inline styles travel with the HTML, so these rules need no `CACHE_NAME` bump.

Recipes (approved mockup values, computed — not eyeballed):

```css
.wbox     { background: color-mix(in oklab, var(--color-base-300) 60%, transparent);
            border-radius: var(--radius-box); }   /* sits on the bg-base-200 card, one level down (§2.3) */
.wlabel   { font-size: 11px; line-height: 1.5; margin-bottom: 8px;
            text-transform: uppercase; letter-spacing: .05em;
            color: color-mix(in oklab, var(--color-base-content) 60%, transparent); }  /* 12.9:1 on the card */
.att-neg  { color: color-mix(in oklab, var(--color-error) 70%, white); }                /* 8.06:1 on the widget fill */
```

- **`.att-neg` is the only alert hue allowed on a widget surface.** Plain `error` on the widget fill measured **2.67:1 — FAIL**; error + 30% white measures 8.06:1. Same trap on badges: solid `badge badge-warning badge-xs` measured **2.79:1** at 10px (needs 4.5:1) and failed the marks DUT contrast sweep, so the notices "New" chip is `badge-soft badge-success` (§2.8 applies unchanged).
- **`.widget-scroll`** is the universal scroll box: `max-height: 320px; overflow-y: auto` plus a thin 6px scrollbar, thumb `color-mix(base-content 25% transparent)`, radius `9999px`. Anything expected to outgrow the card goes in it — never let a widget stretch the row. Currently wraps the **teachers list, the attendance glance list, and the notices list** (v1.19.0 added the last two: five release notices and a long subject list both outgrew the fixed-fit rows).

**The widgets:**

- **profile** — `.wbox` only, **NO `.wlabel`**: the identity is its own label. Blobatar `w-11 h-11` (44px) · name `text-sm font-semibold` · copy-email button `#copyEmail` `text-xs font-mono /70` · reg no `text-xs font-mono /50`, click-to-copy.
- **today** — a class ticker, three rows. **prev:** faded (`h-7 opacity-50`), start `text-xs font-mono tabular-nums` + code `text-xs`. **bright:** start **22px `font-bold font-mono tabular-nums`** + code `text-sm font-bold` + end time `text-xs /50` appended AFTER the code — white → white → grey on purpose, the end time is deliberately unimportant — with the subject name `text-xs /60` below. **next:** same shape as prev, faded. States: `now` (class running) · `up` (break / before first — the bright row is the *upcoming* class) · `done` (faded last row + `All done for today` `text-xs /50`) · no timetable day → hidden. **v1 renders statically**: event-driven one-shot promotion is explicitly deferred, and the ticker added **no new motion** — §7 rules stand as written.
- **week** — headline `text-sm` `N days absent · H hrs lost`; per-day `badge badge-soft badge-warning badge-sm font-mono` chips with `title=` carrying the hours; empty text `No absences this week`.
- **marks** — chips `badge badge-soft badge-sm font-mono tabular-nums` with inner spans: code `text-base-content/70` + score `scored/max font-medium`. Stale entries keep `opacity-60` + a `title` explainer (never colour alone). **No `%`, no overall number** — §4.13's glance rules hold here.
- **exams** — header row: LEFT = `End sem exams` 11px `/60` + `badge badge-soft badge-sm` label + `badge badge-outline badge-sm text-base-content/60` source; RIGHT = countdown `First exam in N days` `text-xs /70`. The countdown lives **in the header** — the old footer countdown div is gone. Rows keep §4.12's dual mobile/desktop markup, divided `py-2 border-t border-base-300 first:border-t-0 first:pt-0`.
- **attendance** — a can-skip glance, list inside `.widget-scroll` (the fixed-fit grid must not stretch it). Header: `Attendance` `.wlabel` + `can skip` 11px `/50` right. Rows: code `w-20 font-mono text-xs text-base-content/60`, value right-aligned mono — neutral skip count = `text-sm tabular-nums base-content`; at-risk value = `.att-neg text-xs` (`attend N` below 75%, `0` exactly at the limit). Row order = courses order = pct-ascending = risk-first. Values are the **same `_bunk_counts` numbers the attendance tab shows** (single source — the glance can never disagree with the page), and rows with `(None, None)` (nothing held) are dropped, never faked as 0. No attendance *detail* is duplicated here; that belongs to §4.15.
- **teachers** — subject-grouped list inside `.widget-scroll` (the grouping IS the view; no toggle in v1). Subject subhead = code `font-mono text-xs /60` + name `text-xs /80`; staff row = initials avatar `grid size-6 rounded-full bg-base-300 font-mono text-[10px] text-base-content/70` (honorific stripped: `Dr.Priyanka Gupta` → `PG`) + name `text-sm truncate` + mode tag `Theory`/`Practical` (parsed from the portal's `Name-Mode` suffix) `font-mono text-xs /50` right-aligned. Caption `From the mid-sem feedback form` `text-xs /70` + the `#fb-cta` primary button below the scroll box — the opt-in flow of §4.16 is untouched. **v1.19.0: the CTA + `#fb-modal` render only while the portal's feedback window is open** (`fb_open` on the users row, learned by each cold sync from the portal's own `Service closed` marker; closed → both disappear, the list stays, the next sync that finds the window open brings them back; `POST /api/feedback/fill` answers 409 without contacting the portal). Pinned by `tests/e2e/test_dash_fit.py` + `tests/unit/test_feedback.py`.
- **notices** — `.wlabel` + list in `.widget-scroll`, same dividers. The head entry only carries `New` = `badge badge-soft badge-success badge-xs font-mono` (see the contrast note above). Entries: version `font-mono text-xs /60` + date `text-xs /50`, title `text-sm font-semibold`, body `text-xs /70`. v1 has no dismissal (localStorage dismissal deferred). `NOTICES` is newest-first and holds real release notes; **a notice for the current release is mandatory** — test_audit_findings `M27` fails the build when the head entry's version stops equaling `VERSION` (v1.19.0 backfilled v1.18.0/v1.17.0 too).

**Tests:** `tests/unit/test_layout.py` — 25 source-level checks (LAYOUT spans, WIDGETS partial existence, `min_w`, `when` filter, unknown-id safety, budget-row derivation, teacher initials/mode, ticker states on a fake clock, CSS block presence, empty=hidden at card level). Run it as its own row in the test matrix:

```bash
DATA_DIR=/tmp/osrm-layout .venv/bin/python tests/unit/test_layout.py
```

### 4.18 Academics tab (SCOPE, v1.29.0)

`academics_view()` (`app/views/academics.py`) builds the tab from `users.scope_json`; `index()` passes it as `academics`, and **None means zero footprint** — no navbar button, no dock button, no panel (feature off via `SCOPE_FEATURES`, no academics ops stored, or every section empty). Four self-hiding cards in ONE `max-w-3xl mx-auto` panel stacked with `flex flex-col gap-3`:

- **Results** — §4.12 row anatomy: a `font-mono text-xs /60` monthyear header with the semester caption right, then rows of title-cased name over `font-mono text-xs /60` code. **Title spans WRAP, never `truncate`**: the measured probe found 16 clipped names at 393px (`truncate` + no hover = unreadable on touch). Grade chip = `badge badge-soft badge-sm font-mono min-w-9 justify-center`; result = `badge badge-outline badge-sm text-base-content/60` "Pass" (quiet — the loud-object budget keeps the CGPA figure as the tab's only accent). An **F grade is error TEXT, never a colored chip**: `.res-fail` (dashboard.html style block) = `color-mix(in oklab, var(--color-error) 70%, white)` — the §4.17 `.att-neg` recipe, because plain `--color-error` measures 4.1:1 on `base-200` (§2.8) — next to a solid `badge-error badge-sm text-base-content` "Fail" so the hue is never the only cue. Provisional/Revaluation subsections (`{Status, Message, Data}` envelopes) render only when `Data` is non-empty (alive-empty = the subsection does not exist).
- **Hero** — the tab's ONE loud figure: `font-mono font-bold text-[22px] tabular-nums` (the §4.17 ticker's hero size, no new scale step), label `CGPA (est.)` carrying the tooltip "credit-weighted from released results; est. = scale not officially published" (never presented as official — the SRM scale is unpublished), `N/163 credits earned` under it, and per-monthyear SGPA rows under a divider, newest first. Freshness reuses `.sync-line` fed with `scope_fetched_at` (relative age, hidden while fresh — the navbar's caption pattern).
- **Credits** — the SAME §4.15 `.meter` + `.mz` bar (never a new bar): **neutral fill always, `background:var(--color-success)` only at ≥100% complete** — deliberately no attendance thresholds (DESIGN §2.6 stays on the attendance tab; a finished credit category is a fact), with `acq/req` in mono beside every bar and a footer `Overall … · Semester N …` (latest semester = the newest one that actually earned credits, never the future 0/N plan row).
- **Subjects** — the program completion grid as a LIST inside the shared `.widget-scroll` box: category subheads `text-sm font-semibold`, completed rows show the soft grade chip + month (+ a quiet `· N attempts` note when attempts > 1), pending rows keep the portal's `-` at `text-base-content/50` with a `title`.

Pinned by `tests/test_scope_academics.py` (CGPA math incl. ROUND_HALF_UP vs banker's, parsers, envelope sections, the zero-footprint gate) and by the PR's measured evidence: contrast probe 0 fails (141 text/bg pairs at 393×851 and 1280×900), geometry (4 cards, one column x/width, uniform 12px gaps, no horizontal overflow).

---

## 5. Layout and responsive

- **Mobile-first single column.** `<main>` is `px-2 lg:px-4 py-5 pb-24 lg:pb-5` (`pb-24` clears the fixed dock; `lg:pb-5` on desktop). `max-w-3xl mx-auto` is **not** on `main` — it moved onto each of the four non-dashboard tabpanels (attendance, timetable, marks, personal), so only the Dashboard tab renders full-width (§4.17). The gutter is **8px below `lg`** because the mobile navbar's own content padding is 8px — the card column then lines up with the logo/icons above it, and the column gains 16px of width on a 393px phone; at `lg` the desktop navbar takes `px-4`, so the gutter steps back to 16px and stays aligned. Both breakpoints keep a real gutter (never `px-0`). Login is a centered card, `w-full max-w-md`, on `min-h-[100dvh]`.
- **Rhythm (the 4px scale, in use):** `gap-2` / `gap-3` inside and between cards · `gap-6` (24px) between Dashboard grid cards (§4.17) · `mb-5` between blocks · card padding `p-4` (`p-5` for the hero, `p-0` for list cards). Don't introduce new spacing values.
- **Vertical gaps are RANKED by relationship, never uniform** (Gestalt proximity — equal gaps everywhere give consistency without hierarchy). Same 4px scale, ordered tight → loose: **0** attached (a field and its own hint/error) → **`gap-2` 8px** feedback that reports on one element (status under its button) → **`gap-3` 12px** peers inside a group (field ↔ field) → **group break**, sized per card **and stepped, never pinned**: `mb-5` 20px between content blocks — and in the login card the two group breaks (the brand band, and password → Sign in = 16px reserved Caps row + the button's margin) step *together* with the card's own `p-6 sm:p-8` padding: **24px below `sm`, 36px at `sm`+ — equal to each other at every breakpoint** (same idea as daisyUI's `--card-p`, a token that resizes instead of a fixed pixel) → **section break**, looser than every group break (login card: 40px whitespace + rule + `pt-3`). A card must show ≥3 of these tiers in order. Horizontal gutters stay uniform — the column is one unit — and card padding must stay larger than the gaps inside it. On the Dashboard grid the tiers read **8 (`.wlabel` margin) < 12 (`gap-3` widget gap) < 16 (`p-4` card pad) < 24 (`gap-6` grid gutter)** — §4.17. Worked example: the login card, audited at 390/768/1280 as **0 < 8 < 12 < 24|36 < 40** (the `24|36` tier is the adaptive one).
- **Section headings:** `text-base font-semibold mb-3`.
- **Breakpoints:** design at 375px first. `sm` (640) switches the course grid to 2 columns and reveals the "Refresh" label. `lg` (1024) goes to 3 columns and flips the Dashboard to `grid-cols-12` (§4.17). No content column grows past `max-w-3xl` — the Dashboard tab is the one full-width exception; every other tabpanel keeps `max-w-3xl mx-auto`.
- **Touch targets ≥ 44px** for anything a thumb must hit (README requirement). `btn` is 40px and `btn-sm` 32px, which is acceptable for toolbar actions only; use `btn-lg` (48px) or `min-h-11` for main actions and tappable rows.
- **Safe areas:** the viewport meta includes `viewport-fit=cover`. The sticky navbar pads with `env(safe-area-inset-top)`; anything fixed to the bottom needs `env(safe-area-inset-bottom)`.
- **Viewport height:** `min-h-[100dvh]`, never `100vh`.
- **Overflow:** wide content (tables, the timetable grid) scrolls inside its own `overflow-x-auto` wrapper. The page itself never scrolls sideways.
- Timetable editor: days are rows, times are columns; cells are ≥ 44px tall.

---

## 6. Depth and elevation

| Level | What | Treatment |
|---|---|---|
| 0 | Page | `bg-base-100` |
| 1 | Container | `bg-base-200` + `border border-base-300`. **No shadow** |
| 2 | Modal | `modal-box` `bg-base-200` + border; daisyUI dims the page behind it |

- `--depth: 1` gives buttons and inputs a faint 6%-white top highlight. On a black button that highlight is the only edge it has. Leave it alone.
- The login card's `shadow-xl` is the **only** shadow in the app: it is the one floating object on an empty page. Don't add others.
- Banned: gradients, glows, `backdrop-blur`, glassmorphism, colored shadows, `hover:scale-*`, `hover:-translate-y-*`, decorative dividers.

---

## 7. States and motion

| State | Rule |
|---|---|
| Focus | Always visible. Inputs keep daisyUI's white ring. `btn-primary` needs `focus-visible:outline-accent`. Never `outline-none` without a replacement |
| Hover | Black/ghost buttons: `hover:bg-base-300`. Clickable rows: `hover:bg-base-300/50`. No lift, scale, or shadow |
| Disabled | The native `disabled` attribute (daisyUI dims it) |
| Loading | Disable the button, switch the label to the progressive form ("Signing in…"), show `loading loading-spinner loading-sm` inside it. Page-level waits use the modal in §4.8 |
| Offline | Bottom `alert-soft alert-warning` banner with one plain sentence |
| Error | A `text-sm text-error` sentence under the form naming what happened and what to try, plus `input-error` on the field at fault |
| Empty | One sentence and the next step, in an `alert alert-soft alert-info`. No illustrations |

**Motion** happens only in response to something the person did: the spinner and `animate-spin` on the refresh icon, a ≤ 200ms border/background transition on drag-and-drop targets. No entrance animations, scroll reveals, parallax, or looping decoration. Add `motion-reduce:animate-none` to anything that spins or pulses.

**Interactive motion** (smoothness campaign, still action-triggered — never on load): a press feedback `scale(.97)` on `:active`; a tab-switch cross-fade up to 220 ms; a sheet/dialog slide up to 320 ms; the pull-to-refresh indicator. All animate **`transform` and `opacity` only** (never `width`/`height`/`top`/`left`/`margin`/`box-shadow`/`filter`), are **interruptible** (a new tap cancels the in-flight one), use the shared easing tokens (`--ease-out`, `--ease-spring`), and are **disabled under `prefers-reduced-motion`**. Hover lift/scale and entrance-on-load animation remain forbidden.

**Avatar rule.** The blobatar's looping idle animation is paused (never removed — the pose is preserved) when scrolled offscreen, on any device whose `data-perf="low"` tier is detected, and while the tab is hidden. Pausing is what keeps an always-on animation from eating a weak phone's attention and battery.

**Page-level refresh rule (§4.8).** A data refresh no longer opens a blocking modal: the refresh icon spins and content updates in place — no flash, scroll position holds, the refresh is interruptible. The modal pattern remains for confirmations and opt-in explainers (§4.8).

---

## 8. Copy

- Plain, direct, second person, sentence case. Say what will happen. One verb per action across the whole flow: **Refresh** → "Refreshing attendance…" → the caption `(5m ago)` beside the button, and nothing at all while the data is younger than 5 minutes.
- Data lines are actionable, not decorative. On the Subjects tab the §4.15 numbers carry this ("26" on the connector = attend 26 in a row); where a sentence is still rendered (`_bunk_line`), it stays "Can miss 3 more classes and stay above 75%" / "Attend the next 2 classes in a row to reach 75%". The UI says "miss", never "bunk".
- Errors name what happened and what to try: "Network error — is the server reachable?". No apologies, no exclamation marks, no emoji, no blame.
- Empty states: one sentence plus the next step ("Your group has no timetable. Use the editor to build one.").
- Spell things the way people know them: NetID, Log out, Attendance, Timetable, Personal details.

---

## 9. Do and don't

| Don't | Do |
|---|---|
| `bg-black`, `bg-gray-900`, `bg-zinc-800`, `#111` | `bg-base-200` / `bg-base-300` |
| `text-white`, `text-gray-400`, `opacity-60` on text | `text-base-content`, `/60`, `/50` |
| A `bg-base-100` card on the `bg-base-100` page | `bg-base-200 border border-base-300` |
| Any `*-primary` for emphasis, focus, links, progress | `accent`, `base-content`, or a status token |
| Gradient heroes, glowing buttons, blur, glass | Flat fills and 1px borders |
| `shadow-md`, `shadow-lg`, colored shadows | `border border-base-300` |
| `rounded-2xl` / `rounded-3xl`, mixed radii | `rounded-box` (containers), `rounded-field` (controls), `rounded-full` (pills, dots, avatars) |
| success/warning/error as decoration, or for "primary action" | Only for status, confirm, and destructive meaning |
| Color-coding subjects or courses by hue | Mono code, position, label |
| Pink for status, links, or buttons | Leave it out; if it earns a place, one badge per screen |
| Light mode, `dark:` variants, theme switching | The single `openSRM` theme |
| Emoji, icon fonts, icon CDNs, remote images | Inline SVG |
| Eyebrow labels above every heading, ALL CAPS everywhere, centered data | Sentence case, left aligned; uppercase only for Personal Details labels and dashboard `.wlabel`s (§4.17) |
| Entrance animations, scroll reveals, hover lift | Motion only in response to an action |
| Animating `width`/`height`/`top`/`left`/`margin`/`box-shadow`/`filter` | Animate `transform` and `opacity` only |
| Full-page reload to show new data | Update the changed parts in place |
| Runtime CSS build (CDN Tailwind), un-hashed static assets | Pre-compiled `app.css`, versioned (`?v=`) immutable assets |
| A looping animation that never stops | Pause it offscreen, on low-tier devices, and when hidden |
| `input-bordered`, `form-control`, `label-text` (daisyUI 4) | `fieldset`, `floating-label`, `input`, `label` |
| `alert()` / `prompt()` in new flows | `modal` or an inline `alert` |
| New component shapes or spacing values | The recipes in §4 and the spacing in §5 |

---

## 10. Implementation constraints (silent-failure list)

1. **CSS is compiled ahead of time, never at runtime.** `app/static/src.css` is the entry (Tailwind `@import`, the daisyUI `@plugin`, `@source` pointing at templates/views/safelist, then the hand-written sheets); `scripts/build-css.sh` compiles it with a version-pinned, sha256-verified Tailwind standalone CLI + daisyUI release into the committed `app/static/app.css`. There is no runtime CDN, no `tailwind.config.js`, and no `node_modules` in the runtime image — the build runs only on a developer machine or CI. Classes written in Jinja are picked up by the scanner **only if they appear literally in a scanned file**; families assembled at render time (grid spans, progress colors) live in `app/static/safelist/classes.html`. A CI check re-builds `app.css` and fails on `git diff --exit-code`, so the committed file can never go stale. `test_audit_findings` L47 pins the compiled build.
2. **Strict CSP** (`_security_headers()` in `app/app.py`): `default-src 'self'`; scripts from `'self'` only, so **no inline `<script>`**; styles from `'self'` and `'unsafe-inline'` (the compiled `app.css` plus inline style attributes); images from `'self'` and `data:` only; no `font-src`, so fonts fall back to `'self'`. No third-party origin remains in the CSP — the jsDelivr entries left with the runtime CDN. Consequences: no Google Fonts, no icon libraries, no other CDNs, no remote images. JavaScript goes in `app/static/*.js`. To add a font, self-host it under `app/static/` and add it to the service worker's precache.
3. **Service worker** (`app/static/sw.js`): HTML = network-first with navigation preload (offline gets the generic no-account page); **versioned assets (`?v=` from `asset()`) = cache-first** — the content hash means the bytes under a URL never change, so warm visits move zero CSS/JS bytes and a deploy is picked up through the new hash, not cache expiry; unversioned statics (icons, manifest) = network-first with cache fallback. If you edit anything under `app/static/`, bump `CACHE_NAME` (`opensrm-v14` → `opensrm-v15`) or installed PWAs keep serving the old file. Inline `<style>` in templates ships with the HTML and updates immediately.
4. **The theme ships once** in `app/templates/partials/theme.html` (included by both pages). Change it there, and Appendix A.
5. **Hand-written CSS uses variables, never hex:** `var(--color-base-200)`; tints via `color-mix(in oklab, var(--color-success) 8%, transparent)`.
6. **PWA chrome** (`<meta name="theme-color">`, `manifest.json` `background_color` / `theme_color`, the service worker's offline page) uses `#111111` from the logo. Leave it unless asked. These are the only places hex is acceptable; take values from §2.2.
7. **HTML built in Python or JS** (`timetable_html()`, `timetable.js`) uses the same tokens and classes as the templates, and must escape any interpolated data.
8. Python changes must pass `ruff` (CI lint).
9. **daisyUI wins inside its own components.** Measured on this build: `text-base-content` — even with `!important` — does **not** override `.badge-info`'s color (the cascade is unchanged; the stylesheet is same-origin so its rules ARE readable from `cssRules` — the old CDN load without `crossorigin` hid them behind a SecurityError). To restyle badge text, use another badge variant or hand-rolled span; never rely on a utility override.
10. **Only the documented opacity steps render** (§2.5: `/40 /50 /60 /70 /90`). Measured: `text-base-content/55` silently rendered at full opacity while `/50` and `/60` applied. Stick to the ladder — arbitrary steps may not ship.
11. **Two ways daisyUI's dock/active styling reaches the navbar tabs.** (a) **daisyUI's "active" fill is invisible on this surface:** `.btn-active` / `[aria-pressed]` / `[aria-current]` all set `--btn-bg: color-mix(in oklab, var(--color-base-200), #000 5%)` = `#090909` — byte-identical to the navbar, because `base-200` is already near-black. Measured: a selected navbar tab sat at **1.000:1** against the bar it lives in. On this theme "active" has to *lighten*: use a `base-content` tint (§4.9) and measure the selected/unselected pair before shipping; never trust daisyUI's default active/pressed state. (b) **`.dock-active:after{width:2.5rem}` also matches navbar tabs**, because `dash.js` toggles `dock-active` on every `[data-tab]` — so a `::after` indicator that declares `left`/`right` but not `width` renders at the leaked 40px (measured left 8 / right 41 inside an 89px pill) instead of its own insets. Declare `width: auto` in the rule that owns the bar; `test_navbar` asserts bar width == pill − 16.
12. **A closed `<details>` still reports a layout rect for its hidden children** (Chrome lays them out via `content-visibility`), so a geometry audit that measures "card height vs deepest descendant" counts the hidden tag form (§4.13) and reports phantom negative slack. Filter measurement sweeps with `!el.closest('details:not([open])')`.
13. **daisyUI 5.7 emits opacity-modified tokens as `oklab(L a b / alpha)`** (Lab form, not LCH) — and the alpha is a DECIMAL number (`oklab(1 0 0 / 0.5)` = 50%), never a percentage. A contrast probe that divides the alpha by 100 unconditionally turns every `/60` token into 0.006 alpha and reports the whole card at ~1:1 (measured on the Teachers card, Oct 2026). `tests/e2e/test_feedback_contrast.py` holds the parser (rgb + oklch + oklab + hex, `alpha()` honoring the optional `%`); crib it for any new color sweep. Only `oklch(1 0 0)`-style full-opacity tokens parse as LCH.
14. **A tab whose content is the only panel taller than the viewport used to shift the whole navbar.** Marks is that panel (1922px vs a 900px viewport); its scrollbar appearing narrowed the layout viewport ~15px on classic-scrollbar platforms and every navbar element re-centred into it (measured headed, 1280×900: tab x 432.4 → 424.9, `navbar-end` x 847.6 → 840.1, `navW` 1280 → 1265 — and back on the next tab, i.e. a visible toggle). `html { scrollbar-gutter: stable }` in `theme.html` reserves the gutter on every tab so there is exactly one layout width (now navW=1265 on all five tabs). Overlay-scrollbar platforms (mobile) are untouched per spec — `stable` reserves nothing there, so the mobile gutter assertions in `test_navbar` still hold. Do not "fix" a per-tab shift by pinning navbar widths: the shift is a viewport-width change, not a navbar bug. `test_navbar` asserts navW is identical across a dashboard→marks→dashboard cycle.
15. **The desktop dashboard fit is a literal, not a formula.** `lg:h-[calc(100dvh-104px)]` assumes navbar 64px + `main` `py-5` (40px); change either and the grid over/under-fills by the same delta with no other symptom (page scrollbar returns, or a dead gap opens under the cards). `tests/e2e/test_dash_fit.py` pins the literal against measured chrome — `gridH == innerH − navH − padTop − padB` and bottom gap == `padB` — so a navbar/padding change fails the test instead of shipping a drifting gap (red run of v1.19.0: gridH 754 vs expected 796). Row sizing is `minmax(0,auto) minmax(0,1fr)` on purpose, each bound by a measurement: equal `1fr` rows starved the people card by 93px at 1280×900 while row 1 idled with 100px of slack, and %-capped rows got stretched to their limit by maximize-tracks (row 1 ate 65% even under normal data — dash_fit 2/20 red). The heavy-data ceiling therefore lives on the CARD: assess carries `LAYOUT["cap"]` → `lg:max-h-[calc((100dvh-104px)*0.65)]`, which clamps the track contribution — an uncapped `auto` row 1 blew up to 640px under a 14-exam stress load and crushed row 2 to 2px at 1024×768 (people card invisible, `minCard=2`). With the cap: row 1 ≤ 65% of the grid, row 2 ≥ 35%−26px on every display from 1024×768 to 3440×1440 (stress sweep green); normal data (row 1 ≈ 287px) sits far below the cap. Card residue scrolls inside the card (`lg:overflow-hidden` shell + `card-body` `lg:min-h-0 lg:overflow-y-auto`), and mobile (<lg) must keep natural page flow — the fit test asserts `scrollHeight > clientHeight` at 393 so nobody "fixes" the phone into a scrollless squeeze.

---

### 10.16 Performance rules

Front-end rules from the smoothness campaign (measured with `scripts/perf_baseline.py`, 6x CPU + Slow 4G; the committed baseline is `docs/perf/baseline.md`). The six that apply to everything written here:

1. **No runtime CDN.** CSS is compiled ahead of time with a pinned Tailwind CLI and committed as `app/static/app.css` (§10.1); runtime CDN loading is not allowed anywhere.
2. **Hashed immutable assets.** Every `/static/` CSS/JS reference goes through the `asset()` Jinja global (`?v=<content-hash>`) and is served `Cache-Control: public, max-age=31536000, immutable`; HTML and `sw.js` stay uncached.
3. **No full-page reloads for data updates.** New data updates the page in place; scroll position, focus, open panels and active tab must survive a sync.
4. **`transform`/`opacity` only** for anything animated (§7); never animate layout properties, never broad `will-change`.
5. **Pause looping animations** when offscreen, when hidden, and on the low-end tier (§7 avatar rule).
6. **Prove perf claims on a throttled machine** with `scripts/perf_baseline.py`, and report only measured numbers — a speed-up that was not measured is not a claim.

## 11. Workflow and checklist

1. **Name what you are styling by its meaning:** surface? status? action? metadata?
2. **Find its recipe** in the cheat sheet (§0) or §4. Copy the nearest existing markup instead of composing from memory.
3. **Pick color by meaning, from a token.** Check the `primary` trap (§2.4) and status-fill contrast (§2.8).
4. **Write token-only classes or variables.**
5. **Check at 375px:** no sideways page scroll, big enough targets, safe areas respected.
6. **Static or token change?** Bump `CACHE_NAME` for `app/static/*`; update both template theme blocks (and Appendix A) for a token.

Pre-flight checklist before you finish:

- [ ] No hex, `rgb()`, `oklch()`, or palette classes in my diff
- [ ] No `*-primary` except `btn-primary` with its hover/focus classes
- [ ] Every container is `bg-base-200 border border-base-300` on a `bg-base-100` page
- [ ] Status colors follow the thresholds, and each has a number, word, or icon beside it
- [ ] Text is at least `/50`; small labels on status fills follow §2.8
- [ ] No shadows, gradients, blur, hover-lift, or entrance animation added
- [ ] New motion is `transform`/`opacity` only, interruptible, and off under `prefers-reduced-motion`
- [ ] Data is in `font-mono`; copy is sentence case; errors say what to do
- [ ] No inline script, external font, icon library, remote image, or CDN-loaded CSS/JS
- [ ] `CACHE_NAME` bumped if anything in `app/static/` changed
- [ ] Templates gained new utility-class families? Added to `safelist/classes.html` + `app.css` rebuilt (§10.16)
- [ ] A data-updating flow updates in place (no full-page reload); any new listener inside `<main>` is delegated or re-run idempotently
- [ ] Looks right at 375px and 1280px, and keyboard focus is visible on every control I touched
- [ ] Dashboard engine touched: `DATA_DIR=/tmp/osrm-layout .venv/bin/python tests/unit/test_layout.py` still passes (25 checks, §4.17)

---

## 12. Known drift (do not fix as drive-bys)

Fix an item only when asked, or when you are already editing that exact rule. Then move it to the pattern in this file.

| # | Drift | Where | Target |
|---|---|---|---|
| 1 | ~~`--radius-box` mismatch~~ → **fixed**: single shared `partials/theme.html` (both pages use `0.5rem`) | — | — |
| 2 | ~~Theme tokens duplicated~~ → **fixed**: shared `partials/theme.html` include | — | — |
| 3 | ~~`timetable.css` hard-coded hex~~ → **fixed**: file uses `var(--color-*)` tokens throughout (verified: 0 hex literals) | — | — |
| 4 | ~~Timetable greens/ambers/reds as lighter Tailwind-400 tints~~ → **fixed**: now `var(--color-success/warning/error)` + `color-mix` tints | — | — |
| 5 | ~~`.tt-wrap` page-colored~~ → **fixed**: `background:var(--color-base-200)` | — | — |
| 6 | ~~daisyUI 4 classes on login~~ → **fixed** (already v5 markup) | — | — |
| 7 | ~~`IBM Plex Mono` referenced but never loaded~~ → **fixed**: file uses generic `monospace` | `timetable.css` | `font-mono` |
| 8 | ~~`/40` contrast~~ → **fixed**: all bumped to `/50` minimum | — | — |
| 9 | ~~Badge/alert contrast~~ → **already compliant**: only status badges are `badge-error` (solid, 4.4:1 ✓) and `badge-soft badge-warning` (soft ≈5.4:1 ✓), plus `alert-soft alert-warning` per §2.8 | — | — |
| 10 | ~~Native `prompt()` for Add Subject~~ → **fixed**: daisyUI `<dialog>` modal | — | — |
| 11 | ~~Invalid `.tt-today::after` content~~ → **fixed** (already `content:""`) | — | — |
| 12 | Browser chrome color `#111111` vs navbar `base-200` ≈ `#090909` | `theme-color`, `manifest.json`, `sw.js` | Leave unless asked |

---

## Appendix A. Theme source

Canonical theme, as authored in the daisyUI generator (kept here as the reference for token values; the runtime theme still ships as the plain `html[data-theme]` block in `partials/theme.html`):

```css
@plugin "daisyui/theme" {
  name: "openSRM";
  default: false;
  prefersdark: true;
  color-scheme: "dark";
  --color-base-100: oklch(20% 0 0);
  --color-base-200: oklch(14% 0 0);
  --color-base-300: oklch(26% 0 0);
  --color-base-content: oklch(100% 0 0);
  --color-primary: oklch(0% 0 0);
  --color-primary-content: oklch(100% 0 0);
  --color-secondary: oklch(65% 0.241 354.308);
  --color-secondary-content: oklch(97% 0.014 343.198);
  --color-accent: oklch(100% 0 0);
  --color-accent-content: oklch(0% 0 0);
  --color-neutral: oklch(26% 0 0);
  --color-neutral-content: oklch(98% 0 0);
  --color-info: oklch(58% 0.158 241.966);
  --color-info-content: oklch(97% 0.013 236.62);
  --color-success: oklch(76% 0.177 163.223);
  --color-success-content: oklch(98% 0.014 180.72);
  --color-warning: oklch(68% 0.162 75.834);
  --color-warning-content: oklch(98% 0.026 102.212);
  --color-error: oklch(57% 0.245 27.325);
  --color-error-content: oklch(97% 0.013 17.38);
  --radius-selector: 0.5rem;
  --radius-field: 0.5rem;
  --radius-box: 0.5rem;
  --size-selector: 0.25rem;
  --size-field: 0.25rem;
  --border: 1px;
  --depth: 1;
  --noise: 0;
}
```

Deployed form (this is what goes in each template's `<style>`):

```css
html[data-theme="openSRM"] {
  --color-base-100: oklch(20% 0 0); --color-base-200: oklch(14% 0 0);
  --color-base-300: oklch(26% 0 0); --color-base-content: oklch(100% 0 0);
  --color-primary: oklch(0% 0 0); --color-primary-content: oklch(100% 0 0);
  --color-secondary: oklch(65% 0.241 354.308); --color-secondary-content: oklch(97% 0.014 343.198);
  --color-accent: oklch(100% 0 0); --color-accent-content: oklch(0% 0 0);
  --color-neutral: oklch(26% 0 0); --color-neutral-content: oklch(98% 0 0);
  --color-info: oklch(58% 0.158 241.966); --color-info-content: oklch(97% 0.013 236.62);
  --color-success: oklch(76% 0.177 163.223); --color-success-content: oklch(98% 0.014 180.72);
  --color-warning: oklch(68% 0.162 75.834); --color-warning-content: oklch(98% 0.026 102.212);
  --color-error: oklch(57% 0.245 27.325); --color-error-content: oklch(97% 0.013 17.38);
  --radius-selector: 0.5rem; --radius-field: 0.5rem; --radius-box: 0.5rem;
  --size-selector: 0.25rem; --size-field: 0.25rem; --border: 1px; --depth: 1; --noise: 0;
  color-scheme: dark;
}
```

## Appendix B. New page skeleton

```html
<!doctype html>
<html data-theme="openSRM">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#111111">
  <title>OpenSRM</title>
  <style>/* deployed theme block from Appendix A */</style>
  <meta name="color-scheme" content="dark">
  <link rel="stylesheet" href="{{ asset('app.css') }}">   <!-- pre-compiled Tailwind+daisyUI (§10.16); never a CDN -->
</head>
<body class="bg-base-100 text-base-content">
  <div class="navbar bg-base-200 border-b border-base-300 sticky top-0 z-20 px-4 py-3"
       style="padding-top:calc(0.75rem + env(safe-area-inset-top))"> … </div>
  <main class="px-2 lg:px-4 py-5 pb-24 lg:pb-5"> … </main>   <!-- tabpanels carry their own max-w-3xl mx-auto; only Dashboard is full-width (§5) -->
  <script src="/static/your-script.js"></script>   <!-- external file only: CSP blocks inline scripts -->
</body>
</html>
```
