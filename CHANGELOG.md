# Changelog

Generated from git history by scripts/release_notes.py. Every GitHub Release body is the same rendering.

## v2.12.0

### What changed

- **release**: generator handles version-only ranges; backfill fetches its own tags
- **release**: backfill re-marks the newest release as latest
- **build**: immutable version tags, provenance and an SBOM (#158)
- **static**: version icon URLs so Cloudflare caches them at the edge (#163)
- **portal**: open the captcha-dataset scope in the HTTP login path (#166)

### Internal

- **release**: stop the workflow re-triggering itself; correct the notes classifier
- **ci**: make the pipeline tell the truth about what it runs (#155)
- **ci**: the scans now block, and the tools that gate are locked (#156)
- **ci**: boot the smoke under prod's own hardening, via compose (#157)
- prove the upgrade path, not just a fresh install (#159)
- **ci**: stop the two copies of Tests cancelling each other on main (#160)
- **ci**: give Tests its own concurrency group so the reusable call survives (#161)
- regenerate committed worker.js from worker.src.js (#164)
- **portal**: capture a labelled CAPTCHA dataset on every successful login (#165)
- bump ruff to 0.17.3 and pip-audit to 2.10.1


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

## v1.27.2

### What changed

- clears pip-audit, v1.27.2

## v1.27.1

### What changed

- **feedback**: auto-archive the CTA while the portal window is closed

### Internal

- test-table row for test_softrefresh_dut (phase 4 DUT)
- run test_softrefresh_dut in the e2e battery (phase 4 DUT)
- css: rebuild app.css — overlay modal removal pruned its loading-lg token (CSS-sync CI gate)

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

## v1.20.0

### What changed

- **security**: preserve contract for attendance_json (audit run-1 #2)
- **security**: push endpoint allowlist + row cap + dequeue deadline (audit run-1 #4/#11)
- **security**: encrypt portal_sessions cookies at rest (audit run-1 #5)
- **security**: one pipeline deadline + bounded portal reads + captcha host confinement (audit run-1 #8/#9/#10)
- **security**: no offline copy of account HTML + JS revalidation (audit run-1 #12/R1)
- **security**: scrub control chars from logs/ntfy + bare 401 for non-ASCII tick secret (audit run-1 #16)
- **dashboard**: uniform 15px edge, widget auto-fit, signed attendance margins, recent-marks highlight (v1.20.0)

### Internal

- **security**: free gates before budget + success-only sync quota (audit run-1 #1/#6)
- **security**: feedback fill through the portal gates + truthful partial report (audit run-1 #3/#17)
- **security**: preflight admission under lock + serialized portal body (audit run-1 #7)
- **security**: attempt-token progress, cross-site logout guard, edge-verified CF trust (audit run-1 #13/#15/#18)
- docs+fix: R1 interconnectivity residue — retention, truth, dead polyfill, silent-blank tab
- docs+tests: remove real student identifiers from tracked files
- **tests**: guide_server expected a lockout string app no longer ships
- redact real student identifiers from 39 documentation screenshots
- dash-fixes DUT screenshots (1920x1039 post-fix, squeeze viewports)
- re-shoot dash-fixes screenshots with redacted seed identity (zz9999) after main's identifier sweep

## v1.19.0

### What changed

- feedback-window CTA gating + mandatory release notices + viewport-fit dashboard (1.19.0)

### Internal

- **review**: stress-tested grid — LAYOUT `cap` clamps row 1 so heavy data can't crush row 2

## v1.18.0

### What changed

- **scraper**: persist the session after a mid-scrape relogin
- **timetable**: sync the official portal timetable (formId 10) with a clock-offset config; archive the manual editor
- **ui**: soft status badges per DESIGN.md §4.5; ship before/after evidence

### Internal

- require_own_server guard kills phantom verdicts; add pr_preflight + post_deploy scripts
- **review**: cross-review pass — DUT guard+overflow, migration comment truth, revert-path wording, AGENTS restore
- DUT matrix row 9/9; drop capture-tool dead scaffolding (2nd-pass findings N2/N3)
- **timetable**: archive all user input — Edit button hidden + save API 403 by default (TIMETABLE_EDITOR gate); tests/DUT/docs updated
- recapture evidence on the post-#45 tree; AGENTS push_api row 42/42 (measured)
- **timetable**: archive edit-history view + retire the obsolete Synced-from-portal badge (same TIMETABLE_EDITOR gate); DUT 10/10
- **timetable**: Soon badge retired (Now pill on the live class); rim tiers proven (grey comfortable/yellow zero-margin/red below 75) with pixel-checked screenshots; sw v27; tests 50/50 + DUT 14/14
- **review**: cross-review fixes — contentless-grid wipe guard (major), location carry per code-swap, truthful offsets comment + ponytail ceiling, derived schema pin restored, preflight comment number, portable capture paths; tests 53/53

## v1.17.0

### What changed

- **dashboard**: Settings tab consolidates personal details, notifications, logout + per-type notification prefs (v1.17.0)

## v1.16.0

### What changed

- compare the portal host on the parsed URL in the egress PoC
- never echo exception text from /api/feedback/fill (CWE-209)
- reserve the scrollbar gutter so the marks tab stops shifting the navbar
- userflow dead-session edges — index 500 race, refresh 401 reason, fetch redirect UX
- **dashboard**: card/widget engine — LAYOUT + WIDGETS registries, full-width 12-col grid

### Internal

- match the jsDelivr doc claim as text, not a URL substring
- test_layout row now 25/25

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

## v1.15.0

### What changed

- attendance view toggle + percentage scale + merged absences card (v1.13.0)
- _faculty_view KeyError on real course shape — dashboard 500 on prod
- feedback fill covers EVERY teacher, one form per teacher

### Internal

- post-deploy smoke must include an authenticated dashboard render
- restore comment opening orphaned by CSS cleanup — .nudP .pn-now was parsed as an invalid selector
- refresh PR screenshots — 7-row real-shape seed, new toggle, 0%/75% scale

## v1.14.0

### What changed

- official Exam Time Table (iden=126) as primary exam source; scribe leak demoted to fallback

### Internal

- exam events: hall/seat allotment push, FN/AN native codes, header-drift-proof ETT parser
- regenerate exam-card screenshots against rebased main (v1.11+ dashboard)
- exam-card screenshots from post-#29-merge render DUT (16/16)

## v1.13.0

### What changed

- mid-sem feedback auto-fill + subject->teacher faculty map
- feedback fill becomes opt-in with full preview before submit
- auto-fill becomes CTA + opt-in explainer modal

### Internal

- mid-sem feedback DUT screenshots (fabricated seed data)
- refreshed mid-sem feedback screenshots (opt-in preview panel, post-merge tree)
- PR dashboard screenshot taken before modal opens
- PR modal/mobile screenshots from final 29/29 DUT run

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

## v1.11.0

### What changed

- v1.11.0

## v1.10.7

### What changed

- **ui**: page gutter 16px -> 8px below lg — the column was misaligned with its own navbar

## v1.10.6

### What changed

- **push**: proper Android small icon — researched spec, not guesswork

## v1.10.5

### What changed

- **push**: drop the custom badge — platform derives the small icon

## v1.10.4

### What changed

- **push**: lean notification format — plain text, half-rect badge, no hero

## v1.10.3

### What changed

- **push**: branded notifications — OpenSRM metadata + brandkit visuals

## v1.10.2

### What changed

- **push**: normalize VAPID_SUBJECT to a mailto: URI before signing

## v1.10.1

### What changed

- push hint must render outside hidden controls (iOS/denied states)

### Internal

- pass Web Push env vars through compose (PUSH_ENABLED default 0)
- test+docs: iOS-not-installed UI path via UA-spoof; compose project-env gotcha
- test+docs: scroll iOS card into frame for screenshot; add push UI screenshots

## v1.10.0

### What changed

- Web Push class reminders (PR #23): migration 11 push tables, pure due-calculation, pywebpush sender, /internal/push/tick + /api/push/*, SW push handlers + receipt, reminders card, docs. Rollout: PUSH_ENABLED off by default.


## v1.9.0

### Internal

- reimagine personal details tab — identity header + responsive collapse groups
- personal panel recipe + cache-name sweep for v14 bump
- personal panel before/after at 393x851@2.75 + 1280x900@2

## v1.8.1

### What changed

- **exams**: subject table with blanked dates preserves stored schedule

## v1.8.0

### What changed

- **marks**: review round — uniform row heights, edit tooltip, glance marks/max

### Internal

- **marks**: neutral internal-marks redesign with class-scoped IE tagging
- marks card recipe (DESIGN 4.13 + 10.11), test matrix, before/after shots
- recipe reflects stretch grid + glance chips; counts to 53/53; re-shot afters (uniform rows, tooltip)

## v1.7.0

### What changed

- **timetable**: no Break divider/hero once the day's last class is done
- **timetable**: section-visible edit history — who edited, when, what changed

### Internal

- progress-endpoint recipe used a netid NETID_RE rejects
- record the login-rejection incident and correct rate-limit/preflight claims
- the deploy watcher it describes does not exist
- compact edit history — terse diff lines, relative time, bulk collapse

## v1.6.0

### What changed

- **navbar**: drop the netid echo, make the focused tab visible, relative sync age
- **navbar**: wordmark radius 8px -> 4px; rounded-box is over-curled at h-8

### Internal

- record the selected-tab rule, the daisyUI active-fill trap, the new caption
- navbar before/after at 1280x900 @2x and 393x851 @2.75x
- **navbar**: underline spans the whole tab — declare width, dock-active leaks 2.5rem
- re-shoot the three desktop shots with the corrected underline
- re-shoot the five after-shots with the 4px wordmark

## v1.5.0

### What changed

- **login**: classify portal rejections on their alert text, not page tokens
- **rate**: count only syncs that can run, and log the paths that were silent

### Internal

- rewrite README for v1.4.0 — fresh mermaid trio, ScribeInner correction
- fix trio bump, PR flow, deploy description, add test matrix
- full 8-directive CSP, honest session pruning, exact limits
- fix cooldown formula, docs layout, IBM Plex, CDN pins
- architecture diagram gets curve:linear — GitHub's renderer trips on the curved cross-cluster edges
- one runnable check for rejection classification + sync quota

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

## v1.2.0

### What changed

- **security**: escape timetable slot values before the |safe render
- **portal**: reset portal-fail-once flag in the HTTP pipeline too
- **security**: make rate-limit check-and-append atomic
- **security**: count per-IP login budget only after credential validation
- **api**: map login/refresh errors to correct HTTP statuses explicitly
- **marks**: parse_marks must return a 2-tuple on every path
- **auth**: enforce 30-day session expiry at read time
- **pwa**: service worker actually registers now (+ static route fixes)
- **security**: aggregate cap on outbound portal requests (anti IP-rotation)
- **compose**: stop publishing 8083 on all interfaces + sync repo file with live
- **security**: login progress endpoint takes netid from POST body, not URL
- **web**: HSTS via CF edge, progressbar labels, keyboard copy, manifest on dashboard

### Internal

- **security**: scrub hardcoded egress proxy token from PoC scripts
- **migrations**: register m001_base — fresh DBs booted with no users/cookies tables
- pin actions to commit SHAs + explicit read-only token default
- replace both bare excepts + drop account name from import comment
- entrypoint set -eu (fail fast on mkdir/secret failure)
- close all 13 findings from the docs audit + real reporting channel
- **backend**: close 6 audit findings — zombie scrape, date/score mixup, shifted rows, counter wipe, dead code
- pin images by digest, blobatar by commit, CDN by version + CI lock check
- **docs**: drop residual false remote-image-host claim (docs-audit finding 8 residue)
- test+docs: in-repo verification suite, AGENTS quickstart, audit record

## v1.1.0

### What changed

- tabbed dashboard (Attendance/Timetable/Personal Details), personal details scraper (formId 17), OpenSRM branding
- restructure repo to app/ package layout matching production container
- CSP-safe tab binding (addEventListener, no inline onclick)
- headless=True in container scraper (proven to work; lab fast scraper uses it since Sep 2026)
- speed: persistent Chromium + worker event-loop + pre-warmed ddddocr (feature/speed-warm)
- Refresh button broken — CSP blocks inline onclick, bind via addEventListener in dash.js
- login page visible brand heading OpenSRM (was SRM Attendance); title already OpenSRM
- ui: better mobile/phone layout — stack personal-details rows, small-screen hero/padding, timetable room
- ui: better Personal Details mobile layout — subtle label above value in mini-card groupings
- ui: cleaner Personal Details mobile — grouped card with uppercase labels, proper padding
- add Cache-Control no-store to all responses — browser was caching stale dashboard HTML
- student photo from portal as nav avatar + period as small note in hero card
- ui: rebrand palette — B&W from logo, remove IBM Carbon blue
- meta: full OpenGraph, Twitter Card, theme-color, robots, apple-touch-icon
- ui: polish rebrand — consistent bg #111111, fix login.css syntax, remove all old colors
- no-store cache for static files (login.css was cached stale)
- PWA manifest + iOS install meta tags + cacheable static JS/JSON
- service worker — network-first dashboard, cache-first static, offline fallback
- PWA offline indicator + deploy
- pwa: full cross-platform support — dedup meta, iOS safe-area, Windows tile, Android manifest, SW on login
- PWA splash — regenerate icons from source, maskable 512px, dark splash bg
- PWA splash — opaque dark icons, 1024px for high-DPI, iOS startup images
- add course list scrape and timetable save
- timetable_html day_slots keying — was keyed by period, now by day
- add datetime import for timetable rendering
- timetable editor — drag-and-drop grid, touch support, save/load API
- pass group_key to timetable_html in index route
- timetable.js + drag-drop-touch.js in DASH template (was misplaced in login)
- hide edit btn when editor open, restore on cancel
- contrast (selected day/badge), grid transposed (days=rows,time=cols), missing timetable.json subjects added
- renderGrid transposed (days=rows, time=cols) — JS was not actually rewritten
- ui: critique fixes — personal sections, clickable links, course readability, hero constraint, logout button, done-dot green
- ui: mobile fixes — login top-aligned, bigger touch targets, hero full-width, tabs bigger, refresh icon-only, personal compact, edit-btn full-width
- ui: tab bar min-height 44px for mobile touch targets
- absent icon — CSS chevron replaces broken Unicode glyph
- password toggle, captcha retry x3, login card tightened, netid email support
- password toggle JS handler (was inert inline button)
- login — toggle button outside input, card true center via margin:auto
- login — toggle button inline with input, card vertically centered, SW cache v4
- **daisyui**: migrate dashboard — navbar, tabs, cards, progress, table, collapse, personal list
- **daisyui**: timetable CSS as external file, fix template variables, merge timetable styles
- CSS theme specificity + personal details grouping
- theme: fix neutral color to oklch(26% 0 0), remove dev-view route
- CHROMIUM_PATH env var, neutral color fix
- ui: rebuild login page with horizontal logo, daisyUI components
- ui: login - unified card, edge-to-edge logo, simpler labels
- ui: login labels -> NetID/Email + Password
- remove loading class from login button — spinner span handles it
- refresh button SVG icon (patch didnt match unicode char)
- DESIGN.md not executable
- login card overflow — fieldset closing tags
- modal listener leak + template formatting
- login always failed - captcha read before blob rendered
- timetable editor Save/Cancel/Add buttons stayed hidden
- accessible tablist - WAI-ARIA roles, roving tabindex, arrow keys
- api_marks queries users table instead of treating netid as dict
- expandable marks cards — click-to-expand, color-coded assessments, loading spinner
- marks UI — remove expand/collapse friction, fix badge contrast
- cache-bust marks.js so users get new UI without 4h wait
- Tier 1 security + frontend + performance audit fixes
- Tier 2 frontend + a11y — aria-live, opacity spec, grid, toast
- revert USER directive — Playwright needs root, skip non-root for now
- parallel scraper + session caching — scrape time ~30s → ~5s
- CSP blocks cdn.jsdelivr.net — Tailwind + daisyUI CSS/JS not loading
- login speed optimizations — ~2s faster
- photo fetch parallelized into JSP block — saves ~600ms
- persistent browser context — no new context per scrape
- auto-relogin when cached session silently expires mid-scrape
- dual-engine captcha solver — ddddocr + vision fallback
- vision-first captcha solving — ddddocr proven wrong, vision proven right
- detailed captcha error messages + friendlier rate-limit text
- portal rate-limit detection + backoff + cooldown
- **egress**: CF Worker egress proxy — worker, deploy notes, A/B login proof
- replace dicebear avatar with animated blobatar
- **auth**: cooldown cascade — one portal-fail per request, no retry on bad password, 150s scrape timeout
- pure-HTTP portal pipeline — http_scraper.fetch() with Playwright fallback
- **http-scraper**: route page+HRD GETs through egress base; resolve relative photo URLs
- _do_login loop-exhaustion return (NoneType unpack crash) + captcha fetch retry/40s via worker
- live login progress — in-memory tracker + /api/login/progress + polling UI
- **login**: progress poll race — done flag stops stale in-flight poll from overwriting the error text
- **poc**: browser-side scrape PoC — stateless cookie-replay portal-proxy worker
- **http**: session reuse raised TypeError → jar wiped while logged_in stayed True
- **login**: preflight — warm portal session + solved captcha while typing password
- **ui**: center mobile top-bar brand (flex-1 had overridden daisyUI centering — measured 195.0px vs 195.0px viewport center)
- **logging**: _Formatter dropped exc_info — tracebacks never reached logs, hiding the timetable import failure for weeks
- **marks**: component rows are [entered_on, name, score/max] — parser took the date as the name; /api/refresh never persisted marks_json so marks froze at login. Parse both fields, persist on refresh, add view models for server-rendered tab

### Internal

- timetable data to JSON, helper functions read dict keys instead of tuples
- remove xvfb (headless=True proven safe, xvfb install/start dead weight since Sep 2026)
- photo_b64 auto-migration idempotent
- photo capture — broader selectors, wait for AJAX load, diagnostic return
- rewrite README, CONTRIBUTING, SECURITY to match current codebase
- custom OpenSRM icon as favicon + brand-mark, remove SP placeholder
- ui: improve contrast — bump dim/muted, subtle refresh button
- bump SW cache to v2 — force fresh asset install for new icons
- comprehensive README, CONTRIBUTING, SECURITY, .gitignore — match current codebase
- remove stray icon comparison screenshots
- rename srm-sp-auto → opensrm across compose
- timetable SQLite schema + group extraction + course scrape + editor API + legacy import
- update README for timetable editor
- remove dead timetable.py (replaced by SQLite-backed timetable_html in app.py)
- absent icon (CSS chevron), netid accepts email (strips @domain), placeholder updated
- update README/CONTRIBUTING/SECURITY, remove stale files
- fix container name in bug report template (srm-sp-auto -> opensrm)
- update accent color to white (oklch 100%)
- GitHub Actions build + deploy via GHCR
- build-only workflow, deploy via dockhand auto-pull
- Dockerfile Playwright env, login.html cleanup, daisyUI themes.css for components
- **dut**: correct daisyUI template vars, tab switching, timetable editor grid
- extract inline HTML templates to Jinja2 files
- remove dev-view route from source
- add ruff lint workflow, dependabot, fix lint errors
- proper OCI labels, metadata-action, healthcheck-ready Dockerfile
- rewrite README, CONTRIBUTING, SECURITY for current codebase
- deps: bump gunicorn 23.0.0 to 26.2.0
- migrate from pip to uv with lockfile
- Dockerfile LABEL backslash escaping
- update for uv migration
- assets: regenerate all icons from source logos, add README header
- phase 1 image optimization — eliminate uv cache, strip unused ONNX models, add .dockerignore
- phase 2 — strip system cruft (icons/doc/gtk/X11/systemd/perl) for ~30MB savings
- multi-stage + headless shell — image 1.38GB -> 1.17GB
- update CONTRIBUTING + README for multi-stage build and headless shell
- Phase 1+2 — CI cache, pinned uv, cv2 stub, dev compose
- navbar overhaul — name display, DiceBear avatar, sync fix, refresh refactor
- navbar polish — gaze avatar, dimmer netid, sync contrast, logout style, word-wrap, table header
- add DESIGN.md
- design system compliance — login form, timetable tokens, SW cache
- inline cv2 stub in Dockerfile (vendor dir deleted)
- design system — badge contrast, error toasts, SW cache
- design system compliance — shared theme, tokens, contrast, modal
- login completely broken — restore ddddocr deps in Dockerfile
- mark DESIGN.md drift #1 and #9 resolved
- dashboard contrast/spacing — table headers, absences gap, bunk text
- table headers brighter, absences gap wider, bunk text clearer
- internal marks backend — parse_marks, formId 13 fetch, /api/marks endpoint
- Internal Marks tab - marks.js, tabpanel, SW cache v8
- internal marks drill-down — pre-fetch component-wise data
- internal marks drill-down uses direct fetch POST instead of broken jQuery
- parse_marks regex for subjectId extraction from onclick attributes
- versioned migration pipeline + structured logging
- ruff import sorting
- relative imports for migrations + logging_setup (add __init__.py)
- Docker hardening — non-root user, healthcheck, log rotation
- Tier 3 + documentation rewrite
- remove inline re import (ruff lint failure)
- photo parallelized into JSP block, lint clean
- zero-nav fast path + multi-user cookie guard
- vision captcha solver, bump retries to 5
- ruff import-sort (I001) in app.py + test-login-ab.py
- **ci**: install git in builder stage — uv needs it to clone blobatar git dep
- security: scrub real credentials from egress/test-login-ab.py
- hot/cold data split + portal session table fix + drop unused photo fetch
- missing 'import os' in egress harness (F821 from creds scrub)
- mermaid architecture/pipeline/structure diagrams in README
- **ui**: navbar/dock navigation, dashboard home tab, attendance redesign, quiet auto-sync
- **ui**: card sync/refresh/logout footer hidden on lg+ — navbar owns them there (visual DUT caught the duplication)
- **timetable**: legacy import was silently broken — SQL binding mismatch (3 placeholders, 4 values) hid by bare except; break rows counted as periods; json consumed even on failure. Map rows by start time, log tracebacks, rename only on success
- **version**: x.y.z from VERSION file — APP_VERSION constant, rendered on login + mobile navbar; pyproject synced; bump policy documented
- **ui**: v1.1.0 — logo navbar + sync/actions/mobile icons-in-navbar; marks tab server-rendered (lazy-loader deleted; its first-button-only binding broke mobile); overall attendance compact; risk-first copy; click-to-copy values; smooth dock transitions; login note rewritten; SW network-first for /static/ (cache-first served stale JS with fresh HTML — the dead-navbar root cause)
- README/CONTRIBUTING for the 1.1.0 setup — fix formId 17→13 (marks, not personal), drop marks.js refs, preflight/network-first/dividers/copy bullets, version bump policy
