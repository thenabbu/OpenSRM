# Contributing to OpenSRM

Thanks for wanting to help! Here's everything you need to get started.

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
uv sync --frozen
playwright install chromium
DATA_DIR=./data gunicorn -w 1 --threads 8 -t 120 --worker-class gthread -b 0.0.0.0:8084 app.app:app
# Access at http://localhost:8084
```

## Submitting changes

1. **Branch** — create a feature branch from `main`
2. **Lint** — `uvx ruff check app/` and `uv lock --check` before pushing (both are exactly what the Lint job runs; the lock check fails if `pyproject.toml` changed without `uv lock`)
3. **Test** — run the suites your change touches (see the test matrix below); everything green before you push
4. **Version** — for user-visible changes bump all three together: `VERSION` + `pyproject.toml`, then run `uv lock` so `uv.lock` matches (patch = fix, minor = feature, major = breaking/user-visible redesign; docs/tests-only changes get no bump). The number renders on the login page and dashboard navbar, and `tests/verify76.py` + CI both enforce the trio. **Also prepend a release entry to `NOTICES`** in `app/app.py` — verify76 `M27` fails the suite when the head notice's version stops equaling `VERSION`, so releases without notices cannot ship
5. **Commit** — clear, descriptive messages. One logical change per commit
6. **Push + PR** — open a PR against `main`. PR CI runs **Lint** (ruff + `uv lock --check`) and **Tests** (`unit` + `docker` + `e2e` — see the matrix below, every suite has a CI runner). The Docker image is built and pushed to `ghcr.io/thenabbu/opensrm` as `:latest` + `:<VERSION>` + `:<short-sha>` only after the merge lands on `main`, and only if `lint` *and* `tests` are green there; the self-hosted deployment then picks it up manually. Merges use merge commits with a `merge: <summary>` subject (no squash), keeping the atomic commits intact

### Commit format

```
type: short description

feat: add internal marks tab
fix: captcha timing race condition
docs: update README with new features
ci: add PR trigger to lint workflow
```

## Test matrix

All plain scripts (no pytest), from the repo root with the repo venv. The `[runner]` tag names the CI job that runs the suite on every PR (`unit`/`e2e` in `.github/workflows/tests.yml`; `—` = local only):

```bash
.venv/bin/python tests/verify76.py          # 72/72 static checks (incl. doc claims)
.venv/bin/python tests/test_exams.py        # 69/69 end-sem probe parser
.venv/bin/python tests/test_exams_view.py   # exam card view model
.venv/bin/python tests/test_marks_view.py   # internal-marks view model (fmt, IE derivation)
# [e2e] Playwright DUTs need a dev server + PLAYWRIGHT_BROWSERS_PATH set:
#   tests/test_sw.py (7/7) · tests/test_xss.py (9/9) · tests/test_marks_dut.py (53/53) — see AGENTS.md for the exact commands
# [unit] guide_static.py · [e2e] guide_check.py (portal mocked in-test) · [—] guide_server.py (7 real logins, never CI)
```

**Careful with live-portal tests:** `guide_server.py` performs 7 real SRM logins per run and the portal rate-limits 10/hour per IP, which is why it is the one suite CI never runs. Tests mint session cookies and never hardcode credentials — keep it that way, and don't loop the live suites. Every fabricated id in a committed test uses the `zz9999` / `xx0001` placeholders: the repo is public.

## What to know before editing

### Design system

The app uses a custom dark daisyUI theme (`openSRM`). Read `DESIGN.md` before touching any template or CSS — the theme has unusual rules (e.g., `primary` is black, surfaces are inverted).

Key rules:
- **Tokens only** — never use hex colors or Tailwind palette classes
- **Status colors follow thresholds** — ≥75% success, 65–74.9% warning, <65% error
- **`primary` is black** — use `accent` (white) for emphasis buttons
- **Borders, not shadows** — no gradients, glows, or glassmorphism

### Architecture

- **Flask + Jinja2** — templates in `app/templates/`, static files in `app/static/`
- **SQLite** — no ORM, raw SQL with `sqlite3.Row` for dict-like access. All connections funnel through `app.app.db()` (10s busy timeout; `SQLITE_JOURNAL_MODE` env, default `delete`) — never open one directly
- **Migrations** — versioned system in `app/migrations.py`. Add new migrations with `@migration(version=N, description="...")`.
- **Logging** — structured logging via `app/logging_setup.py`. Use `log_with_kv(logger, level, msg, key=value)` for machine-parseable output.
- **Playwright** — persistent browser instance launched lazily on first use; one shared context reused per netid (closed when a different netid logs in).
- **No JS frameworks** — vanilla JS only. No build step.
- **Service worker** — bump `CACHE_NAME` in `sw.js` when deploying static asset changes.

### CI/CD

- **Lint** — ruff (`app/` only) + `uv lock --check` on every push and PR
- **Tests** (`.github/workflows/tests.yml`, on every PR to `main` and every push to `main`) — three jobs:
  - `unit` — every suite that needs no server and no network, one step each, fresh `DATA_DIR` per step, `uv sync --frozen`
  - `docker` — builds the image **without pushing**, boots it on an empty volume, then seeds a fabricated user, mints its session cookie inside the container and asserts an authenticated `GET /` is 200 with the seeded data on the page (`/login` alone only proves the shell boots)
  - `e2e` — the Playwright suites, chromium headless shell only: the self-booting ones plus the server-needing ones (one gunicorn behind them, `scripts/ci_e2e_http.sh`); failure logs are uploaded as an artifact
  - `guide_server.py` is deliberately **not** in CI — it performs 7 real portal logins per run and the portal caps 10/hour per IP. `guide_check.py` **is** in CI: it mocks `/api/login` in the browser, so nothing reaches the portal
- **Build** — on push to `main`: Docker image built and pushed to `ghcr.io/thenabbu/opensrm` as `:latest` **plus `:<VERSION>` and `:<short-sha>`** (with `org.opencontainers.image.version`/`revision` labels), gated on `needs: [lint, tests]` so a red suite never pushes `:latest`. Deployments pin/roll back via `OPENSRM_TAG` (see AGENTS.md "Prod deploy")
- **Scans** — `.github/workflows/scans.yml` (gitleaks on full history · pip-audit on the locked export · trivy HIGH/CRITICAL on the built image) — **report-only**: findings land in the job summary, never a red check. docs/SCANS.md documents what each would block on and how to flip one to blocking
- **Deploy** — **manual**, there is no watcher: once CI is green on `main`, `ssh lab 'cd /docker/opensrm && docker compose pull && docker compose up -d opensrm'` (an auto-deploy watcher was deliberately removed at the maintainer's request — do not add one back)

## Portal rate limits

During testing, be aware:
- Per netid: 3 scrapes per 10 minutes (counted only when the sync actually runs — a `Sync in progress` / budget / cooldown rejection is free)
- Per IP: 10 login attempts per hour
- Aggregate server→portal budget: 30 requests per 10 minutes

Don't hammer the portal during testing.

## Questions?

Open a discussion on GitHub or reach out on Discord.
