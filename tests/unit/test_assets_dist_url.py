#!/usr/bin/env python3
"""The dist entry must be served at the URL its own chunks import (P7.6).

Vite emits island chunks importing the shared entry RELATIVELY:

    import{n as e}from"./app-<hash>.js"

`theme.html` emits `<script type="module" src="{{ asset_dist('app') }}">`. If
that URL carries anything the chunk's does not, the browser holds TWO module-map
keys for ONE file and evaluates the body twice: two Preact instances, and
`mountBounded` called twice on the same mount node. Measured in a real browser,
the first call painted 8 rows and the second reconciled them away to 0 —
`[FAIL] online: island painted rows — 0 rows`.

docs/audit/p76-island-zero-rows.md has the trace. The assertion that matters is
the third one: it reads the emitted chunks and compares the specifier they use
against the URL the page is told to load.
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from app.assets_dist import _STATIC_DIR, asset_dist  # noqa: E402

DIST = os.path.join(_STATIC_DIR, "dist")
PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def main():
    if not os.path.exists(os.path.join(DIST, "manifest.json")):
        print("  [SKIP] no dist/ in this checkout — nothing to check")
        return 0

    with open(os.path.join(DIST, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    entry = manifest.get("src/main.ts") or {}
    entry_file = entry.get("file")
    entry_base = os.path.basename(entry_file or "")   # manifest carries 'assets/' ; the dir listing does not

    print("\n-- the served entry URL --")
    served = asset_dist("app")
    chk("entry URL is the bare manifest file",
        served == "/static/dist/" + (entry_file or ""), f"got {served!r}")
    chk("entry URL carries no query string (a query splits the module map)",
        "?" not in served, served)

    print("\n-- every chunk import resolves to that same URL --")
    specs = set()
    assets = os.path.join(DIST, "assets")
    for fn in sorted(os.listdir(assets)):
        if not fn.endswith(".js") or fn == entry_base:
            continue
        with open(os.path.join(assets, fn), encoding="utf-8") as fh:
            body = fh.read()
        for m in re.finditer(r'from"\./(%s)"' % re.escape(entry_base), body):
            specs.add((fn, m.group(1)))
    chk("at least one chunk imports the entry (the build shape is unchanged)",
        bool(specs), "no chunk imports the entry")
    mismatched = [(fn, s) for fn, s in specs
                  if "/static/dist/assets/" + s != served]
    chk("no chunk imports the entry under a DIFFERENT key than the page loads",
        not mismatched,
        f"{len(mismatched)} chunk(s) e.g. {mismatched[:2]} vs served {served!r}")

    print("\n-- the stylesheet keeps its ?v= cache key --")
    css = entry.get("css") or []
    if css:
        url = asset_dist("app.css")
        chk("app.css is versioned", url.startswith("/static/dist/" + css[0] + "?v="), url)
    else:
        print("  [SKIP] entry declares no CSS")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
