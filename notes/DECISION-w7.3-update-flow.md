# Decision: the update flow is a prompt, not a guard — the swap is still silent, and the banner is off-screen

**Status:** proposed — **two gaps confirmed, two plan asks already met.** Neither gap is a
wording problem, so the recommendation is to change code in both places, not the plan.
**Shipped:** W7.3c (`8.3-SWAP-IS-OPT-IN`) — the swap is no longer silent: a first install still
takes over at once, an update waits in `waiting` and the user sees
"A new version of openSRM is ready." with a Reload button, which posts SKIP_WAITING and reloads.
**Date:** 2026-11-17 · **Task:** W7.3 (`RECOVERY_PLAN.md:208`, "update flow `prompt` +
`visibilitychange` check, visible \"New version → Reload\", never a silent swap; test").

## The four asks, measured at `9c533b2`

| # | `RECOVERY_PLAN.md:208` asks for | verdict | evidence |
|---|---|---|---|
| 1 | a visible "New version → Reload" | **half met** | the control exists and ships (`web/src/pwa/banner.ts:77`, in `app/static/dist/assets/app-*.js`, mounted from `web/src/main.ts:550`) — but it renders **off-screen**. See §1. |
| 2 | a `visibilitychange` check | **absent** | `grep -rn visibilitychange web/src app tests` → **0 hits**. Nothing calls `registration.update()` either. |
| 3 | never a silent swap | **unmet** | `web/src/sw-template.js:45` (skipWaiting on install) + `:69`/`:72` (`clients.claim`) = the new worker activates and claims a page that is already running. `update.ts` detects the aftermath; it does not prevent it. See §2. |
| 4 | a test | **met (was half met)** | `update.test.ts` covers the event wiring only; nothing asserted what the user sees. `web/src/pwa/banner.test.ts` is new in this change. See §4. |

`update.ts` is **not** rewritten: its reasoning is sound and this note explains why the
plan's wording cannot be met without moving the constraint it documents.

## 1. The banner is a real button the user cannot see

`banner.ts:33` gives the element
`fixed bottom-20 left-4 right-4 z-50 mx-auto max-w-md …`. Of that string, `bottom-20` and
`shadow-lg` are **missing** from the compiled CSS and the rest are present (`alert`,
`alert-info`, `fixed`, `left-4`, `right-4`, `z-50`, `mx-auto`, `max-w-md`, `text-sm`) —
so this is not a stale build. `scripts/build-css.sh` builds `app/static/src.css`, which is
`@import "tailwindcss" source(none)` plus an explicit `@source` list
(`app/static/src.css:11-15`) naming `templates`, `views`, `app.py`, `static/*.js`,
`safelist` — and **not `web/src`**. `web/tailwind.css:14-18` (the Vite entry that produces
`app/static/dist/assets/app-*.css`) carries the same five lines. So a class that appears
**only** inside the Preact tree is never generated.

`bottom-20` is exactly that, so a `position:fixed` element ends up with `top:auto;
bottom:auto`, which resolves to its **static position** — the end of the document flow.

Measured in Chromium (390x844, the shipped `app-*.css`, the exact class string from
`banner.ts:33`):

| page height | banner `top` | viewport | in viewport |
|---|---|---|---|
| 2400 px (every real route) | **2400 px** | 844 px | **no** |
| 300 px | 300 px | 844 px | yes, but not pinned to the bottom / not clear of the dock |

Not a stale build: the same file *does* contain `left-4`, `right-4`, `z-50`, `alert-info`,
`btn-sm`, `max-w-md`, so the utilities that also occur in `app/templates` were generated
and `bottom-20`/`btn-circle` were not.

**It is not one class.** Sampling `className` tokens in `web/src/**/*.ts*` against the
dist CSS, 5 of 24 are missing: `bottom-20`, `btn-circle`, `shadow-lg`, `text-[11px]`,
`text-base-content/50`. So islands ship a few silently-unstyled elements too.

**Fix (one line per entry, then a rebuild):** add `@source "../web/src"` to
`app/static/src.css` and `@source "../src"` to `web/tailwind.css`. Measured:
`build-css.sh` then emits 155311 B / **25296 B gzipped**, inside the 36864 B budget, and
`scripts/css_parity.py` cannot regress — its check 7 only requires legacy ⊆ dist, and this
widens dist. Verified present after the change: `bottom-20`, `btn-circle`.
Do **not** work around it by swapping in `bottom-0` (the only `bottom-*` in the current
CSS): that puts the alert against the screen edge, under the dock it uses `bottom-20` to
clear.

## 2. "Never a silent swap" is real, and the reason `skipWaiting` exists does not apply to updates

`sw-template.js:35-44` justifies skipWaiting with a **fresh-profile** measurement: without
it "the registration never reaches `activate` and `navigator.serviceWorker.controller`
stays null … `[FAIL] online: service worker is controlling the page`". That is true, and it
is an argument about a FIRST install. It was generalised to updates, where it was never
measured, and that generalisation is the silent swap:

- a new worker installs, `skipWaiting()` promotes it, `activate` runs `caches.claim()`
  **and** deletes every cache except the new `CACHE_NAME` (`sw-template.js:66-68`);
- `controllerchange` fires, and `update.ts:37` turns it into a banner.

So the swap has already happened by the time the user is told about it. The window that
hurts is the **first page load after a deploy**: the old worker serves old HTML (old asset
hashes), the new worker activates and drops those hashes from cache mid-parse, and a chunk
that has not been fetched yet answers 404 — the island never hydrates, which is the exact
failure class this migration already paid for (`P6/P7 islands never hydrated`). `web/src`
imports its chunks only at hydration (`main.ts:41-52`) and there is no client-side
navigation, so a swap in an already-hydrated tab is close to harmless — the danger is
narrow but it is the load that follows a deploy.

**Two options.**

*Change the wording* — record that "prompt after the swap" satisfies the intent. Rejected:
it does not describe the code, and `decisions.md:134` (2026-11-13, `8.3-DOWNGRADE`)
already rejected this exact downgrade in writing.

*Change the worker* — **recommended**, and it is a condition, not a rewrite. The
discriminator the comment already implies:

```js
self.addEventListener('install', () => {
  // First install: take over at once (the fresh-profile constraint above is real).
  // An UPDATE must wait: claiming clients mid-load swaps the bundle under a page
  // that is still fetching its chunks from the previous generation.
  if (self.registration.active === null) void self.skipWaiting();
});
```

`registration.active` is the outgoing worker exactly during an update, so this keeps the
measured first-install behaviour and makes an update wait. When it waits, `activate` never
runs, so the cache wipe above cannot touch the page still being served — the cleanup lands
on the reload that opts in. Then `update.ts` gains its second signal (`updatefound` →
`installing.state === 'installed'` with a controller present) and `applyUpdate` messages
`registration.waiting` instead of `controller`. `controllerchange` stays as the reload
trigger; `update.ts:46-51`'s "did this page already have a controller" guard stays as is.

## 3. Why the `visibilitychange` check is the same unit of work, not a separate one

`decisions.md:134` gives a second reason the plan wants it: **iOS Safari does not fire
`controllerchange` reliably**, so on iOS today the banner may never appear at all — the
signal is the whole feature there. But a re-poll is not free *while skipWaiting is
unconditional*: `registration.update()` on regaining focus is exactly what forces an
install → promote → claim at an arbitrary moment, i.e. it manufactures the mid-load swap
§2 describes. Shipping the poll before the worker guard would make ask 3 measurably worse.
So: same card, worker first, then the poll, then the test that both hold.

## 4. What shipped in this change

`web/src/pwa/banner.test.ts` (4 tests) asserts the user-visible half that `update.test.ts`
cannot see: the element is mounted into `<body>`, hidden on a normal load, then shows
`A new version of openSRM is ready.` with a **Reload** button; a first-time visitor is
never told to reload; clicking Reload reloads exactly once (armed by the click, fired by
the following `controllerchange`, and not twice); dismiss hides it and sets
`pwa-banner-dismissed`. Break-proved: changing the copy to `Update available` → 1 red;
commenting out `el.classList.remove('hidden')` → 1 red; restored → 4 green.

## Reopen conditions

- The CSS fix is worth doing the moment anything else rebuilds `dist` (W7.4 must, for
  `shortcuts`/`display_override`) — one rebuild, one golden capture, not two.
- The worker guard reopens if a first-install path is found where `registration.active` is
  non-null on a genuinely fresh registration, or if CI's `online: service worker is
  controlling the page` leg goes red with the condition in place.
