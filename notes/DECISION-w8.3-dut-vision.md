# W8.3 — the screenshots finally get looked at (and the DUT/dist half was already done)

Card: t_42a5278c. Plan reference: "RECOVERY_PLAN.md:214 W8.3 Unit 9.5".

## The card's premise was wrong four ways

1. **`RECOVERY_PLAN.md` is not in this repo**, and neither is `decisions.md`.
   The plan lives in the mission directory; the repo's convention is
   `notes/DECISION-*.md`. This file follows that.
2. **"DUT 10/10 in CI" was already true.** The only DUT that reports a score in
   the form 10/10 is `tests/e2e/test_page_chrome_dut.py` (10 `check()` calls:
   SW registration on a panel route, the tracking beacon, the offline banner,
   the settings-group disclosure at 1280 and 375 px). It has run in the `e2e`
   job through `scripts/ci_e2e_http.sh` since long before this card — measured
   on this tree: `test_page_chrome_dut | rc=0 | 27s | 10/10 passed`.
   `scripts/dut_suite.sh` runs 14 DUT scripts and all 14 were in CI too, with a
   step that *asserts* that coverage (`dut_suite.sh coverage`) so a new DUT
   cannot be added and silently never run. Nothing was missing there.
3. **"Against built dist" was only half true.** The suites do run against the
   committed `app/static/dist`, but nothing on any runner rebuilt that bundle
   from the source in the same tree, so a source edit with a stale dist passed
   every gate. Fixed by `scripts/build-web.sh --check` in the `web` job: rebuild,
   then `git diff --exit-code` on the two committed build artifacts.
   `build-web.sh` only checked `app/static/dist/` — it now also checks
   `app/static/sw.js`, which carries a build hash and is the file the service
   worker actually caches.
4. **Vision verification did not exist at all.** `tests/golden/v3/screens` holds
   27 committed screenshots (9 routes × 3 viewports) and no gate had ever
   compared them to anything: the drift gate runs with `--no-screens` because
   PNG bytes encode the capture host's font stack. A screenshot nobody looked
   at is not verification.

## What was built

`scripts/vision_verify.py` — judges every route at mobile (390×844) and desktop
(1440×900) width with a vision model, and writes a verdict file per pair
(`notes/vision/<route>-<device>.json`) plus `notes/vision/index.json`.
Exit 0 = every pair MATCH, 1 = a DIFF or an unreadable answer, 2 = cannot run
(no capture, no key). A missing key is a red step, never a skip.

In CI it reuses the capture the golden drift step just made — the drift step now
passes `--out "$RUNNER_TEMP/golden-ci"`, so one browser pass feeds two gates
instead of two. `capture_golden.py` honours an explicit `--out` in `--check`
mode for exactly that reason.

## Why it does not diff the screenshots against the golden

That version was built first and measured wrong. Feeding the model the golden
and the fresh capture and asking "same page?" produced, in 18 pairs, two
invented failures:

| pair | the claim | what the DOM said |
|---|---|---|
| academics-mobile | "label renamed, shows only `(P)`" | `dom/academics.html` byte-identical to the golden's (diff: empty) |
| timetable-desktop | "unescaped HTML payload on screen" | no literal markup in either DOM; the seed plants an XSS payload as a subject name on purpose (`tests/_seed.py:11`) and it is correctly escaped |

Content drift is already proven byte-exactly by the drift gate's `dom/`+`api/`
diff; a vision model reading 11px labels cannot arbitrate it and must not try.
So the model is asked the one question no byte diff can answer — **is this page
broken** — against six observable classes (blank panel, clipped/overflowing
content, blocks drawn on top of each other, unstyled markup, unreadable text,
a page that is mostly blank below the navigation).

Two further measured refinements:

* **Screenshot artifacts are named in the prompt, not argued with.** A full-page
  capture paints a `position: fixed` bottom bar once, at the scroll position, so
  it always appears to cover later content; the seed's XSS payload text is a
  pass condition. Both are excluded by name.
* **A single model's "broken" is a hypothesis.** A flagged pair gets two more
  opinions and the majority decides. Measured: the fixed-nav artifact had one
  model reporting "blocks drawn on top of each other" on `dashboard-mobile`,
  which two models rejected.

## The gate found a real bug on its first live run

`dashboard-mobile` was flagged, and this time it was true. Measured with
`getBoundingClientRect` at 390px, before the fix:

| box | value |
|---|---|
| exam-card header row | 374px wide, 41…349 usable |
| left group (`End sem exams` + `Nov 2026` + `Estimated`) | 262px of content in a **179px** box (`scrollWidth` 262) |
| `Estimated` badge right edge | x = **303** |
| `First exam in 11 days` left edge | x = **228** |

→ 75px of the badge drawn on top of the countdown text, on a 390px phone.
Pre-existing (the old golden showed it too), found by the vision gate, invisible
to every pixel-free gate in the repo.

Fix: the header row wraps (`flex-wrap` + `gap-y-1`) so the countdown drops to its
own line when the badges no longer fit — in `web/src/panels/dashboard/DashboardPanel.tsx`
and its Jinja twin `app/templates/partials/widgets/exams.html`. After: left group
262/262 (fits), overlap 0 at 360, 390, 768 and 1440. `app/static/dist` and
`app/static/sw.js` rebuilt; `tests/golden/v3` recaptured (`dom/`, `api/`,
`routes.json`, `metrics.json` and the 27 screens, all from one capture at one
revision on one host).

## Evidence that the gate is not vacuous

| run | result |
|---|---|
| 18 real pairs, this tree | 18/18 MATCH, exit 0 |
| doctored `marks-390x844.png` (panel area painted flat) | DIFF, exit 1 — untouched `marks-desktop` in the same run MATCH |
| doctored `fees-1440x900.png` (everything below the header wiped) | DIFF, exit 1 — this one initially passed, which is why class (f) exists |
| `check_docs.py` D8 without the `gates.sh` entries | FAIL — a CI step that gates.sh never learned about |
| `capture_golden.sh --check --no-screens --out DIR` | exit 0, and the capture is kept in `DIR` |

## Body I touched and the landmine in it

`capture_golden.py` deleted `out.parent` on a clean `--check` run — safe only
while `out` was always `<mkdtemp>/capture`. Honouring an explicit `--out` made
that expression reachable as "delete the caller's parent directory": measured,
`--out /tmp/golden-ci` ran `shutil.rmtree("/tmp")`. It is now `tmp_root`, set
only from the `mkdtemp` call, and an explicit `--out` is never deleted.

## Key + guard

The step needs `GEMINI_API_KEY` (set on the repository as a secret; the lab's
`GOOGLE_API_KEY` is the same key). 18 calls per run at flash-lite tier, ~2s
each. Fork PRs never receive repository secrets, so the step carries the same
guard the GHCR upgrade smoke uses — GitHub does not hand secrets to a
`pull_request` run from a fork, and a contributor cannot fix that.

## Reading a verdict file

`notes/vision/<route>-<device>.json` records the verdict, the class, the model,
the answering model's corroborators (only when a pair was flagged), and the
hashes of the golden and the fresh capture it judged.

On the capture host the two hashes are equal (the golden was made there). **In
CI they are not, and that is expected**: the drift gate runs `--no-screens`, so
what it proves is `dom/`, `api/`, `routes.json` and `metrics.json`, never the
PNGs - a GitHub runner's font stack is not the lab's. Measured on run
44278658012 (`dashboard-mobile`): `golden_sha` 754409cc9fd764a3 vs `fresh_sha`
37574efbdf48d3fb, verdict MATCH. The judge is asked *is this page broken*, not
*is this the golden*, which is why a font-stack difference is not a failure and
why the hash is recorded rather than compared.

## Proof, in CI, on the pushed branch

Two things had to be true and both were measured on head `40585a5`, all 14
checks green, `mergeStateStatus: CLEAN`:

| what | where it shows |
|---|---|
| `test_page_chrome_dut \| rc=0 \| 11s \| 10/10 passed` | `e2e`, through `ci_e2e_http.sh` |
| the dist the DUTs drive is the one `pnpm build` produces | `web`: `build-web: app/static/dist/ app/static/sw.js matches committed output` |
| `golden OK: 746c069 matches tests/golden/v3` | `e2e`, drift step |
| `vision: 18/18 pairs MATCH (0 not a MATCH)` | `e2e`, vision step, per-pair timings 0.7-72.7s |
| the pixels the model saw are kept | artifact `vision-verdicts` (1.2 MB, 18 verdicts + 18 PNGs) |

The timings are the anti-vacuity check: 18 pairs at roughly two seconds each is
18 real model calls, not a cached table. `scripts/dut_suite.sh` coverage is
asserted in the same job (`dut_suite.sh's 14 DUT scripts all run in this job`),
so a new DUT cannot be added and silently never run.

## One flake, named rather than hidden

`test_canary_sync` red on the first push of this branch ("refresh not ok (http
302)") and green on the identical re-run - 13/13 locally both times. It boots
its own gunicorn and mints its own session; nothing this branch touches is on
that path. The suite's own docstring already records it going red on CI twice
while passing 13/13 locally. Left as a known flake, not papered over.
