"""Gunicorn entrypoint for tests/test_canary_sync.py: the REAL app with the
portal fetch stubbed by netid, so the canary runs its one sync offline.

  zz9999 -> full payload (attendance + marks land in the DB)
  zz9997 -> ok=True but EMPTY attendance/marks (the "portal changed, parse
            returned nothing" arm: sync succeeds, the canary must still fail)
"""
import os
import sys
import time

# worktree root first: this file is imported by gunicorn from the repo cwd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as A          # noqa: E402  (migrations run at import)
from app import http_scraper as H  # noqa: E402

_EMPTY = {"courses": [], "monthly": [], "period": None, "daily_absent": {}}
_FULL = {"courses": [{"code": "TEST101", "name": "Canary Subject"}],
         "monthly": [], "period": None, "daily_absent": {}}


def _stub_fetch(netid, password, helpers, cold=True, prepared=None, deadline=None):
    now = int(time.time())
    if netid == "zz9997":
        return {"ok": True, "data": dict(_EMPTY), "personal": {}, "courses": [],
                "marks": [], "subjects": {}, "fetched": now}
    return {"ok": True, "data": dict(_FULL), "personal": {},
            "courses": [{"code": "TEST101", "name": "Canary Subject", "credits": 3}],
            "marks": [{"code": "TEST101", "name": "Canary Subject",
                       "components": [], "scored_total": 0, "max_total": 0}],
            "subjects": {}, "fetched": now}


H.fetch = _stub_fetch

app = A.app
