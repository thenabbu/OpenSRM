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
tests/                # verify76.py (72 static) + test_sw/test_xss/test_exams*/test_push_* (DUTs + push units) + guide_* (login UX guide suites)
egress/               # CF Worker egress proxy + PoCs — NOT in the image (.dockerignore)
docs/                 # audit/ record (findings + resolution) · push.md + push-device-test.md (Web Push) · screenshots/ + pr/ (PR evidence) · logos
scripts/               # generate_push_keys.py (VAPID/tick-secret) · pr_preflight.sh (pre-merge checks) · post_deploy.sh (purge+smoke)
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
.venv/bin/python tests/verify76.py          # 72/72 static (findings, docs, pins, versions)
.venv/bin/python tests/test_exams.py        # 69/69 (official ETT parser + header-drift adaptability + scribe fallback merge + transition/push events)
.venv/bin/python tests/test_exams_view.py    # dashboard card view model (stamps, labels)
.venv/bin/python tests/test_tt_history.py    # 18/18 (timetable edit log + break-divider fix + location preservation)
.venv/bin/python tests/test_relogin_save.py # 6/6 (mid-scrape relogin persists fresh session + resets portal fail state; stubbed fetch, no network)
.venv/bin/python tests/test_official_tt.py    # 53/53 (portal formId-10 parser + preserve/drift states incl. contentless-grid wipe guard, offset contract official==SLOTS, save/editor stamp round trip + archive gate 403, location carry per code-swap, push+render wiring, rim tiers grey/warn/danger by attendance, Now badge + Soon retired under a faked clock; committed sanitized fixture)
.venv/bin/python tests/test_sessions.py     # 5/5 (multi-device session survives a second login, expiry prunes at read, real logout deletes, prefetch logout is a no-op, index/refresh survive mid-request session loss)
.venv/bin/python tests/test_login_reject.py  # rejection classifier + sync-quota order (offline)
.venv/bin/python tests/test_fault_handling.py  # 9/9 (corrupt-row degradation B1-B4, _semester_int B5, marks preserve B6, S25 refetch, errorhandler)
.venv/bin/python tests/test_logging_telemetry.py # 8/8 (ntfy tripwire gates on ERROR/5xx + async post + failed-send retry, kv cause on 5xx alerts, rotation, telemetry env passthrough)
.venv/bin/python tests/test_marks_view.py    # marks view model (fmt, IE derivation/conversion, class key)
.venv/bin/python tests/test_layout.py       # 25/25 card/widget engine (LAYOUT spans, WIDGETS partials exist, `when`-filter drops all-empty cards, unknown widget id renders nothing, budget rows risk-first, teacher initials/mode, ticker states, CSS block) — no server
.venv/bin/python tests/test_attendance_view.py # 83/83 attendance view model (frozen table, injected today=2026-10-05, budgets, join, degrade cases)
.venv/bin/python tests/test_att_dut.py   # 15/15 attendance tab DUT (view toggle + persistence, table columns/colors, label sandwich order, zero overlaps at 393 AND 320px incl. pole-band boundary seeds, merged absences card + junk-month chip-only degrade, Estimates gate, CL row listed in both views)
.venv/bin/python tests/test_feedback.py      # 71/71 (harvester parse, live question-id extraction, registered markers, faculty view, fb_plan per-teacher rows preview==payload + literal "none", v13 migration + v16 fb_open, endpoint 401, CWE-209 response body, FeedbackWindowClosed vs youLogin classification, _fb_cold state machine (map/closed/degraded), merge contract fb_open learned/preserve/default, fill 409 on closed window, dashboard render gate CTA+modal archived)
.venv/bin/python tests/test_feedback_dut.py  # 31/31 DUT (Teachers card + CTA → opt-in explainer modal with BOTH teachers listed, honest no-session error + toast, negative control, overflow) — needs DATA_DIR+DUT_BASE
.venv/bin/python tests/test_feedback_contrast.py # 8+/8+ WCAG pairs (Teachers card + explainer modal; oklch+oklab parser, decimal-alpha trap) — needs DATA_DIR+DUT_BASE
.venv/bin/python tests/test_dash_fit.py      # 20/20 dashboard fit + feedback archive DUT (desktop: no page scrollbar, grid == 100dvh−104px chrome, rows auto/1fr with the assess card's LAYOUT `cap` max-height — 65%-of-grid ceiling stress-pinned, uncapped auto crushed row 2 to 2px under 14-exam load at 1024×768, %-rows rejected (maximize-tracks stretches them) —, zero card-body residue, notices ≤320; fb_open 1→0→1 render toggle; mobile: page still scrolls, no h-overflow) — self-boots

# push unit suites (no server, no network)
.venv/bin/python tests/test_push_calc.py     # 33/33 (due window edges, blocks/rooms, tz-from-UTC, idempotency, TTL)
.venv/bin/python tests/test_push_store.py    # 28/28 (claims/at-most-once, orphan recovery, AST portable-SQL gate)
.venv/bin/python tests/test_push_send.py     # 16/16 (mocked pywebpush: ok / 410-dead-cleanup / 5xx-retry, deadline)
.venv/bin/python tests/test_push_tick.py     # 21/21 (secret auth, dry-run, allowlist, deadline cut-off, overlap)
.venv/bin/python tests/test_push_api.py      # 42/42 (401 style, validation, DB rate caps, test/receipt flows, per-type notification prefs)

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

# official-timetable DUT — self-boots gunicorn on a free port (seed+mint inside,
# seeds 3 attendance tiers so the rim colours render), DOM-asserts corrected
# clock + archive contract (no badges/history/button, save 403) + rim tiers +
# Soon retired, screenshots desktop+mobile
# (needs PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers)
.venv/bin/python tests/dut_official_tt.py    # 14/14 (archive contract under default TIMETABLE_EDITOR: synced badge gone, edit history gone, edit button absent, save API 403; Soon retired + rim tiers grey/yellow/red by attendance; guards: require_own_server + missing gunicorn; scrollWidth no-overflow @393)

export DATA_DIR=/tmp/osrm-navbar            # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18178 app.app:app &
.venv/bin/python tests/test_navbar.py       # 19/19 (netid echo, selected-tab tint + bar geometry, sync caption, mobile badge, logo radius, page gutter 8px/16px + column alignment, scrollbar-gutter reservation + navW constant across a marks round-trip)
kill %1

export DATA_DIR=/tmp/osrm-personal          # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18179 app.app:app &
DUT_BASE=http://127.0.0.1:18179 .venv/bin/python tests/test_personal.py   # 23/23 Settings tab (row list + logout placement, collapsed personal row, identity header, collapse groups, responsive defaults, 0<8<12 ladder, contrast sweep, copy round-trip)
kill %1

export DATA_DIR=/tmp/osrm-guide
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18098 app.app:app &
export DUT_BASE=http://127.0.0.1:18098
.venv/bin/python tests/guide_static.py      # 9/9  Login Flow UX Guide (source level, no server)
.venv/bin/python tests/guide_check.py       # 30 PASS / 0 FAIL / 1 SKIP / 1 N/A (portal mocked in-test)
.venv/bin/python tests/guide_server.py      # 7/7  7 REAL portal logins — spends the 10/hour IP cap
kill %1

# push DUTs boot their own three gunicorn instances (see header)
.venv/bin/bash tests/run_push_duts.sh        # test_push_sw 8/8 + test_push_ui 25/25 (staggered boots: fresh-DB migrations race)
```
Tests read `DUT_BASE` to point at a different port; `tests/_seed.py` seeds the user + payload — and every HTTP suite calls `require_own_server(BASE)` first, so a suite pointed at another agent's server (or a dead one, or a mismatched `DATA_DIR`) exits 1 with `FAIL[guard]: …` before any browser/login work instead of returning a phantom verdict.

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
# AUTHENTICATED RENDER (added Oct 8 2026 after _faculty_view 500'd every
# dashboard while /login stayed green): mint a cookie for an existing user
# (INSERT INTO cookies) and assert / → 200 with real row data — /login only
# proves the shell boots, not that stored-data paths render.
```
Then run `bash scripts/post_deploy.sh` from the checkout — it does the whole
verification chain (prod-image SHA == origin/main, changed-static purge, edge
MISS + byte-identity, authenticated render, cookie cleanup) in one exit code;
`bash scripts/pr_preflight.sh` is its pre-merge twin (freshness, merge-tree
conflicts, duplicate migrations, version trio/race, sw-cache docs).
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
- SW cache name (read from `sw.js` — current value v27; test_sw.py derives it) must bump when `app/static/` changes — `test_sw.py` asserts it, and README's architecture diagram must match (verify76 L37/D58).
- Editing pyproject without `uv lock` fails CI (`uv lock --check`).
- Login-page version badge comes from the `VERSION` file, not pyproject directly.
- Two `CF_FULL_TOKEN=` lines exist in lab `/docker/.env` — the real one is the LAST (line 20).
- The portal login page markup itself contains `captcha` (x17) and `invalid` (Bootstrap `.invalid-feedback`) — never classify a rejection on those tokens or EVERY failure reads as "invalid captcha" (this hid a wrong password behind 3 captcha retries and burned the portal's own 3-attempts-per-NetID lockout). Classify on the portal's `<h6 class="alert-heading">Alert</h6>` text; `tests/test_login_reject.py` holds the verbatim strings.
