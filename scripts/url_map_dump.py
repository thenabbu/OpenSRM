#!/usr/bin/env python3
"""Dump the canonical url_map: rule|methods|endpoint|view, sorted.

Route-refactor proof tool: dump on two trees (e.g. origin/main and a
branch) and `diff` the outputs — an empty diff means paths, methods,
endpoint names and view functions are all unchanged. The blueprint split
(PR #68) used it to prove the refactor was URL-neutral.

Usage (from the repo root, with the target tree's DATA_DIR set inline):
    DATA_DIR=/tmp/x .venv/bin/python scripts/url_map_dump.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.app as A  # noqa: E402  (sys.path + DATA_DIR must be set first)

for r in sorted(A.app.url_map.iter_rules(),
                key=lambda r: (r.rule, str(sorted(r.methods)), r.endpoint)):
    v = A.app.view_functions.get(r.endpoint)
    print("%s|%s|%s|%s" % (r.rule, ",".join(sorted(r.methods)),
                           r.endpoint, getattr(v, "__name__", "-")))
