#!/usr/bin/env python3
"""W7.5-1 — no HTML is precached, plus the worker's two source invariants.

W7.5-1: the workbox precache manifest must hold no page markup. The rule is
"page markup never sits in a cache", so the test is wider than ``*.html``: a
precached ``/`` or ``/dashboard`` is page markup too, and extension-less entries
are exactly how a route would sneak in. The offline path serves
``/shell/<panel>`` instead, which is rendered with every personal value blanked.

Two invariants pinned here because each is one edit away from being lost and
neither shows up as a red browser run:
  * the ``push`` handler still exists (W7.5-5),
  * ``skipWaiting()`` is guarded by ``registration.active === null`` (W7.3c) —
    unconditional skipWaiting swaps JS under a live page. This is also the
    source-level half of W7.5-3: it is what makes the browser leg measure the
    cache rather than the swap's own forced reload.

Run: python tests/unit/test_sw_precache_no_html.py
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SW = REPO / "app" / "static" / "sw.js"

# Terser may emit either operand order; both sides optional-space.
GUARD = re.compile(
    r"(?:null\s*===?\s*self\.registration\.active"
    r"|self\.registration\.active\s*===?\s*null)\s*&&\s*self\.skipWaiting\(\)")
UNGUARDED = re.compile(r'addEventListener\("install",\s*\(\)\s*=>\s*\{?\s*self\.skipWaiting\(\)')


def manifest(src):
    """The injected Workbox manifest array, as JSON.

    The built worker is minified, so ``precacheAndRoute`` is not spelled out
    (measured: ``L().precache(e)``). Anchor on the data instead and bracket-
    match it — that survives any re-minification.
    """
    start = src.find('[{"revision"')
    if start < 0:
        raise SystemExit("[FAIL] no injected precache manifest found in sw.js")
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "[":
            depth += 1
        elif src[i] == "]":
            depth -= 1
            if depth == 0:
                return json.loads(src[start:i + 1])
    raise SystemExit("[FAIL] the precache manifest array is unbalanced")


def main() -> int:
    if not SW.exists():
        print(f"[FAIL] {SW} missing — run `node workbox-config.js`")
        return 1
    src = SW.read_text(encoding="utf-8")
    urls = [e["url"] for e in manifest(src)]
    if not urls:
        print("[FAIL] precache manifest is empty")
        return 1

    markup = [u for u in urls if Path(u).suffix in ("", ".html", ".htm")]
    if markup:
        print(f"[FAIL] page markup is precached: {markup}")
        return 1

    entry = [u for u in urls if re.match(r"/static/dist/assets/app-[\w-]+\.js$", u)]
    if not entry:
        print("[FAIL] positive control missing: no app-*.js in the precache")
        return 1

    if 'addEventListener("push"' not in src:
        print("[FAIL] the worker has lost its push handler (W7.5-5)")
        return 1
    if UNGUARDED.search(src) or not GUARD.search(src):
        print("[FAIL] skipWaiting() is not guarded to a first install (W7.3c)")
        return 1

    print(f"[PASS] {len(urls)} precache entries, 0 page markup, entry {entry[0]}; "
          "push handler present; skipWaiting guarded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
