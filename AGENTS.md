# AGENTS.md — repo facts (OpenSRM)

Flask monolith that scrapes the SRM student portal over pure HTTP and renders
attendance / marks / timetable dashboards. Jinja templates + a **pre-compiled**
Tailwind 4 + daisyUI 5 stylesheet (no runtime CDN). Design rules live in
`DESIGN.md`; the workflow skill lives outside this repo.

**The one gate that matters:**

```bash
bash scripts/gates.sh          # lint + static gates + unit + e2e, nothing else needed
bash scripts/gates.sh --fast   # lint + static gates only (~15 s)
bash scripts/gates.sh --list   # what it would run, derived from tests.yml
```

It exits **3** with `GATES GREEN (PARTIAL: <what>)` when it skipped anything —
a partial run is not a push bar. Exit 0 (`GATES GREEN`) means nothing was skipped. It reads the suite list out of
`.github/workflows/tests.yml`, so a suite added to CI is picked up
automatically — **never hand-maintain a second list of suites in this file.**

## Where things run

- **Local dev**: repo at `/opt/data/opensrm-repo` on the hermes host, venv
  `.venv` (managed by `uv`). Never npm at runtime — the CSS is compiled ahead
  of time by `scripts/build-css.sh` into the committed `app/static/app.css`.
- **Prod**: lab host, container `opensrm`, compose project `/docker/opensrm`,
  behind a Cloudflare tunnel at `https://srm.200871.xyz`. Operator detail:
  `docs/runbook.md`.
- **Do NOT touch** `flights.200871.xyz` (DNS/ingress) — another agent owns it.

## Layout

```
app/app.py            # create_app() factory (data dir, secret, migrations, OCR prewarm)
                      # + views, session/auth, portal budget, sync orchestration;
                      # re-exports every name that moved out
app/config.py         # AppConfig (frozen dataclass) + from_env(): boot env read ONCE
app/db.py             # sqlite layer: connect(), request-scoped db(), transaction(),
                      # repository — ALL SQL lives here
app/blueprints/       # FlatBlueprint route tables (GO: all routes live here, not in app.py):
                      # auth · dashboard · marks · timetable · push · feedback · internal
                      # Route inventory: scripts/url_map_dump.py | wc -l
app/security.py       # shared route decorators (require_login)
app/state.py          # RateLimiter · ProgressTracker · PortalHealth — every in-memory
                      # limit behind ONE lock with TTL pruning
app/portal/parsers/   # pure portal-HTML parsers: attendance, marks, timetable, exams,
                      # personal, feedback
app/scope/            # SECOND data source — SRM's SCOPE app backend over SOAP:
                      #   client.py (stdlib-only AES envelope, typed faults)
                      #   ops.py    (46-operation catalogue + FEATURES: slug → ops)
                      #   sync.py   (session, hot/cold TTLs, connection pool,
                      #              preserve-if-empty; writes users.scope_json)
app/views/            # dashboard view models: attendance budgets, marks derivation,
                      # ticker, academics/fees/campus, LAYOUT+WIDGETS registries
app/http_scraper.py   # pure-HTTP portal pipeline (archived Playwright fallback)
app/migrations.py     # versioned schema; runs inside create_app()
                      # Count them: grep -c '@migration(version=' app/migrations.py
app/templates|static/ # daisyUI v5, pre-compiled app.css, theme tokens in partials/theme.html
tests/unit/           # no-server suites
tests/e2e/            # Playwright DUTs
egress/               # CF Worker egress proxy + PoCs — NOT in the image (.dockerignore)
edge/maintenance/     # CF Worker: branded maintenance page, survives a total lab outage
ops/observability/    # OPTIONAL metrics stack beside the app (never in the image)
docs/                 # runbook.md · audit/ · push.md · SCANS.md · perf/ · screenshots/
scripts/              # build-css.sh · gates.sh · check_docs.py · check_architecture.py ·
                      # pr_preflight.sh · post_deploy.sh · url_map_dump.py · perf_baseline.py
.github/workflows/    # tests.yml (unit+docker+e2e, PR gate) · build.yml · lint.yml ·
                      # scans.yml (report-only); SHA-pinned actions; `uv lock --check`
```

Suites: run `bash scripts/gates.sh --list`. Counts are deliberately absent —
they went stale three times. If you need a number, derive it.

## Dev loop

```bash
cd /opt/data/opensrm-repo
uvx --quiet ruff check app/     # scope ruff to the files you edited; never `ruff --fix`
# scripts/build-css.sh          # after template edits that add utility classes;
#                               # app.css is committed and CI fails if stale
bash scripts/gates.sh           # the bar
```

Fresh DB per boot: `DATA_DIR=$(mktemp -d)`. Pick a free port first —
8084/8085 get squatted. Migrations run inside `create_app()`.

## CI / merge / release

- **Branches: `main` only.** Merge feature branches, then delete them local and remote.
- Merge commits, never squash. Atomic commits: finding + evidence + fix + how verified.
- **Commit email**: `scripts/wt.sh new <slug>` sets it per-worktree and installs a
  pre-commit hook that refuses a commit in the canonical checkout. If you commit
  by hand, pass `-c user.email=128571614+thenabbu@users.noreply.github.com`; the
  wrong one does not link the commit to the account.
- CI jobs: **Lint** (`ruff` + `uv lock --check` + app.css freshness) · **Tests**
  (`unit` + `docker` + `e2e`) · **Build & Push** (GHCR `:latest` + `:<VERSION>` +
  `:<short-sha>`, `needs: [lint, tests]` on `main`) · **Scans** (report-only).
  A red `unit`/`e2e` on a PR is a real failure, not a flake.
- Release = `VERSION` + `pyproject.toml` + `uv.lock` **in one commit**. Tagging and the
  Release itself are automatic: `.github/workflows/release.yml` tags `vX.Y.Z` and publishes
  a GitHub Release whose body is generated from the commits (`scripts/release_notes.py`).
  The app carries **no** release-notes feed — GitHub Releases is the changelog, and
  `test_audit_findings` M27 fails if an in-app feed ever comes back.
- Deploy is manual and separate from merge approval. `scripts/post_deploy.sh` runs the
  whole verification chain (prod SHA == main, static purge, authenticated render).
  `scripts/pr_preflight.sh` is its pre-merge twin.

## Safety rules (non-negotiable)

- **No secrets in the tree, ever.** All secrets come from env. The egress gate reads
  `SRM_PROXY_TOKEN`.
- **No portal credentials hardcoded.** Tests mint session cookies; they never log in.
  `test_login_guide_server.py` performs real logins — local only, never in a loop (the
  portal caps attempts per IP).
- **Trust CF headers only when `cf-ray` is present.** HSTS is cf-ray-gated on purpose so
  plain-HTTP dev still works.
- **Never write PII into the repo** — it is public. Seeds use fabricated identifiers, and
  `docs/screenshots/` is in scope (the netid renders in the navbar).
- **Rate limits** all live in `app/state.py`, one lock per structure, TTL pruning on
  access. Sync quotas, login attempts, the aggregate portal budget, the queue wait and the
  portal cooldown are all there; read the constants in code, not from this file.
- Before touching a live DB: snapshot first (`sqlite3 ".backup"`, WAL-safe).

## Code gotchas

- **Routes live in `app/blueprints/`, not `app/app.py`.** `grep '@app.route' app/app.py`
  returns nothing — the blueprints register via `bp.add_url_rule`.
- `ss` does not exist on this host — check a port with a python socket bind.
- Flask test client: pass cookies via `set_cookie`; a `Cookie` header in `headers=` is dropped.
- Timetable `DAY_ORDER` uses full weekday names (`Monday`, not `Mon`).
- **SW cache name**: read it out of `app/static/sw.js` and bump it whenever
  `app/static/` changes; `test_sw.py` derives it. Never quote the value in a doc.
- Editing `pyproject.toml` without `uv lock` fails CI.
- The login-page version badge reads the `VERSION` file, not `pyproject.toml`.
- **SQLite**: every connection funnels through `app.db.connect()` (busy timeout, journal
  mode). Never call `sqlite3.connect` directly. Handlers share one request-scoped
  connection closed by `teardown_appcontext`; scripts and threads own and close their own.
  Forensics on a WAL database must copy `-wal` and `-shm` too, or use `.backup`.
- The portal login page markup itself contains `captcha` and `invalid` — classify a
  rejection on the alert-heading text, never on those tokens.
- **`hidden` attribute OR the class, never both** on one node (one visibility mechanism).
- Editing CSS/JS by script: `grep -c "/\*"` must equal `grep -c "\*/"` afterwards.

## Architecture diagram

`docs/architecture.png` is pre-rendered (GitHub's mermaid engine cramps blocks). Regenerate
with `python3 scripts/build_arch_diagram.py`, which asserts the grid/label rules and fails
on an off-edge port, a crossing segment, or a label collision. Read `docs/diagrams.md`
before touching it. Ship html + png + generator together.
