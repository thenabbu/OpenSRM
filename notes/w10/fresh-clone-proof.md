# W10.2 — fresh-clone proof

Proves the branch builds, gates and serves from the remote alone: no local
`.venv`, no `node_modules`, no uncommitted file, no mission-directory input.

- **Proven commit:** `59f8a92` (`feat/preact-migration`, the W10.1 merge tip)
- **Result:** GATES GREEN, exit 0 — **79 PASS / 0 FAIL / 0 SKIP** in **22m14s**
- **Ran:** 2026-11-19, on the lab (`hermes` container, 2 cores / 7.1 GB, ~2 GB
  free), not on the laptop — see *Deviations*.

## The sequence, as run

| Step | Command | Result |
|---|---|---|
| Empty dir + clone | `git clone --branch feat/preact-migration --single-branch git@github.com:thenabbu/OpenSRM.git w102-fresh` | `59f8a92`, 1014 files, **34 s**. `.venv` and `web/node_modules` absent — the clone really started empty |
| Python deps | `uv sync --frozen --extra browser` | **23 s**, from `uv.lock` alone |
| Browser (CI runner step) | `PLAYWRIGHT_BROWSERS_PATH=/opt/data/home/.cache/ms-playwright .venv/bin/playwright install --only-shell chromium` | **43 s**, 125.9 MiB, `chromium_headless_shell-1254` |
| Web build vs committed output | `bash scripts/build-web.sh --check` | **24 s** — `pnpm install --frozen-lockfile` + `pnpm build`, then `build-web: app/static/dist/ app/static/sw.js matches committed output`; `git status` clean |
| The bar | `PLAYWRIGHT_BROWSERS_PATH=… bash scripts/gates.sh` | **GATES GREEN**, exit 0, **22m14s** |
| Serve | `bash scripts/dut_server.sh start 18190 serve` | `/healthz` 200, `/login` 200 (19,198 B), `/` 302 to login |

Gate breakdown: lint 4, static gates 8, unit suites 58, browser suites 9
(`ci_e2e_http.sh` 26 suites · `dash_fit` · `dut_official_tt` · `offline_routes` ·
push DUTs · offline proof · a11y+stress · 11-script DUT suite · golden drift).
Nothing was skipped, so the verdict is the full bar and not a PARTIAL (exit 3).

Two cross-checks that the clone is not quietly reusing local state:

- the rebuilt `app/static/dist/` and `app/static/sw.js` are **byte-identical** to
  what is committed (`git status` = 0 changes after the build);
- the served `/login` references `app-Bo9zt5Qb.js`, the exact chunk hash this
  clone's own Vite build emitted.

## Two setup steps the plan's wording omits

Both are ordinary CI runner setup, not repo defects — but a "fresh clone"
procedure that leaves them out goes red and looks like a broken branch.

1. `uv sync --frozen --extra browser` — a clone has no `.venv`, and `gates.sh`
   and `offline_proof.sh` both expect `.venv/bin/python` at the tree root.
2. `playwright install --only-shell chromium` — the pinned playwright (1.65.1)
   wants `chromium_headless_shell-1254`; a shared browser cache that already had
   `1248` fails **7 browser steps** with `Executable doesn't exist`. That was the
   first attempt here (log kept alongside this run), and it is the same class of
   false red that has burned earlier runs by pointing `PLAYWRIGHT_BROWSERS_PATH`
   at the wrong path.

## Scope: the behaviour matrix is not part of this proof, and not hidden

`docs/BEHAVIOR_MATRIX.json` / `.md` and `notes/build/w5.0-matrix-rebaseline.md`
live only in the mission directory and are **absent from this tree**. Measured,
not assumed:

- `git ls-files | grep -i BEHAVIOR_MATRIX` → nothing
- `git grep -n -iE 'behavior[_ ]?matrix|behaviour[_ ]?matrix|w5\.0-matrix-rebaseline'` → **zero hits anywhere in the tree**, including `scripts/` and `.github/workflows/`

So no gate reads it, no doc cites it, and this proof neither passes nor fails on
it. That is the honest statement of scope: the matrix is unreferenced evidence,
not a build input. Whether it should be committed is still an open decision
(mission `decisions.md`, 2026-11-15 and 2026-11-19) and is **not settled here.**

## Deviation: laptop unavailable, so the bar ran on the lab

`lap` reported the laptop unreachable on LAN (`192.168.29.170`, no route) and
tailscale (no client in this container), so the run went to the lab, against the
2026-11-07 decision that builds run on the laptop. The proof's claim — the repo
reproduces its own build and gate bar in an empty directory — is not affected by
where the CPU sat, and the run did complete green on 2 cores / ~2 GB free. It
did make the run slower than it would be on the laptop.

## Deviation found while proving: the Panel of Judges is not wired to any gate

`scripts/poj.py` and `notes/poj/2026-11-18/*.json` (E1–E14 verdicts) are
committed, but **neither `scripts/gates.sh` nor any `.github/workflows/*.yml`
invokes `poj.py`** — so the W8.6 panel is committed evidence with no gate behind
it, while the plan describes it as running in CI. Not fixed here (out of scope
for a proof card); flagged for the W10.3 auditor.
