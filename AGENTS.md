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
app/app.py            # routes, session/auth, rate limits, sync orchestration — re-exports every name that moved out
app/portal/parsers/   # pure portal-HTML parsers: attendance, marks, timetable, exams, personal, feedback (+ shared helpers)
app/views/            # dashboard view models: attendance budgets, marks IE derivation, ticker, LAYOUT+WIDGETS registries
app/http_scraper.py   # pure-HTTP portal pipeline (Playwright fallback)
app/migrations.py     # versioned schema; runs at import (DATA_DIR)
app/templates|static/ # daisyUI v5, CDN Tailwind (pinned versions + sha384 SRI in partials/theme.html)
tests/                # verify76.py (72 static) + test_sw/test_xss/test_exams*/test_push_* (DUTs + push units) + test_healthz (container probe) + guide_* (login UX guide suites)
egress/               # CF Worker egress proxy + PoCs — NOT in the image (.dockerignore)
docs/                 # audit/ record (findings + resolution) · push.md + push-device-test.md (Web Push) · SCANS.md (supply-chain scans, report-only) · screenshots/ + pr/ (PR evidence) · logos
scripts/               # generate_push_keys.py (VAPID/tick-secret) · rotate_fernet_key.py (Fernet key rotation) · pr_preflight.sh (pre-merge checks) · post_deploy.sh (purge+smoke) · ci_docker_smoke.sh + ci_e2e_http.sh (CI jobs) · canary_sync.sh + canary_cookie.py (one offline-verifiable sync health canary run)
VERSION pyproject.toml uv.lock   # release = bump all three together
.github/workflows/    # tests.yml (unit+docker+e2e, PR gate, reusable) + build.yml (image :latest+:VERSION+:sha, gated on tests) + lint.yml + scans.yml (gitleaks/pip-audit/trivy, report-only); SHA-pinned actions; `uv lock --check`
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

The trailing `# [runner]` column says which CI job runs that suite — `.github/workflows/tests.yml` runs every `[unit]` and `[e2e]` row on each PR and each push to `main`, so a red suite blocks the merge and blocks the `:latest` publish. `[none]` = local only, never CI (`guide_server.py` performs 7 real portal logins per run; the portal caps 10/hour per IP).

```bash
.venv/bin/python tests/verify76.py  # [unit] 72/72 static (findings, docs, pins, versions)
.venv/bin/python tests/test_exams.py  # [unit] 69/69 (official ETT parser + header-drift adaptability + scribe fallback merge + transition/push events)
.venv/bin/python tests/test_exams_view.py  # [unit] dashboard card view model (stamps, labels)
.venv/bin/python tests/test_tt_history.py  # [unit] 18/18 (timetable edit log + break-divider fix + location preservation)
.venv/bin/python tests/test_tt_hero.py  # [unit] 3/3 (the NOW-hero keeps the slot's attendance join `_att` across the dict hop; a missing `_att` is tolerated) — no server
.venv/bin/python tests/test_relogin_save.py  # [unit] 9/9 (mid-scrape relogin persists fresh session + resets portal fail state; portal_sessions encrypted at rest + legacy plaintext row; stubbed fetch, no network)
.venv/bin/python tests/test_fernet_rotation.py  # [unit] 39/39 (FERNET_KEYS -> MultiFernet first-key-encrypts + file-mode default unchanged, rotate script dry-run default / refuse-unreadable-with-count / --skip-unreadable / apply verifies+commits one transaction / idempotent, wrong key -> "" unreadable-creds path, invalid env names FERNET_KEYS without echoing it, no key material in tool output; fabricated keys only)
.venv/bin/python tests/test_official_tt.py  # [unit] 53/53 (portal formId-10 parser + preserve/drift states incl. contentless-grid wipe guard, offset contract official==SLOTS, save/editor stamp round trip + archive gate 403, location carry per code-swap, push+render wiring, rim tiers grey/warn/danger by attendance, Now badge + Soon retired under a faked clock; committed sanitized fixture)
.venv/bin/python tests/test_sessions.py  # [unit] 16/16 (multi-device session survives a second login, expiry prunes at read, real logout deletes + emits its auth line, prefetch logout is a no-op, cross-site logout ignored, index/refresh survive mid-request session loss, token stored as sha256 digest with the raw value never at rest, pre-migration fixture: a v16 DB's raw rows come out of migration 17 hashed and the existing session survives, cross-site guard: SFS cross/same-site and Origin mismatch/'null' refused 403+error= on POST/PUT/PATCH/DELETE, no-header/same-origin/none/GET allowed, /internal/push/tick and /marks/tag exempt (the Cloudflare tunnel rewrites that form POST's fetch metadata — false-403 behind prod while passing locally), refusal logged on opensrm.http)
.venv/bin/python tests/test_login_reject.py  # [unit] rejection classifier + sync-quota order + free-gates-before-budget (section 4) + preflight atomic admission (5) + captcha data-src confinement (6) + attempt-token progress + edge-secret CF trust (7-8) + typed kind→status differential over every {'ok': False} producer, old-vs-new (9) (offline)
.venv/bin/python tests/test_fault_handling.py  # [unit] 12/12 (corrupt-row degradation B1-B4, _semester_int B5, marks preserve B6, refresh subjects preserve R1 + preserve-visibility log line, attendance preserve on partial fetch, S25 refetch, errorhandler)
.venv/bin/python tests/test_logging_telemetry.py  # [unit] 10/10 (ntfy tripwire gates on ERROR/5xx + async post + failed-send retry, kv cause on 5xx alerts, rotation, telemetry env passthrough, control-char scrub in log+ntfy, non-ASCII X-Push-Tick -> 401 not 500)
.venv/bin/python tests/test_metrics.py  # [unit] 10/10 (sync outcome+duration by pipeline/error class, captcha attempts per login, preflight ready/wasted/consumed, scrape-lock rejections, parse-empty per page, /internal/metrics secret-header auth: unset env = off, bare 401, non-ASCII fail-closed; usage_events retention env (365d default, once a day, count logged); every >=400 status line carries error= — offline, red-tested)
.venv/bin/python tests/test_sync_cache.py  # [unit] 6/6 (refresh cache window: inside SYNC_MIN_INTERVAL_S the answer is {ok, cached, age_s} with zero portal calls + one kv log line + opensrm_sync_cached_total + sync_cached usage event and the quota untouched; expired window / window 0 / env parsing unset→300 / 900 / -5 / abc; N concurrent refreshes = ONE portal call, quota charged exactly once, every joiner shares the runner's result (outcome=shared); joiner past the wait → busy 503 while the runner still succeeds; a login with credentials always syncs inside the window; offline, red-tested both guards)
.venv/bin/python tests/test_account_delete.py  # [unit] 15/15 (POST /api/account/delete residue — schema-driven: walks every live table and column, so a later migration that adds an uncovered netid-holding column FAILS the suite; hashed-cookie deletion post-migration-17, portal_sessions, push rows, usage_events, edit-log attribution wiped while shared timetable rows survive, per-netid 429 rate limit, one opensrm.auth line with counts, 401 unauth, cross-site guard passes; offline, mutation-tested)
.venv/bin/python tests/test_sync_queue.py  # [unit] 8/8 (bounded queue wait: exactly C run at once at C=1 (6 racing threads) and C=2 (barrier INSIDE the pipeline — under-admission breaks it), login parks ahead of an earlier refresh and runs first, waiters publish "Waiting for N ahead…" to the progress tracker then hand over to the pipeline, queue timeout → busy kind 503 + opensrm_scrape_lock_rejections_total + quota untouched (red-tested: the caller must WAIT — old code answered at 0.00s), portal-budget buckets (preflight own cap 10, login+preflight share 20, aggregate 30, per-IP 6 unchanged), preflight refused by queue depth > 0 / admitted at 0, Playwright fallback stays serialized at pool=2; offline, barrier-driven)
.venv/bin/python tests/test_canary_sync.py  # [unit] 13/13 (scripts/canary_sync.sh against a self-booting local server with the fetch stubbed by netid: success arm writes the payload, no-creds and empty-parse arms exit non-zero with the reason, a SYNC_MIN_INTERVAL_S cache-window answer fails with no-portal-contact instead of reporting sync=1, cookie deleted after every run, exactly ONE sync; needs gunicorn next to sys.executable)
.venv/bin/python tests/test_marks_view.py  # [unit] marks view model (fmt, IE derivation/conversion, class key)
.venv/bin/python tests/test_layout.py  # [unit] 25/25 card/widget engine (LAYOUT spans, WIDGETS partials exist, `when`-filter drops all-empty cards, unknown widget id renders nothing, budget rows risk-first, teacher initials/mode, ticker states, CSS block) — no server
.venv/bin/python tests/test_attendance_view.py  # [unit] 83/83 attendance view model (frozen table, injected today=2026-10-05, budgets, join, degrade cases)
.venv/bin/python tests/test_att_dut.py  # [e2e] 15/15 attendance tab DUT (view toggle + persistence, table columns/colors, label sandwich order, zero overlaps at 393 AND 320px incl. pole-band boundary seeds, merged absences card + junk-month chip-only degrade, Estimates gate, CL row listed in both views)
.venv/bin/python tests/test_feedback.py  # [unit] 71/71 (harvester parse, live question-id extraction, registered markers, faculty view, fb_plan per-teacher rows preview==payload + literal "none", v13 migration + v16 fb_open, endpoint 401, CWE-209 response body, FeedbackWindowClosed vs youLogin classification, _fb_cold state machine (map/closed/degraded), merge contract fb_open learned/preserve/default, fill 409 on closed window, dashboard render gate CTA+modal archived)
.venv/bin/python tests/test_feedback_dut.py  # [e2e] 31/31 DUT (Teachers card + CTA → opt-in explainer modal with BOTH teachers listed, honest no-session error + toast, negative control, overflow) — needs DATA_DIR+DUT_BASE
.venv/bin/python tests/test_feedback_contrast.py  # [e2e] 8+/8+ WCAG pairs (Teachers card + explainer modal; oklch+oklab parser, decimal-alpha trap) — needs DATA_DIR+DUT_BASE
.venv/bin/python tests/test_dash_fit.py  # [e2e] 23/23 dashboard fit + feedback archive DUT (desktop: no page scrollbar, grid == 100dvh−94px chrome (navbar 64 + uniform 15px edge), uniform 15px card-column edge on BOTH sides scrollbar-strip-compensated + navbar-aligned, rows auto/1fr with the assess card's LAYOUT `cap` max-height — 65%-of-grid ceiling stress-pinned, uncapped auto crushed row 2 to 2px under 14-exam load at 1024×768, %-rows rejected (maximize-tracks stretches them) —, zero card-body residue at 1920×944/1366×768 (widgets absorb the cell), notices ≤320; fb_open 1→0→1 render toggle; mobile: page still scrolls, no h-overflow) — self-boots

# push unit suites (no server, no network)
.venv/bin/python tests/test_push_calc.py  # [unit] 33/33 (due window edges, blocks/rooms, tz-from-UTC, idempotency, TTL)
.venv/bin/python tests/test_push_store.py # [unit] 28/28 (claims/at-most-once, orphan recovery, AST portable-SQL gate)
.venv/bin/python tests/test_push_send.py  # [unit] 16/16 (mocked pywebpush: ok / 410-dead-cleanup / 5xx-retry, deadline)
.venv/bin/python tests/test_push_tick.py  # [unit] 21/21 (secret auth, dry-run, allowlist, deadline cut-off, overlap)
.venv/bin/python tests/test_push_api.py   # [unit] 42/42 (401 style, validation, DB rate caps, test/receipt flows, per-type notification prefs)
.venv/bin/python tests/test_supply_chain.py  # [unit] 26/26 (compose OPENSRM_TAG pin + byte-identical :latest default, build.yml VERSION tag + OCI version/revision labels, scans.yml report-only + SHA-pinned actions, SCANS.md flip-to-blocking docs) — no server
.venv/bin/python tests/test_healthz.py  # [unit] 6/6 (GET /healthz: no cookie -> 200 {status:ok} <=32B, a valid session changes nothing, zero sockets opened = SELECT 1 only, DB failure -> 503 {status:error} with no leak, probe request line demoted to DEBUG while a non-probe request stays INFO+, a 503 still logs ERROR so ntfy pages) — self-booting, no server, red-tested on both guards

export PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers
export DATA_DIR=/tmp/osrm-sw                # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:8084 app.app:app &
.venv/bin/python tests/test_sw.py         # [e2e] 7/7  (SW registration, scope, cache name)
kill %1

export DATA_DIR=/tmp/osrm-xss
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18099 app.app:app &
.venv/bin/python tests/test_xss.py        # [e2e] 9/9  (XSS payload renders inert; positive control)
kill %1

export DATA_DIR=/tmp/osrm-marks
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18180 app.app:app &
.venv/bin/python tests/test_marks_dut.py  # [e2e] 53/53 marks tab (colours, chips, uniform rows, tooltip, glance, dismiss, round-trip)
kill %1

# official-timetable DUT — self-boots gunicorn on a free port (seed+mint inside,
# seeds 3 attendance tiers so the rim colours render), DOM-asserts corrected
# clock + archive contract (no badges/history/button, save 403) + rim tiers +
# Soon retired, screenshots desktop+mobile
# (needs PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers)
.venv/bin/python tests/dut_official_tt.py # [e2e] 14/14 (archive contract under default TIMETABLE_EDITOR: synced badge gone, edit history gone, edit button absent, save API 403; Soon retired + rim tiers grey/yellow/red by attendance; guards: require_own_server + missing gunicorn; scrollWidth no-overflow @393)

export DATA_DIR=/tmp/osrm-navbar            # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18178 app.app:app &
.venv/bin/python tests/test_navbar.py     # [e2e] 19/19 (netid echo, selected-tab tint + bar geometry, sync caption, mobile badge, logo radius, page gutter 8px/15px + column alignment, scrollbar-gutter reservation + navW constant across a marks round-trip)
kill %1

export DATA_DIR=/tmp/osrm-personal          # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18179 app.app:app &
DUT_BASE=http://127.0.0.1:18179 .venv/bin/python tests/test_personal.py   # [e2e] 23/23 Settings tab (row list + logout placement + Delete my data row last, collapsed personal row, identity header, collapse groups, responsive defaults, 0<8<12 ladder, contrast sweep, copy round-trip)
kill %1

export DATA_DIR=/tmp/osrm-accdel            # fresh dir; seed+mint happen inside the test
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18181 app.app:app &
DUT_BASE=http://127.0.0.1:18181 .venv/bin/python tests/test_delete_dut.py   # [e2e] 12/12 Delete my data DUT (Settings row anatomy @1280 AND @393, explainer modal = erase/never-touch contract incl. the SRM-portal line, ONE confirm button, Cancel inert, modal contrast sweep 0 fails both viewports, real confirm → /login round trip + session cookie cleared)
kill %1

export DATA_DIR=/tmp/osrm-guide
.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:18098 app.app:app &
export DUT_BASE=http://127.0.0.1:18098
.venv/bin/python tests/guide_static.py    # [unit] 9/9  Login Flow UX Guide (source level, no server)
.venv/bin/python tests/test_db_concurrency.py  # [unit] 14/14 (db() policy: 10s busy timeout survives a 6s lock hold where the old 5s default failed, thread stress zero locked, SQLITE_JOURNAL_MODE delete/wal/flip-back/invalid fallback via child-process boots)
.venv/bin/python tests/guide_check.py     # [e2e] 30 PASS / 0 FAIL / 1 SKIP / 1 N/A (portal mocked in-test)
.venv/bin/python tests/guide_server.py    # [none] 6 items, green = 0 FAIL (2 come back INCONCLUSIVE when the portal/IP limiter interferes) — 7 live portal probes, NEVER loop it; the wrong-password arm is opt-in via GUIDE_WRONGPASS_NETID=<existing netid>
kill %1

# push DUTs boot their own three gunicorn instances (see header)
.venv/bin/bash tests/run_push_duts.sh        # [e2e] test_push_sw 8/8 + test_push_ui 25/25 (staggered boots: fresh-DB migrations race)
```
Tests read `DUT_BASE` to point at a different port; `tests/_seed.py` seeds the user + payload — and every HTTP suite calls `require_own_server(BASE)` first, so a suite pointed at another agent's server (or a dead one, or a mismatched `DATA_DIR`) exits 1 with `FAIL[guard]: …` before any browser/login work instead of returning a phantom verdict.

## Git & release
- **Branches: `main` only** (merged feature branches get deleted local+remote — do the same).
- Atomic commits; message = finding + evidence + fix + how it was verified.
- **Commit email MUST be `128571614+thenabbu@users.noreply.github.com`** (GH uid 128571614 — never the Discord uid, or commits don't link).
- Push → CI must be green before deploy: **Lint** (`uvx ruff check app/` + `uv lock --check`) · **Tests** (`unit` + `docker` + `e2e`, `.github/workflows/tests.yml`) · **Build & Push** (image → GHCR as `:latest` + `:<VERSION>` + `:<short-sha>` with `org.opencontainers.image.version/.revision` labels, `needs: [lint, tests]` on `main` so a red suite never pushes `:latest`) · **Scans** (gitleaks/pip-audit/trivy, always report-only — docs/SCANS.md) · the CodeQL checks the default code-scanning setup runs. A `unit` or `e2e` job that goes red on a PR is a real suite failure, not a flake — each suite is its own step/line with its own `DATA_DIR`.
- Release: bump `VERSION` + `pyproject.toml` → `uv lock` → commit → tag `vX.Y.Z` → push tag → deploy → smoke.

## Prod deploy + smoke
```bash
ssh lab 'cd /docker/opensrm && docker compose pull && docker compose up -d'
# Rollback to a released image (CI publishes :<VERSION> next to :latest):
#   add OPENSRM_TAG=<VERSION> to /docker/opensrm/.env (the PROJECT env file —
#   compose does NOT read the master /docker/.env for interpolation), then
#   docker compose pull && docker compose up -d opensrm; unset to ride :latest again.
# smoke: https://srm.200871.xyz/login → 200; HSTS header present (cf-ray path);
# GET /healthz → 200 {"status":"ok"} — the endpoint the compose healthcheck
# polls (no session needed); at LOG_LEVEL=INFO its request lines are DEBUG, so
# they never appear in `docker logs opensrm` — that absence means the LOG
# LEVEL, not that the probe stopped (docker inspect opensrm --format
# '{{.State.Health.Status}}' says 'healthy').
# /static/sw.js → service-worker-allowed: / + current cache name (see gotchas);
# POST /api/login/progress {"netid":"ab1234"} → 200, GET → 405.
# ({"netid":"x"} → 400 by design: NETID_RE is ^[a-z0-9]{2,20}$ — the old
#  smoke recipe used "x" and read as a failure until this line was fixed.)
# AUTHENTICATED RENDER (added Oct 8 2026 after _faculty_view 500'd every
# dashboard while /login stayed green): mint a cookie for an existing user
# (make_session_token — it returns the raw token for the cookie; since
# v1.20.3 the cookies row stores its sha256 digest, never the raw value)
# and assert / → 200 with real row data — /login only
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
- Rate limits: 3 syncs/10min/netid (counted only when the sync actually runs — a queue-timeout/busy/cooldown/budget rejection is free, and so are a refresh served from the last completed sync within `SYNC_MIN_INTERVAL_S` (default 300s, 0 disables) and a joiner sharing an in-flight sync's result) · 10/hour IP login · aggregate portal budget 30/10min split into buckets — full login + preflight share 20 (preflight's own cap 10), refresh floor 10, one IP ≤6 unauth tokens · syncs wait in queue up to `SYNC_QUEUE_WAIT_S` (default 45s, 0 = refuse immediately), logins ahead of refreshes, position published as "Waiting for N ahead…" — a waiter past the wait gets the busy 503; `SYNC_MAX_CONCURRENCY` (default 1) sizes the slot pool and the Playwright fallback stays serialized at any setting · preflight 30s/netid, refused when queue depth > 0 · portal cooldown arms at 3 consecutive fails (5 min, doubling, capped 1800s = 30 min).

## Gotchas (bitten at least once)
- `ss` doesn't exist on this host — check ports with a python socket bind, not `ss -tln`.
- Flask test client: pass cookies via `set_cookie`, a `Cookie` header in `headers=` is dropped.
- Timetable `DAY_ORDER` = full weekday names (`Monday`, not `Mon`).
- SW cache name (read from `sw.js` — current value v33; test_sw.py derives it) must bump when `app/static/` changes — `test_sw.py` asserts it, and README's architecture diagram must match (verify76 L37/D58).
- Editing pyproject without `uv lock` fails CI (`uv lock --check`).
- Login-page version badge comes from the `VERSION` file, not pyproject directly.
- SQLite: every connection funnels through `app.app.db()` (10s busy timeout, `SQLITE_JOURNAL_MODE` env, default `delete`). Forensic `docker cp` of the DB must copy `srm.db` **plus `-wal` and `-shm`** when WAL is on — or use `sqlite3 “.backup”` (the daily snapshot pipeline already does; it is WAL-safe). Raw `cp` under WAL silently misses recent commits.
- Two `CF_FULL_TOKEN=` lines exist in lab `/docker/.env` — the real one is the LAST (line 20).
- The portal login page markup itself contains `captcha` (x17) and `invalid` (Bootstrap `.invalid-feedback`) — never classify a rejection on those tokens or EVERY failure reads as "invalid captcha" (this hid a wrong password behind 3 captcha retries and burned the portal's own 3-attempts-per-NetID lockout). Classify on the portal's `<h6 class="alert-heading">Alert</h6>` text; `tests/test_login_reject.py` holds the verbatim strings.
