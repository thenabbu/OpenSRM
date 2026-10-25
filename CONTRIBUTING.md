# Contributing to OpenSRM

Thanks for wanting to help! This guide gets you from clone to merged PR.

## Setup

### Option A: Docker (easiest)

```bash
git clone https://github.com/thenabbu/OpenSRM.git
cd OpenSRM
docker compose up -d
# Access at http://localhost:8083
```

### Option B: Local dev (venv)

```bash
git clone https://github.com/thenabbu/OpenSRM.git
cd OpenSRM
uv venv .venv && source .venv/bin/activate
uv sync --frozen --extra browser
playwright install chromium
DATA_DIR=./data gunicorn -w 1 --threads 8 -t 120 --worker-class gthread -b 0.0.0.0:8084 app.app:app
# Access at http://localhost:8084
```

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are the only toolchain
requirements. There is no Node build: CSS is compiled ahead of time by
`scripts/build-css.sh` and committed as `app/static/app.css`.

## Submitting changes

1. **Branch** — create a feature branch from `main`.
2. **Lint** — `uvx ruff check app/` and `uv lock --check` before pushing
   (both are exactly what the Lint job runs; the lock check fails if
   `pyproject.toml` changed without running `uv lock`).
3. **Test** — run the suites your change touches; everything green before
   you push. The full matrix with per-suite commands and CI runner tags is
   in [AGENTS.md](AGENTS.md#test-matrix-all-green-before-push); the
   conventions live in [tests/README.md](tests/README.md).
4. **Version** — for user-visible changes bump all three together:
   `VERSION` + `pyproject.toml`, then run `uv lock` so `uv.lock` matches
   (patch = fix, minor = feature, major = breaking/user-visible redesign;
   docs/tests-only changes get no bump). The number renders on the login
   page and dashboard navbar, and `tests/unit/test_audit_findings.py` plus
   CI both enforce the trio. **Also prepend a release entry to `NOTICES`**
   in `app/app.py` — `test_audit_findings` `M27` fails the suite when the
   head notice's version stops equaling `VERSION`, so releases without
   notices cannot ship.
5. **Commit** — one logical change per commit, message = finding + evidence
   + fix + how it was verified.
6. **Push + PR** — open a PR against `main`. PR CI runs **Lint**
   (`uvx ruff check app/` + `uv lock --check`) and **Tests**
   (`unit` + `docker` + `e2e`). The Docker image is pushed to
   `ghcr.io/thenabbu/opensrm` as `:latest` + `:<VERSION>` + `:<short-sha>`
   only after the merge lands on `main` and only if lint *and* tests are
   green there; deployment itself is manual (see
   [docs/runbook.md](docs/runbook.md)). Merges use merge commits with a
   `merge: <summary>` subject — never squash — so the atomic commits stay
   intact.

### Commit format

```
type: short description

feat: add internal marks tab
fix: captcha timing race condition
docs: update README with new features
ci: add PR trigger to lint workflow
```

## Design system

The app uses a custom dark daisyUI theme (`openSRM`). Read
[DESIGN.md](DESIGN.md) before touching any template or CSS — the theme has
unusual rules (e.g. `primary` is black, surfaces are inverted). The four
that catch people out first:

- **Tokens only** — never hex colors or Tailwind palette classes
- **Status colors follow thresholds** — ≥75% success, 65–74.9% warning,
  <65% error
- **`primary` is black** — use `accent` (white) for emphasis buttons
- **Borders, not shadows** — no gradients, glows or glassmorphism

## Architecture

- **Flask + Jinja2** — boots through `create_app()` in `app/app.py`;
  templates in `app/templates/`, static in `app/static/`. Routes live in
  seven `app/blueprints/` tables (auth, dashboard, marks, timetable, push,
  feedback, internal), shared decorators in `app/security.py`.
- **Pure code lives outside the monolith** — portal parsers in
  `app/portal/parsers/`, dashboard view models in `app/views/`;
  `app.app` re-exports every moved name so imports and the Dockerfile CMD
  (`app.app:app`) keep working.
- **SQLite** — no ORM, raw SQL through the `app/db.py` repository layer.
  All connections funnel through `app.db.connect()` (10 s busy timeout);
  request handlers share one request-scoped connection closed by the
  teardown, multi-statement units use `with transaction():`.
- **Migrations** — versioned registry in `app/migrations.py`. Add new ones
  with `@migration(version=N, description="...")`.
- **Logging** — `app/logging_setup.py`; use
  `log_with_kv(logger, level, msg, key=value)` for machine-parseable output.
- **Playwright (archived)** — the browser fallback is off by default
  (`PLAYWRIGHT_FALLBACK` unset). When enabled it uses one persistent
  browser instance with a shared context reused per netid (closed when a
  different netid logs in).
- **No JS frameworks** — vanilla JS only, no build step.
- **Service worker** — bump `CACHE_NAME` in `sw.js` when deploying static
  asset changes.

## CI/CD

- **Lint** — ruff (`app/` only) + `uv lock --check` on every push and PR.
- **Tests** (`.github/workflows/tests.yml`) — three jobs:
  - `unit` — every suite that needs no server or network, one step each,
    fresh `DATA_DIR` per step.
  - `docker` — builds the image without pushing, boots it on an empty
    volume, then seeds a fabricated user and asserts an *authenticated*
    `GET /` renders it (`/login` alone only proves the shell boots).
  - `e2e` — the Playwright suites against one gunicorn
    (`scripts/ci_e2e_http.sh`) plus the self-booting DUTs.
  - `test_login_guide_server` is deliberately **not** in CI — it performs
    7 real portal logins per run and the portal caps 10/hour per IP.
    `test_login_guide_check` **is** in CI: it mocks `/api/login` in the
    browser, so nothing reaches the portal.
- **Build** — on push to `main`: image pushed to
  `ghcr.io/thenabbu/opensrm` as `:latest` + `:<VERSION>` + `:<short-sha>`,
  gated on `needs: [lint, tests]` so a red suite never publishes
  `:latest`. The shipped image omits the browser fallback; build with
  `--build-arg WITH_PLAYWRIGHT=1` to include it. Rollback pins
  `OPENSRM_TAG` (see AGENTS.md "Prod deploy").
- **Scans** — gitleaks / pip-audit / trivy in
  `.github/workflows/scans.yml`, **report-only** by design:
  [docs/SCANS.md](docs/SCANS.md) documents what each would block on and how
  to flip one to blocking.
- **Deploy** — **manual**, there is no watcher: once CI is green on `main`,
  follow [docs/runbook.md](docs/runbook.md) (sync the compose file first,
  then `ssh lab 'cd /docker/opensrm && docker compose pull && docker compose
  up -d opensrm'`). An auto-deploy watcher was deliberately removed at the
  maintainer's request — do not add one back.

## Portal rate limits

OpenSRM protects the SRM portal on purpose. When testing, be aware:

- **Per NetID:** 3 scrapes per 10 minutes — counted only when the sync
  actually runs; a queue-timeout / busy / cooldown / budget rejection is
  free.
- **Refresh cache window:** a refresh within `SYNC_MIN_INTERVAL_S`
  (default 300 s, `0` disables) of the last completed sync is answered from
  stored data — no portal request, no quota charge.
- **Sync queue:** a second sync waits up to `SYNC_QUEUE_WAIT_S` (default
  45 s, `0` = refuse immediately) for a running one — logins ahead of
  refreshes — before it gets the busy 503. `SYNC_MAX_CONCURRENCY`
  (default 1) is how many pipelines may run at once.
- **Per IP:** 10 login attempts per hour.
- **Aggregate server→portal budget:** 30 requests per 10 minutes (full
  logins + preflights share 20, preflight capped at its own 10, refresh
  floor 10).

Don't hammer the portal during testing.

## Test hygiene

- All suites are plain scripts (no pytest): `N/M passed`, non-zero exit on
  failure. Always give a suite a fresh `DATA_DIR`.
- Tests mint session cookies and never hardcode credentials — keep it that
  way, and never loop the live-portal suites.
- Every fabricated id in a committed test uses the `zz9999` / `xx0001`
  placeholders: the repo is public.

## Questions?

Open a discussion on GitHub or reach out on Discord.
