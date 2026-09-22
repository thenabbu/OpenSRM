<p align="center">
  <img src="docs/logo-rect.png" alt="OpenSRM" width="400">
</p>

# OpenSRM

A self-hosted attendance dashboard for the SRM Student Portal, built as a progressive web app.

**Live instance:** [srm.200871.xyz](https://srm.200871.xyz)

**Install as an app:** Android Chrome → "Add to Home Screen". iOS Safari → Share → Add to Home Screen.

---

## What it does

- **Login** — authenticates against the SRM portal via Playwright; accepts netid or email; captcha auto-retry (up to 3 attempts)
- **Attendance** — course-wise, monthly, and daily absent details with live percentages; bunk calculator
- **Internal Marks** — CT/FT/attendance component-wise marks per subject, with color-coded status badges
- **Timetable** — per-group schedule from SQLite; current/next class status; drag-and-drop editor with subject palette
- **Personal Details** — student info grouped into sections (Academic, Personal, Family, Contact)
- **Student Photo** — real portal photo as nav avatar (initials fallback)
- **PWA** — installable on Android, iOS, Windows; offline shell with cached last-view

---

## Quick start

```bash
# Production (Docker)
git clone https://github.com/thenabbu/OpenSRM.git
cd OpenSRM
docker compose up -d
# Access at http://localhost:8083

# Development (venv)
uv venv .venv && source .venv/bin/activate
uv sync --frozen
playwright install chromium
DATA_DIR=./data gunicorn -w 1 --threads 8 -b 0.0.0.0:8084 app.app:app
# Access at http://localhost:8084
```

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Flask 3.0, Python 3.11, gunicorn (gthread) |
| Scraping | Playwright (headless Chromium) |
| Captcha | ddddocr (self-contained OCR) |
| Database | SQLite with versioned migration system |
| Frontend | Tailwind CSS + daisyUI (CDN), vanilla JS, Jinja2 |
| PWA | Service worker (network-first dashboard, cache-first static) |
| CI/CD | GitHub Actions → GHCR |
| Deployment | Docker on lab, Cloudflare Tunnel for HTTPS |

---

## How it works

1. **Login** — fills SRM portal form, solves captcha via ddddocr (up to 3 retries), submits via persistent Chromium
2. **Photo** — captures student portal photo → base64 JPEG stored in SQLite
3. **Attendance** — calls `funSetFormId(9)`, parses course/monthly tables from HTML
4. **Internal Marks** — calls `funSetFormId(17)`, extracts component-wise marks with subject IDs from onclick attributes
5. **Personal Details** — calls `funSetFormId(17)`, extracts key-value pairs into grouped sections
6. **Timetable** — renders from SQLite; per-group schedule with drag-drop editor
7. **Store** — saves everything to SQLite (attendance, marks, personal details, photo, timetable)

---

## Project structure

```
app/
├── app.py              # Flask app: routes, scraper, security, APIs
├── migrations.py       # Versioned DB migration system
├── logging_setup.py    # Structured logging (TIMESTAMP LEVEL name key=value)
├── templates/
│   ├── login.html      # Login page
│   ├── dashboard.html  # Dashboard (4 tabs: Attendance, Timetable, Personal, Marks)
│   └── partials/
│       └── theme.html  # Shared daisyUI theme
├── static/
│   ├── dash.js         # Tab switching, offline indicator
│   ├── marks.js        # Internal marks tab
│   ├── timetable.js    # Timetable editor (drag-drop, grid)
│   ├── login.js        # Login form handling
│   ├── sw.js           # Service worker
│   └── ...             # Icons, manifest, CSS
├── data/
│   ├── srm.db          # SQLite (auto-created)
│   ├── secret          # Session secret (auto-generated)
│   └── fernet.key      # Fernet encryption key
Dockerfile              # Multi-stage: Python 3.11-slim + Playwright
docker-compose.yml      # Production config
entrypoint.sh           # Container entrypoint
```

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Port | 8083 | Web interface port |
| Rate limit (netid) | 3 per 10 min | Scrapes per account |
| Rate limit (IP) | 10 per hour | Login attempts per IP |
| Session | 30 days | Cookie lifetime |

Environment variables:
- `DATA_DIR` — SQLite data directory (default: `/app/data`)
- `CHROMIUM_PATH` — Chromium executable path
- `LOG_LEVEL` — Logging verbosity: DEBUG, INFO (default), WARNING, ERROR
- `TZ` — Timezone (default: `Asia/Kolkata`)

---

## Security

- Fernet-encrypted passwords at rest
- HTTP-only session cookies with Secure flag (behind HTTPS)
- CSP headers (script-src 'self', no external scripts)
- Rate limiting per netid and per IP
- Cloudflare Tunnel for HTTPS termination

See [SECURITY.md](SECURITY.md) for details.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — do whatever, no warranty. Not affiliated with SRM Institute.
