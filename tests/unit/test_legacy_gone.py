"""Unit: the hybrid is GONE, not merely unreferenced (W5.5's grep gate).

The plan's wording is "no dash.js|timetable.js|idiomorph|softRefresh outside
notes/docs". Taken literally that gate cannot pass and should not: after the
deletion the names survive in three legitimate places, and all three are the
record of the deletion rather than a use of it.

  * `web/src/**` -- ~30 provenance comments ("ported out of dash.js:165-185")
    that explain WHY each module exists. Deleting them deletes the reason.
  * `tests/` and `tests/golden/v2` -- the suites assert the absence (that is
    their job) and v2 is a dated capture of the OLD build: an artefact, not
    code. v3 carries none of these names.
  * `notes/` and `docs/` -- the mission's decision log.

So this gate is scoped on LIVE REFERENCES, not on the token:

  1. no `<script>`/URL reference to dash.js or timetable.js in the SERVED tree
     (`app/templates/` + `app/static/`, including the committed bundle under
     `app/static/dist`). That tree is the whole claim: if the name cannot reach
     a browser from it, there is no hybrid left.
  2. no dash.js/timetable.js entry in the workbox precache -- neither in
     `web/workbox-config.js`'s globs nor in the BUILT `app/static/sw.js`. A
     precache entry would serve a deleted file forever and make the removal
     look complete while the worker still hands it out.
  3. no `softRefresh(` call site and no `window.softRefresh` assignment, in the
     served tree or in `web/src` (tests excluded -- they assert its absence).
     The call form is checked, not the bare word, because `softRefresh()` also
     appears in prose describing the call that was removed.
  4. `idiomorph` absent from the served tree, case-insensitive -- same
     semantics as the existing check in test_perf_budget.py, kept here as well
     so all four names are answered by one gate. `test_perf_budget.py` also
     proves the vendored FILE is gone; this file proves the NAME is unusable.
  5. the three files themselves do not exist on disk.
  6. POSITIVE CONTROL on the substring trap: `timetable.json` is a LIVE legacy
     data file (imported by `app/app.py`, named in `entrypoint.sh`) whose name
     starts with `timetable.js`. A naive pattern flags that import as a legacy
     JS reference. The pattern is word-bounded for exactly this reason, and the
     control below fails if anyone loosens it back.

Break-proved the honest way: re-adding `<script defer src="{{ asset('dash.js')
}}">` to a template turns check 1 red, and putting the bare word in a comment
does not -- which is the distinction this file exists to keep.

Run: DATA_DIR="$(mktemp -d)" .venv/bin/python tests/unit/test_legacy_gone.py
"""
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
DATA = tempfile.mkdtemp(prefix="osrm-legacy-")
os.environ["DATA_DIR"] = DATA
import atexit  # noqa: E402

atexit.register(shutil.rmtree, DATA, ignore_errors=True)

TEXT_EXT = (".py", ".html", ".js", ".ts", ".tsx", ".css", ".json", ".sh", ".md",
            ".yml", ".yaml", ".txt", ".jsx")

fails = []
total = [0]


def check(name, ok, detail=""):
    total[0] += 1
    # detail is a failure explanation, never decoration: a passing line that
    # also prints "[]" reads as a warning and trains the reader to skip it.
    print(("PASS " if ok else "FAIL ") + name + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def walk(roots, skip=()):
    """Yield (relpath, text) for every text file under `roots`, sorted."""
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(os.path.join(REPO, root)):
            dirnames[:] = sorted(d for d in dirnames if d not in skip)
            for f in sorted(filenames):
                if not f.endswith(TEXT_EXT):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    with open(p, encoding="utf-8", errors="ignore") as fh:
                        yield os.path.relpath(p, REPO), fh.read()
                except OSError:
                    continue


# ── the patterns ───────────────────────────────────────────────────────────
# `\b` after `.js` is load-bearing: timetable.json and timetable.js.map both
# start with timetable.js and neither is a legacy JS reference. Check 6 asserts
# that this boundary still holds against a real timetable.json in the tree.
LEGACY_JS = re.compile(r"(?:dash|timetable)\.js\b", re.I)
# In a JS/CSS/JSON file the name can only be LIVE inside a string literal (a
# script tag does not exist there, and prose does not carry quotes around it).
QUOTED_REF = re.compile(r"""["'][^"'\n]*(?:dash|timetable)\.js[^"'\n]*["']""", re.I)
# Jinja {# #} and HTML <!-- --> are how a template documents a decision. Two
# comments in this tree name dash.js on purpose, explaining the load order and
# the Tailwind safelist they protect -- deleting the name would delete the
# reason. Comments are stripped for the HTML pass only: a script tag cannot
# live inside one, so this cannot hide a real reference.
JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
SOFTREFRESH_LIVE = re.compile(r"(?:\bsoftRefresh\s*\(|window\.softRefresh\b"
                              r"|\bsoftRefresh\s*=\s*function|\.softRefresh\s*=)")
SERVED = ("app/templates", "app/static")


def code_only(rel, text):
    """The file with its prose comments removed; JS line comments are left
    alone (a minified bundle is one line, and stripping `//` would cut it short
    at the first URL and could hide a real reference behind that point)."""
    if rel.endswith(".html"):
        return HTML_COMMENT.sub("", JINJA_COMMENT.sub("", text))
    return text


# ── 1. the served tree carries no reference to a deleted script ────────────
hits = []
for rel, text in walk(SERVED, skip=("node_modules",)):
    stripped = code_only(rel, text)
    pat = LEGACY_JS if rel.endswith(".html") else QUOTED_REF
    for m in pat.finditer(stripped):
        hits.append(f"{rel}: {m.group(0)[:60]}")
check("no script/asset()/quoted path names dash.js or timetable.js in the served tree",
      not hits, "; ".join(sorted(set(hits))[:5]))

# ── 2. the workbox precache names neither ─────────────────────────────────
precache = []
for rel in ("web/workbox-config.js", "app/static/sw.js"):
    p = os.path.join(REPO, rel)
    if not os.path.exists(p):
        precache.append(f"{rel} is MISSING -- the precache can never be asserted")
        continue
    with open(p, encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    # Quoted strings only: a precache entry is always a string literal, while
    # workbox-config.js:73 names dash.js in prose explaining format:'iife'.
    # That comment is the reason the worker is a classic script; deleting it
    # with the name would delete the reason.
    for m in re.finditer(r"[\"'][^\"'\n]*(?:dash|timetable)\.js[^\"'\n]*[\"']", text):
        precache.append(f"{rel}: {m.group(0)[:60]}")
check("workbox precache names neither dash.js nor timetable.js",
      not precache, "; ".join(precache[:5]))

# ── 3. no softRefresh call site left ──────────────────────────────────────
soft = []
for rel, text in walk(SERVED + ("web/src",), skip=("node_modules",)):
    if ".test." in rel or rel.endswith(".test.tsx"):
        continue          # these assert the removal, by name, on purpose
    for m in SOFTREFRESH_LIVE.finditer(text):
        soft.append(f"{rel}: {m.group(0)[:40]}")
check("no softRefresh() call site or window.softRefresh assignment",
      not soft, "; ".join(soft[:5]))

# ── 4. idiomorph is unmentionable in the served tree ──────────────────────
morph = [rel for rel, text in walk(SERVED, skip=("node_modules",))
         if "idiomorph" in text.lower()]
check("idiomorph absent from the served tree", not morph, str(morph[:5]))

# ── 5. the deleted files are still deleted ────────────────────────────────
gone = [p for p in ("app/static/dash.js", "app/static/timetable.js",
                    "app/static/vendor/idiomorph.min.js")
        if os.path.exists(os.path.join(REPO, p))]
check("dash.js, timetable.js and the vendored morph library do not exist",
      not gone, str(gone))

# ── 6. positive control: the word boundary still excludes timetable.json ──
# If someone "fixes" a future false positive by loosening the regex, this goes
# red before the loosening can hide a real reference.
app_py = os.path.join(REPO, "app", "app.py")
legit = open(app_py, encoding="utf-8", errors="ignore").read() if os.path.exists(app_py) else ""
control = "timetable.json" in legit
check("positive control: timetable.json is still a live reference in app/app.py",
      control, "app/app.py no longer mentions it -- re-point this control")
check("the timetable pattern does NOT match timetable.json",
      LEGACY_JS.search("load('timetable.json')") is None,
      f"matched {LEGACY_JS.search('load(timetable.json)')}")

print(f"\nTOTAL: {total[0]} checks | PASS {total[0]-len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
