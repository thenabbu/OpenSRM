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
tests/                # verify76.py (71 static) + test_sw/test_xss/test_exams*/test_push_* (DUTs + push units) + guide_* (login UX guide suites)
egress/               # CF Worker egress proxy + PoCs — NOT in the image (.dockerignore)
docs/                 # audit/ record (findings + resolution) · push.md + push-device-test.md (Web Push) · screenshots/ + pr/ (PR evidence) · logos
scripts/               # generate_push_keys.py (one-time VAPID/tick-secret generator)
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
.venv/bin/python tests/test_exams.py        # 27/27 (end-sem probe parser + candidates + blanked-dates preserve)
.venv/bin/python tests/test_exams_view.py    # dashboard card view model (stamps, labels)
.venv/bin/python tests/test_tt_history.py    # 18/18 (timetable edit log + break-divider fix + location preservation)
.venv/bin/python tests/test_login_reject.py  # rejection classifier + sync-quota order (offline)
.venv/bin/python tests/test_fault_handling.py  # 9/9 (corrupt-row degradation B1-B4, _semester_int B5, marks preserve B6, S25 refetch, errorhandler)
.venv/bin/python tests/test_marks_view.py    # marks view model (fmt, IE derivation/conversion, class key)
.venv/bin/python tests/test_attendance_view.py # 80/80 attendance view model (frozen table, injected today=2026-10-05, budgets, join, degrade cases)
.venv/bin/python tests/test_att_dut.py   # 10/10 attendance tab DUT (view toggle + persistence, table columns/colors, label sandwich order, zero overlaps, merged absences card)

# push unit suites (no server, no network)
.venv/bin/python tests/test_push_calc.py     # 32/32 (due window edges, blocks/rooms, tz-from-UTC, idempotency, TTL)
.venv/bin/python tests/test_push_store.py    # 25/25 (claims/at-most-once, orphan recovery, AST portable-SQL gate)
.venv/bin/python tests/test_push_send.py     # 16/16 (mocked pywebpush: ok / 410-dead-cleanup / 5xx-retry, deadline)
.venv/bin/python tests/test_push_tick.py     # 19/19 (secret auth, dry-run, allowlist, deadline cut-off, overlap)
.venv/bin/python tests/test_push_api.py      # 37/37 (401 style, validation, DB rate caps, test/receipt flows)

export PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers
export DATA_DIR=/tmp/osrm-sw                # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:8084 app.app:app &
.venv/bin/python tests/test_sw.py           # 7/7  (SW registration, scope, cache name)
kill %1

export DATA_DIR=/tmp/osrm-xss
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18099 app.app:app &
.venv/bin/python tests/test_xss.py           # 9/9  (XSS payload renders inert; positive control)
kill %1

export DATA_DIR=/tmp/osrm-marks
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18180 app.app:app &
.venv/bin/python tests/test_marks_dut.py     # 53/53 marks tab (colours, chips, uniform rows, tooltip, glance, dismiss, round-trip)
kill %1

export DATA_DIR=/tmp/osrm-navbar            # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18178 app.app:app &
.venv/bin/python tests/test_navbar.py       # 18/18 (netid echo, selected-tab tint + bar geometry, sync caption, mobile badge, logo radius, page gutter 8px/16px + column alignment)
kill %1

export DATA_DIR=/tmp/osrm-personal          # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18179 app.app:app &
DUT_BASE=http://127.0.0.1:18179 .venv/bin/python tests/test_personal.py   # 18/18 personal tab (identity header, collapse groups, responsive defaults, 0<8<12 ladder, contrast sweep, copy round-trip)
kill %1

export DATA_DIR=/tmp/osrm-guide
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18098 app.app:app &
export DUT_BASE=http://127.0.0.1:18098
.venv/bin/python tests/guide_static.py      # 9/9  Login Flow UX Guide (source level, no server)
.venv/bin/python tests/guide_check.py       # 30 PASS / 0 FAIL / 1 SKIP / 1 N/A (portal mocked in-test)
.venv/bin/python tests/guide_server.py      # 7/7  7 REAL portal logins — spends the 10/hour IP cap
kill %1

# push DUTs boot their own three gunicorn instances (see header)
.venv/bin/bash tests/run_push_duts.sh        # test_push_sw 8/8 + test_push_ui 15/15 (staggered boots: fresh-DB migrations race)
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
# POST /api/login/progress {"netid":"ab1234"} → 200, GET → 405.
# ({"netid":"x"} → 400 by design: NETID_RE is ^[a-z0-9]{2,20}$ — the old
#  smoke recipe used "x" and read as a failure until this line was fixed.)
```
Before touching live DB/SQL: snapshot first (recipe in skill `homelab-backup-management`);
before compose edits: copy `docker-compose.yml.bak-<date>` next to it.

## Safety rules (non-negotiable)
- No secrets/tokens in the tree ever; egress gate reads env `SRM_PROXY_TOKEN`. **PROXY_TOKEN rotated 2026-09-28** — current value at `lab:~/.srm_egress_proxy_token` (600); secrets-API PUT is live immediately (verify with DOUBLE quotes — `"$T1"`, single quotes send the literal string).
- No portal credentials hardcoded; tests mint session cookies, never log in.
- Trust CF headers only with `cf-ray`; HSTS is cf-ray-gated on purpose (plain-HTTP dev).
- Rate limits: 3 syncs/10min/netid (counted only when the sync actually runs — busy/cooldown/budget rejections are free) · 10/hour IP login · aggregate portal budget 30/10min · preflight 30s/netid · portal cooldown arms at 3 consecutive fails (5 min, doubling, capped 1800s = 30 min).

## Gotchas (bitten at least once)
- `ss` doesn't exist on this host — check ports with a python socket bind, not `ss -tln`.
- Flask test client: pass cookies via `set_cookie`, a `Cookie` header in `headers=` is dropped.
- Timetable `DAY_ORDER` = full weekday names (`Monday`, not `Mon`).
- SW cache name (read from `sw.js` — current value v20; test_sw.py derives it) must bump when `app/static/` changes — `test_sw.py` asserts it, and README's architecture diagram must match (verify76 L37/D58).
- Editing pyproject without `uv lock` fails CI (`uv lock --check`).
- Login-page version badge comes from the `VERSION` file, not pyproject directly.
- Two `CF_FULL_TOKEN=` lines exist in lab `/docker/.env` — the real one is the LAST (line 20).
- The portal login page markup itself contains `captcha` (x17) and `invalid` (Bootstrap `.invalid-feedback`) — never classify a rejection on those tokens or EVERY failure reads as "invalid captcha" (this hid a wrong password behind 3 captcha retries and burned the portal's own 3-attempts-per-NetID lockout). Classify on the portal's `<h6 class="alert-heading">Alert</h6>` text; `tests/test_login_reject.py` holds the verbatim strings.
