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
    """Versioned /static/dist/ URL for the Vite build.

    `name` is the Vite import name ('app' -> JS entry, 'app.css' -> the CSS the
    entry imports); the hashed filename comes from .vite/manifest.json. Returns
    '' when dist/ is absent so a checkout without a build still renders (the
    page then runs on the legacy scripts alone — progressive enhancement).
    """
    path = os.path.join(_STATIC_DIR, "dist", ".vite", "manifest.json")
    try:
        with open(path, "rb") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return ""
    entry = manifest.get("src/main.ts") or {}
    if name == "app.css":
        files = entry.get("css") or []
    else:
        files = [entry["file"]] if entry.get("file") else []
    if not files:
        return ""
    return _versioned("dist/" + files[0])
