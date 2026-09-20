# OpenSRM

A self-hosted attendance dashboard for the SRM Student Portal, built as a progressive web app (PWA).

**Live instance:** https://srm.200871.xyz

**Install as an app:** Android Chrome → "Add to Home Screen" banner. iOS Safari → Share → Add to Home Screen.

---

## Features

- **Login** — authenticates against SRM portal via Playwright; accepts netid or email (strips @domain); password visibility toggle; captcha auto-retry (up to 3 attempts)
- **Attendance** — course-wise, monthly, and daily absent details with live percentages; bunk calculator
- **Timetable** — per-group schedule from SQLite; current/next class status; drag-and-drop editor with subject palette; days-as-rows grid
- **Personal Details** — student info grouped into sections (Academic, Personal, Family, Contact); clickable email/phone links
- **Student Photo** — real portal photo as nav avatar (initials fallback)
- **PWA** — installable on Android, iOS, Windows; offline shell with cached last-view; service worker (network-first dashboard, cache-first static)
- **Security** — Fernet-encrypted passwords, rate limiting (3/netid/10min, 10/IP/hr), CSP headers
- **Mobile-first** — responsive layout; 44px touch targets; compact personal grid; icon-only refresh on phones
- **Dark theme** — B&W palette from logo (#111111 bg, #ffffff text, green/amber/red status)

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Flask 3.0, Python 3.11, gunicorn (gthread, 1 worker, 8 threads) |
| Scraping | Playwright (headless Chromium, anti-bot via webdriver strip) |
| Captcha | ddddocr (self-contained, pre-warmed in persistent browser) |
| Database | SQLite (users, attendance, personal details, timetable groups/slots) |
| Frontend | Tailwind CSS v4 + daisyUI v5 (CDN), vanilla JS, Jinja2 templates |
| PWA | Service worker (network-first dashboard, cache-first static) |
| CI/CD | GitHub Actions (ruff lint → Docker build → GHCR push) |
| Deployment | Docker on lab, Cloudflare Tunnel for HTTPS, dockhand auto-pull |

---

## Quick Start

```bash
# Production (Docker)
git clone https://github.com/thenabbu/OpenSRM.git
cd OpenSRM
docker compose up -d
# Access at http://localhost:8083

# Development (venv)
cd OpenSRM
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium
DATA_DIR=./data gunicorn -w 1 --threads 8 -b 0.0.0.0:8084 app.app:app
# Access at http://localhost:8084
```

---

## Project Structure

```
OpenSRM/
├── app/
│   ├── app.py              # Flask app: routes, scraper, security, APIs
│   ├── templates/
│   │   ├── login.html      # Login page (Jinja2)
│   │   └── dashboard.html  # Dashboard page (Jinja2)
│   ├── static/
│   │   ├── manifest.json   # PWA manifest
│   │   ├── sw.js           # Service worker
│   │   ├── dash.js         # Dashboard JS (tabs, offline indicator)
│   │   ├── login.js        # Login JS (auth, password toggle)
│   │   ├── timetable.js    # Timetable editor (drag-drop, grid)
│   │   ├── timetable.css   # Timetable + editor styles
│   │   ├── drag-drop-touch.js  # Touch polyfill for mobile drag-and-drop
│   │   ├── favicon.ico     # Multi-size favicon
│   │   ├── icon-*.png      # PWA icons (192/512/1024/maskable)
│   │   └── apple-touch-startup-*.png  # iOS startup images
│   └── data/
│       ├── srm.db          # SQLite (auto-created)
│       ├── secret          # Session secret (auto-generated)
│       └── fernet.key      # Fernet encryption key
├── .github/
│   ├── workflows/
│   │   ├── build.yml       # Lint → Docker build → GHCR push
│   │   └── lint.yml        # Ruff lint on push
│   └── dependabot.yml      # Auto PRs for dep updates
├── ruff.toml               # Linter config
├── Dockerfile              # Python 3.11-slim + Chromium
├── docker-compose.yml      # Production (port 8083)
├── entrypoint.sh           # Container entrypoint
├── requirements.txt        # Python deps
├── CONTRIBUTING.md
├── SECURITY.md
└── README.md
```

---

## How It Works

1. **Login** — fills SRM portal form, solves captcha via ddddocr (up to 3 retries), submits via persistent Chromium
2. **Photo** — captures student portal photo (img.imgPhoto) → base64 JPEG stored in SQLite
3. **Attendance** — calls funSetFormId(9), parses course/monthly tables from HTML
4. **Daily Absence** — AJAX-fetched per-month details (Promise.all for concurrency)
5. **Personal Details** — calls funSetFormId(17), extracts key-value pairs into grouped sections
6. **Course List** — extracts subject code/name/credits from attendance page for timetable subjects
7. **Timetable** — renders from SQLite timetable_groups/slots; per-group schedule with drag-drop editor
8. **Store** — saves to SQLite (attendance JSON, personal details, photo, timetable groups, timestamps)
9. **Serve** — renders Jinja2 templates with real-time calculations (bunk lines, percentages)

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Port | 8083 | Web interface port |
| Rate limit (netid) | 3 per 10 min | Scrapes per account |
| Rate limit (IP) | 10 per hour | Login attempts per IP |
| Session | 30 days | Cookie lifetime |
| Workers | 1 worker, 8 threads | gunicorn gthread for concurrent requests |

Environment variables:
- `DATA_DIR` — SQLite data directory (default: `/app/data`)
- `CHROMIUM_PATH` — Chromium executable path (default: `/usr/bin/chromium`)
- `TZ` — timezone (default: `Asia/Kolkata`)

---

## PWA

- **Manifest** — display: standalone, dark splash (#111111), maskable adaptive icon
- **Service Worker** — network-first for dashboard (offline fallback), cache-first for static assets
- **Offline** — last-cached dashboard loads when offline, amber banner indicates cached state
- **iOS** — startup images for iPhone 12/13/14 Pro Max, safe-area-inset for notch

---

## CI/CD

- **Lint** — ruff checks on every push to main (catches undefined names, unused imports, bare excepts)
- **Build** — Docker image built and pushed to `ghcr.io/thenabbu/opensrm:latest` with OCI labels
- **Deploy** — dockhand auto-pulls the latest image every 24 hours
- **Dependabot** — weekly pip updates, monthly Actions updates

---

## Known Limitations

- **First-year accounts** — SRM may gate behind ABC ID Generation until Aadhaar form is completed
- **No background sync** — attendance fetched on-demand (login or Refresh click)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Report vulnerabilities responsibly. See [SECURITY.md](SECURITY.md).

## License

MIT — do whatever, no warranty. Not affiliated with SRM Institute.
