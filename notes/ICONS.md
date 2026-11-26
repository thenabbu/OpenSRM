# ICONS.md — PWA icon asset manifest (v3)

Spec for plan unit **8.2**. Source of truth for the mark: `app/static/icon-1024.png`
(1024x1024, verified). The mark is **not redesigned** (decisions.md, 2026-11-07 | assets).
Generation runs on the laptop (constraint C3); outputs are committed (AOT, D1).
Repo audit done read-only on 2026-11-07; every size below was measured, not assumed.

## 1. Current guidance (verified 2026-11-07)

- **web.dev — Web app manifest** (https://web.dev/learn/pwa/web-app-manifest, last updated 2024-12-09):
  - Minimum icon: **512x512**; recommended set includes **192, 384, 1024**.
  - **Maskable**: square image whose main mark sits inside a centered safe zone —
    a circle of radius **40% of the icon width**; maskable icons should be
    **512x512 at least**. `"purpose": "any maskable"` when one image serves both.
- **web.dev — Add a manifest** (https://web.dev/learn/pwa/add-manifest):
  Chromium installability requires **192x192 and 512x512** icons.
- **Microsoft Edge — Define icons and a theme color** (https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/how-to/icon-theme-color):
  - **Level 1** (base): a single 512x512 manifest icon; Edge synthesizes the rest.
  - **Level 2** (tiles, 1x scale), declared as manifest `icons` entries with `purpose: "any"`:
    44x44 app icon, 71x71 small tile, 150x150 medium tile, 310x150 wide tile,
    310x310 large tile, 50x50 store logo, 620x300 splash.
  - **Level 3/4** (all display scales + 16–256px target sizes for taskbar/Start/Alt-Tab):
    highest effort, optional.
- **Apple splash device sizes** — Apple **removed the device screen dimensions
  table from the HIG in September 2026** (documented in pwa-asset-generator
  `src/config/constants.ts:12-16`, GH-1276) and does not publish it anywhere
  else. The current list lives in the file **`apple-fallback-data.json` bundled
  with `pwa-asset-generator`** (elegantapp, master as of 2026-11-07) — 59 devices,
  hand-maintained. The same tool emits the `apple-splash-<w>x<h>.png` files and
  the exact `<link rel="apple-touch-startup-image">` media-query tags in the
  required HTML order (its `constants.ts:21-48`): favicon → `msapplication-*`
  metas → `apple-touch-icon` → `apple-mobile-web-app-capable` →
  `apple-touch-startup-image` (with `prefers-color-scheme: dark` variants).
- **Apple HIG — App Icons**: `apple-touch-icon` at **180x180**.

Tool of record: `npx pwa-asset-generator` (Node 22+, runs on the laptop).
Flags that matter here (its `constants.ts`): `--portrait-only` (app is
portrait-locked), `--maskable` (on by default), `--favicon`, `--mstile`,
`--background` (use `#111111`, not the default transparent), `--padding`
(default 10% — this is the maskable safe-zone padding).

## 2. Existing repo state (measured sizes)

> Historical: the audit below is the 2026-11-07 state. Unit 8.2 shipped it;
> **§7 is the as-built truth** (what exists, what proves it).

All files in `app/static/` unless noted:

| File | Actual size | Purpose | State |
|---|---|---|---|
| `icon-1024.png` | 1024x1024 | manifest `any` + **generation source** | keep |
| `icon-512.png` | 512x512 | manifest `any`; Chromium installability pair | keep |
| `icon-192.png` | 192x192 | manifest `any`; Chromium installability pair | keep |
| `icon-maskable-512.png` | **1024x1024** | manifest `maskable` | **BROKEN** — `manifest.json:30-35` declares `512x512`, file is 1024x1024 |
| `apple-touch-icon.png` | 180x180 | iOS home-screen icon | keep |
| `icon-badge.png` | 96x96 | push notification small icon (`sw.js:152`) | keep |
| `logo-rect.png` | 1500x500 | wordmark in templates (`login.html:41`, `dashboard.html:85,149`) | keep |
| `favicon.ico` | 1 entry: **16x16** | tab/taskbar icon | weak — regenerate multi-size |
| `apple-touch-startup-750x1334.png` … `-1290x2796.png` (6 files) | as named | iOS splash | **DEAD** — no template references them |

Template heads (verified):
- `login.html:6-16` — favicon + 192/512 icon links, `apple-touch-icon` →
  `apple-touch-icon.png` (correct 180), manifest, theme-color, and the full iOS
  meta set: `apple-mobile-web-app-capable` / `status-bar-style`
  (`black-translucent`) / `title` at lines 12-14.
- `dashboard.html:1-14` — `apple-touch-icon` → **`icon-192.png`** (line 5, wrong
  source; 192 ≠ Apple's 180), and the `apple-mobile-web-app-*` metas are
  **missing entirely**.
- **Neither template** contains any `<link rel="apple-touch-startup-image">` —
  the 6 splash PNGs are unreferenced dead files.

## 3. Target asset set (unit 8.2 ships this)

Everything generated from `icon-1024.png`; fill background `#111111` where the
mark doesn't fill the canvas (splashes, maskable padding, tiles).

### 3.1 Web / Android (manifest icons)

| File | Size | purpose | Status |
|---|---|---|---|
| `icon-192.png` | 192x192 | `any` — Chromium installability pair | exists, keep |
| `icon-512.png` | 512x512 | `any` — Chromium installability pair | exists, keep |
| `icon-1024.png` | 1024x1024 | `any` — source of truth | exists, keep |
| `icon-maskable-512.png` | 512x512 | `maskable` — Android adaptive, 40% safe zone | **regenerate** (file is 1024 today) |
| `icon-maskable-1024.png` | 1024x1024 | `maskable` — hi-res adaptive | **missing** |

### 3.2 Favicon

| File | Size | Purpose | Status |
|---|---|---|---|
| `favicon.ico` | multi-size: 16, 24, 32, 48 | tab/taskbar across OS scales | **regenerate** (16x16 only today) |

### 3.3 iOS

| File | Size | Purpose | Status |
|---|---|---|---|
| `apple-touch-icon.png` | 180x180 | home-screen icon | exists, keep |
| `apple-splash-<W>x<H>.png` × 23 | see §4 | launch screen, one per device class | **17 missing**; 6 sizes exist under old `apple-touch-startup-*` names, unreferenced |

Portrait only: `manifest.json:8` locks `orientation: portrait-primary`, so
landscape splashes would be dead files (logged in decisions.md).

### 3.4 Windows (Edge PWA)

| File | Size | Purpose | Status |
|---|---|---|---|
| (existing 192/512/1024 `any` icons) | — | **Level 1**: Edge synthesizes taskbar/Start icons | covered |
| `icon-44.png` | 44x44 | Level 2 — app icon | **missing** |
| `icon-71.png` | 71x71 | Level 2 — small tile | **missing** |
| `icon-150.png` | 150x150 | Level 2 — medium tile | **missing** |
| `icon-310x150.png` | 310x150 | Level 2 — wide tile | **missing** |
| `icon-310.png` | 310x310 | Level 2 — large tile | **missing** |
| `icon-50.png` | 50x50 | Level 2 — store logo | **missing** |
| `icon-620x300.png` | 620x300 | Level 2 — splash (classic package only) | **missing** |

Skipped deliberately: Level 3/4 scale matrices + 16–256px target sizes —
add only if Windows becomes a real distribution target. Level 2 + the 512 base
is the practical flagship bar.

### 3.5 Totals

33 files generated (2 web maskable + 1 favicon + 23 splash + 7 Windows tiles);
6 kept unchanged (192/512/1024, apple-touch-icon, icon-badge, logo-rect).
`icon-badge.png` and `logo-rect.png` are live references — never regenerate them.

## 4. iOS splash — per device class (portrait)

Source: `apple-fallback-data.json` bundled with pwa-asset-generator (59 devices
collapse to 23 unique portrait sizes). `sf` is the pixel ratio that goes into
the media query; tag format (its `constants.ts:282-313`):

```html
<link rel="apple-touch-startup-image" href="/static/apple-splash-<W>x<H>.png"
      media="(device-width: <W/sf>px) and (device-height: <H/sf>px)
             and (-webkit-device-pixel-ratio: <sf>) and (orientation: portrait)">
```

| File (`apple-splash-*.png`) | Size | sf | Devices covered | In repo today? |
|---|---|---|---|---|
| `-1320x2868` | 1320x2868 | 3 | iPhone 17 Pro Max, 16 Pro Max | missing |
| `-1290x2796` | 1290x2796 | 3 | iPhone 16 Plus, 15 Pro Max, 15 Plus, 14 Pro Max | yes (old name, unreferenced) |
| `-1284x2778` | 1284x2778 | 3 | iPhone 14 Plus, 13 Pro Max, 12 Pro Max | missing |
| `-2064x2752` | 2064x2752 | 2 | iPad Pro 13-inch | missing |
| `-1260x2736` | 1260x2736 | 3 | iPhone Air | missing |
| `-2048x2732` | 2048x2732 | 2 | iPad Pro 12.9-inch, iPad Air 13-inch | missing |
| `-1242x2688` | 1242x2688 | 3 | iPhone 11 Pro Max, XS Max | yes (old name, unreferenced) |
| `-1206x2622` | 1206x2622 | 3 | iPhone 17 Pro, 17, 16 Pro | missing |
| `-1179x2556` | 1179x2556 | 3 | iPhone 16, 15 Pro, 15, 14 Pro | missing |
| `-1170x2532` | 1170x2532 | 3 | iPhone 16e, 14, 13 Pro, 13, 12 Pro, 12 | yes (old name, unreferenced) |
| `-1125x2436` | 1125x2436 | 3 | iPhone 11 Pro, XS, X | yes (old name, unreferenced) |
| `-1668x2420` | 1668x2420 | 2 | iPad Pro 11-inch 5th/6th gen | missing |
| `-1668x2388` | 1668x2388 | 2 | iPad Pro 11-inch 1st–4th gen | missing |
| `-1640x2360` | 1640x2360 | 2 | iPad Air 11-inch, Air 10.9-inch, iPad 11-inch | missing |
| `-1080x2340` | 1080x2340 | 3 | iPhone 13 mini, 12 mini | missing |
| `-1488x2266` | 1488x2266 | 2 | iPad mini 8.3-inch | missing |
| `-1668x2224` | 1668x2224 | 2 | iPad Pro 10.5-inch, iPad Air 10.5-inch | missing |
| `-1242x2208` | 1242x2208 | 3 | iPhone 8/7/6s/6 Plus | missing |
| `-1620x2160` | 1620x2160 | 2 | iPad 10.2-inch | missing |
| `-1536x2048` | 1536x2048 | 2 | iPad Pro 9.7", Air 9.7", iPad 9.7", mini 7.9" | missing |
| `-828x1792` | 828x1792 | 2 | iPhone 11, XR | yes (old name, unreferenced) |
| `-750x1334` | 750x1334 | 2 | iPhone 8/7/6s/6, SE 4.7" | yes (old name, unreferenced) |
| `-640x1136` | 640x1136 | 2 | iPhone SE 4", iPod touch 5th gen+ | missing |

Dark-mode note: the app is a dark theme (`theme_color #111111` everywhere);
the single light-orientation set suffices — skip `prefers-color-scheme: dark`
variants until a light theme exists.

## 5. Wiring checklist (unit 8.2)

1. **`manifest.json`**
   - `:30-35` maskable entry: keep `512x512` and make the file match (regenerate).
   - Add `icon-maskable-1024.png` (`1024x1024`, `maskable`).
   - Add the 7 Windows Level-2 tiles as `purpose: "any"` entries.
2. **Template heads** (`login.html`, `dashboard.html` — same block in both;
   prefer a shared include if Phase 3's shell partial exists by then):
   - `apple-touch-icon` → `apple-touch-icon.png` in both (`dashboard.html:5`
     currently points at `icon-192.png`).
   - Add `apple-mobile-web-app-capable=yes`,
     `apple-mobile-web-app-status-bar-style=black-translucent`,
     `apple-mobile-web-app-title=OpenSRM` to `dashboard.html` (missing).
   - Add the 23 `apple-touch-startup-image` link tags (§4) to both templates.
3. **`sw.js`** — extend the precache list (`sw.js:6`: 192/512/1024/maskable-512/
   favicon today) with every new icon file.
4. **Delete** the 6 dead `apple-touch-startup-*.png` in the same commit that
   lands the `apple-splash-*` replacements (one naming scheme, no orphans).
5. **Verify**: DevTools → Application → Manifest shows no icon size mismatch;
   installability check passes; every output PNG's actual pixels re-measured
   (python struct read, same method as this audit) — the existing
   maskable-512 mismatch is exactly the failure mode this check catches.

## 6. Generation command (laptop, per C3)

```sh
cd /home/navya/work/osrm
npx pwa-asset-generator \
  --favicon --maskable --portrait-only \
  --background "#111111" \
  -a app/static/icon-1024.png \
  -m app/static/manifest.json \
  -i app/templates/login.html
```

Caveats for the unit:
- The tool edits the index HTML and manifest **in place** — diff the output and
  port the tag block into the Flask template heads; do not commit blindly.
- Its output names are `manifest-icon-*.png` / `apple-splash-*`; reconcile to
  the repo's `icon-*.png` scheme in the same commit and update every reference.
- Windows Level-2 tiles (44/71/150/310x150/310/50/620x300) are not emitted by
  the tool's defaults — resize from `icon-1024.png` with the same pipeline
  (Lanczos downscale, `#111111` fill) and add them as manifest entries.

## 7. As built (unit 8.2, this commit)

Every file below exists in `app/static/`, was generated by `scripts/build_icons.py`
from the SVGs in `design/icons/`, and is proven by `scripts/check_icons.py` (now in
`scripts/gates.sh` **and** the CI `unit` job — before this unit it existed but no
CI job ran it). 33 generated + 6 kept unchanged, as §3.5 asks.

Every output is rendered from the vector at its own pixel size (`cairosvg`); no
output is a resized raster. The four sources and what each drives:

| Source | Drives |
|---|---|
| `design/icons/onesrm-icon.svg` | `icon-192/512/1024.png`, Windows tiles, splashes — the full-art mark, letters nearly fill the square |
| `design/icons/onesrm-icon-chamfer.svg` | `favicon.svg`, `favicon.ico` — same art, 24px cut corners, alpha kept |
| `design/icons/icon-maskable.svg` | `icon-maskable-192/512/1024.png`, `apple-touch-icon.png` — letters scaled 1.25x about the centre (farthest corner 37.6% of the width, inside the web 40% safe circle), full-bleed, opaque |
| `design/icons/onesrm-adaptive-{background,foreground}.svg` | the Android-spec layers `icon-maskable.svg` is assembled from (letters at 30.1%, inside Android's 66dp safe zone) |

The favicon keeps its transparency: a tab icon sits on the browser's own
background, so the chamfered corners stay transparent. Every PWA and apple icon
is flattened onto `#111111`, because iOS paints transparency black.

### 7.1 Traceability — one row per generated file

| File | Size | Spec row | How it is built | What proves it |
|---|---|---|---|---|
| `icon-maskable-512.png` | 512x512 | §3.1 | `render(icon-maskable.svg, 512)` | manifest IHDR + safe-zone + bleed scan |
| `icon-maskable-1024.png` | 1024x1024 | §3.1 | `render(icon-maskable.svg, 1024)` | manifest IHDR + safe-zone + bleed scan |
| `favicon.ico` | 16,24,32,48 | §3.2 | `render(onesrm-icon-chamfer.svg, 48, alpha)` + multi-frame ICO save | ICO directory parsed: 4 frames |
| `favicon.svg` | 512 viewBox | §3.2 | `onesrm-icon-chamfer.svg` verbatim | head template + golden capture |
| `apple-touch-icon.png` | 180x180 | §3.3 | `render(icon-maskable.svg, 180)` | 180px + **fully opaque** |
| `apple-splash-1320x2868.png` | 1320x2868 | §4 (3, iPhone 17 Pro Max, 16 Pro Max) | `plate((1320,2868), render(onesrm-icon.svg,512), 0.40)` | media query 440x956@3 ↔ IHDR |
| `apple-splash-1290x2796.png` | 1290x2796 | §4 (3, iPhone 16 Plus, 15 Pro Max, 15 Plus, 14 Pro Max) | `plate((1290,2796), render(onesrm-icon.svg,512), 0.40)` | media query 430x932@3 ↔ IHDR |
| `apple-splash-1284x2778.png` | 1284x2778 | §4 (3, iPhone 14 Plus, 13 Pro Max, 12 Pro Max) | `plate((1284,2778), render(onesrm-icon.svg,512), 0.40)` | media query 428x926@3 ↔ IHDR |
| `apple-splash-2064x2752.png` | 2064x2752 | §4 (2, iPad Pro 13-inch) | `plate((2064,2752), render(onesrm-icon.svg,512), 0.40)` | media query 1032x1376@2 ↔ IHDR |
| `apple-splash-1260x2736.png` | 1260x2736 | §4 (3, iPhone Air) | `plate((1260,2736), render(onesrm-icon.svg,512), 0.40)` | media query 420x912@3 ↔ IHDR |
| `apple-splash-2048x2732.png` | 2048x2732 | §4 (2, iPad Pro 12.9-inch, iPad Air 13-inch) | `plate((2048,2732), render(onesrm-icon.svg,512), 0.40)` | media query 1024x1366@2 ↔ IHDR |
| `apple-splash-1242x2688.png` | 1242x2688 | §4 (3, iPhone 11 Pro Max, XS Max) | `plate((1242,2688), render(onesrm-icon.svg,512), 0.40)` | media query 414x896@3 ↔ IHDR |
| `apple-splash-1206x2622.png` | 1206x2622 | §4 (3, iPhone 17 Pro, 17, 16 Pro) | `plate((1206,2622), render(onesrm-icon.svg,512), 0.40)` | media query 402x874@3 ↔ IHDR |
| `apple-splash-1179x2556.png` | 1179x2556 | §4 (3, iPhone 16, 15 Pro, 15, 14 Pro) | `plate((1179,2556), render(onesrm-icon.svg,512), 0.40)` | media query 393x852@3 ↔ IHDR |
| `apple-splash-1170x2532.png` | 1170x2532 | §4 (3, iPhone 16e, 14, 13 Pro, 13, 12 Pro, 12) | `plate((1170,2532), render(onesrm-icon.svg,512), 0.40)` | media query 390x844@3 ↔ IHDR |
| `apple-splash-1125x2436.png` | 1125x2436 | §4 (3, iPhone 11 Pro, XS, X) | `plate((1125,2436), render(onesrm-icon.svg,512), 0.40)` | media query 375x812@3 ↔ IHDR |
| `apple-splash-1668x2420.png` | 1668x2420 | §4 (2, iPad Pro 11-inch 5th/6th gen) | `plate((1668,2420), render(onesrm-icon.svg,512), 0.40)` | media query 834x1210@2 ↔ IHDR |
| `apple-splash-1668x2388.png` | 1668x2388 | §4 (2, iPad Pro 11-inch 1st-4th gen) | `plate((1668,2388), render(onesrm-icon.svg,512), 0.40)` | media query 834x1194@2 ↔ IHDR |
| `apple-splash-1640x2360.png` | 1640x2360 | §4 (2, iPad Air 11-inch, Air 10.9-inch, iPad 11-inch) | `plate((1640,2360), render(onesrm-icon.svg,512), 0.40)` | media query 820x1180@2 ↔ IHDR |
| `apple-splash-1080x2340.png` | 1080x2340 | §4 (3, iPhone 13 mini, 12 mini) | `plate((1080,2340), render(onesrm-icon.svg,512), 0.40)` | media query 360x780@3 ↔ IHDR |
| `apple-splash-1488x2266.png` | 1488x2266 | §4 (2, iPad mini 8.3-inch) | `plate((1488,2266), render(onesrm-icon.svg,512), 0.40)` | media query 744x1133@2 ↔ IHDR |
| `apple-splash-1668x2224.png` | 1668x2224 | §4 (2, iPad Pro 10.5-inch, iPad Air 10.5-inch) | `plate((1668,2224), render(onesrm-icon.svg,512), 0.40)` | media query 834x1112@2 ↔ IHDR |
| `apple-splash-1242x2208.png` | 1242x2208 | §4 (3, iPhone 8/7/6s/6 Plus) | `plate((1242,2208), render(onesrm-icon.svg,512), 0.40)` | media query 414x736@3 ↔ IHDR |
| `apple-splash-1620x2160.png` | 1620x2160 | §4 (2, iPad 10.2-inch) | `plate((1620,2160), render(onesrm-icon.svg,512), 0.40)` | media query 810x1080@2 ↔ IHDR |
| `apple-splash-1536x2048.png` | 1536x2048 | §4 (2, iPad Pro 9.7, Air 9.7, iPad 9.7, mini 7.9) | `plate((1536,2048), render(onesrm-icon.svg,512), 0.40)` | media query 768x1024@2 ↔ IHDR |
| `apple-splash-828x1792.png` | 828x1792 | §4 (2, iPhone 11, XR) | `plate((828,1792), render(onesrm-icon.svg,512), 0.40)` | media query 414x896@2 ↔ IHDR |
| `apple-splash-750x1334.png` | 750x1334 | §4 (2, iPhone 8/7/6s/6, SE 4.7) | `plate((750,1334), render(onesrm-icon.svg,512), 0.40)` | media query 375x667@2 ↔ IHDR |
| `apple-splash-640x1136.png` | 640x1136 | §4 (2, iPhone SE 4, iPod touch 5th gen+) | `plate((640,1136), render(onesrm-icon.svg,512), 0.40)` | media query 320x568@2 ↔ IHDR |
| `icon-44.png` | 44x44 | §3.4 | Lanczos downscale | manifest IHDR |
| `icon-50.png` | 50x50 | §3.4 | Lanczos downscale | manifest IHDR |
| `icon-71.png` | 71x71 | §3.4 | Lanczos downscale | manifest IHDR |
| `icon-150.png` | 150x150 | §3.4 | Lanczos downscale | manifest IHDR |
| `icon-310.png` | 310x310 | §3.4 | Lanczos downscale | manifest IHDR |
| `icon-310x150.png` | 310x150 | §3.4 | mark on #111, 70% of height | manifest IHDR |
| `icon-620x300.png` | 620x300 | §3.4 | mark on #111, 70% of height | manifest IHDR |

Kept unchanged (live references, never regenerated): `icon-192.png`, `icon-512.png`,
`icon-1024.png` (the source), `icon-badge.png` (push small icon), `logo-rect.png`
(wordmark). `apple-touch-icon.png` is kept-by-role but re-emitted opaque (§7.2).

### 7.2 Deviations from this spec, and why

1. **Maskable padding is a circle clip, not a scaled-down full tile.** The source is
   a full-bleed two-tone tile; scaling it to 80% still puts its corners at
   r=0.566·side, outside the 0.4 safe circle, so it can never pass. The shipped
   maskable pair (commit `ba86aee`) already resolved this: the mark is clipped to
   r=0.345 and re-plated on `#111`. `build_icons.py` reproduces that: re-running it
   against the pre-existing `icon-maskable-512.png` yields **RMSE 0.503/255** — the
   same treatment, not a second one.
2. **`apple-touch-icon.png` had an alpha channel.** The old gate checked size only.
   iOS paints transparent pixels black, so a soft-edged 180 faded into a black ring
   on the home screen. It is now `circle_clip(src, 180)` — opaque by construction —
   and the gate asserts `alpha.min() == 255`.
3. **§5.3 (extend the `sw.js` precache) is deliberately NOT done.** The spec was
   written against the hand-written worker. `app/static/sw.js` is now generated by
   `web/workbox-config.js`, whose `globPatterns` are `dist/assets/*.{js,css}` +
   `dist/manifest.json`; every unversioned `/static/*` file (icons, manifest) is
   served **network-first with a cache fallback** (`sw-template.js:162`). Precaching
   33 files — up to 38 KB each, ~600 KB total — would ship a cache-busting burden for
   assets that already update on the next online load. Nothing to change, and the
   cache name does not need a bump (it hashes only the precached dist entries).
4. **Generated on the lab, not the laptop (C3).** 33 resamples from one 1024 source
   peak at ~40 MB and finish in ~20 s; no C3 excursion was warranted. The generator
   is committed, so the operation is reproducible anywhere (`pnpm`/Node not needed).
5. **Splash artwork uses the clipped mark at 40% width**, not the `logo-rect`
   wordmark the six deleted files used. The wordmark is a different asset and the
   brief says every raster comes from `icon-1024.png`; at 40% the mark reads as a
   launch screen rather than a banner.

### 7.3 What the gate proves (and how it was broken on purpose)

`scripts/check_icons.py` reads dimensions out of the **IHDR chunk of the file bytes**
(`struct.unpack('>II', b[16:24])` + PNG magic), never from the name, then checks:
every manifest entry's declared size and `type`; the maskable safe-zone pixel scan;
Chromium's 192 + 512 `any` pair and a ≥512 maskable; the Windows tile rows; the ICO
frame set by parsing the ICO directory; `apple-touch-icon` opacity; that
`partials/pwa_head.html` exists, is included by `base.html` **and** `login.html`, and
that every other template extends `base.html` (else it gets no apple/ms tags); that
each `sizes=` attribute matches real pixels; that each splash's media query
(`device-width x sf`, `device-height x sf`) describes the actual file; and that the
old `apple-touch-startup-*` names are gone and no `apple-splash-*`/`icon-*` file is
unreferenced.

Three defects were planted in the real tree and each went red, then were reverted:
a 150x149 `icon-150.png` → `real pixels == manifest — declared (150, 150), file (150, 149)`;
a deleted `apple-splash-1170x2532.png` → `exists` (twice: file + template reference);
a copy-pasted media query → `matches its media query — query 375x812@3.0 = (1125, 2436), file (1170, 2532)`.
The script also re-runs that proof on every invocation against a synthetic tree
(clean fixture must pass, then a wrong declared size, a wrong splash query, a
1-frame favicon and a full-bleed maskable must each fail), so a green run is
evidence the gate can still fail.

### 7.4 Golden re-capture (inside this PR)

`bash scripts/capture_golden.sh` was re-run and the diff justified, not rubber-stamped:

| Golden | Before | After | Why |
|---|---|---|---|
| `totals.dom_nodes_page` | 310 | 342 | +32 head nodes: 38 emitted by the partial (23 splash links + 6 `msapplication-*` + 3 `apple-mobile-web-app-*` + 2 extra `<link rel=icon>` + manifest + apple-touch) replacing the 6 hand-written head nodes |
| `totals.dom_nodes_all_panels` | 2077 | 2077 | unchanged — no body markup moved |
| `pages./.script_tags` | 3 | 3 | unchanged — no script added |
| `pages./.html_bytes` | 52075 | 57380 | the head block (+5.3 KB uncompressed, +0.5 KB gzipped) |
| `pages./login.html_bytes` | 13745 | 18709 | login.html already had 12 of these tags; the rest arrive from the partial |
| `api_bytes` | 341714 | 904154 | 23 splash PNGs are now served URLs, so the capture pins their bytes (764 KB of `api/static_apple-splash-*.json`) — the same treatment `static_icon-192.png.json` already received |
| `screens/*` | — | reverted | PNG bytes encode the host font stack (`capture_golden.py:72`); CI compares with `--no-screens`, so no screenshot is committed from this run |

`capture_golden.py --check --no-screens` exits 0 on this tree.
