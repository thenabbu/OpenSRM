"""Unit: class tokens that only exist AFTER render must exist in the
compiled app.css. Tailwind's scanner reads source files, so families
assembled in Jinja (home.html LAYOUT loop -> col-span / row-span /
grid-cols / max-h cap) or Python (_BAND_BAR -> progress band) live in
app/static/safelist/classes.html (DESIGN §2.6 / §10.16). If LAYOUT or
_BAND_BAR gains a value nobody safelists, THIS suite fails — the render
proves what actually ships.

Also pins the wiring: the rendered page links the COMPILED stylesheet the
browser actually downloads and runs no CDN origin (DESIGN §10.16 rule 1). Since
the preact migration that sheet is the Vite bundle (web/tailwind.css is a verbatim
mirror of app/static/src.css plus `@source ./src`, i.e. a superset), and the
legacy /static/app.css is deliberately NOT linked a second time — two copies of
the same 27 KB-gz sheet on every route. The token assertions below therefore read
the sheet the page names, not a fixed filename.

Run: DATA_DIR="$(mktemp -d)" .venv/bin/python tests/unit/test_css_safelist.py
"""
import atexit
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
# P3.1: the panels are separate routes now, so the dynamic tokens that used to
# all live on "/" are spread across them. Scan the routes that render them:
# "/" carries the LAYOUT grid spans, "/attendance" the progress bands.
resp = client.get("/")
html = resp.get_data(as_text=True)
for _route in ("/attendance", "/marks"):
    html += "\n" + client.get(_route).get_data(as_text=True)

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
linked = re.findall(r'href="(/static/dist/assets/app-[A-Za-z0-9_-]+\.css)[^"]*"', html)
check("the compiled bundle stylesheet is linked", len(set(linked)) == 1 and len(linked) == 3,
      [l for l in html.splitlines() if ".css" in l][:2])
check("the legacy app.css is NOT linked as well (one copy, not two)",
      "app.css?v=" not in html,
      [l for l in html.splitlines() if "app.css" in l][:1])
check("no CDN origin in rendered page", "jsdelivr" not in html)

# ── every rendered dynamic-family token must be in the linked sheet ──────
css_path = os.path.join(REPO, "app", "static", linked[0][len("/static/"):]) if linked \
    else os.path.join(REPO, "app", "static", "dist", "assets")
check("linked stylesheet exists on disk", os.path.isfile(css_path), css_path)
css = open(css_path, encoding="utf-8").read()
# CSS escapes selector metachars (lg:col-span-8 -> lg\:col-span-8) and
# digit-leading names with a hex escape (.2xl\:grid-cols-3 -> .\32 xl\:...):
# resolve both before the flat comparison, or a `2xl:` token can never match.
css_flat = re.sub(r"\\([0-9a-fA-F]{1,6})\s?", lambda m: chr(int(m.group(1), 16)), css)
css_flat = css_flat.replace("\\", "")

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
check(f"all {len(tokens)} dynamic tokens exist in the linked stylesheet",
      not missing, f"missing={missing}")

# safelist file itself is present (the future-agent discovery point)
check("safelist file committed", os.path.isfile(
    os.path.join(REPO, "app", "static", "safelist", "classes.html")))

# ── W5.4: classes the BUNDLE writes at runtime ────────────────────────────
# These used to reach app.css only because app/static/dash.js and timetable.js
# spelled the same literals; both files are deleted. They stay safelisted and
# pinned here: W7.3b added `@source "../../web/src"` to both CSS entries, but a
# safelist entry is what keeps a *runtime-interpolated* class (one the scanner
# cannot see as a literal) alive, so dropping one is still a silent regression.
# Web/src literal classes are covered by scripts/check_css_classes.py.
RUNTIME = ("alert-warning", "rounded-none", "text-success", "animate-spin",
           "ml-1", "last:border-b-0", "space-y-0.5")
rt_missing = [t for t in RUNTIME if t not in css_flat]
check(f"all {len(RUNTIME)} runtime-written classes exist in the linked stylesheet",
      not rt_missing, f"missing={rt_missing}")

print(f"\n{total[0] - len(fails)}/{total[0]} passed")
if fails:
    print("FAILED:", ", ".join(fails))
    sys.exit(1)
print("ok test_css_safelist")
