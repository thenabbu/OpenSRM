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
11. **daisyUI 5 only.** `input-bordered`, `form-control`, and `label-text` do not exist in v5. Use `fieldset`, `input`, `label`.
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
│ avatar · name / netid / "Synced 5m ago"   [Refresh] [Log out]
├────────────────────────────────────────────────────┤   page: bg-base-100
│  Attendance │ Timetable │ Personal Details            ←  max-w-3xl mx-auto px-4 py-5
│  ┌──────────────────────────────────────────────┐      tabs tabs-border
│  │ (82%)  Overall attendance                    │   ←  card bg-base-200 border-base-300
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

The theme is authored as a daisyUI 5 custom theme (Appendix A), but the app has **no Tailwind build**. It ships as plain CSS variables under `html[data-theme="openSRM"]` in an inline `<style>` block, duplicated in `app/templates/login.html` and `app/templates/dashboard.html`. Every page needs `<html data-theme="openSRM">` plus that block. Do not use `@plugin "daisyui/theme"`; it only works in a build pipeline.

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
| Active tab | `tab tab-active` inside `tabs tabs-border` (underline is `currentColor`, so white) | `text-primary`, `border-primary` on a tab |
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

- **Pink `secondary` is not used anywhere in the shipped UI.** Treat it as the single accent-of-attention: at most one element per screen (a "New" badge, a feature dot, one chart series). Never for status, links, buttons, or container borders/backgrounds. When unsure, leave it out.
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

- **Families:** the system stack only. Default sans (Tailwind `font-sans`) for text, `font-mono` for data. There are no web fonts; the CSP blocks them (§10). `IBM Plex Mono` is named in `timetable.css` but is never loaded, so it silently falls back to the generic monospace.
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

```html
<fieldset class="fieldset">
  <legend class="fieldset-legend">NetID / Email</legend>
  <input type="text" class="input w-full" placeholder="NetID / SRM email id" autocomplete="username">
</fieldset>
```

- Inputs are bordered by default in v5. Focus is daisyUI's white 2px ring; do not override it.
- Invalid: add `input-error` and a `text-sm text-error` sentence below saying what to fix.
- Password toggle: `relative` wrapper, input gets `pr-12`, button is `absolute right-1 top-1/2 -translate-y-1/2 btn btn-ghost btn-sm btn-square` with `aria-label`.

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

<!-- key/value list inside a p-0 card -->
<ul class="list">
  <li class="list-row bg-base-300/50 text-xs font-semibold uppercase tracking-wider text-base-content/50 py-2 px-4">Academic</li>
  <li class="list-row items-center">
    <span class="text-xs text-base-content/50 uppercase tracking-wide w-28 shrink-0">Program</span>
    <span class="text-sm font-mono break-words">B.Tech CSE</span>
  </li>
</ul>
```

- **Accordion:** `collapse collapse-arrow bg-base-200 border border-base-300` with `<input type="radio" name="…">` for one-open-at-a-time; title `text-sm font-semibold`, count as a badge on the right.
- **Tabs:** `tabs tabs-border mb-5` containing `tab` buttons with `role="tab"`; the active one adds `tab-active`.

### 4.10 Icons and avatar

- Icons are **inline SVG**, Heroicons outline style: `fill="none" stroke="currentColor"`, stroke width 1.5–2, `w-4 h-4` (in buttons) or `w-5 h-5`. Never fixed fill colors, never emoji, never an icon font or library (CSP).
- Avatar: `avatar` → `div.bg-base-300.w-9.rounded-full` holding an `<img>` (DiceBear is the only allowed remote image host).

### 4.11 Timetable (server-rendered, `tt-*` classes)

`timetable_html()` in `app.py` emits the markup and `app/static/timetable.css` styles it. That file is still on hard-coded hex; see the migration map in §12. When you touch a rule, rewrite it with variables:

```css
.tt-row--current  { border-color: var(--color-success);
                    background: color-mix(in oklab, var(--color-success) 8%, transparent); }
.tt-badge         { background: var(--color-success); color: var(--color-accent-content); }
.tt-badge--soon   { background: var(--color-accent);  color: var(--color-accent-content); }
.tt-time          { color: color-mix(in oklab, var(--color-base-content) 50%, transparent); }
```

Meaning map: current class = `success` border + 8% tint + "Now" badge · next/soon = white (`accent`) · selected day pill = `accent` fill with `accent-content` text · break = `warning` · drop target hover = `base-content` border · filled cell = `success` border.

---

## 5. Layout and responsive

- **Mobile-first single column.** Dashboard container `max-w-3xl mx-auto px-4 py-5`. Login is a centered card, `w-full max-w-md`, on `min-h-[100dvh]`.
- **Rhythm (the 4px scale, in use):** `gap-2` / `gap-3` inside and between cards · `mb-5` between blocks · card padding `p-4` (`p-5` for the hero, `p-0` for list cards). Don't introduce new spacing values.
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

- Plain, direct, second person, sentence case. Say what will happen. One verb per action across the whole flow: **Refresh** → "Refreshing attendance…" → "Synced just now".
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
| `input-bordered`, `form-control`, `label-text` (daisyUI 4) | `fieldset`, `fieldset-legend`, `input` |
| `alert()` / `prompt()` in new flows | `modal` or an inline `alert` |
| New component shapes or spacing values | The recipes in §4 and the spacing in §5 |

---

## 10. Implementation constraints (silent-failure list)

1. **No build step.** Tailwind v4 (`@tailwindcss/browser@4`) and daisyUI 5 (`daisyui@5`) load from jsDelivr and generate styles at runtime from the DOM. Classes written in Jinja or added by JS are picked up. There is no `tailwind.config.js`, no `@plugin`, and no `@apply` in plain CSS (`@apply` / `@theme` work only inside `<style type="text/tailwindcss">`). Both CDN URLs float within their major version.
2. **Strict CSP** (`set_security_headers()` in `app/app.py`): `default-src 'self'`; scripts from `'self'` and jsDelivr only, so **no inline `<script>`**; styles from `'self'`, `'unsafe-inline'`, and jsDelivr; images from `'self'`, `data:`, and `api.dicebear.com`; no `font-src`, so fonts fall back to `'self'`. Consequences: no Google Fonts, no icon libraries, no other CDNs, no remote images. JavaScript goes in `app/static/*.js`. To add a font, self-host it under `app/static/` and add it to the service worker's precache.
3. **Service worker** (`app/static/sw.js`): cache-first for `/static/*`, network-first for HTML. If you edit anything under `app/static/`, bump `CACHE_NAME` (`opensrm-v4` → `opensrm-v5`) or installed PWAs keep serving the old file. Inline `<style>` in templates ships with the HTML and updates immediately.
4. **The theme block exists twice** (login and dashboard). Change both, and Appendix A.
5. **Hand-written CSS uses variables, never hex:** `var(--color-base-200)`; tints via `color-mix(in oklab, var(--color-success) 8%, transparent)`.
6. **PWA chrome** (`<meta name="theme-color">`, `manifest.json` `background_color` / `theme_color`, the service worker's offline page) uses `#111111` from the logo. Leave it unless asked. These are the only places hex is acceptable; take values from §2.2.
7. **HTML built in Python or JS** (`timetable_html()`, `timetable.js`) uses the same tokens and classes as the templates, and must escape any interpolated data.
8. Python changes must pass `ruff` (CI lint).

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
| 1 | `--radius-box` is `1rem` on login, `0.5rem` on the dashboard | `login.html` theme block | `0.5rem` |
| 2 | Theme tokens are duplicated in two `<style>` blocks and can diverge | both templates | One shared Jinja include |
| 3 | `timetable.css` is hard-coded hex although its header says it uses tokens | `timetable.css` | Migration map below |
| 4 | Timetable greens/ambers/reds are lighter Tailwind-400 tints; the dashboard cards use the theme tokens, so the two screens disagree | `timetable.css` | Tokens |
| 5 | `.tt-wrap` uses `#161616`, the same as the page, so it reads as an outline, not a card | `timetable.css` | `base-200` |
| 6 | daisyUI 4 classes `input-bordered`, `form-control`, `label-text` (no-ops in v5) and `focus:input-primary` (black focus ring) on the login inputs | `login.html` | §4.6 |
| 7 | `IBM Plex Mono` is referenced but never loaded | `timetable.css` | `font-mono` |
| 8 | `text-base-content/40` on informational text (≈ 3.8:1) | `dashboard.html` | `/50` minimum |
| 9 | Solid `btn-success`, `badge-warning`, `alert-warning` with pale labels (1.9–2.8:1) | `dashboard.html`, `dash.js` | §2.8 |
| 10 | Native `alert()` / `prompt()` for errors and "Add subject" | `dash.js`, `timetable.js` | Modal or inline alert |
| 11 | `.tt-today::after{content:;…}` is an invalid declaration, so the "today" dot never renders | `timetable.css` | `content:""` |
| 12 | Browser chrome color `#111111` vs navbar `base-200` ≈ `#090909` | `theme-color`, `manifest.json`, `sw.js` | Leave unless asked |

**`timetable.css` migration map**

| Legacy value | Meaning | Replace with |
|---|---|---|
| `#161616` | `.tt-wrap` background | `var(--color-base-200)` |
| `#1e1e1e` | hero, day pills, palette blocks, filled cells | `var(--color-base-300)` |
| `#2a2a2a` | borders | `var(--color-base-300)` |
| `#888` / `#b0b0b0` | muted / secondary text | `color-mix(in oklab, var(--color-base-content) 50%, transparent)` / `… 70% …` |
| `#fff` fill with `#111` text | selected pill, "Soon" badge, today dot | `var(--color-accent)` with `var(--color-accent-content)` |
| `#fff` text | codes | `var(--color-base-content)` |
| `#4ade80`, `rgba(74,222,128,.05–.08)` | now / current / filled, and their tints | `var(--color-success)`, `color-mix(in oklab, var(--color-success) 8%, transparent)` |
| `#fbbf24` | break | `var(--color-warning)` |
| `#f87171` | remove ✕ | `var(--color-error)` |
| `rgba(255,255,255,.02–.05)` | zebra / hover tint | `color-mix(in oklab, var(--color-base-content) 3%, transparent)` |

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
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <link href="https://cdn.jsdelivr.net/npm/daisyui@5" rel="stylesheet" type="text/css">
</head>
<body class="bg-base-100 text-base-content">
  <div class="navbar bg-base-200 border-b border-base-300 sticky top-0 z-20 px-4 py-3"
       style="padding-top:calc(0.75rem + env(safe-area-inset-top))"> … </div>
  <main class="max-w-3xl mx-auto px-4 py-5"> … </main>
  <script src="/static/your-script.js"></script>   <!-- external file only: CSP blocks inline scripts -->
</body>
</html>
```
