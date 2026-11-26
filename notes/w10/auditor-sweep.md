# W10.3 — final auditor sweep of E1–E14

Tip judged: `59f8a92` (`origin/feat/preact-migration`, 2026-11-20).
Verdicts: `notes/poj/2026-11-20/` (round 2, one JSON per criterion plus `SUMMARY.json`).

**Result: 13 PASS / 1 FAIL / 0 ERROR.** The only failure is E12, and E12 is
`FINAL_REPORT.md`, which the plan schedules in W10.4 — the card AFTER this one.

## Method

"Independent" here means: a session that did not build the panel, re-running it
at the tip, with each PASS spot-checked by a second command.

1. `python3 scripts/poj.py --ref 59f8a92 --round 2` in a detached worktree at the
   tip. No worker summary was used to produce any verdict.
2. Six criteria were re-derived by hand, outside the panel: E3 (route count and
   the single `<nav>` carrier), E9 (gzip size and `app.py` length), E11 (five
   docs and the `preact` count), E13 (`VERSION`, `main` ancestry), E4 and E10
   (the two suites, raw exit codes, no pipe).
3. E1 was read from GitHub, not from a log: `gh run list --branch
   feat/preact-migration`, filtered to the tip sha.

## Per-criterion result

| Criterion | Verdict | Evidence |
|---|---|---|
| E1 every workflow green on HEAD | PASS | Runs 44567882750 (CodeQL), 44567883373 (Scans), 44567883408 (Lint), 44567883661 (Tests) — all `success` on `59f8a92` |
| E2 `gates.sh` on a clean tree | PASS | `gates.sh --fast` exit 0 in a detached worktree |
| E3 9 routes, one shell | PASS | 9 route templates; `<nav>` in `base.html` only |
| E4 no legacy client code | PASS | `test_legacy_gone.py` rc=0, 7 checks; `tests.yml` invokes it |
| E5 Dexie + Zod | PASS | vitest `src/db/db.test.ts` green; `test_logout_wipes_caches.py` green |
| E6 offline in CI | PASS | offline suites referenced in `tests.yml`; `test_offline_shell.py` green |
| E7 PWA correctness | PASS | `check_icons.py` and `test_sw_precache_no_html.py` green |
| E8 hardening in CI | PASS | 7 steps reach `run:` blocks: pip-audit, pnpm audit, trivy, gitleaks, DUT, a11y, stress |
| E9 bundle budgets | PASS | `app.css` gzip = 26,849 B (budget 36,864); `app.py` = 1,298 lines, within ratchet |
| E10 rollback both ways | PASS | `test_rollback_flag.py` rc=0, 99/99 checks |
| E11 architecture docs | PASS | `docs/ARCHITECTURE.md`, `docs/ROLLBACK.md`, `DESIGN.md`, `CONTRIBUTING.md`, `README.md` present; `architecture.html` mentions preact 4 times |
| E12 FINAL_REPORT.md | **FAIL** | File absent. Plan: W10.4 writes it. |
| E13 main untouched, trio | PASS | `VERSION` = 3.0.0; `origin/main` is an ancestor of the tip |
| E14 STATUS.md, board | PASS | mission `board_check.sh` CLEAN; `STATUS.md` fresh |

## E1 is not a vacuous pass

Only 4 of the 7 workflow files ran on the tip. Checked, because "every
workflow green" is trivially true when nothing runs:

- Ran: Lint, Tests, Scans, CodeQL — the first three on `push` to
  `feat/preact-migration`, CodeQL as a `dynamic` event.
- Did not run, by trigger design: `build.yml`, `cd-oclab.yml`, `release.yml`
  (`push: [main]`), `deploy.yml` (`workflow_dispatch` only).

So every workflow that can run on this branch did run, and all passed. The
four that did not run cannot run on a feature branch.

## The committed round-1 summary is stale

`notes/poj/2026-11-18/SUMMARY.json` records `sha 9c112be`, 11 PASS / 3 FAIL
(E1, E11, E12). The tip has moved far past it. The panel's own rule is "if
`SUMMARY.json`'s sha is not HEAD, re-run", so that file is history, not
current truth. Round 2 above supersedes it: E1 and E11 have since been closed
by real work (W10.2's green CI runs; W9.1's docs), leaving E12.

## Plan contradiction: W8's exit cannot hold at W10.3

`RECOVERY_PLAN.md:220` — *Exit: every Phase-9 unit invoked by CI; PoJ all PASS.*

1. **"Every Phase-9 unit invoked by CI" is false, and deliberately so.**
   `scripts/poj.py` appears in no workflow and not in `scripts/gates.sh`
   (`git grep` = 0 hits in both). A PR (#231) did wire it and the step reported
   `PASS 2 / FAIL 9 / ERROR 3` on a runner against `PASS 12 / FAIL 2` locally —
   phantom failures from lab-absolute paths, a missing `node_modules` and a
   worktree with no `.venv`. It was withdrawn in `c8bbcfa`, and `JUDGES.md`
   records "the panel is not a CI gate, deliberately". The clause is therefore
   unmet by a recorded decision, not by an oversight.
2. **"PoJ all PASS" is unsatisfiable in this order.** E12 needs
   `FINAL_REPORT.md`; W10.4 writes it after this card. Judging E12 red is
   correct, but no amount of work inside W10.3 can turn it green.

This needs Navya's ruling, not a rewrite of plan scope. Options: accept and
defer (amend the exit to "all PASS except E12 until W10.4"), reorder W10.4
before the sweep, or wire the panel into CI on the day all 14 are expected
green — the ceiling `JUDGES.md` already names.

## Residual risks

- **E2 is judged with `--fast`.** The full bar at this same sha is W10.2's
  fresh-clone evidence: 79 PASS / 0 FAIL / 0 SKIP, 22m14s, log at
  `/opt/data/missions/opensrm-preact/reports/w102-fresh-clone-gates-green.log`.
- **E5 symlinks `web/node_modules`** from the canonical checkout, because a
  detached worktree has none. The web suite also runs through `ci_web.sh` in the
  gates bar and in CI, so the dependency is not the only proof.
- **E12 is unverifiable** until W10.4 exists.
- **PoJ has no gate** (above): the verdicts are committed evidence, and a human
  or W10.4 must read them.
- **The behaviour matrix is referenced nowhere in the tree** (W10.2's finding,
  re-confirmed: `git grep` = 0 hits). It is not an E-criterion, so it does not
  change this verdict; committing it remains Navya's open decision.
