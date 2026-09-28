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
2. **Lint** — `uvx ruff check app/` and `uv lock --check` before pushing (both are exactly what CI runs; the lock check fails if `pyproject.toml` changed without `uv lock`)
3. **Test** — run the suites your change touches (see the test matrix below); everything green before you push
4. **Version** — for user-visible changes bump all three together: `VERSION` + `pyproject.toml`, then run `uv lock` so `uv.lock` matches (patch = fix, minor = feature, major = breaking/user-visible redesign; docs/tests-only changes get no bump). The number renders on the login page and dashboard navbar, and `tests/verify76.py` + CI both enforce the trio
5. **Commit** — clear, descriptive messages. One logical change per commit
6. **Push + PR** — open a PR against `main`. PR CI runs lint only (ruff + `uv lock --check`); the Docker image is built and pushed to `ghcr.io/thenabbu/opensrm:latest` only after the merge lands on `main`, from where the self-hosted deployment picks it up automatically. Merges use merge commits with a `merge: <summary>` subject (no squash), keeping the atomic commits intact

### Commit format

```
type: short description

feat: add internal marks tab
fix: captcha timing race condition
docs: update README with new features
ci: add PR trigger to lint workflow
```

## Test matrix

All plain scripts (no pytest), from the repo root with the repo venv:

```bash
.venv/bin/python tests/verify76.py          # 71/71 static checks (incl. doc claims)
.venv/bin/python tests/test_exams.py        # 24/24 end-sem probe parser
.venv/bin/python tests/test_exams_view.py   # exam card view model
.venv/bin/python tests/test_marks_view.py   # internal-marks view model (fmt, IE derivation)
# Playwright DUTs need a dev server + PLAYWRIGHT_BROWSERS_PATH set:
#   tests/test_sw.py (7/7) · tests/test_xss.py (9/9) · tests/test_marks_dut.py (45/45) — see AGENTS.md for the exact commands
# Login UX guide suites: guide_static.py / guide_check.py / guide_server.py
```

**Careful with live-portal tests:** `guide_server.py` performs 7 real SRM logins per run and the portal rate-limits 10/hour per IP. Tests mint session cookies and never hardcode credentials — keep it that way, and don't loop the live suites.

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
- **SQLite** — no ORM, raw SQL with `sqlite3.Row` for dict-like access
- **Migrations** — versioned system in `app/migrations.py`. Add new migrations with `@migration(version=N, description="...")`.
- **Logging** — structured logging via `app/logging_setup.py`. Use `log_with_kv(logger, level, msg, key=value)` for machine-parseable output.
- **Playwright** — persistent browser instance launched lazily on first use; one shared context reused per netid (closed when a different netid logs in).
- **No JS frameworks** — vanilla JS only. No build step.
- **Service worker** — bump `CACHE_NAME` in `sw.js` when deploying static asset changes.

### CI/CD

- **Lint** — ruff (`app/` only) + `uv lock --check` on every push and PR
- **Build** — on push to `main`: Docker image built and pushed to `ghcr.io/thenabbu/opensrm:latest`
- **Deploy** — the self-hosted watcher pulls the new image from GHCR, snapshots the DB, and recreates the container

## Portal rate limits

During testing, be aware:
- Per netid: 3 scrapes per 10 minutes
- Per IP: 10 login attempts per hour
- Aggregate server→portal budget: 30 requests per 10 minutes

Don't hammer the portal during testing.

## Questions?

Open a discussion on GitHub or reach out on Discord.
