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
12. **No build step, strict CSP.** Tailwind and daisyUI load from the jsDelivr CDN at runtime. No inline `<script>`, no other CDNs, no web fonts. After editing anything in `app/static/`, bump `CACHE_NAME` in `sw.js` (§10).

### Cheat sheet: what am I styling?

| I'm styling… | Use |
|---|---|
| Page background | `bg-base-100 text-base-content` on `<body>` |
| Card, navbar, modal, table header, accordion | `bg-base-200 border border-base-300` |
| Divider, border, progress track, avatar bg | `border-base-300` / `bg-base-300` |
| Raised strip inside a card | `bg-base-300/50` |
| Body / heading text | inherit (`text-base-content`) |
| Description, caption | `text-base-content/60` · footnote floor `text-base-content/50` |
| Good / at-risk / bad number | `text-success` / `text-warning` / `text-error` (by threshold) |
| Status progress bar | `progress progress-success` / `-warning` / `-error` |
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
│ logo | name     [Dashboard][Attendance]…[Personal]  [Refresh] (5m ago) [Log out]
│                ← role=tab, selected = §4.9 tint     ← caption only once ≥5m old
├────────────────────────────────────────────────────┤   page: bg-base-100
│  ┌──────────────────────────────────────────────┐      max-w-3xl mx-auto px-2 lg:px-4 py-5
│  │ (82%)  Overall attendance                    │   ←  card bg-base-200 border border-base-300
│  │        Can miss 3 more classes and stay …    │
│  └──────────────────────────────────────────────┘
│  Courses                                            ←  text-base font-semibold
│  ┌────────────┐ ┌────────────┐ ┌────────────┐      ←  status color on left border only
│  └────────────┘ └────────────┘ └────────────┘
└────────────────────────────────────────────────────┘
```

---

## 2. Color

### 2.1 How the theme reaches the page

The theme is authored as a daisyUI 5 custom theme (Appendix A), but the app has **no Tailwind build**. It ships as plain CSS variables under `html[data-theme="openSRM"]` in the shared partial `app/templates/partials/theme.html`, included by both `login.html` and `dashboard.html`. Do not use `@plugin "daisyui/theme"`; it only works in a build pipeline.

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
- A raised strip inside a card is `bg-base-300/50` (see the Personal Details section headers). Nest at most two levels: page → container → sub-surface. Never card-in-card-in-card.

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

Thresholds live in `app/app.py`: `ATTENDANCE_TARGET = 0.75`, `ATTENDANCE_WARN = 0.65`; `_status_for_pct()` returns `"ok"`, `"warn"`, or `"danger"`.

| `status` | Range | Token | Note |
|---|---|---|---|
| `ok` | ≥ 75% | `success` | |
| `warn` | 65% to < 75% | `warning` | |
| `danger` | < 65% | `error` | The Python value is `danger`; the CSS token is `error` |

Template pattern, as used today (works because Tailwind runs in the browser; never build class names from user data):

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
| error | solid, default label | 4.4:1; `-soft` is weaker (≈ 3.6–4.0:1) |
| info | solid + `text-accent-content`, or soft | black 5.1:1; default 3.8:1; soft ≈ 4.0–4.5:1 |
| secondary | solid + `text-accent-content` | black 5.7:1; default 3.4:1 |

---

## 3. Typography

- **Families:** the system stack only. Default sans (Tailwind `font-sans`) for text, `font-mono` for data. There are no web fonts; the CSP blocks them (§10). `timetable.css` uses the generic `monospace` stack (an earlier `IBM Plex Mono` mention was never loaded and has been removed).
- **Scale in use:** `text-xs` 12px (meta, captions, stat rows) · `text-sm` 14px (body, values, controls) · `text-base` 16px (section headings, card titles). Nothing larger inside the dashboard. 12px is the floor for new UI.
- **Weights:** 400 body · 500 `font-medium` (field labels, status lines) · 600 `font-semibold` (section headings, names; `btn` is 600 by default) · 700 `font-bold` (percentages only).
- **Mono is for data:** course codes, percentages, times, counts, dates, NetID. Never for sentences.
- **Case:** sentence case for new copy. Uppercase micro-labels (`text-xs uppercase tracking-wide`) exist only in the Personal Details list; do not spread them. Portal data arrives in ALL CAPS, so course names are shown with `capitalize`.
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
| Tertiary / toolbar | `btn btn-ghost btn-sm` | Add `text-base-content/60` for quiet ones (Log out) |
| Confirm / save | `btn btn-success btn-sm text-accent-content` | Forces black label; the default label is 1.9:1 (§2.8) |
| Destructive | `btn btn-error btn-sm` | Pair with a confirm step |
| Icon only | `btn btn-ghost btn-sm btn-square` + `aria-label` | Inline SVG inside |

At most one solid button per row; the rest are `btn-outline` or `btn-ghost`. Labels are verb-first ("Edit timetable", "Save").

### 4.3 Status card (one per course)

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

### 4.4 Hero metric (overall attendance)

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
<dialog id="overlay" class="modal">
  <div class="modal-box bg-base-200 border border-base-300 flex flex-col items-center gap-3">
    <span class="loading loading-spinner loading-lg"></span>
    <span class="text-sm text-base-content/60">Refreshing attendance…</span>
  </div>
</dialog>
```

`modal-box` defaults to `base-100`; the app overrides it to `base-200` to match every other container. Keep that.

### 4.9 Tables, lists, accordions, tabs

```html
<!-- table -->
<div class="overflow-x-auto border border-base-300 rounded-box">
  <table class="table table-sm table-pin-rows">
    <thead><tr class="bg-base-200"><th>Month</th><th>Present</th><th>%</th></tr></thead>
    <tbody><tr><td>Sep</td><td>18</td><td class="font-mono font-bold">92%</td></tr></tbody>
  </table>
</div>

<!-- identity card + grouped detail list (Personal tab) -->
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

- **Detail panel spacing ladder:** label→value `0` (attached) < row gap `gap-2` 8px < card stack `gap-3` 12px — asserted by `tests/test_personal.py`.
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
.tt-row--current  { border-color: var(--color-success);
                    background: color-mix(in oklab, var(--color-success) 8%, transparent); }
.tt-badge         { background: var(--color-success); color: var(--color-accent-content); }
.tt-badge--soon   { background: var(--color-accent);  color: var(--color-accent-content); }
.tt-time          { color: color-mix(in oklab, var(--color-base-content) 50%, transparent); }
```

Meaning map: current class = `success` border + 8% tint + "Now" badge · next/soon = white (`accent`) · selected day pill = `accent` fill with `accent-content` text · break = `warning` · drop target hover = `base-content` border · filled cell = `success` border.

### 4.12 End-sem schedule card (dashboard)

`_exams_view()` builds the view model (`day`, `dow`, `short`, `name_disp`, month-range `label`); the card renders only when exams exist — **empty = hidden, by design** (no empty-state text, unlike sibling cards).

```jinja
<!-- mobile: one landmark (day stamp) + one bright line (name) per row -->
<li class="flex items-start gap-3">
  <span class="w-9 shrink-0 text-center sm:hidden">
    <span class="block font-mono text-[17px] font-semibold leading-none tabular-nums text-base-content">{{ e.day }}</span>
    <span class="block mt-1 text-[11px] uppercase tracking-wider text-base-content/60">{{ e.dow }}</span>
  </span>
  <span class="min-w-0 flex-1 sm:hidden">
    <span class="block text-sm leading-snug text-base-content">{{ e.name_disp }}</span>
    <span class="block mt-0.5 font-mono text-xs text-base-content/60">{{ e.code }} · {{ e.session }}</span>
  </span>
  <!-- desktop: one dense line via sm: switches, zero JS -->
  <span class="hidden sm:flex sm:w-full sm:items-baseline sm:justify-between sm:gap-4">
    <span class="min-w-0 truncate text-sm"><span class="font-mono text-base-content/60">{{ e.code }}</span> <span class="text-base-content">{{ e.name_disp }}</span></span>
    <span class="shrink-0 font-mono text-xs text-base-content/60">{{ e.short }} · {{ e.session }}</span>
  </span>
</li>
```

- **Rows:** `space-y-3 sm:space-y-2`, no dividers — density comes from grouping, not rules (§ B2 / §6). The day stamp is the only 17px/600 element; name is the only `text-base-content` line; everything else `/60` (§2.5 ladder).
- **Names** are title-cased in `_exams_view()` (`name_disp`); storage keeps the portal's ALL-CAPS `name`.
- **Chip** is the default `badge-soft` — same as the marks pills (§2.7: no decorative hue). Measured soft ≈14:1 here; `badge-info` soft measured **4.07:1 on this surface (fails)** — see §10 for the override trap. The **Provisional** caveat lives in the header as `badge-outline badge-sm text-base-content/60` (7.15:1, subtle-but-present) — it replaced the old footnote line. Unlike `badge-info`, outline badges carry no explicit color rule, so `/60` does apply.
- **Verify after any row change:** a contrast probe on the rendered page (canvas-normalized colors composited over the real card bg) and geometry assertions at 393×851 + 1280×900 (one stamp x, one name x, no overlap, no h-overflow, Provisional pill in the header, card bottom above the fixed dock).

### 4.13 Internal marks card (Marks tab)

`_marks_view()` builds the view model: title-cased `title`, `scored_disp`/`max_disp` (`16.20/20` — maxima whole, scores 2 decimals), neutral `pct` + one `outlier`, components sorted by **name** with `date_disp` (`04 Sep`, junk passes through), and per component `derived` / `confirmed` / `ie` (converted paper marks). `_marks_summary()` returns the **3 lowest** subjects for the dashboard glance as `code scored/max` chips (e.g. `21MAB206T 13.40/20` — the values as last synced; **no `%`** on the glance, ordering still risk-first) — there is **no aggregate/overall number anywhere** (brief).

```jinja
<div class="grid grid-cols-1 md:grid-cols-2 gap-3">  <!-- default stretch: side-by-side cards share one height; content stays top-pinned (block flow) -->
  <div class="bg-base-200 border border-base-300 rounded-box p-4">
    <div class="flex items-baseline justify-between gap-2">
      <span class="font-mono text-xs text-base-content/60">21CSS201T</span>
      <span class="font-mono font-bold text-lg tabular-nums">81.0%</span>  <!-- + text-secondary once, if outlier -->
    </div>
    <h3 class="text-sm font-semibold leading-snug">Computer Organization And Architecture</h3>
    <div class="font-mono text-xs text-base-content/50 tabular-nums mb-2">16.20/20</div>
    <div class="border-t border-base-300 pt-2">
      <div class="py-1">
        <div class="flex items-center gap-2">
          <span class="inline-flex items-center justify-center w-14 h-5 shrink-0 rounded-full bg-base-300 text-base-content/70 font-mono text-xs">FT-II</span>
          <span class="text-xs font-mono text-base-content/50">09 Sep</span>
          <span class="font-mono text-xs tabular-nums ml-auto">11.70/15</span>
          <details class="relative shrink-0"><summary>{/* pencil, 24px target */}</summary>
            <form method="post" action="/marks/tag" class="absolute end-0 top-full mt-1 z-10 w-60 bg-base-200 border border-base-300 rounded-box p-3 flex flex-col gap-2">…</form>
          </details>
        </div>
        <div class="flex items-center gap-2 ps-6 mt-0.5">   <!-- nested IE row: 24px indent -->
          <span class="…chip…">IE-1</span>
          <span class="text-xs text-base-content/50">derived</span>
          <span class="font-mono text-xs tabular-nums ml-auto">39.00/50</span>
        </div>
      </div>
    </div>
  </div>
</div>
```

Rules specific to this card:

- **Numbers are neutral.** No status hue on any number — at most ONE `text-secondary`, on the unique lowest subject and only below the 75 target (§2.7). Green/amber/red stay attendance-only (§2.6).
- **No overall %, no per-component %.** Per-subject `%` + `scored/max` only. Maxima print whole (`/15`, never `/15.00`); scores keep 2 decimals; every figure is `font-mono tabular-nums`. Subject names are title-cased in Python (CSS `capitalize` cannot downcase ALL-CAPS portal data).
- **The component chip is a hand-rolled span, not a `.badge`:** daisyUI badges cannot lose their 1px border (§10.9) and this chip must be solid-fill, borderless. Fixed `w-14` (56px = the widest name, `FML-I`) so `FT-II` can never shift the date column. Fill `bg-base-300`, label `text-base-content/70`.
- **Dates** are `04 Sep`, muted `/50`, `text-xs` (12px floor).
- **IE rows** nest under the component they derive from (`ps-6` indent), labelled `derived` or `confirmed`, with marks converted to the paper total (IE-1 → `/50`, IE-2 → `/60`). The portal never labels IEs; `_derive_ie()` guesses `/15` (theory) or `/10` (practical code), and a stored tag always wins.
- **Tag form = `<details>` + `<form method="post" action="/marks/tag">`** — the form itself needs no JS; the only script involved is the outside-click light-dismiss handler in `dash.js` (one `details[open]` guard — and the reason this release bumps the SW cache). The server keys the tag `year|branch|section|course|component` (no semester, no netid): one student's confirmation applies to the whole class and is persisted for the GPA predictor.
- **Verify with** `tests/test_marks_dut.py` (53 checks at 393×851 + 1280×900: uniform chips, date x-alignment, one accent, contrast, uniform row heights + top-pinned content, tooltip on hover, glance marks/max chips, outside-click dismiss, tag round-trip).

### 4.14 Timetable edit history (audit log)

Sits inside `#tab-timetable-view` under the Edit button: a §4.9 accordion (`collapse collapse-arrow bg-base-200 border border-base-300 mt-4`) whose title is `text-sm font-semibold` + a `badge badge-sm` count fed by `/api/timetable/history`. Rows are `py-2 border-b border-base-300 last:border-b-0`, kept terse on purpose: a flex head — name `text-sm font-medium` + mono netid `/60` left, **relative** time `text-xs /60` right (`title=` carries the absolute timestamp) — over change lines `text-xs /60 space-y-0.5` formatted `Mon P3: CS2011 → CS3005` (`+CODE` added, `-CODE` removed; full subject names live in `title=`, never inline). Empty state `text-base-content/60`.

- **XSS rule (audit 2026-09-27 applies here too):** every value in the payload (peer-written subject codes/names, editor name) is student-controlled — `loadHistory()` in `timetable.js` builds it with `textContent`/`createElement` only, **never `innerHTML`**.
- Server: `_tt_diff()` in `app.py` writes `timetable_edit_log` (migration v9) on POST `/api/timetable`; no-op saves are skipped, last 200 entries per group kept.

---

## 5. Layout and responsive

- **Mobile-first single column.** Dashboard container `max-w-3xl mx-auto px-2 lg:px-4 py-5`. The gutter is **8px below `lg`** because the mobile navbar's own content padding is 8px — the card column then lines up with the logo/icons above it, and the column gains 16px of width on a 393px phone; at `lg` the desktop navbar takes `px-4`, so the gutter steps back to 16px and stays aligned. Both breakpoints keep a real gutter (never `px-0`). Login is a centered card, `w-full max-w-md`, on `min-h-[100dvh]`.
- **Rhythm (the 4px scale, in use):** `gap-2` / `gap-3` inside and between cards · `mb-5` between blocks · card padding `p-4` (`p-5` for the hero, `p-0` for list cards). Don't introduce new spacing values.
- **Vertical gaps are RANKED by relationship, never uniform** (Gestalt proximity — equal gaps everywhere give consistency without hierarchy). Same 4px scale, ordered tight → loose: **0** attached (a field and its own hint/error) → **`gap-2` 8px** feedback that reports on one element (status under its button) → **`gap-3` 12px** peers inside a group (field ↔ field) → **group break**, sized per card **and stepped, never pinned**: `mb-5` 20px between content blocks — and in the login card the two group breaks (the brand band, and password → Sign in = 16px reserved Caps row + the button's margin) step *together* with the card's own `p-6 sm:p-8` padding: **24px below `sm`, 36px at `sm`+ — equal to each other at every breakpoint** (same idea as daisyUI's `--card-p`, a token that resizes instead of a fixed pixel) → **section break**, looser than every group break (login card: 40px whitespace + rule + `pt-3`). A card must show ≥3 of these tiers in order. Horizontal gutters stay uniform — the column is one unit — and card padding must stay larger than the gaps inside it. Worked example: the login card, audited at 390/768/1280 as **0 < 8 < 12 < 24|36 < 40** (the `24|36` tier is the adaptive one).
- **Section headings:** `text-base font-semibold mb-3`.
- **Breakpoints:** design at 375px first. `sm` (640) switches the course grid to 2 columns and reveals the "Refresh" label. `lg` (1024) goes to 3 columns. The content column never grows past `max-w-3xl`.
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

---

## 8. Copy

- Plain, direct, second person, sentence case. Say what will happen. One verb per action across the whole flow: **Refresh** → "Refreshing attendance…" → the caption `(5m ago)` beside the button, and nothing at all while the data is younger than 5 minutes.
- Data lines are actionable, not decorative: "Can miss 3 more classes and stay above 75%", "Attend the next 2 classes in a row to reach 75%". The UI says "miss", never "bunk".
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
| Eyebrow labels above every heading, ALL CAPS everywhere, centered data | Sentence case, left aligned; uppercase only for Personal Details labels |
| Entrance animations, scroll reveals, hover lift | Motion only in response to an action |
| `input-bordered`, `form-control`, `label-text` (daisyUI 4) | `fieldset`, `floating-label`, `input`, `label` |
| `alert()` / `prompt()` in new flows | `modal` or an inline `alert` |
| New component shapes or spacing values | The recipes in §4 and the spacing in §5 |

---

## 10. Implementation constraints (silent-failure list)

1. **No build step.** Tailwind v4 (`@tailwindcss/browser@4`) and daisyUI 5 (`daisyui@5`) load from jsDelivr and generate styles at runtime from the DOM. Classes written in Jinja or added by JS are picked up. There is no `tailwind.config.js`, no `@plugin`, and no `@apply` in plain CSS (`@apply` / `@theme` work only inside `<style type="text/tailwindcss">`). Both CDN URLs are pinned to exact versions in `partials/theme.html` (`@tailwindcss/browser@4.3.3`, `daisyui@5.7.46`); `verify76` L47 fails the suite if a pin drifts.
2. **Strict CSP** (`set_security_headers()` in `app/app.py`): `default-src 'self'`; scripts from `'self'` and jsDelivr only, so **no inline `<script>`**; styles from `'self'`, `'unsafe-inline'`, and jsDelivr; images from `'self'` and `data:` only; no `font-src`, so fonts fall back to `'self'`. Consequences: no Google Fonts, no icon libraries, no other CDNs, no remote images. JavaScript goes in `app/static/*.js`. To add a font, self-host it under `app/static/` and add it to the service worker's precache.
3. **Service worker** (`app/static/sw.js`): network-first for `/static/*` and HTML, with cache as the offline fallback. If you edit anything under `app/static/`, bump `CACHE_NAME` (`opensrm-v14` → `opensrm-v15`) or installed PWAs keep serving the old file. Inline `<style>` in templates ships with the HTML and updates immediately.
4. **The theme ships once** in `app/templates/partials/theme.html` (included by both pages). Change it there, and Appendix A.
5. **Hand-written CSS uses variables, never hex:** `var(--color-base-200)`; tints via `color-mix(in oklab, var(--color-success) 8%, transparent)`.
6. **PWA chrome** (`<meta name="theme-color">`, `manifest.json` `background_color` / `theme_color`, the service worker's offline page) uses `#111111` from the logo. Leave it unless asked. These are the only places hex is acceptable; take values from §2.2.
7. **HTML built in Python or JS** (`timetable_html()`, `timetable.js`) uses the same tokens and classes as the templates, and must escape any interpolated data.
8. Python changes must pass `ruff` (CI lint).
9. **daisyUI wins inside its own components.** Measured on the CDN build: `text-base-content` — even with `!important` — does **not** override `.badge-info`'s color (cross-origin stylesheets also hide the rules from `cssRules`). To restyle badge text, use another badge variant or hand-rolled span; never rely on a utility override.
10. **Only the documented opacity steps render** (§2.5: `/40 /50 /60 /70 /90`). Measured: `text-base-content/55` silently rendered at full opacity while `/50` and `/60` applied. Stick to the ladder — arbitrary steps may not ship.
11. **Two ways daisyUI's dock/active styling reaches the navbar tabs.** (a) **daisyUI's "active" fill is invisible on this surface:** `.btn-active` / `[aria-pressed]` / `[aria-current]` all set `--btn-bg: color-mix(in oklab, var(--color-base-200), #000 5%)` = `#090909` — byte-identical to the navbar, because `base-200` is already near-black. Measured: a selected navbar tab sat at **1.000:1** against the bar it lives in. On this theme "active" has to *lighten*: use a `base-content` tint (§4.9) and measure the selected/unselected pair before shipping; never trust daisyUI's default active/pressed state. (b) **`.dock-active:after{width:2.5rem}` also matches navbar tabs**, because `dash.js` toggles `dock-active` on every `[data-tab]` — so a `::after` indicator that declares `left`/`right` but not `width` renders at the leaked 40px (measured left 8 / right 41 inside an 89px pill) instead of its own insets. Declare `width: auto` in the rule that owns the bar; `test_navbar` asserts bar width == pill − 16.
12. **A closed `<details>` still reports a layout rect for its hidden children** (Chrome lays them out via `content-visibility`), so a geometry audit that measures "card height vs deepest descendant" counts the hidden tag form (§4.13) and reports phantom negative slack. Filter measurement sweeps with `!el.closest('details:not([open])')`.

---

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
- [ ] Data is in `font-mono`; copy is sentence case; errors say what to do
- [ ] No inline script, external font, icon library, or remote image
- [ ] `CACHE_NAME` bumped if anything in `app/static/` changed
- [ ] Looks right at 375px and 1280px, and keyboard focus is visible on every control I touched

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

Canonical theme, as authored in the daisyUI generator (kept here as the reference for token values; **not** loadable as-is in this CDN setup):

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
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3"></script>
  <link href="https://cdn.jsdelivr.net/npm/daisyui@5.7.46" rel="stylesheet" type="text/css">
</head>
<body class="bg-base-100 text-base-content">
  <div class="navbar bg-base-200 border-b border-base-300 sticky top-0 z-20 px-4 py-3"
       style="padding-top:calc(0.75rem + env(safe-area-inset-top))"> … </div>
  <main class="max-w-3xl mx-auto px-2 lg:px-4 py-5"> … </main>
  <script src="/static/your-script.js"></script>   <!-- external file only: CSP blocks inline scripts -->
</body>
</html>
```
