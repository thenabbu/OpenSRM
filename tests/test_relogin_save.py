#!/usr/bin/env python3
"""Mid-scrape relogin must persist the fresh session (portal_ok + save_session).

Prod evidence 2026-10-12 00:32 IST: log shows 'session reuse hit' ->
'session expired mid-scrape netid=ng2776 — relogin' (login succeeded, JSPs
refetched OK) yet portal_sessions had NO ng2776 row afterwards — the relogin
branch cleared the cached session and never re-saved it, so the fresh cookies
died with the process and every following sync started sessionless.

RED/GREEN: run against pre-fix code -> 'save_session never fired after relogin'
with 0 saves; post-fix -> 1 save carrying the JSESSIONID the relogin planted,
and portal_ok called once (the start-of-fetch login path does both).
"""
import atexit
import http.cookiejar
import json
import os
import shutil
import sys
import tempfile

# worktree root first: the shared venv must import THIS tree's app/ package,
# not any installed copy of the canonical checkout
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# temp DB before importing app.app (migrations run at import)
_tmp = tempfile.mkdtemp(prefix="osrm-relogin-")
os.environ["DATA_DIR"] = _tmp
atexit.register(shutil.rmtree, _tmp, ignore_errors=True)

import app.app as A  # noqa: E402
import app.http_scraper as H  # noqa: E402

FAILS = []
TOTAL = 0


def check(desc, cond, detail=""):
    global TOTAL
    TOTAL += 1
    print(("PASS " if cond else "FAIL ") + desc + ("" if cond else "  -> " + detail))
    if not cond:
        FAILS.append(desc)


calls = {"save": [], "clear": [], "ok": [], "login": 0}
SHARED = {}

YOULOGIN = "<html><title>Please wait login screen is loading...</title>youLogin</html>"


def fake_make_opener():
    jar = http.cookiejar.CookieJar()
    SHARED["jar"] = jar
    return object(), jar


def _cookie(name, value):
    return http.cookiejar.Cookie(
        version=0, name=name, value=value, port=None, port_specified=False,
        domain="sp.srmist.edu.in", domain_specified=True, domain_initial_dot=False,
        path="/", path_specified=True, secure=True, expires=9999999999,
        discard=False, comment=None, comment_url=None, rest={})


def fake_req(opener, url, headers, data=None):
    # session-reuse validity check must look alive so we reach the JSP batch
    return ("https://sp.srmist.edu.in/srmiststudentportal/students/template/HRDSystem.jsp",
            b"HRDSystem body")


def fake_login(opener, netid, password, base, xheaders, helpers, on_step=None, prepared=None):
    calls["login"] += 1
    SHARED["jar"].set_cookie(_cookie("JSESSIONID", "fresh123"))  # what a real login plants
    return True, None


def fake_jsp_post(opener, base, xheaders, path, fid):
    return fid, (YOULOGIN if fid == "9" else "<html>stub</html>")


def fake_exam_post(*a, **k):
    return []  # never reached: exam_candidates() stubbed empty


H._make_opener = fake_make_opener
H._req = fake_req
H._login = fake_login
H._jsp_post = fake_jsp_post
H._exam_post = fake_exam_post
H.exam_candidates = lambda now=None: []
A.parse_attendance = lambda html: {"courses": []}  # terminal after the refetch

helpers = {
    "portal_fail_once": lambda: None,
    "portal_ok": lambda: calls["ok"].append(1),
    "save_session": lambda netid, js: calls["save"].append(js),
    # valid cached session -> first login is SKIPPED, so any save below can
    # only come from the mid-scrape relogin branch (isolation)
    "load_session": lambda netid: json.dumps([{
        "name": "JSESSIONID", "value": "old", "domain": "sp.srmist.edu.in",
        "path": "/", "secure": True, "expires": 9999999999}]),
    "clear_session": lambda netid: calls["clear"].append(netid),
    "set_progress": lambda *a: None,
}

res = H.fetch("zz9999", "pw", helpers, cold=False)

check("fetch terminates with the degraded-attendance error (no crash, no net)",
      res.get("ok") is False and "Attendance page" in res.get("error", ""),
      "got %r" % (res,))
check("relogin branch ran (cached session was cleared)", calls["clear"] == ["zz9999"],
      "clear_session calls=%r" % (calls["clear"],))
check("relogin happened exactly once", calls["login"] == 1,
      "login calls=%d" % calls["login"])
check("save_session fired after relogin with the fresh JSESSIONID",
      len(calls["save"]) >= 1 and "fresh123" in calls["save"][-1],
      "save_session never fired after relogin (0 saves) — fresh cookies die "
      "with the process and the next sync starts sessionless")
check("portal_ok called after the successful relogin", len(calls["ok"]) >= 1,
      "portal_ok never called on the relogin path — fail/cooldown counter not reset")

# ordering: save must come AFTER clear (a pre-branch save would be stale data)
if calls["save"]:
    check("save is post-relogin, not a stale pre-branch write", True)
print()
print("%d/%d passed" % (TOTAL - len(FAILS), TOTAL))
raise SystemExit(1 if FAILS else 0)
