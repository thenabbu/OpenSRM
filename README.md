<p align="center">
  <img src="docs/logo-rect.png" alt="OpenSRM" width="400">
</p>

# OpenSRM

A self-hosted attendance dashboard for the SRM Student Portal, built as a progressive web app.

**Live instance:** [srm.200871.xyz](https://srm.200871.xyz)

**Install as an app:** Android Chrome → "Add to Home Screen". iOS Safari → Share → Add to Home Screen.

---

## What it does

- **Login** — authenticates against the SRM portal via a pure-HTTP pipeline (Playwright fallback); accepts netid or email; captcha auto-retry (up to 3 attempts); live step-by-step progress while logging in
- **Attendance** — course-wise, monthly, and daily absent details with live percentages; bunk calculator
- **Internal Marks** — CT/FT/attendance component-wise marks per subject, with color-coded status badges
- **Timetable** — per-group schedule from SQLite; current/next class status; drag-and-drop editor with subject palette
- **Personal Details** — student info grouped into sections (Academic, Personal, Family, Contact)
- **Hot/cold data** — attendance + marks refreshed on every sync; personal details/timetable reused until stale (24h)
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
| Scraping | Pure HTTP (urllib) against the portal; Playwright (headless Chromium) fallback |
| Captcha | ddddocr (self-contained OCR) |
| Database | SQLite with versioned migration system |
| Frontend | Tailwind CSS + daisyUI (CDN), vanilla JS, Jinja2 |
| PWA | Service worker (network-first dashboard, cache-first static) |
| CI/CD | GitHub Actions → GHCR |
| Deployment | Docker on lab, Cloudflare Tunnel for HTTPS |

---

## Architecture

```mermaid
flowchart TD
    subgraph client["Client — PWA"]
        UI["Login + dashboard<br/>daisyUI / vanilla JS"]
        SW["Service worker opensrm-v9<br/>cache-first shell"]
    end

    subgraph lab["Lab host — Docker container opensrm"]
        FL["Flask + gunicorn :8083"]
        PROG["Login progress tracker<br/>GET /api/login/progress"]
        HS["http_scraper<br/>pure HTTP pipeline"]
        PW["Playwright fallback<br/>headless Chromium"]
        DB[("SQLite<br/>users · portal_sessions<br/>timetable · schema_version")]
        FL --> PROG
        FL --> HS
        HS -->|"HttpScraperError"| PW
        FL <--> DB
    end

    subgraph cf["Cloudflare"]
        TUN["Tunnel → srm.200871.xyz"]
        EG["egress worker srm-egress<br/>SRM_EGRESS_URL failover"]
    end

    P["SRM Student Portal<br/>sp.srmist.edu.in"]

    UI -->|HTTPS| TUN
    TUN --> FL
    SW --> UI
    UI -->|poll steps| PROG
    HS -->|"direct egress"| P
    HS -.->|"optional failover"| EG
    EG --> P
    PW -->|"if HTTP fails"| P
```

---

## How it works

1. **Login** — `http_scraper` fetches the login page (nonce, honeypot, captcha), solves the captcha via ddddocr (up to 3 retries), then POSTs `LoginServlet` with the portal's anti-bot tokens
2. **Progress** — each step publishes to an in-memory tracker; the login screen polls `/api/login/progress` and shows the user what is happening
3. **Hot data** — attendance (`funSetFormId(9)`) and internal marks (`funSetFormId(17)`) fetched on every sync
4. **Cold data** — personal details re-fetched only when older than 24h; timetable rendered from SQLite
5. **Store** — parsed JSON written to SQLite; on pipeline failure the login falls back to Playwright

```mermaid
sequenceDiagram
    actor U as User browser
    participant F as Flask /api/login
    participant S as http_scraper
    participant P as SRM portal
    U->>F: POST /api/login (netid, password)
    F->>F: rate limit + Fernet decrypt
    F->>S: fetch(cold=True)
    S->>P: GET youLogin.jsp
    P-->>S: nonce, honeypot, captcha image
    S->>P: GET captcha (stamped Referer + Cookie)
    P-->>S: captcha PNG
    S->>S: ddddocr OCR, retry up to 3
    F-->>U: progress: solving captcha (polled)
    S->>P: POST LoginServlet (dtoken, cptoken, telemetry)
    P-->>S: HRDSystem — session established
    S->>P: POST attendance formId 9 + marks formId 17
    P-->>S: HTML tables
    S->>S: parse tables to JSON
    S-->>F: attendance, marks, personal, courses
    F-->>U: 200 OK → dashboard
```

---

## Project structure

```mermaid
flowchart LR
    subgraph core["app/ — backend"]
        APP["app.py<br/>routes · security · sync<br/>login progress tracker"]
        SCR["http_scraper.py<br/>login · captcha · JSP fetch"]
        MIG["migrations.py<br/>versioned schema"]
        LOG["logging_setup.py<br/>TIMESTAMP LEVEL name kv"]
    end

    subgraph front["frontend"]
        TPL["templates/<br/>login · dashboard · theme"]
        ST["static/<br/>dash.js · marks.js<br/>timetable.js · login.js · sw.js"]
    end

    subgraph eg["egress/"]
        WK["worker.js — Cloudflare egress worker"]
        AB["test-login-ab.py — direct vs worker A/B"]
        POC["poc/ — browser-side scrape PoC"]
    end

    subgraph dep["deploy"]
        DF["Dockerfile — multi-stage + chromium"]
        DC["docker-compose.yml — port 8083"]
        CI[".github/workflows/ — build.yml → GHCR"]
    end

    DATA[("data/ — srm.db · fernet.key · secret")]

    APP --> SCR
    APP --> MIG
    APP --> LOG
    APP --> TPL
    TPL --> ST
    APP --> DATA
    SCR -.->|"SRM_EGRESS_URL"| WK
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
