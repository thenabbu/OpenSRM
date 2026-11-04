# Changelog

Generated from git history by `scripts/release_notes.py`. Every GitHub Release body is the same rendering.

## v2.11.0

### What changed

- scope: fetch the real dues, fix the fees tab showing ₹0 to a student who owes (#150)


## v2.10.1

### What changed

- **scope**: zero-dep SOAP client + 43-op catalog + feature toggles
- **scope**: m018 session columns + cold-sync scaffold
- **dashboard**: ticker 'now' row can shrink — long subject no longer overflows mobile
- **scope**: profile widget photo + settings scope fields + one-liner
- **scope**: Fees tab — dues hero, paid-by-year, receipt ledger
- **campus**: Campus tab — placement board, library, hostel+transport, notifications
- **scope**: hourwise attendance joined to timetable + subject-named absences
- **scope**: Academics tab — released results, derived CGPA, credits, subjects
- **scope**: ship placement/library/campus DEFAULT-OFF (opt-in via SCOPE_FEATURES)
- **attendance**: Detailed attendance — month dropdowns of date x hour cells
- **academics**: CGPA hero owns the results; one credits+subjects card
- **fees**: quiet paid list + collapsed receipt ledger (review rework)
- **academics**: SGPA belongs in the expanded body, not the semester summary
- **fees**: the date|name rule actually paints
- **sync**: soft-refresh no longer shifts the dashboard frame (card x / top gutter 15 -> 30)
- **merge**: keep main's fixed navbar in the mobile bar
- **tools**: every Tools row names a real destination, and hourwise/profile get rows
- **attendance**: table Margin uses the canonical _bunk_counts sign, not raw attended-ceil(0.75*total)
- **scope**: give SCOPE a lifecycle trigger so the panels actually populate
- **scope**: stop sending a password to getStudentLogin — it never validated one
- **scope**: trigger no-ops when SCOPE_FEATURES is off
- **scope**: drop getStudentPhoto from the JSON sync ops — it aborts the batch
- **preflight**: compare VERSION per ref, not via git log -S
- **obs**: instrument HTTP, DB, scope, push and process
- **obs**: rebuild the dashboard and add rules for the new series
- **obs**: stat panels reduce with a calc NAME, not an integer
- **obs**: user activity, tab usage and per-source sync cost
- **timetable**: redesign the Timetable tab to the approved reference
- **tt**: keep the attendance tag's phrase contiguous
- **tt**: word order per tier — '0 margin' not 'margin 0'
- **tt**: subject name leads, mobile pass
- **tt**: mobile row is two lines — code left, attendance tag far right
- **scope**: fetch sync ops concurrently instead of one-at-a-time
- **tt**: loosen row spacing, render rooms, cover the room branch
- **obs**: stat tiles show one correct number
- **attendance**: 2dp truncated percentages, never rounded
- **attendance**: 1dp truncated percentages (variant of #120)
- **edge**: reproducible maintenance page served at the edge during an outage
- **security**: match Origin against the PUBLIC hostname, not the tunnel's IP
- **observability**: answer who-uses-it, how long they wait, and where sync time goes
- **attendance**: stop painting the stale Absences card during a scope sync
- **sync**: refresh stale portal data on dashboard load
- **auto-sync**: import decrypt_pw from the crypto leaf, not from db (#144)
- **auto-sync**: read the payload shape _refresh_core actually returns
- **fees,settings**: 1px rule not 4px, and the phone gear gets an id

### Internal

- **scope**: foundation test suite — 17/17 offline
- **test**: pre-migration fixture holds back ALL versions >16, not just 17
- profile enrichment suite 7/7 + AGENTS matrix row
- scope profile widget + personal details (1280x900 + 393x851)
- **fees**: grid columns for paid rows + verification screenshots
- scope-hourwise before/after (393 + 1280)
- two-seed DUT screenshots — empty-state navbar proof + synthetic full render
- **phase-5**: touch feel — press feedback, JS tab motion, bottom sheets, v1.28.0
- empty commit to re-trigger pull_request workflows
- **merge**: resolve the VERSION/NOTICES/pyproject conflicts cut off by a truncated conflict log — marker scan across the whole tree is clean, uv lock regenerated at 1.28.0
- **phase-6**: avatar rest + low-end tier + batched gaze — v1.29.0
- **phase-7**: pull-to-refresh for touch — v1.30.0
- **phase-8**: guardrail tests so the whole campaign stays fixed
- structured suite layout — tests/unit + tests/e2e, consistent names
- archive the Playwright fallback (PLAYWRIGHT_FALLBACK gate) + slim the image (WITH_PLAYWRIGHT)
- bump playwright
- rebuild README, CONTRIBUTING, SECURITY and AGENTS for human readers
- before/after README rendering evidence (GitHub main vs this branch)
- dedicated Architecture section — full portal-to-pixel data-flow diagram
- data-flow diagram tuned for README width (vertical pipeline)
- refresh README render evidence (architecture diagram iteration)
- re-capture README render evidence with the diagram painted
- replace the GitHub-rendered mermaid with a pre-rendered diagram
- refresh render evidence (pre-rendered diagram on the branch page)
- architecture diagram rev2 — applies the architecture review
- refresh render evidence (review-revised diagram)
- diagram-building guideline + generator as a repo tool
- refresh render evidence (diagram guideline added to doc list)
- bump python:3.11-slim digest + system setuptools — fixable HIGH/CRITICAL 6 -> 0
- rebuild app.css for the .hw-* grid rules (24,845 B gzipped, 36,864 budget)
- re-capture the profile evidence after the review corrections
- **nav**: Tools dock tab replaces Settings; refresh/settings flank the wordmark
- re-capture evidence after the reorganisation
- evidence for the detailed-attendance grid
- **tools**: Academics entry gates on released results, not the provisional window
- full-viewport captures instead of cropped elements
- before/fixed corner comparison for the layout-shift PR
- rebuild app.css for the seeded --sbw markup
- **ui**: self-hiding overlay scrollbar, navbars pinned to the viewport (v1.32.0)
- resolve sibling conflicts, normalise the version trio to 2.0.0
- bring in feat/scope-foundation, normalise version trio to 2.0.0
- **merge**: restore main's viewport pinning and scrollbar model
- rebuild app.css so the CI currency gate passes
- before/after full-viewport captures
- **ci**: remove stray .venv symlink and ignore venv in git
- assert SCOPE panels actually render, not just that / returns 200
- **migrations**: reject duplicate version at registration, not mid-boot
- add dut_server.sh and ci_wait.sh
- correct stale migration count and static-gate count
- add wt.sh and prod_logs.sh
- **obs**: import time in scope client; regenerate dashboard; docs
- v2.5.0
- timetable redesign, desktop + mobile (seeded zz9999)
- bump break-divider + hero-break assertions to the new markup
- refresh to the final build (tag phrase order)
- recapture with the real shell chrome (navbar + dock in frame)
- **scope**: hot/cold TTL split — 24h for settled data
- v2.6.1
- v2.7.0
- README catches up with the two-source architecture (portal + SCOPE) (#119)
- attendance 2dp capture
- ATTENDANCE_DECIMALS is the one precision knob
- extract the four leaf modules from app.py
- point AGENTS layout and runbook at the edge maintenance worker
- extract the scraper and the portal control plane
- extract the declarative tables into app/static_data.py
- extract the attendance and timetable view models
- **security**: cross-site guard compared netlocs, refusing same-origin POSTs
- pin the clock — the suite was red for 60 seconds every day
- rebuild app.css after the extraction moved templates' class scan
- extract the dashboard route into app/views/dashboard.py
- extract push notifications and the health/metrics probes
- rebuild app.css after cycle F
- **facade**: constrain the rebind fan-out; repoint stale docs
- import sort + rebuild app.css (CI ruff + CSS-current steps)
- **edge**: forward the public host, and close the origin bypass
- move the proxy-trust helpers out of the facade into app/edge.py
- **edge**: key the origin bypass guard on X-Forwarded-Host, not Host
- record that srm-origin is internal-only, enforced by a WAF rule
- screenshot of the attendance tab mid-sync (old card absent)
- pin the analytics arithmetic, visit span, and item beacon
- **observability**: filter 5xx panels on status_class, and gate invented labels
- add scripts/check_docs.py doc-consistency gate
- rewrite AGENTS.md as repo facts; add scripts/gates.sh
- wire test_auto_sync into the unit job
- rewrite the new panels in plain language
- **observability**: shorten two truncated titles, finish the plain-legend rename
- move visit tracking out of app.py into observability
- wire test_product_analytics into the unit job
- order the dashboard by the product questions, drop duplicates
- CI parity, honest verdict, route-auth + comment-balance gates
- point commit identity at the worktree hook; state the PARTIAL verdict
- remove the in-app release-notes feed; GitHub Releases is the changelog
- seed rich data in scroll-dependent suites


## v2.10.0

### What changed

- **observability**: answer who-uses-it, how long they wait, and where sync time goes
- **attendance**: stop painting the stale Absences card during a scope sync

### Internal

- screenshot of the attendance tab mid-sync (old card absent)
- pin the analytics arithmetic, visit span, and item beacon
- **observability**: filter 5xx panels on status_class, and gate invented labels
- rewrite the new panels in plain language
- **observability**: shorten two truncated titles, finish the plain-legend rename
- move visit tracking out of app.py into observability

## v2.9.5

### What changed

- **sync**: refresh stale portal data on dashboard load

### Internal

- record that srm-origin is internal-only, enforced by a WAF rule

## v2.9.4

### Internal

- move the proxy-trust helpers out of the facade into app/edge.py
- **edge**: key the origin bypass guard on X-Forwarded-Host, not Host

## v2.9.3

### Internal

- extract the four leaf modules from app.py
- extract the scraper and the portal control plane
- extract the declarative tables into app/static_data.py
- extract the attendance and timetable view models
- rebuild app.css after the extraction moved templates' class scan
- extract the dashboard route into app/views/dashboard.py
- extract push notifications and the health/metrics probes
- rebuild app.css after cycle F
- **facade**: constrain the rebind fan-out; repoint stale docs
- import sort + rebuild app.css (CI ruff + CSS-current steps)
- **edge**: forward the public host, and close the origin bypass

## v2.9.2

### What changed

- **security**: match Origin against the PUBLIC hostname, not the tunnel's IP

### Internal

- pin the clock — the suite was red for 60 seconds every day

## v2.9.1

### Internal

- **security**: cross-site guard compared netlocs, refusing same-origin POSTs

## v2.9.0

_Internal-only release: no user-visible change._

## v2.8.1

### What changed

- **attendance**: 1dp truncated percentages (variant of #120)
- **edge**: reproducible maintenance page served at the edge during an outage

### Internal

- attendance 2dp capture
- ATTENDANCE_DECIMALS is the one precision knob
- point AGENTS layout and runbook at the edge maintenance worker

## v2.8.0

### What changed

- **attendance**: 2dp truncated percentages, never rounded

### Internal

- README catches up with the two-source architecture (portal + SCOPE) (#119)

## v2.7.1

### What changed

- **obs**: stat tiles show one correct number

## v2.7.0

### What changed

- SCOPE sync speedup versioned


## v2.6.1

### What changed

- **timetable**: redesign the Timetable tab to the approved reference
- **tt**: keep the attendance tag's phrase contiguous
- **tt**: word order per tier — '0 margin' not 'margin 0'
- **tt**: subject name leads, mobile pass
- **tt**: mobile row is two lines — code left, attendance tag far right
- **scope**: fetch sync ops concurrently instead of one-at-a-time
- **tt**: loosen row spacing, render rooms, cover the room branch
- release: v2.6.1

### Internal

- timetable redesign, desktop + mobile (seeded zz9999)
- bump break-divider + hero-break assertions to the new markup
- refresh to the final build (tag phrase order)
- recapture with the real shell chrome (navbar + dock in frame)
- **scope**: hot/cold TTL split — 24h for settled data

## v2.6.0

### What changed

- **obs**: user activity, tab usage and per-source sync cost

## v2.5.1

### What changed

- **obs**: stat panels reduce with a calc NAME, not an integer

## v2.5.0

### What changed

- **scope**: stop sending a password to getStudentLogin — it never validated one
- **scope**: trigger no-ops when SCOPE_FEATURES is off
- **scope**: drop getStudentPhoto from the JSON sync ops — it aborts the batch
- **preflight**: compare VERSION per ref, not via git log -S
- **obs**: instrument HTTP, DB, scope, push and process
- **obs**: rebuild the dashboard and add rules for the new series
- release: v2.5.0

### Internal

- assert SCOPE panels actually render, not just that / returns 200
- **migrations**: reject duplicate version at registration, not mid-boot
- add dut_server.sh and ci_wait.sh
- correct stale migration count and static-gate count
- add wt.sh and prod_logs.sh
- **obs**: import time in scope client; regenerate dashboard; docs

## v2.4.1

### What changed

- **tools**: every Tools row names a real destination, and hourwise/profile get rows
- **attendance**: table Margin uses the canonical _bunk_counts sign, not raw attended-ceil(0.75*total)
- **scope**: give SCOPE a lifecycle trigger so the panels actually populate

## v2.4.0

### What changed

- **scope**: profile widget photo + settings scope fields + one-liner
- **scope**: Fees tab — dues hero, paid-by-year, receipt ledger
- **campus**: Campus tab — placement board, library, hostel+transport, notifications
- **scope**: hourwise attendance joined to timetable + subject-named absences
- **scope**: Academics tab — released results, derived CGPA, credits, subjects
- **scope**: ship placement/library/campus DEFAULT-OFF (opt-in via SCOPE_FEATURES)
- **attendance**: Detailed attendance — month dropdowns of date x hour cells
- **academics**: CGPA hero owns the results; one credits+subjects card
- **fees**: quiet paid list + collapsed receipt ledger (review rework)
- **academics**: SGPA belongs in the expanded body, not the semester summary
- **fees**: the date|name rule actually paints
- **sync**: soft-refresh no longer shifts the dashboard frame (card x / top gutter 15 -> 30)
- merge(foundation): resolve sibling conflicts, normalise the version trio to 2.0.0
- merge(foundation): bring in feat/scope-foundation, normalise version trio to 2.0.0
- **merge**: keep main's fixed navbar in the mobile bar

### Internal

- profile enrichment suite 7/7 + AGENTS matrix row
- scope profile widget + personal details (1280x900 + 393x851)
- **fees**: grid columns for paid rows + verification screenshots
- scope-hourwise before/after (393 + 1280)
- two-seed DUT screenshots — empty-state navbar proof + synthetic full render
- rebuild app.css for the .hw-* grid rules (24,845 B gzipped, 36,864 budget)
- re-capture the profile evidence after the review corrections
- re-capture evidence after the reorganisation
- evidence for the detailed-attendance grid
- **tools**: Academics entry gates on released results, not the provisional window
- full-viewport captures instead of cropped elements
- before/fixed corner comparison for the layout-shift PR
- rebuild app.css for the seeded --sbw markup
- **ui**: self-hiding overlay scrollbar, navbars pinned to the viewport (v1.32.0)
- **merge**: restore main's viewport pinning and scrollbar model
- rebuild app.css so the CI currency gate passes
- before/after full-viewport captures
- **ci**: remove stray .venv symlink and ignore venv in git

## v2.0.0

### What changed

- **dashboard**: ticker 'now' row can shrink — long subject no longer overflows mobile
- **dashboard**: ticker rows tolerate a long code — no horizontal overflow
- Revert "merge: scope profile enrichment — blobatar, family/dob/address, ticker overflow fix"
- Revert "merge: SCOPE client foundation — app/scope/, m018, feature toggles"
- **scope**: zero-dep SOAP client + 43-op catalog + feature toggles
- **scope**: m018 session columns + cold-sync scaffold
- **feedback**: auto-archive the CTA while the portal window is closed

### Internal

- **phase-0**: frontend perf baseline harness + measured numbers
- FAIL line names the overflowing element (env-break diagnosis)
- **phase-0**: refresh baseline against merged main (v1.26.0 rollback)
- **scope**: foundation test suite — 17/17 offline
- **test**: pre-migration fixture holds back ALL versions >16, not just 17
- phase-1 rules — pre-compiled CSS, motion limits, perf rules
- **phase-2**: pre-compiled CSS — checkpoint commit (parity pass in progress)
- phase-2 status + campaign handoff (gateway restart checkpoint)
- **phase-2**: parity pass — back-to-back captures, only the new release notice differs
- **phase-3**: remember the app's own files — immutable versioned assets, SW cache-first, v1.26.3
- **shots**: restore phase-0 baseline captures overwritten by the phase-3 metrics run
- **phase-4**: in-place refresh — syncs morph the page, no more reload flash, v1.27.0
- test-table row for test_softrefresh_dut (phase 4 DUT)
- run test_softrefresh_dut in the e2e battery (phase 4 DUT)
- css: rebuild app.css — overlay modal removal pruned its loading-lg token (CSS-sync CI gate)
- **phase-5**: touch feel — press feedback, JS tab motion, bottom sheets, v1.28.0
- empty commit to re-trigger pull_request workflows
- **merge**: resolve the VERSION/NOTICES/pyproject conflicts cut off by a truncated conflict log — marker scan across the whole tree is clean, uv lock regenerated at 1.28.0
- **phase-6**: avatar rest + low-end tier + batched gaze — v1.29.0
- **phase-7**: pull-to-refresh for touch — v1.30.0
- **phase-8**: guardrail tests so the whole campaign stays fixed
- structured suite layout — tests/unit + tests/e2e, consistent names
- archive the Playwright fallback (PLAYWRIGHT_FALLBACK gate) + slim the image (WITH_PLAYWRIGHT)
- bump playwright
- rebuild README, CONTRIBUTING, SECURITY and AGENTS for human readers
- before/after README rendering evidence (GitHub main vs this branch)
- dedicated Architecture section — full portal-to-pixel data-flow diagram
- data-flow diagram tuned for README width (vertical pipeline)
- refresh README render evidence (architecture diagram iteration)
- re-capture README render evidence with the diagram painted
- replace the GitHub-rendered mermaid with a pre-rendered diagram
- refresh render evidence (pre-rendered diagram on the branch page)
- architecture diagram rev2 — applies the architecture review
- refresh render evidence (review-revised diagram)
- diagram-building guideline + generator as a repo tool
- refresh render evidence (diagram guideline added to doc list)
- bump python:3.11-slim digest + system setuptools — fixable HIGH/CRITICAL 6 -> 0
- **nav**: Tools dock tab replaces Settings; refresh/settings flank the wordmark

## v1.32.0

_Internal-only release: no user-visible change._

## v1.31.0

### Internal

- **phase-8**: guardrail tests so the whole campaign stays fixed
- structured suite layout — tests/unit + tests/e2e, consistent names
- archive the Playwright fallback (PLAYWRIGHT_FALLBACK gate) + slim the image (WITH_PLAYWRIGHT)

## v1.30.0

### Internal

- **phase-7**: pull-to-refresh for touch — v1.30.0

## v1.29.0

### Internal

- **phase-6**: avatar rest + low-end tier + batched gaze — v1.29.0

## v1.28.0

### Internal

- **phase-5**: touch feel — press feedback, JS tab motion, bottom sheets, v1.28.0
- empty commit to re-trigger pull_request workflows
- **merge**: resolve the VERSION/NOTICES/pyproject conflicts cut off by a truncated conflict log — marker scan across the whole tree is clean, uv lock regenerated at 1.28.0

## v1.27.0

### Internal

- **phase-4**: in-place refresh — syncs morph the page, no more reload flash, v1.27.0

## v1.26.4

### What changed

- **feedback**: auto-archive the CTA while the portal window is closed

### Internal

- **shots**: restore phase-0 baseline captures overwritten by the phase-3 metrics run

## v1.26.3

### Internal

- phase-2 status + campaign handoff (gateway restart checkpoint)
- **phase-2**: parity pass — back-to-back captures, only the new release notice differs
- **phase-3**: remember the app's own files — immutable versioned assets, SW cache-first, v1.26.3

## v1.26.2

### Internal

- phase-1 rules — pre-compiled CSS, motion limits, perf rules
- **phase-2**: pre-compiled CSS — checkpoint commit (parity pass in progress)

## v1.26.1

### What changed

- **dashboard**: ticker rows tolerate a long code — no horizontal overflow

### Internal

- **phase-0**: frontend perf baseline harness + measured numbers
- FAIL line names the overflowing element (env-break diagnosis)
- **phase-0**: refresh baseline against merged main (v1.26.0 rollback)

## v1.26.0

### What changed

- require_login resolves get_current_user through app.app at call time
- optional observability stack + push-tick dead-man metrics
- pass METRICS_SECRET through compose + run post_deploy smoke as the app uid
- **scope**: zero-dep SOAP client + 43-op catalog + feature toggles
- **scope**: m018 session columns + cold-sync scaffold
- **scope**: profile widget photo + settings scope fields + one-liner
- **dashboard**: ticker 'now' row can shrink — long subject no longer overflows mobile
- Revert "merge: scope profile enrichment — blobatar, family/dob/address, ticker overflow fix"
- Revert "merge: SCOPE client foundation — app/scope/, m018, feature toggles"

### Internal

- move parsers and view models out of app/app.py (moves only, zero behaviour change)
- update layout/structure claims for the parser and view-model move
- one DB layer — app/db.py connect/request scope/transactions + repository
- db-layer sweep — AGENTS layout+matrix+gotcha, CONTRIBUTING, README diagram
- scope the 'only place SQL lives' claim precisely
- application factory — boot side effects live in create_app(config)
- create_app isolation suite + CI unit step
- application factory in AGENTS layout, README numbers, CONTRIBUTING
- split route registration into 7 blueprints, zero url_map change
- blueprint layout, routes count, factory-matrix row for the split
- RateLimiter/ProgressTracker/PortalHealth in app/state.py (locks + TTL pruning)
- operator runbook + restore-drill script; fix scheduler/env-file/number drift
- push_tick docstring names the real scheduler (Hermes cron job, cron-job.org kept as alternative per docs/push.md) — the dead-man docs in this PR reference it, so the handler's own doc must agree
- **observability**: serve Grafana on the LAN (password-gated)
- **scope**: foundation test suite — 17/17 offline
- **test**: pre-migration fixture holds back ALL versions >16, not just 17
- profile enrichment suite 7/7 + AGENTS matrix row
- scope profile widget + personal details (1280x900 + 393x851)

## v1.25.0

### What changed

- **sync**: bounded queue wait for the portal slot + per-sync fail context + bucketed portal budget
- release: v1.23.0 (sync queue wait SYNC_QUEUE_WAIT_S + bucketed portal budget)
- **container**: non-root runtime, read-only rootfs and measured resource limits

### Internal

- **healthz**: GET /healthz — unauthenticated DB-only healthcheck probe
- correct the container posture and add /healthz to the live docs

## v1.24.0

### What changed

- delete my data — POST /api/account/delete erases every stored netid row

### Internal

- supply-chain scans (report-only) + VERSION image tags with rollback pin
- per-job summaries for all three scans; pip-audit -o overwrite hazard
- re-shoot v1.22.1 release notice (post-v1.22.0 merge, 1280x900, fabricated zz9999 seed)
- delete-my-data docs, DUT and release trio

## v1.22.1

### What changed

- **security**: store session tokens as sha256 digests + refuse cross-site state-changing requests

### Internal

- v1.20.3 release notice render (1280x900, fabricated zz9999 seed)
- re-shoot v1.21.1 release notice (merged tree, 1280x900, fabricated zz9999 seed)
- list the new sync cache/join counters in the metrics env row
- **security**: exempt /marks/tag from the cross-site guard

## v1.22.0

### What changed

- sync cache window + per-netid single flight on /api/refresh
- release: v1.22.0 (sync cache window SYNC_MIN_INTERVAL_S + per-netid single flight)

## v1.21.1

### What changed

- **security**: store session tokens as sha256 digests + refuse cross-site state-changing requests

### Internal

- typed non-dict sync guard (producer-inventory gate)
- v1.20.3 release notice render (1280x900, fabricated zz9999 seed)

## v1.21.0

### Internal

- **observability**: /internal/metrics + sync counters/timers, logging sweep, usage retention env, canary_sync.sh
- release: v1.21.0 (metrics endpoint, retention env, canary docs, CI wiring)

## v1.20.3

### What changed

- rotatable password-encryption key (FERNET_KEYS MultiFernet + rotate tool)
- **security**: store session tokens as sha256 digests + refuse cross-site state-changing requests

### Internal

- add SRI integrity (sha384) + crossorigin to the pinned CDN tags
- before/after login shots (pixel-identical) + correct DESIGN 10.9 cssRules claim
- stop feeding decrypt results into the rotation test's print output
- typed sync results (kind→status table) + one persist_sync path
- keep get_blob() password reads out of the rotation test's print output
- run the kind differential before the dead-kind check
- correct the suite count quoted in 9b90614's message

## v1.20.2

### What changed

- ntfy handler swallowed the first alert on hosts up less than 60s

### Internal

- gate merges and the :latest publish on the project's own test suites
- self-booting DUTs resolved gunicorn from a hardcoded dev-host path
- dut_official_tt wrote screenshots to a dev-host-only path
- red-test the gate — reintroduce the swallowed-first-alert bug for one run
- Revert "ci: red-test the gate — reintroduce the swallowed-first-alert bug for one run"
- SQLite writers fail with 'database is locked' under concurrent requests

## v1.20.1

### Internal

- refresh AGENTS test-matrix rows for v1.20.0 (dash_fit 23/23 + 94px chrome + 15px edge, navbar gutter 15px)
- pin refresh subjects preserve (R1) + log every preserve keep
- correct R1 fix attribution in the refresh-subjects audit record

## v1.17.0

### What changed

- **dashboard**: Settings tab consolidates personal details, notifications, logout + per-type notification prefs (v1.17.0)

## v1.15.4

### What changed

- **dashboard**: institute mail, bare reg no, all-subject marks chips with stale flag, minimal score decimals

### Internal

- before/after pair for the dashboard widget fixes

## v1.15.3

### What changed

- list portal CL / CLASS IN CHARGE row on the attendance tab

## v1.15.2

### Internal

- before/after attendance pairs for the pole-cluster fix
- review record for PRs #25-32 — causes, fixes, standing rules, deferred
- stop killing concurrent sessions on every login; guard GET /logout against speculation prefetch
- incident record - short-lived sessions (2026-10-10)

## v1.15.1

### Internal

- code-review fixes for PRs #25-32 — preserve contracts, pole overlap, logging tripwire, dead code
- sweep claims invalidated by the #25-32 review fixes

## v1.12.2

### What changed

- **logging**: ntfy alert carries the kv cause

## v1.12.1

### What changed

- **portal**: re-derive attendance body after mid-scrape relogin (S25)
- **logging**: every >=400 request logs its cause; noise cut; rotation; ntfy alerting
- **telemetry**: usage_events table + _track() — know how the app is used

### Internal

- **app**: fault-handling hardening — guarded decodes, marks preserve, global errorhandler
- test+docs: fault-handling regression suite, matrix row, incident record
- **logging**: log_with_kv honors the logger level; opensrm.portal pinned DEBUG

## v1.12.0

### What changed

- mid-sem feedback auto-fill + subject->teacher faculty map

## v1.11.1

### What changed

- **portal**: re-derive attendance body after mid-scrape relogin (S25)

### Internal

- **app**: fault-handling hardening — guarded decodes, marks preserve, global errorhandler
- test+docs: fault-handling regression suite, matrix row, incident record

## v1.10.7

### What changed

- **ui**: page gutter 16px -> 8px below lg — the column was misaligned with its own navbar

Web Push class reminders (PR #23): migration 11 push tables, pure due-calculation, pywebpush sender, /internal/push/tick + /api/push/*, SW push handlers + receipt, reminders card, docs. Rollout: PUSH_ENABLED off by default.

## v1.8.1

### What changed

- **exams**: subject table with blanked dates preserves stored schedule

## v1.7.0

### What changed

- **timetable**: no Break divider/hero once the day's last class is done
- **timetable**: section-visible edit history — who edited, when, what changed

### Internal

- progress-endpoint recipe used a netid NETID_RE rejects
- record the login-rejection incident and correct rate-limit/preflight claims
- the deploy watcher it describes does not exist
- compact edit history — terse diff lines, relative time, bulk collapse

## v1.4.0

### What changed

- **web**: exam card — wrap subject names instead of truncating at mobile width
- **web**: unclutter the exam card on mobile — aligned date column
- **login**: rank the card's vertical gaps by relationship, not one flat gap
- **web**: redesign the exam card rows — day stamps, real hierarchy
- **web**: align the exam card with DESIGN.md — house rules win
- **web**: exam card polish per review — spell the session, strengthen the name
- **login**: match the brand band's gap to the password -> action break

### Internal

- **exams**: end-sem schedule card via ScribeInner month/year probe
- **docs**: redact token prefix in audit record — verify76 H2a was failing on clean main
- PROXY_TOKEN rotation complete — leaked value dead, live value stored on lab
- add login UX screenshots for PR review
- screenshots for the end-sem schedule card PR
- re-shoot screenshots at mobile 2.75x DPR
- **login**: make the group breaks adaptive to the screen, not a pinned 36px
- **web**: Provisional becomes a header pill, footnote dropped
- run the Login Flow UX Guide checklist end-to-end; honest lockout countdown

## v1.3.0

### What changed

- **login**: floating-label inputs, guide-compliant auth form, tighter hierarchy
