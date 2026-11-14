#!/usr/bin/env python
"""Deterministic golden capture of an OpenSRM revision.

REVISION-INDEPENDENT: --repo <path> says which checkout/worktree to capture; it
drives BOTH the app under test and the seed script, so a detached worktree at an
old SHA can be captured while HEAD stays elsewhere. Precedence:
    --repo  >  $OPENSRM_REPO  >  /opt/data/opensrm-repo
The interpreter that imports the app comes from --python, else
<repo>/.venv/bin/python, else $OPENSRM_REPO/.venv/bin/python (a worktree usually
has no venv of its own). The resolved SHA is printed and recorded in
metrics.json, so a capture can never be mistaken for a different revision.

Produces under --out (default /opt/data/missions/opensrm-preact/captures):
  routes.json          9 tab ids + each visible panel's normalized outer HTML
  dom/<tab>.html       post-JS DOM of each tab panel (normalized)
  screens/<tab>-<vp>.png  full-page screenshots, 390x844 / 768x1024 / 1440x900
  api/<endpoint>.json  GET response bodies + status (static assets included)
  metrics.json         byte sizes, gzip sizes, script/node counts, revision

Determinism: clean DATA_DIR each run, seed_rich() + fabricated scope blob
(all 9 features, fresh ts), frozen client clock (page.clock), paused CSS/SVG
animations, reduced motion, service workers blocked, external requests
aborted, and a READY SIGNAL instead of a timer or networkidle (see settle()).

WHAT IS DELIBERATELY NORMALISED (a future reader must not mistake these for
app behaviour — every item below is masked at record time, on the post-JS DOM
and on every text API body, because it changes between runs or between builds
with no UI meaning):
  1. `?v=<hash>` asset version queries (app.py asset()) — stripped.
  2. Vite build hashes inside dist filenames — `SettingsPanel-Crq-6lwG.js`
     becomes `SettingsPanel-HASH.js`. Unmasked, every `pnpm build` would fail
     the diff on a content-identical app.
  3. `data-ts` / `data-full` attributes on the navbar sync line — removed.
  4. Relative ages: "(5m ago)", "3d ago", "just now" -> a fixed "ago"
     placeholder. Rendered from wall-clock, never from app state.
  5. Epoch ints under known JSON keys (ts, fetched_at, last_sync, ...) -> 0,
     and ISO timestamps -> 1970-01-01T00:00:00.
  6. `/internal/metrics` values -> 0 (histogram sums, RSS, sync ages). Metric
     names and labels stay: those are the structural contract.
  7. Recorded byte/gzip sizes are computed on the NORMALIZED bytes, not the
     wire bytes, so they do not wobble by a few bytes run to run.
  8. blobatar's random avatar animation phases / gaze angles (`--mo-phase:-1773ms`,
     `--mo-look-x:-1.64`, ...). The SVG is generated per request, so the same
     student's avatar blinks differently on every page load. Recorded bodies are
     pinned to `:0`, and the browser is served documents with the same values
     pinned (_pin_mo_vars) so the screenshots are byte-identical too. Cosmetic
     only — no state is read from those vars.
Session tokens, random netids and CSRF-ish values do not appear in the
captured surface (verified: logout's Set-Cookie is the fixed epoch deletion
cookie; /api/push/status carries no secret). If one ever does, mask it here and
add a line to this list — an unmasked volatile field is a golden that fails
for no reason.

Read-only on the repo. No commit. Seed user zz9999 only.

--check DIR captures into a throwaway dir and diffs it against DIR (default
tests/golden/v3), printing every file that differs and exiting non-zero. That is
the drift gate CI runs (`bash scripts/capture_golden.sh --check`). Two files are
exempt: README.md (this tool regenerates it) and metrics.json's `revision` (it
names the SHA the golden was captured at, which is by definition older than the
HEAD being checked — comparing it would leave the gate permanently red).
--no-screens exists because PNG bytes encode the host's font stack: a GitHub
runner is not the machine the goldens were captured on.
"""
import argparse
import base64
import difflib
import gzip
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# Browsers: honour whatever the machine already has. The lab keeps them on the
# big disk; the laptop (where playwright runs — L8/L9) has the default cache.
_LAB_PW = "/opt/data/cache/scratch/pw-browsers"
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and Path(_LAB_PW).exists():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _LAB_PW

# Both are re-bound by --repo/--python in main(); these are the fallbacks.
CANONICAL = Path(os.environ.get("OPENSRM_REPO", "/opt/data/opensrm-repo"))
REPO = CANONICAL
PY = Path("/opt/data/opensrm-repo/.venv/bin/python")
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
# No leading \s in the pattern on purpose: home.html renders
#   class="sync-line ..."data-ts="…"
# with NO space before data-ts (a template slip), so anchoring on whitespace
# silently left the epoch in the golden and the diff never came out empty.
RE_DT_ATTR = re.compile(r'\s*data-(?:ts|full)="[^"]*"')
RE_AGOP = re.compile(r"\(\d+(?:m|h|d) ago\)")
RE_AGOP2 = re.compile(r"\b\d+(?:\.\d+)?\s*(?:s|m|h|d|w)\s+ago\b")
RE_JUST_NOW = re.compile(r"\bjust now\b")
# blobatar stamps RANDOM animation phases / gaze angles into the avatar SVG's
# inline style (--mo-phase:-1773ms, --mo-look-x:-1.64, ...). Cosmetic, but they
# move the rendered pixels, so they must be pinned for the recorded body AND
# the screenshot (see _pin_mo_vars).
RE_MO_VAR = re.compile(r"(--mo-[a-z0-9-]+)\s*:\s*-?[\d.]+(?:ms)?")
# Vite content hash inside a dist filename: SettingsPanel-Crq-6lwG.js ->
# SettingsPanel-HASH.js. 8 chars of [A-Za-z0-9_-] before .js/.css only, so
# icon-192.png and apple-touch-icon.png are untouched.
RE_ASSET_HASH = re.compile(r"-([A-Za-z0-9_-]{8})(\.(?:js|css))\b")
RE_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?")
RE_EPOCH_KEY = re.compile(r'("(?:ts|fetched_at|last_fetch|updated_at|last_sync|last_ok|fetched)"\s*:\s*)(\d{9,13})')


def normalize(s: str) -> str:
    """Mask the bits that move between runs/builds but mean nothing to a UI diff.

    Every rule here is listed in the module docstring — keep the two in sync.
    """
    s = RE_VQ.sub("", s)                      # ?v=<hash> asset version queries
    s = RE_ASSET_HASH.sub(r"-HASH\2", s)      # dist build hashes in filenames
    s = RE_DT_ATTR.sub("", s)                 # sync-line data-ts/data-full epochs
    s = RE_AGOP.sub("()", s)                  # "(5m ago)" sync captions
    s = RE_AGOP2.sub("ago", s)                # any other relative time
    s = RE_JUST_NOW.sub("ago", s)             # sub-minute age caption
    s = RE_MO_VAR.sub(r"\1:0", s)             # random blobatar animation phases
    s = RE_ISO.sub("1970-01-01T00:00:00", s)  # ISO timestamps
    s = RE_EPOCH_KEY.sub(lambda m: m.group(1) + "0", s)  # epoch int in known keys
    return s


def selftest() -> int:
    """The normaliser is the only logic a wrong edit can silently break:
    a rule that stops matching produces a golden that differs every run."""
    cases = [
        ('<script src="/static/dist/assets/SettingsPanel-Crq-6lwG.js?v=abc123">',
         '<script src="/static/dist/assets/SettingsPanel-HASH.js">'),
        ('<link href="/static/dist/assets/app-Dw5KSv9_.css">',
         '<link href="/static/dist/assets/app-HASH.css">'),
        ('<img src="/static/icon-192.png">', '<img src="/static/icon-192.png">'),
        ('<a href="/static/apple-touch-icon.png">', '<a href="/static/apple-touch-icon.png">'),
        ('synced <span data-ts="1794600000" data-full="2026-11-13T21:00:00Z">',
         'synced <span>'),
        ('<span>5m ago</span>', '<span>ago</span>'),
        ('<span>(3d ago)</span>', '<span>()</span>'),
        ('<span>just now</span>', '<span>ago</span>'),
        ('<svg style="--mo-phase:-1773ms;--mo-head:#e2d1e1">',
         '<svg style="--mo-phase:0;--mo-head:#e2d1e1">'),
        ('--mo-look-x:-1.64;', '--mo-look-x:0;'),
        ('{"ts": 1794600000, "name": "x"}', '{"ts": 0, "name": "x"}'),
        ('at 2026-11-13T21:00:00', 'at 1970-01-01T00:00:00'),
    ]
    bad = [(a, normalize(a), b) for a, b in cases if normalize(a) != b]
    for a, got, want in bad:
        print(f"FAIL {a!r} -> {got!r} (want {want!r})")
    print(f"selftest: {len(cases) - len(bad)}/{len(cases)} normalisation cases pass")

    # compare_tree is the gate itself. Build a golden and a capture that differ
    # in exactly the documented ways and assert what gets reported.
    with tempfile.TemporaryDirectory() as d:
        g, c = Path(d) / "golden", Path(d) / "got"
        for root in (g, c):
            (root / "dom").mkdir(parents=True)
            (root / "screens").mkdir()
            (root / "dom" / "x.html").write_text("<b>1</b>\n")
            (root / "README.md").write_text("hand-written notes\n")
            (root / "metrics.json").write_text(jdump({"revision": "aaaa111", "n": 1}))
            (root / "screens" / "x-1.png").write_bytes(b"\x89PNG-one")
        (c / "README.md").write_text("regenerated by the tool\n")     # exempt
        (c / "metrics.json").write_text(jdump({"revision": "bbbb222", "n": 1}))  # exempt
        (c / "screens" / "x-1.png").write_bytes(b"\x89PNG-two")      # other host
        gate_cases = [("clean check reports nothing", compare_tree(g, c, screens=False), [])]
        (c / "dom" / "x.html").write_text("<b>2</b>\n")          # real drift
        gate_cases.append(("real drift is named", compare_tree(g, c, screens=False),
                           ["differs:         dom/x.html"]))
        gate_cases.append(("screens compared when asked", compare_tree(g, c, screens=True),
                           ["differs:         dom/x.html",
                            "differs:         screens/x-1.png"]))
        bad2 = [(n, got, want) for n, got, want in gate_cases if got != want]
        for n, got, want in bad2:
            print(f"FAIL {n}: got {got!r} want {want!r}")
        print(f"selftest: {len(gate_cases) - len(bad2)}/{len(gate_cases)} drift-gate cases pass")
    return 1 if bad or bad2 else 0


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


def inject_scope(data_dir: str) -> int:
    """Write the fabricated scope blob. Returns its `ts`, because the browser
    clock is pinned relative to it (see browser_capture) — the sync caption's
    "Ns ago" is the last thing that still moved between runs, and it moved by
    the couple of seconds between seeding and page load."""
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
    return now


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
# THE READY SIGNAL. networkidle is unsatisfiable in this app (main.ts
# warmShells() keeps 8 /shell/* requests pending through the service worker, so
# the network never goes idle — decisions.md NETWORKIDLE-IS-UNSATISFIABLE-HERE),
# and a fixed sleep is only a bet on how slow the machine is. So the wait is on
# the app's own completion marker: every island mount carries `data-hydrated`
# (stamped by that island's own hydrate function, HYDRATED_ATTR) or
# `data-mounted-at` (the cache branch), and only a mounted island can produce
# either. A revision with no `[data-island]` at all (the pre-island baseline)
# has nothing to hydrate, so its marker set is empty and this reduces to
# "document complete" — one predicate, both revisions, no branching.
READY_JS = """() => {
  if (document.readyState !== 'complete') return false;
  const isl = Array.from(document.querySelectorAll('[data-island]'));
  return isl.every(e => !!(e.dataset.hydrated || e.dataset.mountedAt));
}"""

READY_DIAG_JS = """() => {
  const isl = Array.from(document.querySelectorAll('[data-island]'));
  return {readyState: document.readyState, islands: isl.length,
          pending: isl.filter(e => !(e.dataset.hydrated || e.dataset.mountedAt))
                      .map(e => e.dataset.island)};
}"""

SETTLE_TIMEOUT_MS = 30_000


def settle(page, what: str) -> None:
    """Block until the page finished its own boot, or report what did not.
    No fixed sleep and no networkidle anywhere in this path."""
    try:
        page.wait_for_function(READY_JS, timeout=SETTLE_TIMEOUT_MS)
    except Exception:
        raise RuntimeError(f"{what} never became ready: {page.evaluate(READY_DIAG_JS)}")


def _pin_mo_vars(route, request, base: str):
    """Serve every document with the avatar's random animation phases pinned.

    blobatar stamps RANDOM `--mo-*` phases and gaze angles into the avatar
    <svg>'s inline style, so two captures of the same revision render the
    avatar at different blink/gaze offsets: the DOM differed and
    settings-1440x900.png was never byte-identical. Pinning at the response
    (not in the DOM after the fact) means the islands hydrate with the same
    values the recorded body has, so the DOM, the props JSON and the pixels
    all agree. Cosmetic only: nothing reads these vars for state.
    """
    if not request.url.startswith(base):
        return route.abort()
    if request.resource_type != "document":
        return route.continue_()
    resp = route.fetch()
    return route.fulfill(response=resp, body=RE_MO_VAR.sub(r"\1:0", resp.text()))


def freeze(page) -> None:
    """Stop everything that still moves, then flush a frame so what is captured
    and screenshotted is the frozen paint.

    Three sources of movement that are NOT wall-clock normalisable, because they
    change PIXELS and the bytes of the PNG:
      1. gaze.js drives --mo-track-* through requestAnimationFrame forever, so
         each screenshot catches the eyes somewhere else. Its controller exposes
         stop(), and it is per-avatar (`_blobatarGaze`).
      2. the idle blink/bob/breathe loops are CSS keyframes: pausing leaves them
         at an arbitrary elapsed offset, so they are switched off, not paused.
      3. any --mo-* value the driver wrote last is pinned to 0.
    No sleep anywhere: two rAFs is the frame flush.
    """
    page.evaluate("""() => {
      document.querySelectorAll('.blobatar-gaze').forEach(s => {
        try { if (s._blobatarGaze && s._blobatarGaze.stop) s._blobatarGaze.stop(); } catch (e) {}
      });
      document.querySelectorAll('[style*="--mo-"]').forEach(el => {
        for (const name of Array.from(el.style)) {
          if (name.startsWith('--mo-') && /^-?[\\d.]+(?:ms)?$/.test(el.style.getPropertyValue(name).trim())) {
            el.style.setProperty(name, '0');
          }
        }
      });
      document.querySelectorAll('svg').forEach(s => { try { s.pauseAnimations && s.pauseAnimations(); } catch (e) {} });
    }""")
    page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important}")
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r())))")


# Deterministic rasterisation. Without these the binary PNGs of a
# content-identical page come back with 1-5 differing pixels between runs: the
# compositor picks different layer tiles and re-rasterises text with LCD
# subpixel AA at slightly different offsets. These flags pin the colour profile,
# the scale factor and the text rasteriser, and make each screenshot wait for
# every compositor stage. Verified by the same-SHA twice diff being empty.
DET_ARGS = [
    "--force-color-profile=srgb",
    "--force-device-scale-factor=1",
    "--disable-lcd-text",
    "--font-render-hinting=none",
    "--disable-gpu",
    "--disable-partial-raster",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--run-all-compositor-stages-before-draw",
    "--hide-scrollbars",
]


def browser_capture(base: str, token: str, out: Path, blob_ts: int) -> dict:
    from playwright.sync_api import sync_playwright
    tabs_html = {}          # tab -> normalized outerHTML (last viewport = desktop)
    tabs_nodes = {}         # tab -> node count (desktop)
    page_nodes = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(args=DET_ARGS)
        for vpname, w, h in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1,
                                      service_workers="block", reduced_motion="reduce")
            ctx.add_cookies([{"name": "srm_session", "value": token, "url": base}])
            page = ctx.new_page()
            try:
                # Pin the client clock to the blob's ts so every age label the
                # page renders is the SAME on every run of this revision. (This
                # playwright's clock takes SECONDS and keeps ticking; drift is
                # sub-second, so the age stays in the "just now" bucket — the
                # caption was the last thing whose glyphs moved between runs.)
                page.clock.install(time=blob_ts)
            except Exception:
                pass                      # ponytail: old playwright -> rely on fresh-seed freshness
            page.route("**/*", lambda r: _pin_mo_vars(r, r.request, base))
            page.goto(base + "/", wait_until="domcontentloaded")
            for idx, tab in enumerate(TABS):
                # TABS[0] (dashboard) is the route we just loaded. Every other tab
                # is reached by its real nav control: a client-side panel toggle on
                # the pre-island baseline (synchronous), a real MPA navigation on
                # HEAD. wait_for_load_state is a no-op for the former.
                if idx:
                    btn = page.locator(f'[data-tab="{tab}"]:visible').first
                    try:
                        btn.click(timeout=10000)
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
                    page.wait_for_load_state("load")
                settle(page, f"{tab} @ {vpname}")
                freeze(page)
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


def metrics(results: dict, browser: dict, api_dir: Path, out: Path, rev: str = "") -> dict:
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
        # Which revision this baseline is. Two captures are only comparable when
        # this matches — that is the whole point of --repo.
        "revision": rev,
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

Deterministic baseline of ONE revision of the app. `--repo` decides which
checkout is captured, so an old SHA can be baselined from a detached worktree
while HEAD stays on another branch; the resolved SHA is recorded in
`metrics.json` (`revision`) and printed. Regenerate with
`scripts/capture_golden.sh`, then diff against this dir — `dom/`, `api/`,
`routes.json` and `metrics.json` must be byte-identical; screenshots must be
~0% pixel difference (they were 0/23,259,114 px on the two-run determinism
check).

## One command

```
bash scripts/capture_golden.sh /tmp/golden-check            # HEAD of this checkout
python scripts/capture_golden.py --repo ../wt-v2 --out /tmp/v2 \\
    --python /opt/data/opensrm-repo/.venv/bin/python         # an explicit worktree
diff -r tests/golden /tmp/golden-check      # expect: no output
```

Wipes the target dir, seeds a clean
`DATA_DIR=/tmp/osrm-premig` (`tests/_seed.py` `seed_rich()`, user
`zz9999` only), injects the fabricated scope blob, boots gunicorn on
127.0.0.1 (port 18185 if free, else auto-increment), captures, and
shuts the server down. Read-only on the repo; nothing is committed.
`--repo` (or `$OPENSRM_REPO`) sets both the app under test and the seed
script; `--python` (or `<repo>/.venv/bin/python`, then
`$OPENSRM_REPO/.venv/bin/python`) is the interpreter that imports it.
Playwright chromium lives at `/opt/data/cache/scratch/pw-browsers`
(`playwright install chromium` if missing) — or wherever
`$PLAYWRIGHT_BROWSERS_PATH` already points.

## Drift gate (`--check`)

```
bash scripts/capture_golden.sh --check                # exit 0 == this tree matches the golden
bash scripts/capture_golden.sh --check --no-screens   # cross-host (CI): PNGs follow the font stack
```

Captures into a throwaway dir and diffs it against `tests/golden/v3`, printing
every file that differs and exiting non-zero. Two exemptions: this README (the
tool regenerates it) and `metrics.json`'s `revision` (provenance — it names the
SHA the golden was captured at, which is always older than the HEAD being
checked).

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
2. **Vite build hashes inside dist filenames** — `SettingsPanel-Crq-6lwG.js`
   is recorded as `SettingsPanel-HASH.js`, and `app-Dw5KSv9_.css` as
   `app-HASH.css`. The hash changes on every rebuild of *identical* source, so
   an unmasked one makes the golden fail for no behavioural reason. Only
   `.js`/`.css` with an 8-char `[A-Za-z0-9_-]` tail is touched, so
   `icon-192.png` is left alone.
3. **`data-ts` / `data-full` attributes on the sync line** — the
   dashboard's "last synced" epoch + ISO string. Removed (the values are
   re-derived by the island at boot).
4. **Relative-time strings** (`just now`, `Ns ago`, `Nm ago`, ...) —
   rendered from wall-clock; replaced with a fixed `ago` placeholder.
5. **Epoch / ISO timestamps in visible text** — same reason.
6. **`/internal/metrics` values** — Prometheus counters/timers for the
   live process (histogram sums, RSS, sync ages) change every run by
   design; values are zeroed, metric names + labels (the structural
   contract) are kept.
7. **Recorded sizes are computed on the normalized bytes**, not the
   raw wire bytes — raw HTML contains the volatile bits above, so
   raw sizes would wobble by a few bytes between runs.

## How the browser wait works (no sleeps, no networkidle)

`networkidle` is unsatisfiable here: `main.ts` `warmShells()` keeps eight
`/shell/*` requests pending through the service worker, which never emit
Playwright `requestfinished` (`decisions.md`
`NETWORKIDLE-IS-UNSATISFIABLE-HERE`). A capture that waits for it can only
succeed by timing out.

So the wait is an explicit ready signal: **every `[data-island]` mount must
carry `data-hydrated`** (stamped by that island's own hydrate function) or
`data-mounted-at` (the cache branch), and `document.readyState` must be
`complete`. A revision with no islands at all (the pre-island baseline) has an
empty marker set, so the same predicate reduces to "document complete" —
one predicate covers both revisions. Animation freeze is two
`requestAnimationFrame`s after that, not a delay.

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


# ── drift gate ───────────────────────────────────────────────────────
CHECK_DEFAULT = "tests/golden/v3"


def compare_tree(golden: Path, got: Path, screens: bool = True) -> list:
    """Every file that differs between a golden dir and a fresh capture.

    Byte-exact on purpose: a gate that tolerates a drifting byte is not a gate.
    The only two exemptions are documented in the module docstring (README.md,
    and metrics.json's `revision`). `screens=False` drops screens/ for
    cross-host runs, where PNG bytes follow the available fonts.
    """
    diffs = []
    rels = set()
    for root in (golden, got):
        for f in root.rglob("*"):
            if f.is_file():
                rels.add(f.relative_to(root).as_posix())
    for rel in sorted(rels):
        if rel == "README.md":
            continue
        if not screens and rel.startswith("screens/"):
            continue
        a, b = golden / rel, got / rel
        if not a.exists():
            diffs.append(f"only in capture: {rel}")
        elif not b.exists():
            diffs.append(f"only in golden:  {rel}")
        elif rel == "metrics.json":
            ja, jb = json.loads(a.read_text()), json.loads(b.read_text())
            ja["revision"] = jb["revision"] = ""
            if jdump(ja) != jdump(jb):
                diffs.append(f"differs:         {rel}")
        elif a.read_bytes() != b.read_bytes():
            diffs.append(f"differs:         {rel}")
    return diffs


# ── main ─────────────────────────────────────────────────────────────
def git_rev(repo: Path) -> str:
    """The SHA this capture is OF. Fake when the path is not a git checkout
    (`--repo` accepts a plain source tree), but never silently blank."""
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() or "not-a-git-checkout"


def resolve_python(explicit) -> Path:
    """Interpreter that can import the app. A worktree has no .venv of its own,
    so the canonical venv is the second candidate, not a hardcoded path."""
    cands = [Path(explicit)] if explicit else [REPO / ".venv" / "bin" / "python",
                                               CANONICAL / ".venv" / "bin" / "python"]
    for c in cands:
        if c.exists():
            return c
    raise SystemExit(f"no python interpreter at {[str(c) for c in cands]} — pass --python")


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic golden capture of one OpenSRM revision.")
    ap.add_argument("--repo", default=str(CANONICAL),
                    help="checkout/worktree to capture (default: $OPENSRM_REPO, else "
                         "/opt/data/opensrm-repo). Drives the app AND the seed script.")
    ap.add_argument("--python", default=None,
                    help="interpreter that imports the app (default: <repo>/.venv/bin/python, "
                         "then $OPENSRM_REPO/.venv/bin/python)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--port", type=int, default=18185)
    ap.add_argument("--check", nargs="?", const="", default=None, metavar="DIR",
                    help="capture into a throwaway dir and diff it against DIR "
                         "(default tests/golden/v3); exit 1 naming every file that differs")
    ap.add_argument("--no-screens", action="store_true",
                    help="with --check: skip screens/ (PNG bytes follow the host's fonts)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the normalisation cases and exit (no server, no browser)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    global REPO, PY
    REPO = Path(args.repo).resolve()
    if not (REPO / "app" / "app.py").exists():
        print(f"--repo {REPO} has no app/app.py — not an OpenSRM checkout")
        return 2
    PY = resolve_python(args.python)
    rev = git_rev(REPO)

    check_against = None
    if args.check is not None:
        check_against = Path(args.check).resolve() if args.check else REPO / CHECK_DEFAULT
        if not check_against.is_dir():
            print(f"--check: no golden dir at {check_against}")
            return 2

    # --check never writes into the reference dir — it captures into a throwaway
    # tree and diffs that against the golden.
    out = (Path(tempfile.mkdtemp(prefix="golden-check-")) / "capture"
           if check_against is not None else Path(args.out))
    if out.exists():
        shutil.rmtree(out)
    for d in ("dom", "screens", "api"):
        (out / d).mkdir(parents=True)
    print(f"      repo {REPO} @ {rev} — python {PY}")

    print(f"[1/5] seeding {DATA_DIR} (clean state) ...")
    token = seed(DATA_DIR)
    print(f"      token minted: {token[:6]}... ({len(token)} chars)")
    print("[2/5] injecting fabricated scope blob (all 9 features, fresh ts) ...")
    blob_ts = inject_scope(DATA_DIR)

    port = free_port(args.port)
    print(f"[3/5] gunicorn on 127.0.0.1:{port} ...")
    server, logf = start_server(DATA_DIR, port)
    base = f"http://127.0.0.1:{port}"
    rc = 0
    try:
        print("[4/5] API capture ...")
        results = api_capture(base, token, out)
        print(f"      {len(results)} endpoints captured")
        print("[5/5] browser capture (3 viewports x 9 tabs, ready-signal waits) ...")
        browser = browser_capture(base, token, out, blob_ts)
        if len(browser["tabs_html"]) != len(TABS):
            missing = [t for t in TABS if t not in browser["tabs_html"]]
            raise RuntimeError(f"panels missing from DOM: {missing}")
        capture_logout(base, token, out)
        m = metrics(results, browser, out / "api", out, rev)
        write_readme(out)
        t = m["totals"]
        print(f"      done. html={t['html_bytes']}B js={t['js_bytes']}B api={t['api_bytes']}B")
        print(f"      dom nodes: page={t['dom_nodes_page']} panels={t['dom_nodes_all_panels']}")
        if check_against is not None:
            diffs = compare_tree(check_against, out, screens=not args.no_screens)
            if diffs:
                rc = 1
                print(f"GOLDEN DRIFT: {len(diffs)} file(s) differ from {check_against}")
                for d in diffs[:60]:
                    print(f"  {d}")
                if len(diffs) > 60:
                    print(f"  ... and {len(diffs) - 60} more")
                # WHAT moved, not just which file: the first differing text files
                # get a short unified diff. A list of names is not actionable on
                # a CI runner you cannot log into; PNGs are named only.
                shown = 0
                for rel in (d.split()[-1] for d in diffs):
                    if shown >= 3 or rel.startswith("screens/"):
                        continue
                    a, b = check_against / rel, out / rel
                    if not (a.is_file() and b.is_file()):
                        continue
                    try:
                        al = a.read_text().splitlines()
                        bl = b.read_text().splitlines()
                    except UnicodeDecodeError:
                        continue
                    hunk = list(difflib.unified_diff(al, bl, f"golden/{rel}", f"capture/{rel}",
                                                     lineterm="", n=1))
                    if hunk:
                        shown += 1
                        print(f"  --- {rel}: first {min(24, len(hunk))} of {len(hunk)} diff lines ---")
                        for line in hunk[:24]:
                            print(f"  {line[:200]}")
                print(f"capture kept for inspection: {out.parent}")
            else:
                shutil.rmtree(out.parent, ignore_errors=True)
                print(f"golden OK: {rev} matches {check_against}")
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
    print(f"exit {rc} — {rev} captured to {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
