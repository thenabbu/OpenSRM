# OpenSRM

A self-hosted attendance dashboard for the SRM Student Portal.  
Built for students who want a fast, clean view of their attendance without digging through the official portal every time.

**Live instance:** https://srm.200871.xyz

---

## Features

- **Login** — authenticates against SRM's student portal (Playwright + captcha solver)
- **Attendance** — course-wise, monthly, and daily absent details
- **Timetable** — live weekly schedule with current/next class status
- **Multi-user** — per-user accounts, encrypted credentials, session cookies
- **Security** — Fernet-encrypted passwords at rest, rate limiting, CSP headers, HSTS
- **Resilient** — detects ABC ID Generation blocks on first-year accounts and returns a clear error

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Flask, Python 3.11, gunicorn |
| Scraping | Playwright (system Chromium, headful via Xvfb) |
| Captcha | ddddocr (self-contained) or caplab (lab host) |
| Database | SQLite (per-user attendance, encrypted credentials) |
| Frontend | Hand-written CSS (IBM Carbon aesthetic), no framework |
| Deployment | Docker, Cloudflare Tunnel |

---

## Quick Start



---

## Project Structure



---

## How It Works

1. **Login** — fills the SRM portal form, solves the captcha, submits via Playwright
2. **Navigate** — calls funSetFormId(9) to load the attendance page
3. **Parse** — extracts course-wise and monthly tables from the HTML
4. **Daily Absence** — fetches per-month absence details via AJAX
5. **Serve** — renders everything in a clean dashboard with view-model calculations

---

## Configuration

The app is designed to work out of the box with sensible defaults.  
Key settings are in docker-compose.yml and app.py:

| Setting | Default | Description |
|---------|---------|-------------|
| Port | 8083 | Web interface port |
| Rate limit (netid) | 3 per 10 min | Scrapes per account |
| Rate limit (IP) | 10 per hour | Login attempts per IP |
| Session | 30 days | Cookie lifetime |
| Workers | 1 (required) | Gunicorn workers |

---

## Known Limitations

- **First-year accounts** — SRM may gate access behind mandatory ABC ID Generation until the Aadhaar form is completed. The app detects this and returns an actionable error.
- **Headful only** — requires Xvfb (virtual display) because the portal has light anti-bot detection
- **No background sync** — attendance is fetched on-demand when you log in or click Refresh

---

## Contributing

See CONTRIBUTING.md for guidelines.

---

## Security

Report vulnerabilities responsibly. See SECURITY.md.

---

## License

MIT — do whatever, no warranty. Not affiliated with SRM Institute.
