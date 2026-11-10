"""Versioned URLs for the Vite build in app/static/dist/.

Split out of app.py so the app module stays under its line budget
(scripts/check_architecture.py). Pure path/dict work — no Flask, no import
of app.app (which imports this module), so there is no cycle.
"""
import hashlib
import json
import os

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _versioned(rel):
    """`/static/<rel>?v=<sha256[:10]>` — same scheme as app.asset()."""
    path = os.path.join(_STATIC_DIR, rel)
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()[:10]
    return "/static/%s?v=%s" % (rel, digest)


def asset_dist(name):
    """Served /static/dist/ URL for the Vite build.

    `name` is the Vite import name ('app' -> JS entry, 'app.css' -> the CSS the
    entry imports); the hashed filename comes from dist/manifest.json. Returns
    '' when dist/ is absent so a checkout without a build still renders (the
    page then runs on the legacy scripts alone — progressive enhancement).

    The JS entry is NOT `?v=`-versioned, and that is load-bearing. Every island
    chunk imports the entry RELATIVELY (`import … from "./app-<hash>.js"`), so a
    query string here gives the browser two module-map keys for one file: the
    body evaluated twice, two Preact instances, and `mountBounded` called twice
    on the same mount node — the second render reconciled the first tree away
    and left 0 rows (P7.6, docs/audit/p76-island-zero-rows.md). The filename is
    already content-hashed, so `?v=` buys nothing; CSS keeps it because a
    stylesheet has no module map to split.
    """
    path = os.path.join(_STATIC_DIR, "dist", "manifest.json")
    try:
        with open(path, "rb") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return ""
    entry = manifest.get("src/main.ts") or {}
    if name == "app.css":
        files = entry.get("css") or []
        return _versioned("dist/" + files[0]) if files else ""
    if not entry.get("file"):
        return ""
    return "/static/dist/" + entry["file"]
