"""Unit: class tokens that only exist AFTER render must exist in the
compiled app.css. Tailwind's scanner reads source files, so families
assembled in Jinja (dashboard.html LAYOUT loop -> col-span / row-span /
grid-cols / max-h cap) or Python (_BAND_BAR -> progress band) live in
app/static/safelist/classes.html (DESIGN §2.6 / §10.16). If LAYOUT or
_BAND_BAR gains a value nobody safelists, THIS suite fails — the render
proves what actually ships.

Also pins the wiring: the rendered page links asset('app.css'), never a
CDN origin (DESIGN §10.16 rule 1).

Run: DATA_DIR="$(mktemp -d)" .venv/bin/python tests/test_css_safelist.py
"""
import atexit
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
DATA = tempfile.mkdtemp(prefix="osrm-csssync-")
os.environ["DATA_DIR"] = DATA
atexit.register(shutil.rmtree, DATA, ignore_errors=True)

import tests._seed as seed_mod  # noqa: E402

seed_mod.seed_rich()  # every LAYOUT card + band bar must render

from app.app import app  # noqa: E402

tok = seed_mod.mint_token()
client = app.test_client()
client.set_cookie("srm_session", tok)
resp = client.get("/")
html = resp.get_data(as_text=True)

fails = []
total = [0]


def check(name, ok, detail=""):
    total[0] += 1
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


# ── wiring: compiled CSS linked, CDN gone ────────────────────────────────
check("dashboard rendered", resp.status_code == 200 and "zz9999" in html,
      f"status={resp.status_code}")
check("asset('app.css') linked (versioned)", "app.css?v=" in html,
      [l for l in html.splitlines() if "app.css" in l][:1])
check("no CDN origin in rendered page", "jsdelivr" not in html)

# ── every rendered dynamic-family token must be in app.css ──────────────
css = open(os.path.join(REPO, "app", "static", "app.css"), encoding="utf-8").read()
# CSS escapes selector metachars (lg:col-span-8 -> lg\:col-span-8): compare flat
css_flat = css.replace("\\", "")

FAMILIES = ("col-span", "row-span", "grid-cols", "progress-", "max-h-")
tokens = set()
for m in re.finditer(r'class="([^"]*)"', html):
    for t in m.group(1).split():
        if any(f in t for f in FAMILIES):
            tokens.add(t)

# non-vacuous: the seed must render the known dynamic values at all
for must in ("lg:col-span-8", "lg:row-span-2",
             "lg:max-h-[calc((100dvh-94px)*0.65)]", "sm:grid-cols-2"):
    check(f"rendered: {must}", must in tokens or must in html.split(), f"tokens={sorted(tokens)}")
check("rendered: a progress band", any(t.startswith("progress-") for t in tokens),
      sorted(t for t in tokens if t.startswith("progress-")))

missing = sorted(t for t in tokens if t not in css_flat)
check(f"all {len(tokens)} dynamic tokens exist in app.css", not missing, f"missing={missing}")

# safelist file itself is present (the future-agent discovery point)
check("safelist file committed", os.path.isfile(
    os.path.join(REPO, "app", "static", "safelist", "classes.html")))

print(f"\n{total[0] - len(fails)}/{total[0]} passed")
if fails:
    print("FAILED:", ", ".join(fails))
    sys.exit(1)
print("ok test_css_safelist")
