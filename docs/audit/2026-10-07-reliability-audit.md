# 2026-10-07 — reliability audit: unexplained prod failures, silent error paths

Scope: two weeks of prod logs (persistent `/app/data/opensrm.log`, Sep 22 → Oct 7,
77k lines) + a full static audit of `app/*.py` (3,919 LOC: 64 `except` clauses,
all routes). Findings: 90 total (11 P1, 24 P2, 55 P3) and 25 silent failure modes.

## Symptom

Prod intermittently 500s/503s with causes that were "sometimes logged, sometimes
missed"; some features silently render empty instead of failing.

## Root causes found (with evidence)

1. **S25 — stale attendance body after mid-scrape relogin** (`http_scraper.py:491`).
   `content_html` was bound before the session-reuse check; the relogin branch
   refetched `parallel_html` but never re-derived `content_html`, so
   `parse_attendance` parsed the dead session's 466-byte body and returned
   `Attendance page did not load` → 503 blaming the user's account.
   Evidence: prod log 2026-10-07 00:35:58/00:39:43/01:41:14 — refetch `200 19378B`
   and `courses=8` seconds later in the same lines as the 503.
2. **Unguarded `json.loads` on stored rows** (`index()` ×3, `api_marks`) — one
   corrupt row 500'd `/` on every load (audit B1-B4; the sibling exam decode was
   already guarded, proving the risk was known).
3. **`_semester_int` IndexError** on empty/`None` `Semester` (probe-verified) —
   raised inside `_group_key` *before* its own guard → 500 on `/` and every
   timetable API (B5).
4. **`marks_json` had no preserve-if-empty** (login/refresh) while personal/
   subjects/exams did — a marks parse failure returns `marks=[]` with `ok=True`
   and silently wiped stored marks (B6; HTTP path logged it only at DEBUG).
5. **No `@app.errorhandler`** — unhandled exceptions (e.g. sqlite lock errors
   under 1 gunicorn worker × 8 gthread threads) surfaced as bare Flask 500s with
   zero `opensrm.*` lines.
6. **Silent swallows in auth/session paths** — Playwright personal/course/marks
   parse failures, post-login timetable save, session save, corrupt-row readers:
   36 handlers left no trace at any level; prod ran `LOG_LEVEL=DEBUG` (compose
   default overriding the Dockerfile) yet 13 more handlers logged only at DEBUG.

## Fixes (this PR)

- `http_scraper.py`: re-derive `content_html` after the relogin refetch (S25);
  marks parse failure promoted DEBUG → WARNING.
- `app.py`: `_jload()` helper (degrade + log on corrupt/wrong-shape rows) used at
  the 4 unguarded decodes + exam decode; `_semester_int` empty/None guard;
  `_fmt_score`/`_fmt_max` junk guards (a stored null score TypeError'd into a 500);
  marks preserve-if-empty on login and refresh; global `@app.errorhandler(Exception)`
  (HTTPExceptions pass through; everything else → one ERROR line with path +
  traceback, JSON 500); `api_refresh` no-stored-creds paths now log and return
  **401** (were silent 200s — dash.js reads the body, verified safe); the legacy
  `timetable.json` open/parse moved inside its try (a corrupt file could
  crash-loop the container at import); the 12 dangerous silent `except` sites
  now log (WARNING for data/state paths, with `exc_info` on the timetable save).

## Verification

- New `tests/test_fault_handling.py`: **9/9 on the branch, 1/9 FAIL on
  `origin/main`** (each failure prints its diagnosis — IndexError, missing
  helper, false S25 count, HTML 500, wiped marks…). Red/green proven both ways.
- Full unit matrix green: verify76 71/71, exams 27/27, tt_history 18/18,
  login_reject, marks_view, attendance_view, tt_hero, push suites
  (calc/store/send/tick/api), `ruff check app/`, `uv lock --check`.

## Standing rules for future sessions

- **Never decode a stored JSON column unguarded** — use `_jload(raw, default)`
  (it also checks shape). A stored-row corruption must degrade + log, never 500.
- **Any fetch that can return empty-on-failure needs preserve-if-empty** before
  it is written to `users` — attendance already had it; marks now does.
- **A relogin/refetch inside a scraper must re-derive every derived binding**
  from the refetched payload — one stale binding blames the user for our bug.
- A status code alone is never a diagnosis: log the cause `error=` at the same
  second as the status line (the Sep 30 refresh incident, `app.py:1957`).

## Deliberately left unfixed (tracked for the logging/telemetry PR)

- Access-log `error=` for >=400 responses, healthcheck/DEBUG noise cut (86% of
  the log file), log rotation, tick-secret 401 / push 502 / rate-limit cause
  lines, kv quoting, request-id correlation, `usage_events` telemetry, ntfy
  ERROR alerter — all specified in the logging + telemetry audits.
- SQLite WAL (needs a backup-path audit first: file-copy snapshots would miss
  the -wal file); B13 gunicorn `-t 120` vs 150s scrape budget (needs runtime
  confirmation); client-side JS errors are invisible to the server by design.
