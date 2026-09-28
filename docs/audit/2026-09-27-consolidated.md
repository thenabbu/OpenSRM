# OpenSRM Audit — consolidated 76 findings (commit 2bed463) + resolution

> **Status: ALL FIXED.** Fix batches `394c8ff` → `a8ffccf` (21 commits, pushed, CI green,
> deployed to prod). Verification: `tests/verify76.py` 71/71 · fresh-DB boot ·
> `tests/test_sw.py` 7/7 · `tests/test_xss.py` 9/9 · prod 12-point smoke.
> Outstanding: none. Egress worker PROXY_TOKEN rotated + verified 2026-09-28
> (leaked value 401s; live value stored at `lab:~/.srm_egress_proxy_token`, mode 600).
> Tooling lives in `tests/`; record written 2026-09-27.

---

All 6 reports in, every critical/high claim verified against source by me, findings deduped. Here's the consolidated audit.

---

# OpenSRM Code Review & Audit — commit `2bed463`

**Method:** 6 parallel reviewers (backend, frontend, security-audit, infra/egress, dependencies, docs), each loading its own skills first (`security-audit`, `codebase-inspection`, `systematic-debugging`, `srm-portal-attendance`, `docker-compose-deployment`, `homelab-backup-management`, `web-interface-guidelines`, `daisyui`). **I re-verified every critical/high finding + 8 mediums against the actual source myself (✅ marks below)** — nothing here is taken on trust. **89 raw findings → 76 unique: 1 critical, 4 high, ~23 medium, ~24 low, ~22 info.**

## 🔴 CRITICAL

**1. ✅ Fresh database boots completely broken — `migrations.py:95`**
`m001_base()` — the *only* code that creates `users`/`cookies` — has **no `@migration(version=1)` decorator** (every sibling m002–m007 has one). On a new DATA_DIR: registry = `[2,3,4,6,7]` → `ALTER TABLE users` fails → swallowed by `except OperationalError: pass` (lines 93/112/116/142/146) → schema records "version 7 applied", tables never exist → **every request 500s** while logs claim success. Prod survives only because its DB predates the migration system. Reviewer reproduced this on a temp DB; I confirmed the missing decorator + swallowing excepts by reading the file.
→ *Fix:* add `@migration(version=1, description="base users/cookies")`; narrow the excepts to ignore only `duplicate column name`.

## 🟠 HIGH

**2. ✅ Live secret committed to the public repo — `egress/poc/dump_headers.py:9` + `referer_probe.py:11`**
`x-proxy-token = <redacted>` hardcoded (grep confirmed both files) — that's the live gate on `srm-egress.200871.xyz`. Worse: `Dockerfile:47 COPY . .` with `egress` absent from `.dockerignore` (grep = 0) ships it **into the public GHCR image** too.
→ *Fix:* rotate the Worker PROXY_TOKEN, replace literals with `os.environ[...]`, add `egress/` to `.dockerignore`.

**3. ✅ Stored cross-user XSS via shared timetable — `dashboard.html:274` + `app.py:1276-1278`**
Custom subject code/name/location from `/api/timetable` go into HTML via `str.format` with **zero `html.escape`** (grep confirms none in app.py) behind `{{ timetable | safe }}`. Group is keyed by program/batch/semester/section — **prod has 6 real users** (ag2188, an0750, av5351, ds4647, ng2776, sg2935), so same-section students share one slot set: one student's write renders in classmates' dashboards. CSP doesn't save it: `script-src … https://cdn.jsdelivr.net` allows an attacker-published npm package as script origin.
→ *Fix:* `markupsafe.escape()` on code/name/location in `timetable_html()`; consider self-hosting CDN assets.
*(needs-validation: one end-to-end browser payload confirm — the sink + shared path + script origin are all source-verified.)*

**4. ✅ PWA/service worker never registers — `login.html:121-122`**
Inline `<script>` is blocked by `script-src 'self'` (app.py:1033), *and* `scope:"/"` would throw anyway — no `Service-Worker-Allowed` header exists anywhere (grep). This also **explains the original navbar bug**: an ancient registration (scope `/static/`) kept serving stale JS with fresh HTML; new devices get no SW at all. My v10 network-first fix works for existing devices, but offline/PWA is dead code for everyone.
→ *Fix (decision):* move registration into `login.js` + add the header in `static_no_cache()`, **or delete sw.js + registration entirely** (it never worked — ponytail says delete). Your call.

**5. ✅ Portal cooldown can never arm — `app.py:619`**
`_request_fail_counted = False` exists *only* inside Playwright's `_do_login()`; the pure-HTTP path never resets it → after the first counted fail, `_portal_fail_once()` is a no-op forever → `_portal_consecutive_fails` never reaches 3 → the self-protection that pauses logins when SRM starts rate-limiting **never engages** (grep: only writes are 308/325/619).
→ *Fix:* reset the flag at the start of each `fetch_attendance()`.

## 🟡 MEDIUM (23, grouped)

**Backend correctness**
- ✅ wrong password returns **503 not 401** (`app.py:1377` keys on `"login failed"` but real error is `"invalid credentials…"`) — *I downgraded from high: it's a wrong contract, not a defeated control*
- ✅ `parse_marks` mixes bare `return out` with `return out, {}` (433/435/443/447) → callers unpack → swallowed ValueError → silent empty marks
- Playwright timeout at 945: coroutine keeps running on shared page while lock is released (zombie double-drive) + `_browser = None` without closing → **one leaked Chromium per failed scrape** (OOM risk)
- Rate-limit checkers are non-atomic read-modify-write under `--threads 8` (281) → caps exceed by ~thread count
- `/api/login` burns the per-IP budget *before* validating credentials (1358) → 11 × `{}` POSTs = hour-long self-DoS
- Session tokens never expire at read time (180: no `created` check) — 30-day limit only applies when someone re-logs-in (backend + security both found it)
- Component parser: numeric dates (`12/09/2026`) misread as scores; date regex needs 3+ letter months (507) — *reproduced with regex probe*
- Attendance parsing is positional with magic cell counts (381) → portal column change = silently shifted data

**Security**
- No aggregate budget on portal-bound work: per-IP/per-netid only, + unauthenticated `/api/login/preflight` bypasses `_check_rate` entirely → rotating IPs multiplies load from the **one shared egress IP** and can drive the global cooldown for everyone (security + backend found independently)

**Frontend/SW**
- SW caches **every HTML page incl. personal data**, never cleared on logout → readable offline after logout (sw.js:42)
- SW caches 4xx/5xx without `resp.ok` check (sw.js:32) → errors served as pages

**Deployment/supply-chain**
- ✅ compose publishes `8083:8080` on all interfaces, bypassing the CF front end (bind `127.0.0.1:` — *verify cloudflared reaches it locally first*)
- Container runs as root, `--no-sandbox` (Dockerfile:49 — documented deliberate; accepted-risk, should be in SECURITY.md)
- ✅ GitHub Actions pinned by mutable tags not SHAs (build.yml/lint.yml — build has `packages:write`)
- Docker base images tag-pinned, not digest-pinned; `blobatar` tracks branch `feat/python-sdk` not a commit
- ✅ **`uv.lock` stale: says version 1.0.0, pyproject says 1.1.0** — my fault from yesterday's amend; no CI runs `uv lock --check`
- `egress/DEPLOY.md:7` publicly documents the CF token's exact path/line + account ID; `app.py:112` comment contains `ng2776` (both ✅ grepped)

**Docs**
- ✅ README:197 + SECURITY.md:20 claim *"script-src 'self', no external scripts"* — **false**, jsdelivr is allowed (and that allowance is what makes finding #3 executable); SECURITY.md:38 claims healthcheck+log-rotation exist in prod compose — they don't (only dev compose)
- README:40 gunicorn quick-start missing `-t 120` → anyone following it gets 30s worker kills on slow logins
- DESIGN.md:81/452 still says theme CSS is duplicated in both templates — it's a shared partial now

## 🔵 LOW / INFO (sample)
Two bare `except: pass` I **missed** in the earlier fix pass (1509/1537) ✅ · Playwright silent-retry branch skips credential refill (666) · raw exception text returned to API clients (951) · `/api/login/progress` unauthenticated + netid in query string · static route hardcodes `/app/app/static` (breaks local dev) · README diagram says `opensrm-v9` cache-first · Flask "3.0" vs 3.1.3 · `SECURITY.md` reporting channel has no address · no HSTS header · rate-dict `.clear()` wipes all counters at cap · dead code (dup `import threading`, `photo_b64` write-only, `dataset.copyFlash`) · a11y: copy targets not keyboard-focusable, progress bars unnamed · manifest.json only on login page · CDN (jsdelivr) = main supply-chain exposure, unpinned floating `@4`/`@5` versions.

## ✅ Verified clean (each reviewer traced these)
SQL fully parameterized, no f-string SQL · CF headers only trusted with `cf-ray` · `secrets.token_hex(32)` sessions, one token per netid · CSP/nosniff/frame-deny/16KB body cap present · attendance math (`_bunk_line`/overall) **provably correct** · no `eval`/`innerHTML`-of-data in JS (textContent everywhere), no inline handlers, no `javascript:` URLs · password only ever in POST body · tab system has proper ARIA + roving tabindex · gaze honors `prefers-reduced-motion` · **all pinned deps current, CVE-free** (flask 3.1.3, jinja2 3.1.6 incl. CVE-2025-27516 fix, gunicorn 26.2.0, cryptography 50.0.1 — verified live) · uv.lock pins everything + `--frozen` in Docker build · dependabot covers pip/actions/docker · build job scoped `contents:read`+`packages:write` · entrypoint quotes all expansion + 0600 secret · no passwords/emails/reg-nos in the tree (test harnesses read env) · formIds/endpoints/ports/rate-limits in docs match code · git-URL cookie-replay worker PoC has no live creds.

## Fix order (proposal)
1. **P0** — rotate proxy token + scrub 2 files + `.dockerignore`; migration decorator (test with fresh `DATA_DIR`); `html.escape` in `timetable_html`; `uv lock`
2. **P1** — cooldown flag reset; 401 classification; `parse_marks` tuples; session expiry at read; SW decision (fix vs delete)
3. **P2** — rate-limit atomicity; IP-budget ordering; aggregate portal budget; SW cache hygiene; compose loopback bind (after tunnel check)
4. **P3** — CI SHA-pins; docs corrections (CSP claims, healthcheck, gunicorn `-t`, DESIGN theme, README SW rows); lows/infos

needs-validation: end-to-end XSS payload in browser · cloudflared/monitoring reachability before loopback bind · Dependabot handling of the git-branch dep.

---

Want me to start executing? Suggested: **P0 batch first** (token rotation needs you for the Worker secret — I'll give you the exact command; the other three I can do, test with a fresh-DB boot, commit atomically). Also decide on the **SW fix vs delete** question in P1.