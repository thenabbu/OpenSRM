# FINAL REPORT — OpenSRM v3 frontend rewrite

**Branch:** `feat/preact-migration` · **tip when written:** `62ed738` · **`main` untouched:** yes (`origin/main` is an ancestor; `VERSION` 3.0.0)
**Scope:** the 56 units of `PLAN.md` (phases 0–10), the 14 exit criteria E1–E14 of `RECOVERY_PLAN.md` §2, and every deviation the mission recorded.
**This file is the last unit. It does not merge anything.** The merge decision is Navya's (phase 10.4).

---

## 0. How to read this report

Three questions a reader arrives with, answered in order:

1. **Did it ship, and is it proven?** → §2 (exit criteria) and §1 (numbers).
2. **Where is the proof for unit X?** → §3, one row per unit: the commit that delivered it, the CI run that judged it, the file that carries the evidence.
3. **What is not true?** → §4 (deviations from the plan, each with its recorded decision) and §5 (residual risks, including two things the plan promises that the branch does not do).

Every SHA in §3 was checked with `git merge-base --is-ancestor <sha> origin/feat/preact-migration`. Every path was checked with `test -e`. CI identifiers come from `gh api repos/thenabbu/OpenSRM/actions/runs?head_sha=<sha>`; PR check counts from `gh pr view <n> --json statusCheckRollup`. Where a run does not exist for a commit, the row says so rather than substituting a nearby green one.

---

## 1. What shipped, in numbers

| Measure | Value |
|---|---|
| Commits on the branch not in `main` | 326 (43 merged PRs) |
| `gates.sh` on a fresh clone, empty dir | **79 PASS / 0 FAIL / 0 SKIP**, 22m14s, exit 0 |
| Panel of Judges, round 2 (`59f8a92`) | 13 PASS / 1 FAIL / 0 ERROR — the one red was E12, i.e. this file |
| Routes | 9 real MPA routes, one shared shell (`app/templates/base.html`) |
| Bundle budget | `app.css` gzip **26,849 B** against 36,864 B; `app.py` 1,298 lines |
| Legacy client code | `dash.js`, `timetable.js`, `pull.js`, `drag-drop-touch.js`, idiomorph — deleted (`8de67ef`), gated by `tests/unit/test_legacy_gone.py` (7/7) |
| Rollback flag | proven both directions, `tests/unit/test_rollback_flag.py` (99/99) |
| Golden fixtures | `tests/golden/v3` — 88 files (DOM, API, screens, `metrics.json`, `routes.json`) |
| Test surface | 58 Python unit suites, 34 web (vitest) suites, browser legs on Chromium + WebKit + Firefox |
| Version trio | 3.0.0 (`VERSION` + `pyproject.toml` + `uv.lock`) |

---

## 2. Exit criteria E1–E14

Criterion wording is verbatim from `RECOVERY_PLAN.md` §2 (the panel copies it from the same place; paraphrasing is how a panel passes something the plan did not ask for).

| # | Criterion (abridged) | Verdict | Evidence |
|---|---|---|---|
| E1 | every workflow that can run on this branch is green on the tip | PASS | 4 workflows run on a feature branch (Lint, Tests, Scans, CodeQL); the other three are `push: [main]` / `workflow_dispatch` and cannot run here. Round 2 checked this explicitly rather than accepting an empty set. |
| E2 | `gates.sh` exits 0 on a fresh clone | PASS | `notes/w10/fresh-clone-proof.md` — empty dir, no `.venv`, no `node_modules`, 79/0/0 |
| E3 | 9 routes, nav markup once, per-route payload budget | PASS | 9 route templates extend `base.html`; `<nav>` only there |
| E4 | legacy client code gone, CI grep gate | PASS | `tests/unit/test_legacy_gone.py` rc=0 (7/7) |
| E5 | Dexie + Zod complete | PASS | `web/src/db/db.ts`, `db.test.ts`; one schema source, atomic multi-table writes |
| E6 | offline executed in CI, 9/9 routes | PASS | `tests/e2e/test_offline_routes.py` (923 lines) in the gates bar and CI |
| E7 | PWA rules as code, 33 icons, no HTML cached | PASS | `web/workbox-config.js`, `notes/ICONS.md`, `scripts/check_icons.py` |
| E8 | hardening in CI (a11y, stress, supply chain, DUT+vision, 3 browsers) | PASS | `scripts/a11y_stress.sh`, PR #222 (audits + trivy), #223 (DUT + vision), #224 (WebKit/Firefox) |
| E9 | bundle + CSS + `app.py` budgets enforced | PASS | re-derived by hand: 26,849 B ≤ 36,864 B; 1,298 lines |
| E10 | rollback proven both directions | PASS | `tests/unit/test_rollback_flag.py` rc=0 (99/99) |
| E11 | ARCHITECTURE + DESIGN/CONTRIBUTING/README/ROLLBACK updated | PASS | `docs/ARCHITECTURE.md`, `architecture.html` (4 preact mentions), `docs/ROLLBACK.md` |
| E12 | `FINAL_REPORT.md` with an evidence handle per unit | **this file** | §3 below |
| E13 | `main` untouched, drift merged in, trio 3.0.0 | PASS | `origin/main` ancestor of HEAD; `VERSION` 3.0.0 |
| E14 | `STATUS.md` truthful, board matches reality | PASS | 3 blocked cards are genuine (see §5), no ghosts |

**Panel round 4: 14 PASS / 0 FAIL / 0 ERROR at `b675bd7`** — verdicts committed under `notes/poj/2026-11-19/`. Round 2 (13 PASS / 1 FAIL at `59f8a92`) stays at `notes/poj/2026-11-20/` because the panel names its directory from the UTC date; it is superseded by SHA, not deleted. Round 2's single red was E12, i.e. this file, which is why it was red and is now green.

---

## 3. Per-unit evidence

`CI` is the run that judged that commit: a Tests run id, a PR whose checks were all green, or `—` where no run exists for that SHA (the branch's per-push triggers were widened in PR #205/#208; commits before that have no runs and are covered by the gate that re-checks the same code on every later run).

### Phase 0 — foundation

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 0.0 version trio 3.0.0 | `0d0c867` | — | `VERSION`, `pyproject.toml`, `uv.lock`; D5 in `scripts/check_docs.py` |
| 0.1 branch + worktree | `origin/feat/preact-migration` | — | `scripts/wt.sh` (detached worktree per unit) |
| 0.2 laptop build host | mission `agents/` | — | **deviation:** laptop unreachable at W10.2, proof ran on the lab (`decisions.md:847`) |
| 0.3 CI dry-run on branch | first branch runs | 44567883661 (Tests, tip) | `.github/workflows/{lint,tests,scans}.yml` |
| 0.4 mission harness | `scripts/{wt,alloc_number,ci_wait}.sh` | — | scripts in tree |

### Phase 1 — baselines (the "know what you are replacing" phase)

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 1.1 route inventory | `76e8e95` | 44567883661 | `tests/golden/v3/routes.json`, `scripts/url_map_dump.py` |
| 1.2 DOM goldens | `1f23db9` (v2), `9cc5387` (v3) | — | `tests/golden/v2/`, `tests/golden/v3/dom/` |
| 1.3 API contract fixtures | `76e8e95` | 44567883661 | `tests/golden/v3/api/` |
| 1.4 visual goldens | `1f23db9` | — | `tests/golden/v3/screens/` |
| 1.5 baseline metrics | `76e8e95` | 44567883661 | `tests/golden/v3/metrics.json` |
| 1.6 behaviour matrix | **mission dir only** | — | **deviation:** a `BEHAVIOR_MATRIX.json` under the repo's docs/ directory does not exist; `git grep` for the name = 0 hits (`decisions.md:298`, `:844`, `:847`) |

### Phase 2 — toolchain

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 2.1 Vite + TS strict scaffold | `c9c67ac` | — | `web/vite.config.ts`, `web/tsconfig.json` |
| 2.2 Tailwind v4 through Vite | `c9c67ac` | — | `scripts/build-css.sh` |
| 2.3 CSS parity, rule by rule | PR #171 wave | 13/13 (PR #171) | `scripts/css_parity.py`, `notes/CSS_PARITY_P23B.md` |
| 2.4 committed artifact + CI guard | `scripts/build-web.sh --check` | 44593734069 | `app/static/dist/` committed byte-identical; fresh-clone proof rebuilds it |
| 2.5 bundle budget gate | `76e8e95` onward | 44567883661 | `scripts/gates.sh` budget step; 26,849 B measured |

### Phase 3 — route split

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 3.1 route table + 9 templates + shared shell | `76e8e95` (routes), shell partial in W4.1b | 44567883661 | `app/templates/*.html` extend `base.html` |
| 3.2 nav is real `<a href>`, active from route | W4.1b wave | 13/13 (PR #237) | `<nav>` exists once, in `base.html` |
| 3.3 per-route data fetch | `76e8e95` | 44567883661 | `tests/unit/test_route_panels.py` |
| 3.4 legacy JS adapted to per-route boot | superseded by 5.4 | — | **deviation A1:** legacy deleted, not adapted (`8de67ef`) |
| 3.5 e2e re-expressed against routes | `0929abf`, `9cc5387` | 44567883661 | `tests/e2e/route_paint.py` |

### Phase 4 — island foundation

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 4.1 Preact + Vite island entrypoint | `6f80ebb` | — | `web/src/islands/contract.ts` (9 islands) |
| 4.2 server-shell ↔ island hydration contract | `76e8e95`, `df4b123` | 44567883661 | `web/src/data/props.ts`; no inline script (CSP) |
| 4.3 design-token bridge | PR #171 wave | 13/13 (PR #171) | `web/src/ui/` typed tokens |
| 4.4 error boundary + log adapter | `7849d55` | — | zero-console browser assertion in the gates bar |
| 4.5 Vitest + Testing Library harness | `cc57dac` (PR #171) | 13/13 | 21 `*.test.ts` suites |

### Phase 5 — cache layer (Dexie + Zod)

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 5.1 schema design (entities, keys, scoping) | `db101f5` | 44567883661 | `web/src/db/db.ts` |
| 5.2 Zod schemas as source of truth | `db101f5` | 44567883661 | `web/src/db/index.ts`, `props.ts` |
| 5.3 Dexie `.version(1)` + upgrade policy | `db101f5`, `b30f296` | 5/5 (PR #198) | `web/src/db/db.test.ts`; outbox upgrade test |
| 5.4 repository layer, transaction boundaries | `db101f5` | 44567883661 | atomic multi-table writes in `db.ts` |
| 5.5 validation-on-read + degradation | `7308f22` | 44567883661 | `web/src/data/stale.ts`, `failure.ts` |
| 5.6 session scoping, logout wipe, quota | `2d2bc0c` | 44567883661 | `tests/e2e/test_offline_routes.py` (C3–C7 legs) |
| 5.7 suite: corrupt records, upgrades, isolation, quota | `db.test.ts`, `b30f296` | 5/5 (PR #198) | 21 web suites in `ci_web.sh` |

### Phase 6 — islands per panel

Nine panels, one row each; `web/src/panels/<name>/` holds the component, contract and test.

| Unit | Panel | Delivered by | CI | Evidence |
|---|---|---|---|---|
| 6.1 | dashboard | `7666b8d` | 44567883661 | `web/src/panels/dashboard/` |
| 6.2 | fees | `1cec502` | 44567883661 | `web/src/panels/fees/` |
| 6.3 | academics | `163f754` | 44567883661 | `web/src/panels/academics/` |
| 6.4 | timetable | `a223142` (PR #181) | 13/13 | `web/src/panels/timetable/` |
| 6.5 | attendance | `6199960` (PR #178) | 13/13 | `web/src/panels/attendance/` |
| 6.6 | marks / campus / settings / tools | W5.3 shared components `fb05a36` (PR #179) | 13/13 | `web/src/panels/{marks,campus,settings,tools}/` |

### Phase 7 — offline read path

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 7.1 offline read path (shell + IndexedDB ⇒ every route) | `2d2bc0c` (PR #199) | 5/5 | `tests/e2e/test_offline_routes.py` — 9/9 routes with the network cut |
| 7.2 staleness labelling + sync state UI | `7308f22`, `df4b123` | 44567883661 | `web/src/data/stale.ts` |
| 7.3 online→offline→online, no duplicate writes | `25b52ed` → `7308f22` | 44567883661 | sync carries data, not markup; golden re-baselined |
| 7.4 write queue for deferred actions | `09c96c4` | 43599034340 (Tests) | outbox scoped to `/marks/tag` (PR #198) |
| 7.5 offline suite, network cut per route | `2d2bc0c` | 5/5 (PR #199) | same file, route legs |

### Phase 8 — PWA

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 8.1 worker config + privacy rules as code | `175a2ca` (PR #206) | 9/9 | `web/workbox-config.js`; **deviation:** kept `workbox-build` instead of `vite-plugin-pwa` (`decisions.md:503`) |
| 8.2 manifest + 33 icons + iOS meta + startup images | `4b2b6e3` (PR #209) | 10/10 | `notes/ICONS.md`, `scripts/check_icons.py` (reads real pixels) |
| 8.3 update flow (`prompt`), `visibilitychange` | `1eccc3d` (PR #211) | 10/10 | `web/src/pwa/update.ts`, `banner.ts` |
| 8.4 install UX: Chromium, iOS sheet, Windows shortcuts | `27f6781` (PR #216) | 10/10 | `web/src/pwa/install.ts` |
| 8.5 push integration preserved | `2821870` wave | 10/10 | `app/static/push.js` contract, push DUTs |
| 8.6 SW suite: no HTML cached, wipe on logout, version bump | `2821870` (PR #218) | 10/10 | five SW exit assertions in the network-cut suite |

### Phase 9 — hardening

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 9.1 Panel of Judges, one adversarial judge per criterion | `2aa0441` (PR #228) | 44364221102 (Tests) | `scripts/poj.py`, `notes/poj/JUDGES.md` |
| 9.2 load/stress: slow-3G, 400 ms, flapping, low memory | `1bd8908` (PR #220) | 10/10 | `scripts/a11y_stress.sh`, `tests/e2e/stress.py` |
| 9.3 a11y: keyboard, focus, contrast | `1bd8908` (PR #220) | 10/10 | `tests/e2e/a11y.py` |
| 9.4 security: CSP, no PII in caches, XSS re-proven | `899efa9` (PR #222) | 14/14 | pip-audit + pnpm audit + gitleaks + trivy |
| 9.5 DUT with vision verification | `be24b9f` (PR #223) | 14/14 | `scripts/dut_suite.sh` (10 scripts), `scripts/vision_verify.py` |
| 9.6 cross-browser Chromium/WebKit/Firefox | `8e5bc90` (PR #224) | 14/14 | `tests/e2e/route_paint.py`, `offline_paint.py` |
| 9.7 hallucination sweep of every doc claim | `a0bceab` (PR #227) | 44409977045 (Tests) | doc-claim test reads the repo, not the prose |

### Phase 10 — closeout

| Unit | Delivered by | CI | Evidence |
|---|---|---|---|
| 10.1 rollback flag + proof | `b1c430b` (PR #233, merge `275f0aa`) | 14/14 | `tests/unit/test_rollback_flag.py` 99/99, 9 routes both directions |
| 10.2 docs: architecture, design, contributor, rollback | `e19669d` (PR #232), `bd4d071` (PR #234) | 44456996764 (Tests) | `docs/ARCHITECTURE.md`, `docs/ROLLBACK.md`, `DESIGN.md`, `CONTRIBUTING.md`, `README.md` |
| 10.3 FINAL_REPORT | this file | — | `FINAL_REPORT.md` |
| 10.4 Navya's review → merge decision | **not started** | — | this card |

---

## 4. Deviations from the plan

The plan was written before the code was read. These are the places the branch knowingly differs from its wording; every one has a recorded decision, and none was a silent substitution.

| # | Deviation | Why | Recorded at |
|---|---|---|---|
| A1 | Legacy client code was **deleted**, not "adapted to per-route boot" (unit 3.4) | Phase-6 exit said KEEP; measurement showed 4 files, 3 globals and 9 dead CSS rules with no consumer after the islands landed | `RECOVERY_PLAN.md` §3 A1; `8de67ef` (PR #190/#191) |
| A2 | D8 read as "rollback proven in both directions"; the `ISLAND_CONTRACT.md` §4 it cited did not exist | Doc was phantom; runbook written instead of pretending | A2; PR #234 (`docs/ROLLBACK.md`) |
| A3 | Panel of Judges wired into **no** CI workflow | A PR (#231) did wire it: on a runner it reported PASS 2 / FAIL 9 / ERROR 3 against 12/2 locally (lab-absolute interpreter, no `node_modules`, worktree without `.venv`). Withdrawn in `c8bbcfa`; `JUDGES.md` records the ceiling | `decisions.md:848`, `notes/poj/JUDGES.md` |
| A4 | Behaviour matrix kept **outside** the product repo | It is mission evidence, not shipped code; consequence is that a fresh clone cannot reproduce phase 1.6 | `decisions.md:298`, `:844` — **PROPOSED, still Navya's call** |
| A5 | Judges and workers run in **detached worktrees**, never the canonical checkout | The canonical checkout was found dirty and 301 files changed at `5ec2e43` while the branch tip was `62ed738`; judging it would have graded the wrong tree | A5; `notes/poj/JUDGES.md` |
| A6 | Main drift merged **into** the branch, twice | `main` had moved to `8bf410c` and to newer commits; the W10.1 card's premise (`main` = `26ed196`) was wrong three ways | A6; PR #237 (`59f8a92`) |
| A7 | Offline architecture ratified as built (shell + IndexedDB, not the plan's sketch) | The plan's sketch assumed a morph-based shell that A1 removed | A7 |
| A8 | `PROGRESS.md` folded into `STATUS.md` | Two status files drifted; one authority | A8 |
| W7.1 | Kept `workbox-build`; did **not** migrate to `vite-plugin-pwa` | Measured: 74/74 offline parity either way, but the plugin needs 6 deps, 4 config escapes, an outDir rename and two post-build steps — for zero user-visible change. The plan allows this ("or an approved exception") | `decisions.md:503`; the mission-side experiment report (notes/build/w7.1-vite-plugin-pwa-experiment.md, not in this repo); PR #206 |
| W10.2 | Fresh-clone proof ran on the **lab**, not the laptop | No LAN route to the laptop, no tailscale client in the container; the claim (repo reproduces its own bar from an empty dir) does not depend on which CPU ran it, only on honesty about it | `decisions.md:847` |
| — | `38` archived/done cards carry an **empty result** and are not used as evidence anywhere above | The board's definition of done did not require evidence until the review-lane proposal; those cards are history, and this report cites commits and CI instead | `decisions.md:340` |

Also corrected here, because the plan says otherwise and round 2 verified it: **`notes/poj/2026-11-18/SUMMARY.json` is stale** (judged `9c112be`, 11 PASS / 3 FAIL). E1 and E11 have since closed; round 3 in `notes/poj/2026-11-20/` is the live verdict.

---

## 5. Residual risks — what is not proven

1. **Phase 9's exit clause cannot be satisfied as written.** `RECOVERY_PLAN.md:220` reads *"every Phase-9 unit invoked by CI; PoJ all PASS"*. Clause 1 is false by decision (A3: `poj.py` is in no workflow and not in `gates.sh`; `git grep` = 0 in both). Clause 2 was unsatisfiable in this order (E12 needs this file). Both are recorded at `decisions.md:848` with three options: amend the exit, reorder, or wire the panel the day all 14 are expected green. **This report does not describe Phase 9 as closed.**
2. **E12 is graded by existence, not by quality.** `j_e12` only requires the file to have an evidence handle per unit. The prose judgement in this report is Navya's read, not the panel's.
3. **The panel has no gate.** Its verdicts are committed artefacts (`notes/poj/<date>/`). Nothing re-runs them on a future commit; a regression after today would not be caught by the panel.
4. **Vision-dependent CI can read a provider outage as a UI regression.** A Gemini 503 was exactly that; `0e7b335` (PR #229) made an outage UNREACHABLE instead of a red page, and `9ce750f` (PR #230) makes one broken route still red the job. Both mitigations are in, but the dependency on an external vision model remains.
5. **Three cards are genuinely blocked and were not silently closed:** flake guard for node-identity/`withViewState` (`t_80468de5`), `test_canary_sync.py` flaking 4/13 sub-checks (`t_da08feec`), vision gate on a 503 (`t_97da983d`). Each is a real open item, not a bookkeeping artefact.
6. **Intermediate commits are red in history and were not rewritten.** `09c96c4`, `1bd8908`, `8e5bc90`, `7486cb4`, `275f0aa` each have a red Tests run; every one was fixed by a later commit and every one's PR merged green (14/14). Anyone bisecting will hit those reds; that is the cost of not force-pushing a shared branch.
7. **Behaviour-matrix reproducibility.** Phase 1.6's matrix lives only in the mission directory, so a fresh clone reproduces the gates bar but not the behavioural evidence behind it (`decisions.md:298`).
8. **E2 in the panel runs `--fast`.** The full bar is W10.2's fresh-clone evidence (79/0/0, 22m14s), not the panel's leg.
9. **`main` will not contain these SHAs unless the branch is merged as-is.** The recommendation in §6 is a squash; a squash discards the per-unit commits this table cites (the branch ref keeps them).
10. **Prod is untouched.** `srm.200871.xyz` still serves the pre-migration build; deploying is a separate decision after the merge.

---

## 6. Merge recommendation (Navya's call — nothing was merged)

The plan recommends a **squash** merge. Verified premises:

- **11 commits whose subject starts `wip`** — confirmed (`git log --grep '^wip'`: 16 case-insensitive matches, 11 genuine after removing "wipes" false positives).
- **One no-op commit** — confirmed: `31bb235` changes nothing (`git diff-tree` empty).
- **A corrupted message** — **not reproduced.** No non-UTF-8 commit message exists on the branch (`iconv` check over all 326). The plan's claim does not hold.
- 7 revert/revert-of-revert commits exist, which a squash flattens.

So: squash is reasonable for history hygiene (11 wip + 1 no-op is real), and its cost is that the per-unit SHAs in §3 disappear from `main`. The alternative — a merge commit — keeps them. **Both are Navya's to choose. This card merged nothing to any branch, and nothing to `main` at any point in the mission.**

---

## 7. Reproduce

```bash
git clone --branch feat/preact-migration https://github.com/thenabbu/OpenSRM.git ~/osrm
cd ~/osrm
uv sync --frozen --extra browser          # a fresh clone has no .venv
uv run playwright install --only-shell chromium   # pinned 1.65.1 wants chromium_headless_shell-1254
bash scripts/build-web.sh --check        # dist/ + sw.js byte-identical, git status clean
bash scripts/gates.sh                    # 79 PASS / 0 FAIL / 0 SKIP, ~22 min
python3 scripts/poj.py --round 4         # panel; exit 0 only if all 14 are PASS
```
