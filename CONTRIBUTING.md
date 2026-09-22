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
2. **Lint** — run `ruff check app/` before committing (CI blocks on failures)
3. **Test** — verify against the live SRM portal (login, attendance, timetable editor)
4. **Commit** — clear, descriptive messages. One logical change per commit.
5. **Push** — push to main. CI runs lint → Docker build → GHCR push automatically.

### Commit format

```
type: short description

feat: add internal marks tab
fix: captcha timing race condition
docs: update README with new features
ci: add PR trigger to lint workflow
```

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
- **Playwright** — persistent browser instance, fresh context per login. Chromium launched once at startup.
- **No JS frameworks** — vanilla JS only. No build step.
- **Service worker** — bump `CACHE_NAME` in `sw.js` when deploying static asset changes.

### CI/CD

- **Lint** — ruff checks on every push to main and PRs
- **Build** — Docker image built and pushed to `ghcr.io/thenabbu/opensrm:latest`
- **Deploy** — dockhand auto-pulls the latest image

## Portal rate limits

During testing, be aware:
- Per netid: 3 scrapes per 10 minutes
- Per IP: 10 login attempts per hour

Don't hammer the portal during testing.

## Questions?

Open a discussion on GitHub or reach out on Discord.
