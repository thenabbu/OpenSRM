# OpenSRM test suite

Plain-script convention (no pytest): every suite runs its own checks, prints
`N/M passed`, and exits non-zero on failure. This folder is organised so a
suite's **name and location tell you what it is**:

```
tests/
├── unit/                        36 suites — no server, no browser, no network
├── e2e/                         20 suites — Playwright browser DUTs
│   └── run_push_duts.sh         boots the 3 gunicorn instances push DUTs need
├── _seed.py                     shared seeder + require_own_server() guard
├── _canary_stub_app.py          gunicorn entry used by test_canary_sync
├── _capture_before_after.py     manual before/after screenshot helper (not a suite)
├── fixtures/                    committed sanitized portal responses
└── README.md                    this file
```

## Naming conventions

- `tests/<layer>/test_<topic>.py` — every suite starts with `test_`, the layer
  directory says how it runs, the topic says what it covers.
- `_dut` suffix = browser flow test (drives the real UI); `_view` = pure view
  model (unit); `guide_*` trio was renamed to `test_login_guide_{static,check,server}`.
- `_`-prefixed files at the root are helpers — never run them directly.
- One suite = one CI step, so a red suite names itself in the checks UI
  (`.github/workflows/tests.yml`).

## Running

```bash
# single unit suite — always give it a fresh DATA_DIR
DATA_DIR="$(mktemp -d)" .venv/bin/python tests/unit/test_exams.py

# every unit suite (what CI's `unit` job does, one process each)
for f in tests/unit/*.py; do DATA_DIR="$(mktemp -d)" .venv/bin/python "$f" || echo "FAIL $f"; done

# browser suites that need a server (one gunicorn behind all of them)
bash scripts/ci_e2e_http.sh test_sw test_xss test_navbar ...

# self-booting e2e (bring their own server)
DATA_DIR="$(mktemp -d)" .venv/bin/python tests/e2e/test_dash_fit.py
.venv/bin/python tests/e2e/test_dut_official_tt.py

# push DUTs (staggered boots on 18185/18186/18187)
VENV="$PWD/.venv" bash tests/e2e/run_push_duts.sh
```

**Careful:** `tests/e2e/test_login_guide_server.py` performs 7 REAL portal
logins per run (portal caps 10/hour/IP) — it is deliberately not in CI.

## What each suite covers

The full per-suite matrix (check counts, contracts, runner tags) lives in
`AGENTS.md` — search for `# [unit]` / `# [e2e]`. CI runs every `[unit]` and
`[e2e]` row on each PR via `.github/workflows/tests.yml`; `[none]` rows are
manual-only.
