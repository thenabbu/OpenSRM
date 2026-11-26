# Panel of Judges — one adversarial judge per criterion E1–E14

Unit 9.1 (`RECOVERY_PLAN.md:219`). The panel exists so that "done" is decided
by something that was trying to fail the work, not by the worker that did it.

Run it:

```bash
python3 scripts/poj.py                    # all 14 judges, fresh worktree at HEAD
python3 scripts/poj.py --only E1,E4       # a subset
python3 scripts/poj.py --round 2          # record a re-run
python3 scripts/poj.py --dry-run           # list judges, run nothing
```

Verdicts land in `notes/poj/<date>/E<N>.json` plus `SUMMARY.json`. Exit 0 only
when every judged criterion is PASS.

## The two tiers, and why

**`machine` — the verdict IS a command's exit code.** Eleven criteria are
already decided by gates in this repo (`test_legacy_gone.py`, `check_icons.py`,
`build-css.sh`'s 36,864 B check, `check_architecture.py`, …). A judge that
re-litigates an exit code in prose adds an opinion, not evidence — and a
confident verdict with no command behind it is the failure this project has
already paid for once.

**`llm` — a reading, only where nothing can be executed.** E12 (report quality)
is the only remaining one. Even there the judge first checks the artefact exists
before judging its contents; a missing file is not a matter of taste.

Every judge runs in a **fresh detached worktree at the tip**, never the worker's
own tree — a dirty or one-commit-behind tree would judge code that is not the
deliverable. Break-proofs must therefore be **committed** before they are visible
to a judge; editing the calling tree proves nothing.

A judge that cannot run returns **ERROR**, never PASS and never FAIL. An
unrunnable judge has acquitted and convicted nobody, and calling it FAIL puts a
phantom finding on the board.

## Round 1 — 2026-11-18, tip `8e5bc90`

**11 PASS / 3 FAIL / 0 ERROR.** The three failures are honest and each maps to
work, not to a defect in the panel:

| Criterion | Verdict | Why | Owner |
|---|---|---|---|
| E1 | FAIL | `Tests` red at `8e5bc90` (run 44338873020). `unit`/`web`/`docker` green; `e2e` fails on the Vision step — external Gemini 503/429, reproducible on the base branch with none of this code. | **new card** (see decisions.md) |
| E11 | FAIL | `docs/ARCHITECTURE.md` absent; `architecture.html` mentions preact 0 times. | `W9.1 t_5cc66987` |
| E12 | FAIL | `FINAL_REPORT.md` absent. | `W10.4` |

E11 and E12 are **not** new cards: the work that satisfies them is already
scheduled downstream, and filing duplicates is the "ghost card" failure E14
itself grades. The FAIL is the panel's way of saying "not yet", not "unowned".

## Per-criterion briefs

Each brief is what the judge does, and what would make it go red.

### E1 — every CI job green on HEAD
Reads GitHub for every workflow run at the published branch tip. Reds on any
`conclusion != success`, listing run URLs. Judging a local unpushed commit is
an ERROR, not a FAIL: no run exists to be green.

### E2 — `gates.sh` exits 0 on a fresh clone
Requires a clean tree first (a dirty tree cannot be a clone), then runs
`gates.sh --fast`. The browser tier is E8's judge; running it twice would double
the runtime for the same evidence.

### E3 — 9 routes, one shared shell, payload budget
Counts route templates (excluding `base.html` the shell and `login.html` the
unauthenticated page — including them gives 10 and a false FAIL), requires
exactly ONE template carrying `<nav>` markup, and runs `check_architecture.py`
for the `app.py` budget.

### E4 — no legacy client code
Runs `tests/unit/test_legacy_gone.py`, then asserts CI actually invokes it. A
gate nobody runs is worth nothing, and that second assertion is the part usually
missing.

### E5 — Dexie + Zod complete
Runs the Vitest `src/db/db.test.ts` suite and `test_logout_wipes_caches.py`.
Symlinks `node_modules` from the canonical checkout because a fresh worktree has
none, and the suite cannot run without it.

### E6 — offline executed in CI
Requires the offline suites to be referenced by a workflow AND
`test_offline_shell.py` to pass. "Works offline" that never runs in CI is a
claim, not a fact.

### E7 — PWA correctness
`check_icons.py` (manifest + template wiring + real IHDR sizes) and
`test_sw_precache_no_html.py` (the SW must never cache page markup).

### E8 — hardening executed and in CI
Reads **every** workflow, not just `tests.yml`: the supply-chain scans live in
`scans.yml`. Reads only `run:` content — inline commands and block-scalar bodies
— because a step's name also appears in labels and comments, so grepping raw
YAML calls a disabled step "wired". Suites that reach CI indirectly through a
driver (`.sh`) count only when **both** links hold: CI runs the driver, and the
driver runs the suite.

### E9 — bundle budgets
`app.css` gzipped must be ≤ 36,864 B (reads the live size, not the script's
constant) and `app.py` within its line ratchet.

### E10 — rollback both directions
`test_rollback_flag.py`: flag unset/empty hydrates; `PREACT_ISLANDS=0` serves a
complete server-rendered page with no island tag and no blank body.

### E11 — architecture docs
The five files exist and `architecture.html` actually mentions preact. Existence
is checked before quality; a missing file is not a style question.

### E12 — FINAL_REPORT
Exists, with an evidence handle per unit. Currently absent by plan — W10.4
writes it.

### E13 — main untouched, drift merged, trio 3.0.0
`check_docs.py`'s D5 trio check, `VERSION` == 3.0.0, and `origin/main` an
ancestor of HEAD (drift merged INTO the branch, never the reverse).

### E14 — STATUS.md truthful, board sane
Runs the mission's own `scripts/board_check.sh` (the real board invariant) rather
than judging board state itself, and requires `STATUS.md` to be fresh — stale
prose is the leading indicator of a lying one.

## Known ceilings

- **E2 is `--fast`, not the full gate.** The browser tier needs
  `PLAYWRIGHT_BROWSERS_PATH` and a venv a fresh worktree does not have. Full
  parity is E8's machine check plus CI. `ponytail:` if local full-parity is ever
  needed, pass `--full` and bootstrap the venv in the judge.
- **E12 cannot be machine-decided.** "Evidence handle for every unit" is a
  judgement about prose. The judge only proves the file exists.
- **The panel is not a CI gate, deliberately.** E1/E11/E12 are red *by plan*
  (the vision-outage run, and docs W9.1/W10.4 have not run yet). A CI job that
  fails on honestly-red criteria would block every merge for reasons that are
  not defects. Verdicts are committed instead, each carrying the `sha` it judged
  so staleness is visible: if `SUMMARY.json`'s sha is not HEAD, re-run.
  `ponytail:` add a CI gate only for the day all 14 are expected green — i.e.
  after W10 — and scope it to E1–E14 at full pass.
- **E1 depends on an external model API** for its vision step, so a red E1 can
  mean "Gemini is down" rather than "the branch is broken". The judge reports the
  run URL precisely so a human can tell those apart in one click.
