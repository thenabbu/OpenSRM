# Contributing to OpenSRM

## Quick Start

### Production (Docker)
```bash
git clone https://github.com/thenabbu/OpenSRM.git
cd OpenSRM
docker compose up -d
# Access at http://localhost:8083
```

### Development (venv)
```bash
git clone https://github.com/thenabbu/OpenSRM.git
cd OpenSRM
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium
DATA_DIR=./data gunicorn -w 1 --threads 8 -t 120 --worker-class gthread -b 0.0.0.0:8084 app.app:app
# Access at http://localhost:8084
```

## Guidelines

1. **Branch** — create a feature branch from main
2. **Lint** — run `ruff check app/` before committing (CI blocks on failures)
3. **Test** — verify against the live SRM portal (login, attendance, timetable editor)
4. **Commit** — clear, descriptive messages. One logical change per commit.
5. **Push** — push to main. CI runs lint then Docker build then GHCR push automatically.

## Architecture Constraints

- **gunicorn: 1 worker, 8 threads** — Chromium + ddddocr are process-level singletons. Multiple workers = OOM. Threads handle concurrency.
- **Templates** — Jinja2 files in `app/templates/`. Not inline strings. Use `render_template()`.
- **No new JS frameworks** — vanilla JS + CSS. No React, no build step.
- **SQLite** — idempotent ALTER TABLE with try/except for migrations. No ORM.
- **Static file caching** — .js and .json are max-age=3600 (for PWA). CSS has no-store.
- **Service Worker** — bump CACHE_NAME in sw.js on deploys that change static assets.
- **Persistent browser** — Chromium launched once, reused via dedicated event loop. Fresh context per login. Do not close the browser instance.
- **CSS** — Tailwind CSS v4 + daisyUI v5 via CDN. Custom theme via html data-theme="openSRM" with oklch variables.

## CI/CD

- **Lint** — ruff checks on every push to main
- **Build** — Docker image built and pushed to ghcr.io/thenabbu/opensrm:latest
- **Deploy** — dockhand auto-pulls every 24 hours
- **Dependabot** — auto PRs for pip and Actions updates

## Features Reference

- **Captcha retry** — up to 3 attempts per login, page reload between retries
- **NetID/email login** — input strips @domain suffix server-side
- **Password toggle** — client-side type=password/text switch
- **Timetable editor** — per-group drag-drop with subject palette (subjects from course list scrape)
- **Daily absences** — expand/collapse per-month, AJAX-fetched

## Portal Rate Limits

- Per-netid: 3 scrapes per 10 minutes
- Per-IP: 10 login attempts per hour
- Do not hammer during testing.

## Code Style

- Python: PEP 8, enforced by ruff
- CSS: Tailwind + daisyUI, dark theme (#111111 bg)
- Commit messages: type: description (feat/fix/ci/docs/refactor)
