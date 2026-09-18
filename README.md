# OpenSRM

A self-hosted attendance dashboard for the SRM Student Portal, built as a progressive web app (PWA).

**Live instance:** https://srm.200871.xyz

**Install as an app:** Android Chrome → "Add to Home Screen" banner. iOS Safari → Share → Add to Home Screen.

---

## Features

- **Login** — authenticates against SRM's student portal (Playwright + captcha solver)
- **Attendance** — course-wise, monthly, and daily absent details with live percentages
- **Timetable** — weekly schedule with current/next class status
- **Personal Details** — student info scraped from the portal
- **Student Photo** — real portal photo as the nav avatar (with initials fallback)
- **Period Note** — attendance period shown in the hero card
- **Multi-user** — per-user accounts, encrypted credentials, session cookies
- **Security** — Fernet-encrypted passwords, rate limiting (3/netid/10min, 10/IP/hr), CSP headers, HSTS
- **PWA** — installable on Android, iOS, and Windows; offline shell with cached last-view
- **Mobile-first** — responsive layout, stacked cards on phones, safe-area support for notched devices
- **Dark theme** — B&W palette from the logo (#111111 bg, #ffffff text, green/amber/red status)

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Flask 3.0, Python 3.11, gunicorn (1 worker, 8 threads) |
| Scraping | Playwright (headless Chromium, anti-bot via webdriver strip) |
| Captcha | ddddocr (self-contained) or caplab (lab host) |
| Database | SQLite (attendance + personal details + photo) |
| Frontend | Hand-written CSS (dark theme), vanilla JS, no framework |
| PWA | Service worker (network-first dashboard, cache-first static) |
| Deployment | Docker, Cloudflare Tunnel |

---

## Quick Start

```bash
git clone https://github.com/thenabbu/OpenSRM.git
cd OpenSRM
docker compose up -d --build
# Access at http://localhost:8083
```

---

## Project Structure

```
OpenSRM/
├── app/
│   ├── app.py              # Flask app: routes, scraper, security, templates, PWA meta
│   ├── timetable.py        # Timetable renderer (loads data/timetable.json)
│   ├── data/
│   │   ├── timetable.json  # Weekly schedule (5 days × 8 time slots)
│   │   ├── srm.db          # SQLite (users, attendance, personal, photos)
│   │   ├── secret          # Session secret (auto-generated)
│   │   └── fernet.key      # Fernet encryption key
│   └── static/
│       ├── manifest.json   # PWA manifest
│       ├── sw.js           # Service worker
│       ├── dash.js         # Dashboard JS + offline indicator
│       ├── login.js        # Login JS
│       ├── login.css       # Login styles
│       ├── favicon.ico     # Multi-size favicon (16/32/48)
│       ├── icon-192.png    # PWA icon 192px
│       ├── icon-512.png    # PWA icon 512px
│       ├── icon-1024.png   # PWA icon 1024px (high-DPI splash)
│       ├── icon-maskable-512.png  # Maskable adaptive icon
│       └── apple-touch-startup-*.png  # iOS startup images
├── scripts/
│   └── srm_attendance.py   # Standalone scraper (testing)
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
├── CONTRIBUTING.md
├── SECURITY.md
└── README.md
```

---

## How It Works

1. **Login** — fills SRM portal form, solves captcha via ddddocr, submits via Playwright
2. **Photo** — captures student portal photo (`img.imgPhoto`) → base64 JPEG stored in SQLite
3. **Attendance** — calls `funSetFormId(9)`, parses course/monthly tables from HTML
4. **Daily Absence** — AJAX-fetched per-month details (`Promise.all` for concurrency)
5. **Personal Details** — calls `funSetFormId(17)`, extracts key-value pairs
6. **Store** — saves to SQLite (attendance JSON, personal details, photo, timestamps)
7. **Serve** — renders dashboard with real-time calculations (bunk lines, percentages)

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Port | 8083 | Web interface port |
| Rate limit (netid) | 3 per 10 min | Scrapes per account |
| Rate limit (IP) | 10 per hour | Login attempts per IP |
| Session | 30 days | Cookie lifetime |
| Workers | 1 (required) | Single gunicorn worker for browser singletons |

---

## PWA

The app is installable as a PWA on Android, iOS, and Windows:

- **Manifest** — `display: standalone`, dark splash (#111111), maskable adaptive icon
- **Service Worker** — network-first for dashboard (offline fallback), cache-first for static assets
- **Offline** — last-cached dashboard loads when offline, amber banner indicates cached state
- **iOS** — startup images for iPhone 12/13/14 Pro Max, safe-area-inset for notch

---

## Known Limitations

- **First-year accounts** — SRM may gate behind ABC ID Generation until Aadhaar form is completed
- **No background sync** — attendance fetched on-demand (login or Refresh click)
- **Single worker** — Chromium + ddddocr are process-level singletons; more workers = OOM

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Report vulnerabilities responsibly. See [SECURITY.md](SECURITY.md).

## License

MIT — do whatever, no warranty. Not affiliated with SRM Institute.
