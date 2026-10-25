# AGENTS.md — quickstart for a working agent (OpenSRM)

Flask monolith that scrapes the SRM student portal (pure-HTTP pipeline;
Playwright fallback archived behind `PLAYWRIGHT_FALLBACK`, off by default
and Chromium is omitted from the shipped image unless built
`WITH_PLAYWRIGHT=1`) and renders attendance/marks/timetable dashboards.

**Release rule:** version lives in the `VERSION` file (read by `app.py` →
login badge). Keep `VERSION` == `pyproject.toml` == `uv.lock`
(`tests/unit/test_audit_findings.py` M23 checks this).

## Where things run

- **Local dev**: repo at `/opt/data/opensrm-repo` (hermes host), venv
  `.venv` (uv; NEVER npm at runtime — CSS is compiled ahead of time with a
  pinned Tailwind CLI and committed as `app/static/app.css`
  (`scripts/build-css.sh`), no runtime CDN; pnpm only for isolated one-off
  JS tooling, never in the runtime image).
- **Prod**: lab host, container `opensrm` (compose project at
  `/docker/opensrm` — the live file lags the repo copy until synced;
  `docs/runbook.md` Deploy sequences the sync), port `127.0.0.1:8083` +
  `172.31.0.1:8083` (cloudflared gateway), served at
  https://srm.200871.xyz via CF tunnel
  `c2308be7-6527-4da3-a96c-49c4b4c918c0`.
- **Do NOT touch** `flights.200871.xyz` (DNS/ingress) — another agent owns
  that subdomain.

## Layout

```
app/app.py            # create_app() factory (data dir, secret, migrations, OCR prewarm) + views,
                      # session/auth, portal budget, sync orchestration — re-exports every name
                      # that moved out; registers the route blueprints
app/config.py         # AppConfig (frozen dataclass) + from_env(): boot env read ONCE
                      # (DATA_DIR, OCR_PREWARM); request-time knobs stay env-per-call by design
app/db.py             # sqlite layer: connect() (pragmas, per-app DB path inside an app context),
                      # request-scoped db() + teardown, transaction(), repository (all SQL lives here)
app/blueprints/       # FlatBlueprint route tables (endpoints stay bare): auth · dashboard · marks ·
                      # timetable · push · feedback · internal — 23 rules → app/app.py views
                      # (/avatar + /avatar/<name> register at app level; 26 routes total)
app/security.py       # shared route decorators (require_login — guards views across blueprints)
app/state.py          # RateLimiter · ProgressTracker · PortalHealth — every in-memory limit behind
                      # ONE lock with TTL pruning (old module-level names re-exported by app.py)
app/portal/parsers/   # pure portal-HTML parsers: attendance, marks, timetable, exams, personal,
                      # feedback (+ shared helpers)
app/views/            # dashboard view models: attendance budgets, marks IE derivation, ticker,
                      # LAYOUT+WIDGETS registries
app/http_scraper.py   # pure-HTTP portal pipeline (archived Playwright fallback)
app/migrations.py     # versioned schema (16 migrations → v17); runs inside create_app()
app/templates|static/ # daisyUI v5, pre-compiled app.css (pinned Tailwind CLI build via
                      # scripts/build-css.sh; safelist for render-time classes), theme tokens in
                      # partials/theme.html
tests/                # unit/ (36 no-server suites) · e2e/ (20 Playwright DUTs) · _seed/_canary
                      # helpers + fixtures/ · README.md = the manifest
egress/               # CF Worker egress proxy + PoCs — NOT in the image (.dockerignore)
ops/observability/    # OPTIONAL metrics stack next to the app (never in the image): Prometheus
                      # (scrapes GET /internal/metrics with X-Metrics-Token from a 600-mode secret
                      # file) + Grafana (read-only provisioned dashboard) + Alertmanager
                      # (webhook -> ntfy); bring-up/panels/alerts: docs/runbook.md
docs/                 # runbook.md (operator runbook) · audit/ records · push.md · SCANS.md ·
                      # perf/ · screenshots/ + pr/ (PR evidence) · privacy.md · logos
scripts/              # generate_push_keys.py · rotate_fernet_key.py · restore_drill.sh ·
                      # url_map_dump.py (canonical route dump) · pr_preflight.sh · post_deploy.sh ·
                      # ci_docker_smoke.sh + ci_e2e_http.sh · canary_sync.sh + canary_cookie.py ·
                      # perf_baseline.py
VERSION pyproject.toml uv.lock   # release = bump all three together
.github/workflows/    # tests.yml (unit+docker+e2e, PR gate) + build.yml (image :latest+:VERSION+
                      # :sha, gated on tests) + lint.yml + scans.yml (report-only); SHA-pinned
                      # actions; `uv lock --check`
```

## Dev loop (do this every time)

```bash
cd /opt/data/opensrm-repo
uvx --quiet ruff check app/          # == CI lint
uv lock --check                      # == CI lock check (after pyproject edits run `uv lock` first)
# scripts/build-css.sh                # after template edits that add new utility classes
#                                     # (app.css is committed; CI fails if stale)

# pick a FREE port first — 8084/8085 get squatted by other local services:
python3 -c "import socket;s=socket.socket();s.bind(('127.0.0.1',18099));print('free');s.close()"
DATA_DIR=/tmp/osrm-dev LOG_LEVEL=DEBUG .venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:<PORT> app.app:app
```

Migrations run inside `create_app()` — the module-level `app = create_app()`
still boots at import, so a fresh `DATA_DIR` = fresh DB, boots clean.

## Test matrix (all green before push)

Trailing `# [runner]` = the CI job that runs the suite (`.github/workflows/tests.yml`
runs every `[unit]` and `[e2e]` row on each PR and each push to `main`; a red
suite blocks the merge and the `:latest` publish). `[none]` = local only,
never CI (`test_login_guide_server` performs 7 real portal logins per run;
the portal caps 10/hour per IP).

```bash
# ── unit (no server / no browser) ──────────────────────────────────────────
.venv/bin/python tests/unit/test_audit_findings.py  # [unit] 72/72 static gates: findings, doc claims, pins, version trio
.venv/bin/python tests/unit/test_scope_fees.py  # [unit] 7/7 (SCOPE fees: ##-split parser on the real fixture row incl. amount-with-.00 + "13-Aug-2025" date + junk/short rows, dues logic (paid==total+trailing 0 -> 0; synthetic 100/150 -> 50; trailing=50 -> 50; view sum + warning/error level), narration first-clause split never raises on unicode/tab/CR/LF garbage, ledger sorted newest voucherdate first, feature gate off -> no tab (view None + SCOPE_FEATURES env + template {% if fees %} guard) — offline, no server/DB)
.venv/bin/python tests/unit/test_app_factory.py  # [unit] 24/24 create_app factory: boot-env isolation between two apps, route surface + bare endpoint names, gunicorn app.app:app contract, OCR prewarm opt-out
.venv/bin/python tests/unit/test_exams.py  # [unit] 69/69 official ETT parser + header drift + scribe fallback merge + transition/push events
.venv/bin/python tests/unit/test_exams_view.py  # [unit] dashboard exam card view model (stamps, labels)
.venv/bin/python tests/unit/test_tt_history.py  # [unit] 18/18 timetable edit log + break dividers + location preservation
.venv/bin/python tests/unit/test_tt_hero.py  # [unit] 3/3 NOW-hero keeps the attendance join across the dict hop
.venv/bin/python tests/unit/test_relogin_save.py  # [unit] 9/9 mid-scrape relogin persists the fresh session + resets portal fail state
.venv/bin/python tests/unit/test_fernet_rotation.py  # [unit] 39/39 MultiFernet first-key-encrypts, rotate script dry-run/apply/idempotent, no key material in output
.venv/bin/python tests/unit/test_official_tt.py  # [unit] 53/53 portal formId-10 parser + preserve/drift states, offset contract official==SLOTS, editor archive gate, rim tiers, Now badge
.venv/bin/python tests/unit/test_sessions.py  # [unit] 16/16 multi-device sessions, expiry-at-read, logout auth lines, prefetch no-op, sha256 digests, cross-site 403 guard
.venv/bin/python tests/unit/test_account_delete.py  # [unit] 15/15 account deletion residue (schema-driven), rate limit, auth line, control account survives
.venv/bin/python tests/unit/test_login_reject.py  # [unit] rejection classifier + quota order + preflight admission + typed kind→status differential
.venv/bin/python tests/unit/test_state_classes.py  # [unit] 11/11 RateLimiter/ProgressTracker/PortalHealth: TTL pruning, exact caps under threads, cooldown escalation
.venv/bin/python tests/unit/test_fault_handling.py  # [unit] 12/12 corrupt-row degradation, marks/subjects/attendance preserve-if-empty, errorhandler
.venv/bin/python tests/unit/test_logging_telemetry.py  # [unit] 10/10 ntfy ERROR/5xx tripwire, kv cause, rotation, control-char scrub
.venv/bin/python tests/unit/test_metrics.py  # [unit] 10/10 metric series + secret-header auth + usage retention + error= on every >=400 line
.venv/bin/python tests/unit/test_observability_assets.py  # [unit] 10/10 ops stack guard rails: metric series exist, no PII labels, images pinned, secrets untracked
.venv/bin/python tests/unit/test_sync_cache.py  # [unit] 6/6 refresh cache window: cached answer with zero portal calls, single-flight join shares one result
.venv/bin/python tests/unit/test_sync_queue.py  # [unit] 9/9 bounded queue wait, login-ahead-of-refresh, portal-budget buckets, fallback archived by default
.venv/bin/python tests/unit/test_canary_sync.py  # [unit] 13/13 canary_sync.sh against a self-booting server with the fetch stubbed; cache-window answer fails it
.venv/bin/python tests/unit/test_marks_view.py  # [unit] marks view model (fmt, IE derivation/conversion, class key)
.venv/bin/python tests/unit/test_layout.py  # [unit] 25/25 card/widget engine (LAYOUT spans, WIDGETS partials, all-empty card drop, budgets, ticker)
.venv/bin/python tests/unit/test_css_safelist.py  # [unit] 10/10 render-time dynamic class tokens exist in the committed app.css; no CDN origin
.venv/bin/python tests/unit/test_perf_budget.py  # [unit] 15/15 perf guardrails: zero off-origin hosts, CSP, app.css gzip budget, cache matrix, SW rules
.venv/bin/python tests/unit/test_attendance_view.py  # [unit] 83/83 attendance view model (frozen table, budgets, join, degrade cases)
.venv/bin/python tests/unit/test_feedback.py  # [unit] 71/71 feedback harvester, plan preview==payload, fb_open merge contract, closed-window 409, render gates
.venv/bin/python tests/unit/test_push_calc.py  # [unit] 33/33 due-window edges, blocks/rooms, tz-from-UTC, idempotency, TTL
.venv/bin/python tests/unit/test_push_store.py # [unit] 28/28 claims/at-most-once, orphan recovery, AST portable-SQL gate
.venv/bin/python tests/unit/test_push_send.py  # [unit] 16/16 mocked pywebpush: ok / 410-dead-cleanup / 5xx-retry, deadline
.venv/bin/python tests/unit/test_push_tick.py  # [unit] 27/27 secret auth, dry-run, allowlist, overlap, dead-man metrics, no PII labels
.venv/bin/python tests/unit/test_push_api.py   # [unit] 42/42 401 style, validation, DB rate caps, test/receipt flows, notification prefs
.venv/bin/python tests/unit/test_login_guide_static.py    # [unit] 9/9  Login Flow UX Guide (source level, no server)
.venv/bin/python tests/unit/test_supply_chain.py  # [unit] 26/26 compose OPENSRM_TAG pin, build.yml tags/labels, scans report-only, SHA-pinned actions
.venv/bin/python tests/unit/test_healthz.py  # [unit] 6/6 /healthz: <=32B, SELECT 1 only, 503 on DB failure, probe demoted to DEBUG
.venv/bin/python tests/unit/test_db_concurrency.py  # [unit] 14/14 10s busy timeout survives lock holds, journal-mode delete/wal/flip-back via child boots
.venv/bin/python tests/unit/test_db_layer.py  # [unit] 24/24 request-scoped connection closed by teardown, SAVEPOINT isolation, upsert/preserve contracts

# ── e2e (Playwright DUTs) ──────────────────────────────────────────────────
# One gunicorn behind the ci_e2e_http.sh list; self-booting DUTs own theirs.
# Needs PLAYWRIGHT_BROWSERS_PATH + DUT_BASE — see tests/README.md for the
# exact per-suite commands and ports.
bash scripts/ci_e2e_http.sh test_sw test_xss test_navbar test_marks_dut \
  test_personal test_softrefresh_dut test_touchfeel_dut test_lowtier_dut \
  test_pull_dut test_perf_budget_e2e test_delete_dut test_att_dut \
  test_feedback_dut test_feedback_contrast test_login_guide_check
.venv/bin/python tests/e2e/test_dash_fit.py        # [e2e] dashboard fit: no desktop page scrollbar, uniform grid, fb_open render toggle
.venv/bin/python tests/e2e/test_dut_official_tt.py # [e2e] official-timetable archive contract + rim tiers + Now badge + no overflow
VENV="$PWD/.venv" bash tests/e2e/run_push_duts.sh  # [e2e] test_push_sw + test_push_ui (staggered boots)
.venv/bin/python tests/e2e/test_login_guide_server.py    # [none] 7 live portal probes — NEVER loop it; green = 0 FAIL
```

Counts above are the suites' own verdict lines as last verified; if a suite
reports a different total, trust the run and update the row.

Tests read `DUT_BASE` to point at a different port; `tests/_seed.py` seeds
the user + payload — and every HTTP suite calls `require_own_server(BASE)`
first, so a suite pointed at another agent's server (or a dead one, or a
mismatched `DATA_DIR`) exits 1 with `FAIL[guard]: …` before any
browser/login work instead of returning a phantom verdict.

## Architecture diagram (docs/architecture.png)

The README's diagram is a pre-rendered image — GitHub's mermaid engine
cramps blocks (measured: 758px iframe vs 1063px layout) and mermaid v11
ignores nested `direction`, so images are the only way to control the
render. Full guideline: `docs/diagrams.md` (design rules, skin tokens,
arrow semantics, verification checklist — read it before touching a diagram).

```bash
python3 scripts/build_arch_diagram.py      # regen docs/architecture.html (asserts grid/text/label rules)
# PNG: python3 <diagram-design skill>/scripts/export_png.py docs/architecture.html docs/architecture.png 2
#     python3 <diagram-design skill>/scripts/self_check.py docs/architecture.html
```

Rules that are easy to get wrong: every coord on the 4px grid; no formIds /
percentages / schema versions / `app/...` paths in boxes (prose and
Configuration own those); arrow kinds must all appear in the legend; HTTP
boundaries are bidirectional; config gates (e.g. `SRM_EGRESS_URL`) are named
in the legend, never drawn as connections. Ship html + png + generator
together; `test_audit_findings` must stay 72/72.

## Git and release

- **Branches: `main` only** (merged feature branches get deleted local+remote
  — do the same).
- Atomic commits; message = finding + evidence + fix + how it was verified.
- **Commit email MUST be `128571614+thenabbu@users.noreply.github.com`**
  (GH uid 128571614 — never the Discord uid, or commits don't link).
- Push → CI green before deploy: **Lint** (`uvx ruff check app/` +
  `uv lock --check`) · **Tests** (`unit` + `docker` + `e2e`) · **Build &
  Push** (image → GHCR as `:latest` + `:<VERSION>` + `:<short-sha>`,
  `needs: [lint, tests]` on `main` so a red suite never pushes `:latest`) ·
  **Scans** (report-only) · the CodeQL checks the default code-scanning
  setup runs. A `unit`/`e2e` red on a PR is a real failure, not a flake.
- Release: bump `VERSION` + `pyproject.toml` → `uv lock` → commit → tag
  `vX.Y.Z` → push tag → deploy → smoke.

## Prod deploy and smoke

```bash
ssh lab 'cd /docker/opensrm && docker compose pull && docker compose up -d'
# Rollback to a released image (CI publishes :<VERSION> next to :latest):
#   add OPENSRM_TAG=<VERSION> to /docker/opensrm/.env (the PROJECT env file —
#   compose does NOT read the master /docker/.env for interpolation), then
#   docker compose pull && docker compose up -d opensrm; unset to ride :latest again.
# smoke: https://srm.200871.xyz/login → 200; HSTS header present (cf-ray path);
# GET /healthz → 200 {"status":"ok"} — the endpoint the compose healthcheck polls
# (no session needed); at LOG_LEVEL=INFO its request lines are DEBUG, so absence
# from `docker logs opensrm` means the LOG LEVEL, not that the probe stopped
# (docker inspect opensrm --format '{{.State.Health.Status}}' says 'healthy').
# /static/sw.js → service-worker-allowed: / + current cache name (see gotchas);
# POST /api/login/progress {"netid":"ab1234"} → 200, GET → 405.
# ({"netid":"x"} → 400 by design: NETID_RE is ^[a-z0-9]{2,20}$.)
# AUTHENTICATED RENDER: mint a cookie for an existing user (make_session_token —
# returns the raw token for the cookie; since v1.20.3 the cookies row stores its
# sha256 digest) and assert / → 200 with real row data — /login only proves the
# shell boots, not that stored-data paths render.
```

Then `bash scripts/post_deploy.sh` from the checkout — the whole verification
chain (prod-image SHA == origin/main, changed-static purge, edge MISS +
byte-identity, authenticated render, cookie cleanup) in one exit code.
`bash scripts/pr_preflight.sh` is its pre-merge twin (freshness, merge-tree
conflicts, duplicate migrations, version trio/race, sw-cache docs).

Before touching live DB/SQL: snapshot first (recipe in skill
`homelab-backup-management`); before compose edits: copy
`docker-compose.yml.bak-<date>` next to it. Full operator runbook:
`docs/runbook.md`.

## Safety rules (non-negotiable)

- **No secrets in the tree, ever.** The egress gate reads env
  `SRM_PROXY_TOKEN`. **PROXY_TOKEN rotated 2026-09-28** — current value at
  `lab:~/.srm_egress_proxy_token` (600); secrets-API PUT is live
  immediately (verify with DOUBLE quotes — `"$T1"`, single quotes send the
  literal string).
- **No portal credentials hardcoded.** Tests mint session cookies, never
  log in.
- **Trust CF headers only with `cf-ray`**; HSTS is cf-ray-gated on purpose
  (plain-HTTP dev).
- **Rate limits** (all state in `app/state.py`, one lock per structure with
  TTL pruning on access; memory bound in SECURITY.md):
  - 3 syncs / 10 min / netid — counted only when the sync actually runs; a
    queue-timeout/busy/cooldown/budget rejection is free, and so are a
    refresh served from the last completed sync within
    `SYNC_MIN_INTERVAL_S` (default 300 s, `0` disables) and a joiner
    sharing an in-flight sync's result.
  - 10 / hour / IP login attempts.
  - Aggregate portal budget 30 / 10 min: full login + preflight share 20
    (preflight's own cap 10), refresh floor 10, one IP ≤ 6 unauth tokens.
  - Syncs wait in queue up to `SYNC_QUEUE_WAIT_S` (default 45 s,
    `0` = refuse immediately), logins ahead of refreshes, position shown as
    "Waiting for N ahead…" — a waiter past the wait gets the busy 503.
    `SYNC_MAX_CONCURRENCY` (default 1) sizes the slot pool; the archived
    Playwright fallback stays serialized at any setting.
  - Preflight: 30 s per netid, refused when queue depth > 0.
  - Portal cooldown arms at 3 consecutive fails (5 min, doubling, capped
    1800 s = 30 min).

## Gotchas (bitten at least once)

- `ss` doesn't exist on this host — check ports with a python socket bind,
  not `ss -tln`.
- Flask test client: pass cookies via `set_cookie`; a `Cookie` header in
  `headers=` is dropped.
- Timetable `DAY_ORDER` = full weekday names (`Monday`, not `Mon`).
- SW cache name (read from `sw.js` — current value v37; test_sw.py derives
  it) must bump when `app/static/` changes — `test_sw.py` asserts it, and
  README's architecture section must match (test_audit_findings L37/D58).
- Editing pyproject without `uv lock` fails CI (`uv lock --check`).
- Login-page version badge comes from the `VERSION` file, not pyproject
  directly.
- SQLite: every connection funnels through `app.db.connect()` (10s busy
  timeout, `SQLITE_JOURNAL_MODE` env, default `delete`) — never
  `sqlite3.connect` directly. Request handlers share ONE request-scoped
  connection (closed by the `teardown_appcontext` hook, even when a handler
  raises); scripts and background threads own + close their own. Forensic
  `docker cp` of the DB must copy `srm.db` **plus `-wal` and `-shm`** when
  WAL is on — or use `sqlite3 ".backup"` (the daily snapshot pipeline
  already does; it is WAL-safe). Raw `cp` under WAL silently misses recent
  commits.
- Two `CF_FULL_TOKEN=` lines exist in lab `/docker/.env` — the real one is
  the LAST (line 20).
- The portal login page markup itself contains `captcha` (x17) and
  `invalid` (Bootstrap `.invalid-feedback`) — never classify a rejection on
  those tokens or EVERY failure reads as "invalid captcha" (this hid a
  wrong password behind 3 captcha retries and burned the portal's own
  3-attempts-per-NetID lockout). Classify on the portal's
  `<h6 class="alert-heading">Alert</h6>` text;
  `tests/unit/test_login_reject.py` holds the verbatim strings.
