"""Unit: perf-budget guardrails (phase 8 of the smoothness campaign).

Static contracts that keep the earlier phases fixed:
  1. dashboard + login HTML reference no third-party hosts; CSP has no CDN.
  2. app.css gzipped <= 35 KB.
  3. versioned static = immutable; sw.js = no-cache + Service-Worker-Allowed;
     HTML = no-store.
  4. dash.js: location.reload() only inside the softRefresh catch net.
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

# ── 2. app.css budget ─────────────────────────────────────────────────────
css_path = os.path.join(REPO, "app", "static", "app.css")
raw = open(css_path, "rb").read()
gz = len(gzip.compress(raw, 9))
check("app.css gzipped <= 35 KB", gz <= 35 * 1024, f"{gz} bytes")

# ── 3. cache headers ─────────────────────────────────────────────────────
r = client.get("/static/dash.js?v=deadbeef11")
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

# ── 4. dash.js: location.reload only inside softRefresh ──────────────────
src = open(os.path.join(REPO, "app", "static", "dash.js"), encoding="utf-8").read()
code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("//"))
start = code.index("function softRefresh")
end = code.index("function ref(quiet)", start)
reloads = [m for m in range(len(code)) if code.startswith("location.reload()", m)]
inside = [m for m in reloads if start < m < end]
check("dash.js: location.reload only inside softRefresh (2 sites)",
      len(reloads) == 2 and len(inside) == 2,
      f"{len(reloads)} total, {len(inside)} inside")

# ── 5. sw.js: navigation preload enabled ─────────────────────────────────
sw = open(os.path.join(REPO, "app", "static", "sw.js"), encoding="utf-8").read()
check("sw.js enables navigationPreload", "navigationPreload.enable()" in sw)
# the HTML branch (accept: text/html) must never touch the caches — account
# pages are network-only with the generic offline fallback (audit decision)
html_branch = sw[sw.index("text/html"):sw.index("Versioned assets")]
check("sw.js never caches account HTML",
      "caches." not in html_branch and "cache.put" not in html_branch)
check("sw.js cache-first branch exists for versioned assets",
      "searchParams.get('v')" in sw)

print(f"\nTOTAL: {total[0]} checks | PASS {total[0]-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
