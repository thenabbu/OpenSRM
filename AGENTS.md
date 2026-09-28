# AGENTS.md — quickstart for a working agent (OpenSRM)

One-paragraph pitch: Flask monolith that scrapes the SRM student portal (pure-HTTP
pipeline, Playwright fallback) and renders attendance/marks/timetable dashboards.
**Version lives in `VERSION`** (read by `app.py` → login badge); keep
`VERSION` == `pyproject.toml` == `uv.lock` (tests/verify76.py M23 checks this).

## Where things run
- **Local dev**: repo at `/opt/data/opensrm-repo` (hermes host), venv `.venv` (uv; NEVER npm — no frontend build, CDN only; pnpm if JS tooling is ever needed).
- **Prod**: lab host, container `opensrm` (repo copy at `/docker/opensrm`, **repo `docker-compose.yml` == live file**), port `127.0.0.1:8083` + `172.31.0.1:8083` (cloudflared gateway), served at https://srm.200871.xyz via CF tunnel `c2308be7-6527-4da3-a96c-49c4b4c918c0`.
- **Do NOT touch** `flights.200871.xyz` (DNS/ingress) — another agent owns that subdomain.

## Layout
```
app/app.py            # monolith: routes, parsers, session/auth, rate limits
app/http_scraper.py   # pure-HTTP portal pipeline (Playwright fallback)
app/migrations.py     # versioned schema; runs at import (DATA_DIR)
app/templates|static/ # daisyUI v5, CDN Tailwind (pinned versions in partials/theme.html)
tests/                # verify76.py (71 static) + test_sw/test_xss/test_exams* (DUTs) + guide_* (login UX guide suites)
egress/               # CF Worker egress proxy + PoCs — NOT in the image (.dockerignore)
docs/audit/           # audit record: findings + resolution
VERSION pyproject.toml uv.lock   # release = bump all three together
.github/workflows/    # build.yml (image) + lint.yml; SHA-pinned actions; `uv lock --check`
```

## Dev loop (do this every time)
```bash
cd /opt/data/opensrm-repo
uvx --quiet ruff check app/          # == CI lint
uv lock --check                      # == CI lock check (after pyproject edits run `uv lock` first)

# pick a FREE port first — 8084/8085 get squatted by other local services:
python3 -c "import socket;s=socket.socket();s.bind(('127.0.0.1',18099));print('free');s.close()"
DATA_DIR=/tmp/osrm-dev LOG_LEVEL=DEBUG .venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:<PORT> app.app:app
```
Migrations run on import (fresh `DATA_DIR` = fresh DB, boots clean — that's test C1).

## Test matrix (all green before push)
```bash
.venv/bin/python tests/verify76.py          # 71/71 static (findings, docs, pins, versions)
.venv/bin/python tests/test_exams.py        # 24/24 (end-sem probe parser + candidates)
.venv/bin/python tests/test_exams_view.py   # dashboard card view model (stamps, labels)

export PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers
export DATA_DIR=/tmp/osrm-sw                # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:8084 app.app:app &
.venv/bin/python tests/test_sw.py           # 7/7  (SW registration, scope, cache name)
kill %1

export DATA_DIR=/tmp/osrm-xss
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18099 app.app:app &
.venv/bin/python tests/test_xss.py          # 9/9  (XSS payload renders inert; positive control)
kill %1

export DATA_DIR=/tmp/osrm-guide
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18098 app.app:app &
export DUT_BASE=http://127.0.0.1:18098
.venv/bin/python tests/guide_static.py      # 9/9  Login Flow UX Guide (source level, no server)
.venv/bin/python tests/guide_check.py       # 30 PASS / 0 FAIL / 1 SKIP / 1 N/A (portal mocked in-test)
.venv/bin/python tests/guide_server.py      # 7/7  7 REAL portal logins — spends the 10/hour IP cap
kill %1
```
Tests read `DUT_BASE` to point at a different port; `tests/_seed.py` seeds the user + payload.

## Git & release
- **Branches: `main` only** (merged feature branches get deleted local+remote — do the same).
- Atomic commits; message = finding + evidence + fix + how it was verified.
- **Commit email MUST be `128571614+thenabbu@users.noreply.github.com`** (GH uid 128571614 — never the Discord uid, or commits don't link).
- Push → CI (build+lint) must be green before deploy.
- Release: bump `VERSION` + `pyproject.toml` → `uv lock` → commit → tag `vX.Y.Z` → push tag → deploy → smoke.

## Prod deploy + smoke
```bash
ssh lab 'cd /docker/opensrm && docker compose pull && docker compose up -d'
# smoke: https://srm.200871.xyz/login → 200; HSTS header present (cf-ray path);
# /static/sw.js → service-worker-allowed: / + current cache name (see gotchas);
# POST /api/login/progress {"netid":"x"} → 200, GET → 405.
```
Before touching live DB/SQL: snapshot first (recipe in skill `homelab-backup-management`);
before compose edits: copy `docker-compose.yml.bak-<date>` next to it.

## Safety rules (non-negotiable)
- No secrets/tokens in the tree ever; egress gate reads env `SRM_PROXY_TOKEN`. **PROXY_TOKEN rotated 2026-09-28** — current value at `lab:~/.srm_egress_proxy_token` (600); secrets-API PUT is live immediately (verify with DOUBLE quotes — `"$T1"`, single quotes send the literal string).
- No portal credentials hardcoded; tests mint session cookies, never log in.
- Trust CF headers only with `cf-ray`; HSTS is cf-ray-gated on purpose (plain-HTTP dev).
- Rate limits: 3 syncs/10min/netid · 10/hour IP login · preflight 30s/netid · 1800s cooldown after 3 portal fails.

## Gotchas (bitten at least once)
- `ss` doesn't exist on this host — check ports with a python socket bind, not `ss -tln`.
- Flask test client: pass cookies via `set_cookie`, a `Cookie` header in `headers=` is dropped.
- Timetable `DAY_ORDER` = full weekday names (`Monday`, not `Mon`).
- SW cache name (`opensrm-v12`, read from `sw.js`) must bump when `app/static/` changes — `test_sw.py` asserts it.
- Editing pyproject without `uv lock` fails CI (`uv lock --check`).
- Login-page version badge comes from the `VERSION` file, not pyproject directly.
- Two `CF_FULL_TOKEN=` lines exist in lab `/docker/.env` — the real one is the LAST (line 20).
