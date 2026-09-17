# OpenSRM

A self-hosted attendance dashboard for the SRM Student Portal.
Built for students who want a fast, clean view of their attendance without digging through the official portal every time.

**Live instance:** https://srm.200871.xyz

---

## Features

- **Login** — authenticates against SRM's student portal (Playwright + captcha solver)
- **Attendance** — course-wise, monthly, and daily absent details
- **Timetable** — live weekly schedule with current/next class status (loaded from JSON config)
- **Personal Details** — student info scraped from the portal (program, registration, etc.)
- **Student Photo** — real portal photo shown as the nav avatar, with initials fallback
- **Multi-user** — per-user accounts, encrypted credentials, session cookies
- **Security** — Fernet-encrypted passwords at rest, rate limiting, CSP headers, HSTS, no-store cache control
- **Resilient** — detects ABC ID Generation blocks on first-year accounts and returns a clear error
- **Mobile-friendly** — responsive layout for phone screens (stacked cards, adapted timetable)

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Flask, Python 3.11, gunicorn (1 worker, 8 threads) |
| Scraping | Playwright (headless Chromium, anti-bot bypass via webdriver strip) |
| Captcha | ddddocr (self-contained) or caplab (lab host) |
| Database | SQLite (per-user attendance + personal details + photo, encrypted credentials) |
| Frontend | Hand-written CSS (IBM Carbon aesthetic), no framework |
| Deployment | Docker, Cloudflare Tunnel |

---

## Quick Start

```bash
# Clone
git clone https://github.com/thenabbu/OpenSRM.git
cd OpenSRM

# Build and run
docker compose up -d --build

# Access
open http://localhost:8083
```

The app is designed to work out of the box. Key settings are in `docker-compose.yml` and `Dockerfile`:

| Setting | Default | Description |
|---------|---------|-------------|
| Port | 8083 | Web interface port |
| Rate limit (netid) | 3 per 10 min | Scrapes per account |
| Rate limit (IP) | 10 per hour | Login attempts per IP |
| Session | 30 days | Cookie lifetime |
| Workers | 1 (required) | Single gunicorn worker for browser singletons |

---

## Project Structure

```
OpenSRM/
├── app/
│   ├── app.py              # Main Flask app: routes, scraper, security, templates
│   ├── timetable.py        # Timetable renderer (loads data/timetable.json)
│   ├── data/
│   │   ├── timetable.json  # Weekly schedule data (5 days × 8 time slots)
│   │   ├── srm.db          # SQLite database (users, attendance, photos)
│   │   ├── secret          # Session secret key (auto-generated)
│   │   └── fernet.key      # Fernet key for password encryption
│   └── static/
│       ├── login.css       # Login page styles
│       ├── login.js        # Login page logic (spinner, submit, error display)
│       └── dash.js         # Dashboard logic (tab switching, refresh, live sync)
├── scripts/
│   └── srm_attendance.py   # Standalone scraper (for testing/debugging)
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh           # Container init (secret key generation)
├── requirements.txt
├── CONTRIBUTING.md
├── SECURITY.md
└── README.md
```

---

## How It Works

1. **Login** — fills the SRM portal form, solves the captcha, submits via Playwright
2. **Photo** — captures the student's portal photo (AJAX-loaded `img.imgPhoto`) and stores as base64 JPEG
3. **Navigate** — calls `funSetFormId(9)` to load the attendance page
4. **Parse** — extracts course-wise and monthly tables from the HTML
5. **Daily Absence** — fetches per-month absence details via AJAX (`Promise.all` for concurrency)
6. **Personal Details** — calls `funSetFormId(17)` to scrape key-value student info
7. **Store** — saves all data to SQLite (attendance JSON, personal details, photo, timestamps)
8. **Serve** — renders a dashboard with real-time calculations (bunk lines, percentages, status tiers)

---

## Architecture Notes

- **Single worker** — gunicorn runs 1 worker with 8 threads. Required because Chromium + ddddocr are process-level singletons (persistent browser pool, pre-warmed solver).
- **Headless** — Chromium runs headless (`headless=True`). Anti-bot bypass is achieved by stripping `navigator.webdriver` and disabling the `AutomationControlled` blink feature. Xvfb was removed Sep 2026.
- **Rate limits** — per-netid (3/10min) prevents portal abuse; per-IP (10/hr) prevents brute-force.
- **Session replay** — after initial login, a `JSessionID` cookie can be reused for subsequent page loads within the same browser context.

---

## Known Limitations

- **First-year accounts** — SRM may gate access behind mandatory ABC ID Generation until the Aadhaar form is completed. The app detects this and returns a clear error.
- **No background sync** — attendance is fetched on-demand when you log in or click Refresh.
- **Photo quality** — student photos are captured at the portal's display resolution (typically ~200px), not full resolution.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## Security

Report vulnerabilities responsibly. See [SECURITY.md](SECURITY.md).

---

## License

MIT — do whatever, no warranty. Not affiliated with SRM Institute.
