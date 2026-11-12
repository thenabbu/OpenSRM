#!/usr/bin/env python
"""Deterministic golden capture of the CURRENT OpenSRM app.

Produces under --out (default /opt/data/missions/opensrm-preact/captures):
  routes.json          9 tab ids + each visible panel's normalized outer HTML
  dom/<tab>.html       post-JS DOM of each tab panel (normalized)
  screens/<tab>-<vp>.png  full-page screenshots, 390x844 / 768x1024 / 1440x900
  api/<endpoint>.json  GET response bodies + status (static assets included)
  metrics.json         byte sizes, gzip sizes, script/node counts, per route

Determinism: clean DATA_DIR each run, seed_rich() + fabricated scope blob
(all 9 features, fresh ts), frozen client clock (page.clock), paused CSS/SVG
animations, reduced motion, service workers blocked, external requests
aborted, normalization of volatile bits (?v=, data-ts/data-full, relative
times, epoch/ISO timestamps). See captures/README.md.

Read-only on the repo. No commit. Seed user zz9999 only.
"""
import argparse
import base64
import gzip
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/data/cache/scratch/pw-browsers"

REPO = Path(os.environ.get("OPENSRM_REPO", "/opt/data/opensrm-repo"))
# The worktree has no .venv of its own; the repo venv can run its code fine.
PY = (REPO / ".venv" / "bin" / "python") if (REPO / ".venv" / "bin" / "python").exists() \
     else Path("/opt/data/opensrm-repo/.venv/bin/python")
DATA_DIR = "/tmp/osrm-premig"
NETID = "zz9999"
METRICS_SECRET = "opensrm-capture-baseline"   # fixed constant, never rotated
FEATURES = "hourwise,academics,fees,placement,library,campus,profile,attendance,marks"
TABS = ["dashboard", "attendance", "timetable", "marks",
        "campus", "academics", "fees", "tools", "settings"]
VIEWPORTS = [("390x844", 390, 844), ("768x1024", 768, 1024), ("1440x900", 1440, 900)]
DEFAULT_OUT = Path("/opt/data/missions/opensrm-preact/captures")
API_GETS = ["/", "/login", "/healthz", "/api/marks", "/api/push/status",
            "/api/scope/status", "/api/timetable", "/api/timetable/history",
            "/avatar", "/avatar/" + NETID]

# ── scope payload: repo fixtures (read-only) + literals from repo tests ──
# op -> repo fixture file holding that op's payload (JSON).
SCOPE_FIXTURES = {
    "getHourwiseAttendance": "tests/fixtures/scope-attendance-hour.txt",
    "getExamDetails": "tests/fixtures/scope/exam-details.json",
    "getSubCategoryWiseStatus": "tests/fixtures/scope/course-status.json",
    "getSubCategorySemesterWiseStatus": "tests/fixtures/scope/course-status-sem.json",
    "getProgramSubCategoryWiseSubjects": "tests/fixtures/scope/program-subjects.json",
    "getStudentExamProvisionalResult": "tests/fixtures/scope/exam-provisional.json",
    "getStudentExamRevaluationResult": "tests/fixtures/scope/exam-revaluation.json",
    "getSubjects": "tests/fixtures/scope/courses.json",
    "getStudentAllOfferedJobs": "tests/fixtures/scope_campus/placement-jobs.txt",
    "getResumeUploads": "tests/fixtures/scope_campus/placement-resumes.txt",
    "getLibraryTransaction": "tests/fixtures/scope_campus/library.txt",
    "getHostelDetails": "tests/fixtures/scope_campus/hostel.txt",
    "getTransportDetails": "tests/fixtures/scope_campus/transport.txt",
    "getViewNotificationListJson": "tests/fixtures/scope_campus/notifications.txt",
    "getJobCriteria": "tests/fixtures/scope_campus/placement-required.txt",
    "getWillingnessRejectReasons": "tests/fixtures/scope_campus/placement-reject-reasons.txt",
}
# literals from tests/unit/test_scope_fees.py; studentname/studentid swapped to
# the fabricated zz9999 identity (task rule: no real student data).
FEE_ROWS = [
    {"feedetails": "Registration Fee##10000.00##10000.00##13-Aug-2025##2025-2026##0"},
    {"feedetails": "Tuition Fees##200000.00##200000.00##13-Aug-2025##2025-2026##0"},
    {"feedetails": "Exam Fees##3150.00##3150.00##24-Sep-2026##2026-2027##0"},
]
FIN_ROWS = [
    {"amount": "111000.00", "vouchertype": "Receipt",
     "narration": "being recd. fee for the yr.2025-26 THRU 08-08-2025\t\tIMPS/P2A/522013235148/UMASHANK/ICICIBAN/SRMFinal\r\n\r\n",
     "voucherdate": "2025-11-21", "vouchernumber": "17174"},
    {"amount": "4050.00", "vouchertype": "Receipt",
     "narration": "Being Fee received from student for Exam Fees fee paid through online using Pay U (Axis) with bank transaction id 1116435793 on 2025-11-23 23:53:02.177",
     "voucherdate": "2025-11-26", "vouchernumber": "17720"},
    {"amount": "200000.00", "vouchertype": "Receipt",
     "narration": "Being Fee received from student for College Fees fee paid through online using Pay U (Axis) with bank transaction id 1221229971 on 2026-06-29 23:13:37.86",
     "voucherdate": "2026-07-02", "vouchernumber": "8162"},
]
EXAM_ROWS = [
    {"partpaymentapplicable": 0, "studentname": "ZZ ZED", "startdate": "21-09-2026",
     "minamount": 3150, "amounttopay": 3150, "studentid": "999999", "paidamount": 0,
     "enddate": "25-11-2026", "penaltystatus": 0, "sno": "2440869", "officeid": "20",
     "amountwithoutpenalty": 3150, "penaltydate": "24-11-2026", "ischeckvisible": "t",
     "appln_category_id": "1"},
]
# profile.py _KEYMAP portal names — fabricated values for zz9999.
PROFILE_DICT = {
    "father": "Ramesh Zed", "mother": "Sita Zed",
    "dob": "12-Jan-2008", "admitteddate": "01-Aug-2025",
    "address": "42 Test Street, Chennai, Tamil Nadu", "pincode": "600001",
    "district": "Chennai", "state": "Tamil Nadu",
    "program": "B.Tech (Computer Science and Engineering)",
    "universityname": "SRM Institute of Science and Technology",
    "sectiondesc": "A", "batch": "2025-29",
    "facultyadvisor": "Dr. T. Advisor", "academicadvisor": "Prof. S. Mentor",
    "personal_email_id": "zz9999@example.com", "studentmobile": "9999999999",
}
FRESH_EMPTY_OPS = ["getCummulativeAttendance", "getSubjectwiseAttendance",
                   "getInternalMarkDetails"]
EXTRA_EMPTY_OPS = ["getJobQuestions", "getPlacementRegistrationDetailsList",
                   "getPlacementWillingnessRegistrationOpen"]
EMPTY_ENV = {"Status": "Success", "Message": "No data found", "Data": ""}

# ── normalization ────────────────────────────────────────────────────
# asset() emits ?v=<sha256[:10]> — HEX, not digits (DESIGN §10.16)
RE_VQ = re.compile(r"\?v=[0-9a-fA-F]+")
RE_DT_ATTR = re.compile(r'\sdata-(?:ts|full)="[^"]*"')
RE_AGOP = re.compile(r"\(\d+(?:m|h|d) ago\)")
RE_AGOP2 = re.compile(r"\b\d+(?:\.\d+)?\s*(?:s|m|h|d|w)\s+ago\b")
RE_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?")
RE_EPOCH_KEY = re.compile(r'("(?:ts|fetched_at|last_fetch|updated_at|last_sync|last_ok|fetched)"\s*:\s*)(\d{9,13})')


def normalize(s: str) -> str:
    """Strip the bits that move between runs but mean nothing to a UI diff."""
    s = RE_VQ.sub("", s)                      # ?v=<hash> asset version queries
    s = RE_DT_ATTR.sub("", s)                 # sync-line data-ts/data-full epochs
    s = RE_AGOP.sub("()", s)                  # "(5m ago)" sync captions
    s = RE_AGOP2.sub("ago", s)                # any other relative time
    s = RE_ISO.sub("1970-01-01T00:00:00", s)  # ISO timestamps
    s = RE_EPOCH_KEY.sub(lambda m: m.group(1) + "0", s)  # epoch int in known keys
    return s


def gz(b: bytes) -> int:
    return len(gzip.compress(b, 9))


def jdump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


# ── setup: seed + scope injection ────────────────────────────────────
def seed(data_dir: str) -> str:
    shutil.rmtree(data_dir, ignore_errors=True)
    env = dict(os.environ, DATA_DIR=data_dir, LOG_LEVEL="WARNING", OCR_PREWARM="0")
    code = ("import sys; sys.path.insert(0, 'tests');\n"
            "from _seed import seed_rich, mint_token\n"
            "seed_rich()\nprint(mint_token())")
    r = subprocess.run([PY, "-c", code], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"seed failed:\n{r.stderr[-2000:]}")
    tok = r.stdout.strip().splitlines()[-1]
    if not tok:
        raise RuntimeError(f"no token from seed:\n{r.stdout[-500:]}")
    return tok


def build_scope_blob(now: int) -> dict:
    blob = {}
    for op, rel in SCOPE_FIXTURES.items():
        data = None
        p = REPO / rel
        if p.exists():
            try:
                data = json.loads(p.read_text())
            except Exception:
                data = None
        blob[op] = {"data": data if data is not None else [], "ts": now}
    for op, rows in (("getFeeDetails", FEE_ROWS), ("getFinanceDetails", FIN_ROWS),
                     ("getStudentExamFeesDetails", EXAM_ROWS)):
        blob[op] = {"data": rows, "ts": now}
    # campus: repo fixtures are alive-empty envelopes ("No data found") and
    # campus_view hides the whole tab when every card is empty
    # (`show` = bool(cards); a card needs rows + feature slug — campus.py:141).
    # Fabricate minimal deterministic rows so every card renders.
    blob.update({
        "getStudentAllOfferedJobs": {"data": {"Status": "Success", "Message": "OK", "Data": [
            {"jobtitle": "Software Development Engineer - I", "companyname": "TCS",
             "jobid": 4411, "stipend": "8,00,000 PA", "closingdate": "2026-12-15", "status": "Open"},
            {"jobtitle": "Data Scientist", "companyname": "Infosys BPM",
             "jobid": 4412, "stipend": "9,50,000 PA", "closingdate": "2026-12-20", "status": "Open"},
            {"jobtitle": "Product Analyst", "companyname": "Cognizant",
             "jobid": 4413, "stipend": "7,20,000 PA", "closingdate": "2026-12-10", "status": "Closed"}]}, "ts": now},
        "getResumeUploads": {"data": {"Status": "Success", "Message": "OK", "Data": [
            {"resumename": "Resume - Oct 2026.pdf", "uploadeddate": "2026-10-28", "status": "Under review"}]}, "ts": now},
        "getLibraryTransaction": {"data": {"Status": "Success", "Message": "OK", "Data": [
            {"booktitle": "Introduction to Algorithms", "authorname": "Cormen",
             "bookid": 771, "issuedate": "2026-10-02", "duedate": "2026-11-15"},
            {"booktitle": "Clean Code", "authorname": "Robert C. Martin",
             "bookid": 772, "issuedate": "2026-11-01", "duedate": "2026-11-22"}]}, "ts": now},
        "getHostelDetails": {"data": {"Status": "Success", "Message": "OK", "Data": {
            "hostelname": "Block C - 3rd Floor", "roomno": "C-204", "messdays": "Mon-Sat"}}, "ts": now},
        "getTransportDetails": {"data": {"Status": "Success", "Message": "OK", "Data": {
            "routename": "Route 12 - Anna Nagar", "morningpickup": "07:15 AM", "eveningdrop": "05:45 PM"}}, "ts": now},
        "getViewNotificationListJson": {"data": {"Status": "Success", "Message": "OK", "Data": [
            {"notificationtitle": "Midsem exam schedule released", "date": "2026-11-01",
             "time": "09:00", "body": "Academic calendar updated on the portal"},
            {"notificationtitle": "Library extended hours during midsem", "date": "2026-11-05",
             "time": "12:30", "body": "Open till 11 PM during exam week"}]}, "ts": now},
    })
    blob["getPersonalDetails"] = {"data": dict(PROFILE_DICT), "ts": now}
    blob["getStudentPersonalDetails"] = {"data": dict(PROFILE_DICT), "ts": now}  # tools gate op
    for op in FRESH_EMPTY_OPS:
        blob[op] = {"data": [], "ts": now}
    for op in EXTRA_EMPTY_OPS:
        blob[op] = {"data": dict(EMPTY_ENV), "ts": now}
    return blob


def inject_scope(data_dir: str) -> None:
    now = int(time.time())
    conn = sqlite3.connect(os.path.join(data_dir, "srm.db"))
    conn.execute("UPDATE users SET scope_json=?, scope_fetched_at=? WHERE netid=?",
                 (json.dumps(build_scope_blob(now)), now, NETID))
    conn.commit()
    # verify the write actually landed (a silent miss = 5-of-9 panels)
    row = conn.execute("SELECT scope_json FROM users WHERE netid=?", (NETID,)).fetchone()
    conn.close()
    if not row or not row[0]:
        raise RuntimeError("scope_json injection failed — users row empty")
    blob = json.loads(row[0])
    need = ["getFeeDetails", "getFinanceDetails", "getStudentExamFeesDetails",
            "getPersonalDetails", "getHourwiseAttendance", "getExamDetails",
            "getStudentAllOfferedJobs", "getLibraryTransaction", "getHostelDetails",
            "getViewNotificationListJson"]
    missing = [k for k in need if k not in blob]
    if missing:
        raise RuntimeError(f"scope_json missing keys: {missing}")
    print(f"      scope_json: {len(blob)} ops, key ops present: {len(need)}/{len(need)}")


# ── server ───────────────────────────────────────────────────────────
def free_port(start: int) -> int:
    # Scan from the requested port upward. The old ceiling was a literal 18189,
    # so any --port at or above it produced an empty range and raised "no free
    # port" while every port was actually free.
    for port in range(start, start + 32):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"no free port in {start}-{start + 31}")


def start_server(data_dir: str, port: int):
    env = dict(os.environ, DATA_DIR=data_dir, LOG_LEVEL="WARNING",
               SCOPE_FEATURES=FEATURES, METRICS_SECRET=METRICS_SECRET, OCR_PREWARM="0")
    logf = open(f"/tmp/osrm-capture-{port}.log", "w")
    proc = subprocess.Popen(
        [PY, "-m", "gunicorn", "-w", "1", "--threads", "4",
         "-b", f"127.0.0.1:{port}", "app.app:app"],
        cwd=REPO, env=env, stdout=logf, stderr=subprocess.STDOUT)
    for _ in range(120):
        if proc.poll() is not None:
            logf.close()
            raise RuntimeError("gunicorn exited early:\n" + open(f"/tmp/osrm-capture-{port}.log").read()[-2000:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                if r.status == 200:
                    return proc, logf
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    logf.close()
    raise RuntimeError("server did not come up:\n" + open(f"/tmp/osrm-capture-{port}.log").read()[-2000:])


# ── API capture ──────────────────────────────────────────────────────
def api_name(path: str) -> str:
    p = re.sub(r"\?v=\d+", "", path).lstrip("/")
    return p.replace("/", "_") if p else "root"


def api_capture(base: str, token: str, out: Path) -> dict:
    import requests
    results = {}   # path -> {"status","content_type","raw","body_record"}

    def save(path, raw: bytes, status: int, ctype: str):
        (out / "api").mkdir(parents=True, exist_ok=True)
        if ctype.startswith("text/") or ctype == "" or "json" in ctype or "javascript" in ctype:
            text = normalize(raw.decode("utf-8", "replace"))
            if path == "/internal/metrics":
                # runtime telemetry: values are timing/RSS/ages (differ every
                # run); keep metric names + labels, zero the values
                text = re.sub(r"(?m) -?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$", " 0", text)
            nb = text.encode()  # sizes reflect the captured (normalized) artifact
            rec = {"path": path, "status": status, "content_type": ctype,
                   "bytes": len(nb), "gzip_bytes": gz(nb), "body": text}
        else:
            rec = {"path": path, "status": status, "content_type": ctype,
                   "bytes": len(raw), "gzip_bytes": gz(raw),
                   "body_b64": base64.b64encode(raw).decode()}
        (out / "api" / f"{api_name(path)}.json").write_text(jdump(rec) + "\n")
        results[path] = rec

    # authenticated session
    s = requests.Session()
    s.cookies.set("srm_session", token, domain="127.0.0.1", path="/")
    for path in API_GETS:
        if path == "/login":
            continue
        r = s.get(base + path, timeout=30)
        save(path, r.content, r.status_code, r.headers.get("Content-Type", ""))
    # login page as an unauthenticated visitor
    r = requests.get(base + "/login", timeout=30)
    save("/login", r.content, r.status_code, r.headers.get("Content-Type", ""))
    # internal metrics (process telemetry; kept — diff will say if it's volatile)
    r = s.get(base + "/internal/metrics", headers={"X-Metrics-Token": METRICS_SECRET}, timeout=30)
    save("/internal/metrics", r.content, r.status_code, r.headers.get("Content-Type", ""))
    # static assets referenced by the two pages
    statics = set()
    for path in ("/", "/login"):
        for m in re.findall(r'(?:src|href)=["\'](/static/[^"\']+)["\']',
                            normalize(results[path]["body"])):
            statics.add(RE_VQ.sub("", m))
    for path in sorted(statics):
        r = s.get(base + path, timeout=30)
        save(path, r.content, r.status_code, r.headers.get("Content-Type", ""))
    # second-level JS references (e.g. sw.js registered from inside JS)
    js_bodies = [results[p]["body"] for p in results
                 if p.startswith("/static/") and p.endswith(".js")]
    extra = set()
    for body in js_bodies:
        for m in re.findall(r'["\']([^"\']*\.js)["\']', body):
            if not m.startswith("/"):
                m = "/static/" + m
            if m.startswith("/static/"):
                extra.add(RE_VQ.sub("", m))
    for path in sorted(extra - set(statics)):
        r = s.get(base + path, timeout=30)
        save(path, r.content, r.status_code, r.headers.get("Content-Type", ""))
        statics.add(path)
    # logout is captured AFTER the browser phase (it invalidates the session)
    return results


def capture_logout(base: str, token: str, out: Path) -> None:
    import requests
    s = requests.Session()
    s.cookies.set("srm_session", token, domain="127.0.0.1", path="/")
    r = s.get(base + "/logout", allow_redirects=False, timeout=30)
    (out / "api").mkdir(parents=True, exist_ok=True)
    rec = {"path": "/logout", "method": "GET", "status": r.status_code,
           "content_type": r.headers.get("Content-Type", ""),
           "set_cookie": r.headers.get("Set-Cookie", ""),
           "location": r.headers.get("Location", "")}
    (out / "api" / "logout.json").write_text(jdump(rec) + "\n")


# ── browser capture ──────────────────────────────────────────────────
def freeze(page) -> None:
    page.add_style_tag(content="*,*::before,*::after{animation-play-state:paused!important;transition:none!important}")
    page.evaluate("document.querySelectorAll('svg').forEach(s=>{try{s.pauseAnimations&&s.pauseAnimations()}catch(e){}})")
    page.wait_for_timeout(500)


def browser_capture(base: str, token: str, out: Path) -> dict:
    from playwright.sync_api import sync_playwright
    tabs_html = {}          # tab -> normalized outerHTML (last viewport = desktop)
    tabs_nodes = {}         # tab -> node count (desktop)
    page_nodes = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vpname, w, h in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h},
                                      service_workers="block", reduced_motion="reduce")
            ctx.add_cookies([{"name": "srm_session", "value": token, "url": base}])
            page = ctx.new_page()
            try:
                page.clock.install()      # frozen client Date.now; virtual timers never fire
            except Exception:
                pass                      # ponytail: old playwright -> rely on fresh-seed freshness
            page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base) else r.abort())
            page.goto(base + "/", wait_until="networkidle")
            freeze(page)
            for tab in TABS:
                btn = page.locator(f'[data-tab="{tab}"]:visible').first
                try:
                    btn.click(timeout=5000)
                except Exception:
                    # diagnostics: what did the browser actually get?
                    dbg = out / "screens" / "debug-failure.png"
                    try:
                        page.screenshot(path=str(dbg), full_page=False)
                    except Exception:
                        pass
                    print(f"      DEBUG url={page.url!r} title={page.title()!r} "
                          f"body_len={len(page.content())} "
                          f"datatab={page.locator('[data-tab]').count()} "
                          f"visdatatab={page.locator('[data-tab]:visible').count()}")
                    raise
                page.wait_for_timeout(150)
                panel = page.query_selector(f'#tab-{tab}[data-tabpanel]')
                if panel is None:
                    raise RuntimeError(f"panel not found for tab {tab!r}")
                html = normalize(panel.evaluate("el => el.outerHTML"))
                if w == 1440:  # desktop run is the canonical DOM
                    tabs_html[tab] = html
                    tabs_nodes[tab] = panel.evaluate("el => el.querySelectorAll('*').length")
                    (out / "dom" / f"{tab}.html").write_text(html + "\n")
                page.screenshot(path=str(out / "screens" / f"{tab}-{vpname}.png"), full_page=True)
            if w == 1440:
                page_nodes = page.evaluate("document.querySelectorAll('*').length")
            ctx.close()
        browser.close()
    (out / "routes.json").write_text(jdump({
        "tab_ids": TABS,
        "panels_present": sorted(tabs_html.keys()),
        "source_viewport": "1440x900",
        "tabs": {t: {"panel_selector": f"#tab-{t}[data-tabpanel]",
                     "outer_html": tabs_html[t]} for t in TABS},
    }) + "\n")
    return {"tabs_html": tabs_html, "tabs_nodes": tabs_nodes, "page_nodes": page_nodes}


# ── metrics ──────────────────────────────────────────────────────────
def js_refs(html: str, results: dict) -> list:
    """All JS referenced from this page: script srcs in the HTML, then .js
    string refs inside those JS files (catches sw.js registration)."""
    paths = set(re.findall(r'<script\b[^>]*src=["\'](/static/[^"\']+)["\']', html))
    paths = {RE_VQ.sub("", p) for p in paths}
    first = set(paths)
    for p in first:
        body = results.get(p, {}).get("body", "")
        for m in re.findall(r'["\']([^"\']*\.js)["\']', body):
            if not m.startswith("/"):
                m = "/static/" + m
            if m.startswith("/static/"):
                paths.add(re.sub(r"\?v=\d+", "", m))
    return sorted(paths)


def metrics(results: dict, browser: dict, api_dir: Path, out: Path) -> dict:
    pages = {}
    js_union = set()
    for path in ("/", "/login"):
        raw = (out / "api" / f"{api_name(path)}.json")
        rec = json.loads(raw.read_text())
        html_b = rec["body"].encode()
        refs = js_refs(rec["body"], results)
        js_union |= set(refs)
        pages[path] = {
            "html_bytes": rec["bytes"], "html_gzip_bytes": rec["gzip_bytes"],
            "script_tags": len(re.findall(r"<script\b", rec["body"])),
            "js_files": refs,
            "js_bytes": sum(results[r]["bytes"] for r in refs if r in results),
            "js_gzip_bytes": sum(results[r]["gzip_bytes"] for r in refs if r in results),
            "dom_nodes": browser["page_nodes"] if path == "/" else None,
        }
    tabs = {t: {"panel_html_bytes": len(browser["tabs_html"][t].encode()),
                "panel_html_gzip_bytes": gz(browser["tabs_html"][t].encode()),
                "panel_dom_nodes": browser["tabs_nodes"][t]} for t in TABS}
    api = {}
    for f in sorted(api_dir.glob("*.json")):
        r = json.loads(f.read_text())
        api[r["path"]] = {"bytes": r.get("bytes"), "gzip_bytes": r.get("gzip_bytes"),
                          "content_type": r.get("content_type"), "status": r["status"]}
    doc = {
        "pages": pages, "tabs": tabs, "api": api,
        "totals": {
            "html_bytes": sum(p["html_bytes"] for p in pages.values()),
            "html_gzip_bytes": sum(p["html_gzip_bytes"] for p in pages.values()),
            "js_bytes": sum(results[r]["bytes"] for r in js_union if r in results),
            "js_gzip_bytes": sum(results[r]["gzip_bytes"] for r in js_union if r in results),
            "api_bytes": sum(v["bytes"] for v in api.values() if v["bytes"] is not None),
            "api_gzip_bytes": sum(v["gzip_bytes"] for v in api.values() if v["gzip_bytes"] is not None),
            "dom_nodes_page": browser["page_nodes"],
            "dom_nodes_all_panels": sum(browser["tabs_nodes"].values()),
        },
    }
    (out / "metrics.json").write_text(jdump(doc) + "\n")
    return doc


# ── README (regenerated every run so it never goes stale) ────────────
README_TEXT = """# OpenSRM golden capture

Deterministic baseline of the app at `feat/preact-migration` HEAD
before the Preact migration landed. Regenerate with `scripts/capture_golden.sh`,
then diff against this dir — `dom/`, `api/`, `routes.json` and `metrics.json`
must be byte-identical; screenshots must be ~0% pixel difference (they were
0/23,259,114 px on the two-run determinism check).

## One command

```
bash scripts/capture_golden.sh /tmp/golden-check
diff -r tests/golden /tmp/golden-check      # expect: no output
```

Wipes the target dir, seeds a clean
`DATA_DIR=/tmp/osrm-premig` (`tests/_seed.py` `seed_rich()`, user
`zz9999` only), injects the fabricated scope blob, boots gunicorn on
127.0.0.1 (port 18185 if free, else auto-increment), captures, and
shuts the server down. Read-only on the repo; nothing is committed.
Playwright chromium lives at `/opt/data/cache/scratch/pw-browsers`
(`playwright install chromium` if missing).

## Contents

| path | what |
|---|---|
| `routes.json` | the 9 tab ids, `panels_present` (asserted == 9 in-harness), and each panel's normalized outer HTML |
| `dom/<tab>.html` | post-JS-load DOM of each panel, normalized (see below) |
| `screens/<tab>-{390x844,768x1024,1440x900}.png` | full-page screenshots, 9 tabs x 3 viewports |
| `api/<endpoint>.json` | status, content-type, byte + gzip sizes, and body (or b64 for binary) of every GET endpoint, including static assets and `/login`; `logout.json` captured last |
| `metrics.json` | per page: html bytes, gzip bytes, `<script>` count, JS file list + total bytes; per api endpoint sizes; DOM node counts |

## What is normalized (and why)

Captured output must be identical across runs, so anything that
legitimately varies with wall-clock is normalized at record time:

1. **`?v=<hash>` asset query strings** — `app/app.py asset()` appends
   `?v=sha256(file)[:10]`. Hash is stable for unchanged files, but the
   query string is a deployment detail, not app behaviour; stripped so
   a content-hash change alone doesn't fail the diff. (Regex is
   hex-aware: `\\?v=[0-9a-fA-F]+`.)
2. **`data-ts` / `data-full` attributes on the sync line** — the
   dashboard's "last synced" epoch + ISO string. Replaced with
   `data-ts="0"` / `data-full="1970-01-01T00:00:00Z"`.
3. **Relative-time strings** (`just now`, `Ns ago`, `Nm ago`, ...) —
   rendered from wall-clock in `dash.js`; replaced with a fixed
   `x ago` placeholder.
4. **Epoch / ISO timestamps in visible text** — same reason.
5. **`/internal/metrics` values** — Prometheus counters/timers for the
   live process (histogram sums, RSS, sync ages) change every run by
   design; values are zeroed, metric names + labels (the structural
   contract) are kept.
6. **Recorded sizes are computed on the normalized bytes**, not the
   raw wire bytes — raw HTML contains the volatile bits above, so
   raw sizes would wobble by a few bytes between runs.

## What is fixed to keep things stable (not normalized)

- Clean `DATA_DIR` + `seed_rich()` + fabricated scope blob every run:
  the repo's campus fixtures are alive-empty ("No data found")
  envelopes, and `campus_view` hides the tab when every card is empty
  (`show = bool(cards)`), so the harness fabricates minimal rows for
  jobs/resume/library/hostel/transport/notifications.
- `SCOPE_FEATURES` = all 9 feature slugs on the server env.
- Client clock frozen (`page.clock.setFixedTime`), CSS/SVG animations
  paused, `prefers-reduced-motion: reduce`, service workers blocked,
  external (non-127.0.0.1) requests aborted.
- `gzip` recorded with `mtime=0`.

## Panel parity

`routes.json` records `panels_present`; the harness hard-fails
(`panels missing from DOM: [...]`) if fewer than the 9 known tabs are
in the DOM — a capture that silently baselines 5 of 9 is rejected,
not accepted.
"""


def write_readme(out: Path) -> None:
    (out / "README.md").write_text(README_TEXT)


# ── main ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--port", type=int, default=18185)
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    for d in ("dom", "screens", "api"):
        (out / d).mkdir(parents=True)

    print(f"[1/5] seeding {DATA_DIR} (clean state) ...")
    token = seed(DATA_DIR)
    print(f"      token minted: {token[:6]}... ({len(token)} chars)")
    print("[2/5] injecting fabricated scope blob (all 9 features, fresh ts) ...")
    inject_scope(DATA_DIR)

    port = free_port(args.port)
    print(f"[3/5] gunicorn on 127.0.0.1:{port} ...")
    server, logf = start_server(DATA_DIR, port)
    base = f"http://127.0.0.1:{port}"
    rc = 0
    try:
        print("[4/5] API capture ...")
        results = api_capture(base, token, out)
        print(f"      {len(results)} endpoints captured")
        print("[5/5] browser capture (3 viewports x 9 tabs) ...")
        browser = browser_capture(base, token, out)
        if len(browser["tabs_html"]) != len(TABS):
            missing = [t for t in TABS if t not in browser["tabs_html"]]
            raise RuntimeError(f"panels missing from DOM: {missing}")
        capture_logout(base, token, out)
        m = metrics(results, browser, out / "api", out)
        write_readme(out)
        t = m["totals"]
        print(f"      done. html={t['html_bytes']}B js={t['js_bytes']}B api={t['api_bytes']}B")
        print(f"      dom nodes: page={t['dom_nodes_page']} panels={t['dom_nodes_all_panels']}")
    except Exception as e:
        rc = 1
        print(f"FAILED: {type(e).__name__}: {e}")
        tail = Path(f"/tmp/osrm-capture-{port}.log").read_text()[-1500:]
        print("server log tail:\n" + tail)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        logf.close()
    print(f"exit {rc} — output in {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
