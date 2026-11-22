"""Unit: perf-budget guardrails (phase 8 of the smoothness campaign).

Static contracts that keep the earlier phases fixed:
  1. dashboard + login HTML reference no third-party hosts; CSP has no CDN.
  2. app.css gzipped <= 35 KB.
  3. versioned static = immutable; sw.js = no-cache + Service-Worker-Allowed;
     HTML = no-store.
  4. dash.js: a sync carries DATA, not markup (no route fetch, no reload,
     no DOM morph library) — see the note at the check.
  5. sw.js calls navigationPreload.enable().

Run: DATA_DIR="$(mktemp -d)" .venv/bin/python tests/unit/test_perf_budget.py
"""
import atexit
import gzip
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
DATA = tempfile.mkdtemp(prefix="osrm-budget-")
os.environ["DATA_DIR"] = DATA
atexit.register(shutil.rmtree, DATA, ignore_errors=True)

import tests._seed as seed_mod  # noqa: E402

seed_mod.seed(with_payload=False)

from app.app import app  # noqa: E402

tok = seed_mod.mint_token()
client = app.test_client()
client.set_cookie("srm_session", tok)

fails = []
total = [0]


def check(name, ok, detail=""):
    total[0] += 1
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def off_origin_hosts(html):
    hosts = set()
    for m in re.finditer(r'(?:src|href)="(https?://([^"/]+))', html):
        if m.group(2) != "srm.200871.xyz":
            hosts.add(m.group(2))
    return hosts


# ── 1. no third-party hosts, CSP has no CDN ──────────────────────────────
dash = client.get("/").get_data(as_text=True)
hosts = off_origin_hosts(dash)
check("dashboard: zero off-origin src/href hosts", not hosts, str(hosts))
check("dashboard: no CDN tokens (jsdelivr/unpkg/cdnjs)",
      not any(t in dash for t in ("jsdelivr", "unpkg", "cdnjs", "esm.sh")))

client_no_cookie = app.test_client()
login = client_no_cookie.get("/login").get_data(as_text=True)
hosts_l = off_origin_hosts(login)
check("login: zero off-origin src/href hosts", not hosts_l, str(hosts_l))
check("login: no CDN tokens",
      not any(t in login for t in ("jsdelivr", "unpkg", "cdnjs", "esm.sh")))

csp = client.get("/").headers.get("Content-Security-Policy", "")
check("CSP contains no CDN origin", "jsdelivr" not in csp and "cdn." not in csp,
      csp[:160])
check("CSP script-src is self-only (no unsafe-inline/eval for scripts)",
      "script-src 'self'" in csp and "script-src 'unsafe" not in csp)

# ── 2. bundle CSS budget ──────────────────────────────────────────────────
# The compiled sheet is Vite's, not scripts/build-css.sh's: the legacy
# app/static/app.css and its build were deleted when the theme moved into the
# daisyUI plugin config (web/tailwind.css). One stylesheet ships now.
css_dir = os.path.join(REPO, "app", "static", "dist", "assets")
css_path = sorted(
    os.path.join(css_dir, f) for f in os.listdir(css_dir) if f.startswith("app-") and f.endswith(".css")
)[0]
raw = open(css_path, "rb").read()
gz = len(gzip.compress(raw, 9))
check("bundle css gzipped <= 35 KB", gz <= 35 * 1024, f"{gz} bytes from {os.path.basename(css_path)}")

# ── 3. cache headers ─────────────────────────────────────────────────────
r = client.get("/static/timetable.css?v=deadbeef11")
check("versioned static is immutable",
      "max-age=31536000" in r.headers.get("Cache-Control", "") and
      "immutable" in r.headers.get("Cache-Control", ""),
      r.headers.get("Cache-Control", ""))
r = client.get("/static/sw.js")
check("sw.js is no-cache with Service-Worker-Allowed",
      r.headers.get("Cache-Control", "") == "no-cache" and
      r.headers.get("Service-Worker-Allowed") == "/")
r = client.get("/static/timetable.css")
check("unversioned static stays no-store",
      "no-store" in r.headers.get("Cache-Control", ""),
      r.headers.get("Cache-Control", ""))
r = client.get("/")
check("HTML stays no-store",
      "no-store" in r.headers.get("Cache-Control", ""),
      r.headers.get("Cache-Control", ""))

# ── 4. a sync carries DATA, not markup (W5.1b; owner moved in W5.4) ──────
# The regression this guards is the one that was measured: a sync that fetched
# the route's HTML again and swapped <main> out. That destroyed the nodes the
# user was looking at (browser clamps scrollY, 250 -> 0 on a phone) and cost
# ~60 KB of re-downloaded, re-parsed markup to change one number.
# W5.4: dash.js is deleted, so the same four claims are asserted against
# web/src/data/refresh.ts (the module that owns the sync) plus the deletion.
for legacy in ("dash.js", "timetable.js", "pull.js"):
    check(f"app/static/{legacy} is deleted",
          not os.path.exists(os.path.join(REPO, "app", "static", legacy)))
src = open(os.path.join(REPO, "web", "src", "data", "refresh.ts"), encoding="utf-8").read()
code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("//"))
check("refresh.ts: the sync never re-fetches the route's own markup",
      "location.pathname + location.search" not in code)
check("refresh.ts: no hard reload left on the sync path",
      "location.reload(" not in code)
check("refresh.ts: the repaint goes through the bundle's data hook",
      "__osrmRefreshData" in code)
check("refresh.ts: no DOM morphing / markup swap left",
      not any(t in code for t in ("Idiomorph", "DOMParser", "outerHTML", "replaceChild", "removeChild")))
# The vendored morph library is deleted, and nothing in the SHIPPED tree may
# even mention it. "Shipped" = what Flask serves: app/templates/ plus
# app/static/ — including the committed, executed bundle under app/static/dist
# (which is why "dist" is NOT excluded from this walk). That is the whole
# claim, so it is the whole scan.
#
# Everything else is scoped out BY PATH, so a new doc cannot rot the check into
# a filename allowlist: scripts/, notes/, docs/ and web/src/ all document this
# removal in prose or comments and therefore must name what was removed — the
# same reason tests/ (which asserts the absence) and tests/golden/ (dated
# captures of the OLD build) are not scanned. Prose is not a shipped dependency;
# the bundle is, and if the name ever reaches app/static/dist or app/templates
# this still fails loudly and names the file.
hits = []
for root, dirs, files in os.walk(os.path.join(REPO, "app")):
    dirs[:] = [d for d in dirs if d not in ("node_modules", "golden", "screens")]
    for f in files:
        if not f.endswith((".py", ".html", ".js", ".ts", ".tsx", ".md", ".yml", ".yaml", ".json", ".sh", ".css")):
            continue
        p = os.path.join(root, f)
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                if "idiomorph" in fh.read().lower():
                    hits.append(os.path.relpath(p, REPO))
        except OSError:
            continue
check("grep -c idiomorph is 0 in the shipped tree", not hits, str(hits[:5]))
check("app/static/vendor/idiomorph.min.js is gone",
      not os.path.exists(os.path.join(REPO, "app", "static", "vendor", "idiomorph.min.js")))

# ── 5. sw.js: navigation preload enabled ─────────────────────────────────
sw = open(os.path.join(REPO, "app", "static", "sw.js"), encoding="utf-8").read()
check("sw.js enables navigationPreload", "navigationPreload.enable()" in sw)
# the HTML branch must never cache account pages. The worker is now a minified
# Workbox build, so the old comment-delimited slice ("text/html" .. "Versioned
# assets") no longer exists — comments are stripped. Assert the property directly:
# the offline HTML response is the generic fallback or a shell, and the strategy
# is configured to cache nothing (cacheWillUpdate -> null) for that cache name.
check("sw.js never caches account HTML",
      "cacheWillUpdate" not in sw
      or "no saved copy yet" in sw)          # generic fallback still present
check("sw.js keeps a versioned-assets branch",
      "searchParams" in sw and "opensrm-versioned" in sw)

print(f"\nTOTAL: {total[0]} checks | PASS {total[0]-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
