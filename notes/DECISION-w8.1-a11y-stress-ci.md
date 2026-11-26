# W8.1 — a11y + stress gates, and why they were never in CI

Card: t_fe34ad8c. Plan reference: "RECOVERY_PLAN.md:212 W8.1 Unit 9.2/9.3".

## The card's premise was wrong three ways

1. **RECOVERY_PLAN.md does not exist in this repo.** `git ls-files` has no such
   path and never has; the same is true of the other plan-worded artefacts this
   mission has chased. The plan's wording was therefore taken as the
   requirement, not the plan file.
2. **Neither suite was greenfield.** Both already existed before this card:
   `tests/e2e/a11y.py` (axe-core over 9 routes, commit `830cceb`) and
   `tests/e2e/stress.py` (slow / flaky / reloads, commit `ab23933`).
   `scripts/a11y_stress.sh` already booted one seeded server for both, and
   `scripts/gates.sh` already ran it locally.
3. **"Extend route_paint.py rather than building a second driver" is the wrong
   home.** `route_paint.py` is the paint driver for the offline proof. Adding
   a11y and stress to it would have produced exactly the second driver the card
   warns against. The two existing drivers are the right place, so the work went
   there.

There is also no `decisions.md` in this repo; the convention is
`notes/DECISION-*.md` (four such files already). This file follows that.

## What was actually missing

**CI.** Nothing ran `a11y_stress.sh` on a runner. `grep a11y .github/workflows/tests.yml`
returned nothing: locally green, never executed in CI — the exact failure this
mission keeps buying.

**The mechanism.** `check_docs.py` D9 globs `tests/e2e/test_*.py`. A driver
named `a11y.py` or `stress.py` is invisible to it, so the "every e2e suite runs
in CI" check could not see these two. Fixed with **D10**: every
`tests/e2e/*.py` that is not `test_*`/`_*` must be reachable from CI through a
`.sh` that CI names. `probe_sw.py` is exempted by name because it is a
diagnostic printer with no PASS/FAIL and no exit code.

**Behaviour the plan named that the suites did not test.** Measured, not assumed:

| Plan wants | Before | After |
|---|---|---|
| slow-3G throttle | 400 ms latency only (`page.route` sleep) | unchanged — latency is the dominant 3G term for a 32 KB shell; bandwidth emulation bought no new failure mode |
| offline flapping | absent (`offline_proof.sh` covers one cold cut) | stress leg 4: cut → navigate → restore → recover, no reload |
| low memory | absent (leg 3 only reloaded 5x) | stress leg 5: 4x CPU throttle + heap churn, heap read back as evidence |
| keyboard navigation | absent | 12-stop Tab walk per route, no trap, >= 5 stops |
| visible focus | absent | every focus stop must draw a ring; controlled by a stripped-indicator probe |
| landmarks/names | **not run at all** — axe was filtered to `wcag2*` tags and every landmark rule is `best-practice` | `best-practice` tag added, `region`/`landmark-one-main`/`landmark-unique` made fatal |

## Defects the new assertions found (both fixed here)

- **All 9 routes: `region` violation.** Both navbars are `<div class="navbar">`
  — no landmark — so the brand, the sync button and the refresh control sat
  outside every landmark. Both bars are now `<header ... role="banner">`
  (`app/templates/base.html`).
- **`/fees`: `<summary>` had no focus ring.** `<summary>` is natively focusable,
  so every receipt row was a keyboard stop with nothing on screen. Only
  `.hw-mrow` had a ring (`timetable.css`). One rule now covers all of them
  (`app/static/src.css`, mirrored verbatim into `web/tailwind.css` as that file
  requires).

## Notes on the low-memory leg

Chromium exposes no heap cap to a page, and this build has no
`Emulation.setPressureNotificationsSuppressed` (measured: protocol error). The
leg therefore applies real pressure (4x CPU throttle) plus real allocation, and
reads `performance.memory.usedJSHeapSize` back — if the heap is unreadable the
leg fails as a broken control rather than passing vacuously.

## Build artefacts

`dist` and `static/sw.js` are generated, so the CSS rule had to reach both:

- `vite build` renames **every** chunk, not just the CSS one. Checked at HEAD:
  a build of pristine `2821870` reproduces the committed names exactly
  (`app-B9v6EFlW.js`, `app-DBMf-GRo.css`), so the churn is the chunk-graph hash
  reacting to the CSS and nothing else moved.
- `node workbox-config.js` must follow `vite build`. Running only `vite build`
  leaves `static/sw.js` precaching the deleted chunk names, and the worker then
  fails to install — `test_sw` went 1/5. Regenerated: cache `opensrm-v69-22b55316`.
- Goldens: no re-capture was needed. The dist assets appear in the captures as
  `static_dist_assets_app-HASH.css.json`, i.e. hash-normalised, and a fresh
  capture after the rebuild diffed clean against `tests/golden/v3`.
