# Contributing to OpenSRM

## Quick Start

```bash
git clone https://github.com/thenabbu/OpenSRM.git
cd OpenSRM
docker compose up -d --build
```

## Guidelines

1. **Branch** — create a feature branch from main
2. **Test** — verify against the live SRM portal (login, attendance, timetable editor)
3. **Commit** — clear, descriptive messages. One logical change per commit.
4. **PR** — open against main with description of what changed and why.

## Architecture Constraints

- **gunicorn: exactly 1 worker** — Chromium + ddddocr are process-level singletons. More workers = OOM.
- **No inline JS** — CSP blocks it (script-src 'self'). All handlers in static/*.js via addEventListener.
- **No new frameworks** — vanilla JS + CSS. No React, no build step.
- **SQLite** — idempotent ALTER TABLE with try/except for migrations. No ORM.
- **Static file caching** — .js and .json are max-age=3600 (for PWA). CSS has no-store.
- **Service Worker** — bump CACHE_NAME in sw.js on deploys that change static assets.
- **Persistent browser** — Chromium launched once, reused via dedicated event loop. Fresh context per login. Don't close the browser instance.

## Features Reference

- **Captcha retry** — up to 3 attempts per login, page reload between retries
- **NetID/email login** — input strips @domain suffix server-side
- **Password toggle** — client-side type=password/text switch
- **Timetable editor** — per-group drag-drop with subject palette (subjects from course list scrape)
- **Daily absences** — expand/collapse per-month, AJAX-fetched

## Portal Rate Limits

- Per-netid: 3 scrapes per 10 minutes
- Per-IP: 10 login attempts per hour
- Don't hammer during testing.

## Code Style

- Python: PEP 8 where reasonable
- CSS: hand-written, dark theme (#111111 bg), IBM Plex Sans
- Commit messages: type: description (feat/fix/ui/meta/docs/pwa)
