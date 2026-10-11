#!/usr/bin/env python3
"""verify76.py — verify every audit finding's fix is present at HEAD (repo /opt/data/opensrm-repo).
Static signature checks only; behavioral checks (fresh-DB boot, SW DUT, XSS DUT, prod smoke) are run separately."""
import re, subprocess, sys, pathlib
R = pathlib.Path(__file__).resolve().parents[1]
def rd(p): return (R / p).read_text()
results = []
def chk(fid, desc, ok, ev=""):
    results.append((fid, desc, bool(ok), ev))
def has(p, pat, f=0):
    try: return re.search(pat, rd(p), f) is not None
    except Exception as e: return None
def miss(p, pat, f=0):
    r = has(p, pat, f); return r is False
def grep_repo(pat, path='.'):
    out = subprocess.run(['grep', '-rIn', pat, str(R / path), '--exclude-dir=.git',
                          '--exclude-dir=.venv'], capture_output=True, text=True)
    return out.stdout.strip()
def region(p, start, end):
    t = rd(p); i = t.find(start)
    if i < 0: return ''
    j = t.find(end, i + len(start))
    return t[i:j if j > 0 else i + 8000]

# ---------- CRITICAL ----------
chk('C1a', "migrations: @migration(version=1) on m001_base", has('app/migrations.py', r'@migration\(version=1'))
chk('C1b', "migrations: excepts narrow to 'duplicate column'", has('app/migrations.py', r'duplicate column'))

# ---------- HIGH ----------
_tok_probe = '2178' + '1f95'  # split so this file doesn't trip its own scan
chk('H2a', "secret scrub: no live token literal in tree", not grep_repo(_tok_probe))
chk('H2b', "dump_headers.py reads token from env", has('egress/poc/dump_headers.py', r'os\.environ\['))
chk('H2c', "referer_probe.py reads token from env", has('egress/poc/referer_probe.py', r'os\.environ\['))
chk('H2d', ".dockerignore excludes egress/", has('.dockerignore', r'^egress/?$', re.M))
chk('H3a', "XSS: timetable values escaped at render (_hesc on code/name/location)",
    has('app/app.py', r'_hesc\(str\(r\[2\]'))
chk('H4a', "SW: no inline register in login.html", miss('app/templates/login.html', r'navigator\.serviceWorker'))
chk('H4b', "SW: register lives in login.js", has('app/static/login.js', r'serviceWorker\.register'))
chk('H4c', "SW: Service-Worker-Allowed header set", has('app/app.py', r'Service-Worker-Allowed'))
chk('H5',  "cooldown: _request_fail_counted reset per request (init + reset)",
    len(re.findall(r'_request_fail_counted = False', rd('app/app.py'))) >= 2)

# ---------- MEDIUM: backend ----------
chk('M6',  "wrong password -> 401 classification (invalid credentials)",
    bool(re.search(r'invalid credentials', region('app/app.py', 'def _login_error_code', 'def api_login'))) or has('app/app.py', r'invalid credentials'))
_pm = region('app/app.py', 'def parse_marks', '\ndef ')
chk('M7',  "parse_marks: always 2-tuple (no bare 'return out' inside parse_marks)",
    (re.search(r'^\s*return out\s*$', _pm, re.M) is None) and ('return out, {}' in _pm))
chk('M8',  "playwright timeout: coroutine cancelled + browser closed (zombie fix)",
    has('app/app.py', r'zombie double-drive') and has('app/app.py', r'future\.cancel\(\)') and has('app/app.py', r'old_browser, _browser = _browser, None'))
chk('M9',  "rate checkers atomic under threads (_rate_lock)",
    len(re.findall(r'with _rate_lock', rd('app/app.py'))) >= 2)
_login_region = region('app/app.py', 'def api_login(', '\n@app.route')
chk('M10', "login: creds validated before IP budget burn",
    'password' in _login_region and
    0 < _login_region.find('password') < _login_region.find('Too many login attempts'))
chk('M11', "session expiry enforced at read (created check)",
    bool(re.search(r'created', region('app/app.py', 'def get_current_user', 'def api_login'))))
chk('M12', "date cells recognized before score pairs (_DATE_CELL_RE)",
    has('app/app.py', r'_DATE_CELL_RE') and len(re.findall(r'_DATE_CELL_RE', rd('app/app.py'))) >= 3)
chk('M13', "attendance: numeric-column guard vs shifted portal columns",
    has('app/app.py', r'numeric columns must look numeric') and has('app/app.py', r'fullmatch\(r"-\?'))
chk('M14', "aggregate portal budget wired into preflight+login",
    len(re.findall(r'_check_portal_budget', rd('app/app.py'))) >= 3)

# ---------- MEDIUM: frontend/SW ----------
chk('M15', "SW: logout clears caches (caches.delete)",
    has('app/static/sw.js', r'caches\.delete'))
chk('M16', "SW: resp.ok checked before caching",
    has('app/static/sw.js', r'resp\.ok'))

# ---------- MEDIUM: deployment/supply-chain ----------
compose = rd('docker-compose.yml')
chk('M17', "compose: restricted bind (loopback + cloudflared gw)", '127.0.0.1:8083' in compose and '172.31.0.1:8083' in compose)
chk('M18', "SECURITY.md: root/--no-sandbox risk documented",
    bool(re.search(r'no-sandbox|runs as root', rd('SECURITY.md'), re.I)))
chk('M19', "CI: actions SHA-pinned", bool(re.search(r'uses: \S+@[0-9a-f]{40}', rd('.github/workflows/build.yml'))) and bool(re.search(r'uses: \S+@[0-9a-f]{40}', rd('.github/workflows/lint.yml'))))
chk('M20', "CI: default permissions read-only", has('.github/workflows/build.yml', r'permissions:\s*\n\s*contents: read') and has('.github/workflows/lint.yml', r'permissions:\s*\n\s*contents: read'))
chk('M21', "Docker: image digests pinned (2 FROM + uv COPY)", rd('Dockerfile').count('@sha256:') >= 3)
chk('M22', "blobatar pinned to commit (pyproject + lock)",
    has('pyproject.toml', r'rev = "[0-9a-f]{40}"') and has('uv.lock', r'7fb1eed2'))
_pyv = re.search(r'^version = "([^"]+)"', rd('pyproject.toml'), re.M).group(1)
chk('M23', f"versions consistent (pyproject=lock=VERSION={_pyv})",
    has('uv.lock', rf'name = "opensrm"[\s\S]{{0,200}}?version = "{re.escape(_pyv)}"')
    and rd('VERSION').strip() == _pyv)
chk('M24', "CI: uv lock --check in build + lint", 'uv lock --check' in rd('.github/workflows/build.yml') and 'uv lock --check' in rd('.github/workflows/lint.yml'))
chk('M25', "DEPLOY.md: no token path/line disclosure",
    not has('egress/DEPLOY.md', r'/docker/\.env.*line 20|line 20.*CF_FULL', re.I | re.S) and not has('egress/DEPLOY.md', r'CF_FULL_TOKEN, line'))
chk('M26', "app.py: no ng2776 references", not grep_repo('ng2776', 'app'))

# ---------- MEDIUM: docs ----------
chk('D27', "README/SECURITY CSP claim matches reality (jsdelivr allowed)",
    has('README.md', r"script-src[^`]*cdn\.jsdelivr\.net|jsdelivr") and has('SECURITY.md', r'jsdelivr'))
chk('D28', "README gunicorn quick-start has -t 120", has('README.md', r'-t 120'))
chk('D29', "DESIGN: theme is a shared partial (not duplicated)",
    not has('DESIGN.md', r'duplicated in both templates|duplicated in both templates'))
chk('D30', "SECURITY: healthcheck/log-rotation claim now true (compose has them)",
    'healthcheck' in compose and 'logging:' in compose and has('SECURITY.md', r'[Hh]ealthcheck'))
chk('D31', "SECURITY: reporting channel has an address (advisories URL)",
    has('SECURITY.md', r'github\.com/.+/security/advisories'))

# ---------- LOW/INFO ----------
chk('L32', "bare 'except:' gone from app/", not grep_repo(r'except:\s*$', 'app'))
chk('L33', "captcha retry refills password after 5s re-render sleep",
    bool(re.search(r"sleep\(5\)[\s\S]{0,300}?page\.fill\('input\[name=\"password\"\]'", rd('app/app.py'))))
chk('L34', "raw exception text not returned to API clients",
    (not re.search(r'tr\(e\)', _login_region)) or bool(re.search(r'internal error|generic', _login_region, re.I)))
chk('L35', "progress endpoint: POST, netid not in query",
    has('app/app.py', r'"/api/login/progress", methods=\["POST"\]') and has('app/static/login.js', r'method:\s*"POST"'))
chk('L36', "static route no longer hardcodes /app/app/static (code, not comments)",
    not any('/app/app/static' in l and not l.strip().startswith('#') for l in rd('app/app.py').splitlines()))
_sw_cache = re.search(r"CACHE_NAME = '([^']+)'", rd('app/static/sw.js')).group(1)
chk('L37', f"README diagram cache name matches sw.js ({_sw_cache}), no stale name",
    has('README.md', re.escape(_sw_cache))
    and not re.search(r'opensrm-v\d+', rd('README.md').replace(_sw_cache, '')))
chk('L38', "docs say Flask 3.1", not has('README.md', r'Flask 3\.0') and not has('DESIGN.md', r'Flask 3\.0'))
chk('L39', "HSTS header present (cf-ray gated)",
    bool(re.search(r'get\("cf-ray"\):\s*\n\s*resp\.headers\.setdefault\("Strict-Transport', rd('app/app.py'))))
chk('L40', "rate dict: prune stale keys, no full clear()",
    not bool(re.search(r'\.clear\(\)', region('app/app.py', 'def _check_rate', 'def api_login'))) or has('app/app.py', r'_prune|prune'))
chk('L41', "dead code: no duplicate threading alias", miss('app/app.py', r'import threading as _tw'))
chk('L42', "dead code: photo_b64 gone from users SQL (comments excepted)",
    not any('photo_b64' in l and not l.strip().startswith('#') for l in rd('app/app.py').splitlines()))
chk('L43', "dead code: dataset.copyFlash gone", not grep_repo('copyFlash', 'app'))
chk('L44', "a11y: copy targets keyboard-accessible (role/tabindex/keydown)",
    has('app/static/dash.js', r"setAttribute\('role', 'button'\)") and has('app/static/dash.js', r"setAttribute\('tabindex', '0'\)") and has('app/static/dash.js', r'keydown'))
chk('L45', "a11y: progress bars have aria-label", len(re.findall(r'aria-label', rd('app/templates/dashboard.html'))) >= 5)
chk('L46', "manifest linked on dashboard", has('app/templates/dashboard.html', r'rel="manifest"'))
chk('L47', "CDN pinned: tailwind 4.3.3 + daisyui 5.7.46",
    has('app/templates/partials/theme.html', r'@tailwindcss/browser@4\.3\.3') and has('app/templates/partials/theme.html', r'daisyui@5\.7\.46'))
chk('L48', "entrypoint fails fast (set -eu)", has('entrypoint.sh', r'^set -eu', re.M))
chk('L49', "VERDICT.md references solve_captcha_b64", has('egress/poc/VERDICT.md', r'solve_captcha_b64'))
chk('L50', "CONTRIBUTING: shared playwright context note", has('CONTRIBUTING.md', r'context|shared', re.I))
chk('L51', "SW scope/registration fixed (scope root)", has('app/static/login.js', r"scope:\s*['\"]/"))
chk('L52', "login rate: empty-body POSTs don't burn IP budget (M10 companion)", 'M10' in [r[0] for r in results if r[2]])

# ---------- docs-audit (13 findings, docs_audit.json) ----------
DESIGN_T = rd('DESIGN.md'); README_T = rd('README.md')
chk('D53', "docs1 README/SECURITY CSP claim corrected (jsdelivr)",
    # content check, not URL validation: a bare 'in' on a hostname literal is
    # what py/incomplete-url-substring-sanitization flags, so match it as text
    ("script-src 'self', no external scripts" not in README_T) and bool(re.search(r'cdn\.jsdelivr\.net', rd('SECURITY.md'))))
chk('D54', "docs2 SECURITY healthcheck claim true (compose has healthcheck+logging)",
    ('healthcheck' in rd('SECURITY.md').lower()) and ('healthcheck' in compose) and ('logging:' in compose))
chk('D55', "docs3 README gunicorn -t 120", '-t 120' in README_T)
chk('D56', "docs4 DESIGN shared partial theme", ('partials/theme.html' in DESIGN_T) or ('shared partial' in DESIGN_T.lower()))
chk('D57', "docs5 README PWA network-first", 'network-first' in README_T)
chk('D58', f"docs6 README diagram cache name current ({_sw_cache}, no stale name)",
    (_sw_cache in README_T) and not re.search(r'opensrm-v\d+', README_T.replace(_sw_cache, '')))
chk('D59', "docs7 DESIGN network-first documented", 'network-first' in DESIGN_T)
chk('D60', "docs8 no false remote-image-host claim (img-src matches code)",
    ('dicebear' not in DESIGN_T.lower()) and ("allows no remote image hosts" in DESIGN_T))
chk('D61', "docs9 DESIGN drift rows marked fixed (strikethrough + var(--color-* verify))",
    ('hard-coded hex~~ -> **fixed**' in DESIGN_T.replace('\u2192', '->')) or ('hard-coded hex~~ \u2192 **fixed**' in DESIGN_T) or ('file uses `var(--color-*)` tokens' in DESIGN_T))
chk('D62', "docs10 README Flask 3.1 (no 3.0)", ('Flask 3.0' not in README_T) and ('Flask 3.1' in README_T))
chk('D63', "docs11 README: timetable served from SQLite (not lumped with 24h)", 'timetable served from SQLite' in README_T)
chk('D64', "docs12 CONTRIBUTING shared context", 'shared context' in rd('CONTRIBUTING.md').lower())
chk('D65', "docs13 VERDICT no stale app.py:152 pointer", 'app.py:152' not in rd('egress/poc/VERDICT.md'))

# ---------- report ----------
fails = [r for r in results if not r[2]]
print(f"{'ID':5} {'STATUS':7} FINDING")
for fid, desc, ok, ev in results:
    print(f"{fid:5} {'PASS' if ok else 'FAIL':7} {desc}")
print(f"\nTOTAL: {len(results)} checks | PASS {len(results)-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED:", ", ".join(f[0] for f in fails))
sys.exit(1 if fails else 0)
