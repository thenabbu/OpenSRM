"""The /logout handler must clear EVERY cache, not just the current one.

Why this exists: the worker's logout route originally did
`caches.delete(CACHE_NAME)` only. The offline shells live in 'opensrm-shell'
and the assets in 'workbox-precache-*', so a logged-out device kept both and
could load the app's panels offline. "Logout leaves no trace" was false.

This reads the built worker. It is a source assertion on purpose: the runtime
behaviour needs a live server + a real browser across a process boundary, which
scripts/offline_proof.sh already covers. Keep this one cheap and always-on.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SW = REPO / "app" / "static" / "sw.js"

fails = []


def check(name, cond, detail=""):
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}{(' — ' + detail) if detail else ''}")
        fails.append(name)


def main():
    if not SW.exists():
        print(f"  [FAIL] {SW} missing — run the web build")
        return 1
    src = SW.read_text(encoding="utf-8")

    # Isolate the logout route. Minified, terser emits the comparison with the
    # literal FIRST: `P(({url:e})=>"/logout"===e.pathname, async(...)=>{...})`.
    # Requiring `pathname === '/logout'` missed it entirely, which would have
    # made every assertion below vacuously pass on an empty body.
    m = re.search(r"""['"]/logout['"]\s*===\s*\w+\.pathname(.{0,900})""", src, re.S)
    check("worker has a /logout route", m is not None)
    body = m.group(1) if m else ""

    # The fix: it must iterate caches.keys() and delete each one.
    check(
        "logout clears every cache (iterates caches.keys())",
        "caches.keys()" in body,
        "found only a single-cache delete — shells and precache survive logout",
    )
    check(
        "logout does not delete only CACHE_NAME",
        not re.search(r"caches\.delete\(\s*CACHE_NAME\s*\)", body),
        "reverted to the single-cache delete",
    )

    # Positive control: the shell cache name must exist somewhere in the worker,
    # otherwise "every cache" is trivially true because there is only one.
    check(
        "control: 'opensrm-shell' exists in the worker at all",
        "opensrm-shell" in src,
        "if the shell cache is gone the assertion above proves nothing",
    )

    print(f"\nRESULT: {'PASS' if not fails else 'FAIL'} — {len(fails)} failed")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
