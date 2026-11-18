# Decision: supply-chain gate for `web/`, and what is accepted

**Status:** decided — `pnpm audit` gates the merge; one HIGH is accepted.
**Date:** 2026-11-18 · **Task:** W8.2

## What the card asked for, and what was already true

The card named four scans "to add": gitleaks, pip-audit, trivy, pnpm audit. Three
of the four already ran on every PR and already blocked the merge
(`.github/workflows/scans.yml`, flipped to blocking on 2026-11-05). The real gap
was the fourth: nothing audited `web/`'s node dependencies, at all.

Three other card premises were wrong and are corrected here:

- There is no `RECOVERY_PLAN.md` in the repo, and no `decisions.md`. The
  convention for a decision record is this file — `notes/DECISION-*.md`.
- `web/` does not exist on `main`. The preact client lives on
  `feat/preact-migration`, which is where this whole wave's PRs land.
- "image label == HEAD" needed no work *to the expression* — but nothing ever
  checked the artifact, so that half of the card was not actually proven. The
  label is set (`org.opencontainers.image.revision=${{ github.sha }}`, pinned by
  `test_supply_chain.py`), and the live image agrees: reading
  `ghcr.io/thenabbu/opensrm@sha256:adb79d8e…` returns
  `274efc685045dda3ab10620d257e9e23d19d1110`, the `main` commit that built it.
  A pin on the expression only proves the string is in the workflow, so a
  "Pushed image is labelled with this commit" step now reads the pushed digest
  back and fails if `revision != github.sha` or the version label differs from
  the `VERSION` file. Keyed on the digest, not `:latest`, which is mutable.

## The gate

A fourth job, `web-deps`, audits `web/pnpm-lock.yaml` on every PR to `main` and
every push. It does not run `pnpm install` — the audit reads the lockfile, so no
dependency's postinstall executes on a runner. It uses the same Node 22 and
pnpm 9.15.9 pin as the `web` job in `tests.yml`.

`scans.yml` also gained `feat/preact-migration` in its PR and push branch lists,
matching what `tests.yml` already does. Without it this job — and the other
three — never run on the branch this wave actually lands on, so the gate would
exist and never execute. That entry goes away when the migration merges to
`main`.

`pnpm audit` exits non-zero as soon as it finds anything down to `low`, and the
runner's `bash -e` kills the step at that exact moment — the trap the pip-audit
job hit before it grew a reporter. So its exit code is swallowed with `|| true`
and a Python block owns the verdict, exactly as the pip-audit job does:

- any HIGH/CRITICAL whose GHSA id is not in `ACCEPTED` → **fails the job**;
- an unreadable or missing report → **fails the job** ("the audit did not run"),
  because a green check over an unaudited tree is worse than a red one;
- an `ACCEPTED` id that stops being reported → prints a reminder to drop it.

`ACCEPTED` is a list of named GHSA ids, never a severity floor.

## Audit result at the base commit, and the disposition

Baseline (`efe9bdb`, before this branch): **2 CRITICAL, 2 HIGH, 5 moderate** in
571 packages.

| Severity | Package | Advisory | Disposition |
|---|---|---|---|
| CRITICAL ×2 | `tinypool@1.1.1` (via `vitest@3.2.7`) | GHSA-5gmw-xhrv-c9v3, GHSA-85c8-ppgw-ccpr | **fixed** — vitest 4 dropped tinypool entirely |
| HIGH | `picomatch@4.0.7` (via vite's globber) | GHSA-fc5q-39xc-vjpf | **accepted** — see below |
| moderate | `glob@11.1.0`, `minimatch@10.2.6` (via `workbox-build`) | — | below the gate; not accepted, not fixed |

**The fix.** `vitest` 3.2.7 → 4.1.12 removes `tinypool` from the tree (the lock
no longer contains it at all). Both CRITICALs are dev-only — they need a JS test
run inside the process — and they are the same two the P9.4b image scan found.
The suite is unchanged: **380 tests in 34 files pass before and after**, and the
run got faster (94.6 s → 59.8 s). No other dependency moved.

**The acceptance.** `GHSA-fc5q-39xc-vjpf` (picomatch ReDoS) has no fix to take:
the registry's newest release *is* the vulnerable `4.0.7`, and OSV lists
`patched_versions: <0.0.0`. It is reached only by vite's glob matcher while
building `web/` — picomatch is not in the image and not in the browser bundle.
It stays accepted, named, and visible in every job summary until upstream ships
a patched release; the job then prints the reminder to delete the entry.

## Proof the gate fires in all four directions

The reporter was extracted from the committed YAML and run against four inputs:

| Input | Expected | Result |
|---|---|---|
| the real lockfile (only the accepted picomatch HIGH) | pass | rc=0, summary lists 1 accepted |
| one new unaccepted HIGH | fail | rc=1, names GHSA-0000-0000-0000 |
| a CRITICAL coming back (tinypool) | fail | rc=1, names GHSA-5gmw-xhrv-c9v3 |
| no report at all (audit never ran) | fail | rc=1, "the audit did not run" |

## Re-proven alongside it

- **XSS + CSP**: `tests/e2e/test_xss.py` → 9/9 checks, `V1 ALL PASS`, including
  "no CSP violations" and its own "escaped payload IS rendered" control.
- **CSP detector is not vacuous**: a "no violations" assertion also passes in a
  world with no policy at all, so the listener was forced. Injecting an inline
  `<script>` into a live `/timetable` produced
  `Executing inline script violates … 'script-src 'self''` on the console, the
  script did not run, and the check fired. The header's text is separately
  pinned by `tests/unit/test_perf_budget.py`.
- **No PII in the offline shell**: `tests/unit/test_offline_shell.py` → 16/16,
  with its own controls ("real page contains the netid", "real page has island
  props blocks") so an empty shell cannot pass by being empty.
- **Logout wipes every cache**: `tests/unit/test_logout_wipes_caches.py` → pass,
  including the control that `opensrm-shell` exists in the worker at all.

All four suites already run in CI (`tests.yml`: unit job + the e2e `ci_e2e_http.sh`
list), so this is re-proof of live gates, not new scaffolding.

## Also corrected

`docs/SCANS.md` claimed "report-only" in its title while saying in its body that
all three jobs blocked, described a `continue-on-error` flip procedure that no
longer existed, and named gitleaks-action v2 where the workflow pins v3.0.0. The
pin meant to catch that drift asserted the *stale* text (`continue-on-error`
must be in the doc). Rewritten to what the workflow does, and the pin now
asserts the four blocking tools and the accepted advisory.
