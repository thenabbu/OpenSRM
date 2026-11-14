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
4. **Version** — you normally do not touch it. If a merge to `main` carries
   `app/` or `Dockerfile` changes without moving `VERSION`, the `Release`
   workflow's `bump` job opens a `chore(release)` PR that moves the trio
   (`VERSION` + `pyproject.toml` + `uv.lock`) and auto-merges it once the
   required checks pass: `patch` by default, `minor` when the push carried a
   `feat`, and `major` never automatically — say so in the PR body if a change
   is breaking. The trio is also checked by `check_docs.py` D5 and
   `test_audit_findings` M23, and the number renders on the login page and
   dashboard navbar. The same workflow tags `vX.Y.Z`, publishes the GitHub
   Release whose notes are generated from the commits in the range, and
   refreshes `CHANGELOG.md`. Release notes are not written by hand and do not
   live in the app.
   `main` is protected by required checks, so **nothing pushes to it directly** —
   not a human, not the bot. Everything lands through a PR.
5. **Commit** — one logical change per commit, message = finding + evidence
   + fix + how it was verified.
6. **Push + PR** — open a PR against `main`. PR CI runs **Lint**
   (`uvx ruff check app/` + `uv lock --check`) and **Tests**
   (`unit` + `docker` + `e2e`). The Docker image is pushed to
   `ghcr.io/thenabbu/opensrm` as `:latest` + `:<VERSION>` — a release push
   only, and only if the tests are
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
  `app/portal/parsers/`, dashboard view models in `app/views/`, the SCOPE
  source in `app/scope/` (client / ops catalogue / sync);
  `app.app` re-exports every moved name so imports and the Dockerfile CMD
  (`app.app:app`) keep working.
- **Two data sources** — the portal scraper (`http_scraper.py` +
  `portal/parsers/`) and the SCOPE SOAP client (`app/scope/`) are independent:
  separate sessions, separate rate limits, separate freshness windows. SCOPE
  writes one `users.scope_json` blob and a feature surface renders only when
  its `SCOPE_FEATURES` slug is on **and** that blob holds a non-empty answer.
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
- **Build** — on push to `main`: the image is built every time but pushed to
  `ghcr.io/thenabbu/opensrm` as `:latest` + `:<VERSION>` only when that push
  moved `VERSION` (a manually dispatched run builds without publishing unless
  `republish` is set), gated on `needs: [lint, tests]` so a red suite never publishes
  `:latest`. The shipped image omits the browser fallback; build with
  `--build-arg WITH_PLAYWRIGHT=1` to include it. Rollback pins
  `OPENSRM_TAG` (see AGENTS.md "Prod deploy").
- **Scans** — gitleaks / pip-audit / trivy in
  `.github/workflows/scans.yml`, **blocking**. A leaked secret, a vulnerable
  dependency or a fixable HIGH/CRITICAL CVE fails the run.
  [docs/SCANS.md](docs/SCANS.md) covers what each gates and why there is no
  `.trivyignore`-style escape hatch.
- **Deploy** — **gated, never automatic**: there is still no watcher. Nothing
  deploys until a human approves the `production` environment on a
  `workflow_dispatch` run, and `scripts/deploy_gated.sh` then does the
  mechanical part (verified snapshot, digest pin, health + render checks,
  auto-rollback). Run it with `DEPLOY_DRY_RUN=1` first; see
  [docs/runbook.md](docs/runbook.md). An auto-deploy watcher was deliberately
  removed at the maintainer's request — do not add one back. The approval gate
  is what keeps that promise while removing the 1am manual steps.

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
