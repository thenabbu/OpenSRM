"""Fabricated SCOPE blob for tests: makes every data-gated surface eligible.

`scope_json` is the one input that decides which panels can exist (campus /
academics / fees / tools all self-hide without it), so any suite that wants
"the full app" has to put a blob on the users row. This is that blob, built
INSIDE the repo from `tests/fixtures/` + literals — no path outside the tree,
so it works on a clean CI checkout.

Identity is the fabricated zz9999 user (`tests/_seed.py`). No real student data.
`tests/e2e/test_route_panels.py` uses it; `scripts/capture.py` (out of tree)
builds the same shape for golden captures.
"""
import json
import os
import sqlite3
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Suites hit these for real when present; park them on a dead loopback port so
# the background kick can only fail fast without a password (mint_token seeds
# an unusable one), never reach the portal. Set before the app is imported.
os.environ.setdefault("SRM_EGRESS_BASE", "http://127.0.0.1:9")

# Features whose panel is gated on data (the ones the blob has to satisfy).
FEATURES = "hourwise,academics,fees,placement,library,campus,profile,attendance,marks"

# op -> repo fixture holding that op's payload.
FIXTURES = {
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
    "getJobCriteria": "tests/fixtures/scope_campus/placement-required.txt",
    "getWillingnessRejectReasons": "tests/fixtures/scope_campus/placement-reject-reasons.txt",
}

# The campus fixtures are alive-EMPTY envelopes ("No data found") and the
# campus tab hides itself when every card is empty, so these four get
# fabricated rows instead.
CAMPUS_ROWS = {
    "getStudentAllOfferedJobs": [
        {"jobtitle": "Software Development Engineer - I", "companyname": "Alpha Corp",
         "jobid": 4411, "stipend": "8,00,000 PA", "closingdate": "2026-12-15", "status": "Open"},
        {"jobtitle": "Product Analyst", "companyname": "Beta Ltd",
         "jobid": 4413, "stipend": "7,20,000 PA", "closingdate": "2026-12-10", "status": "Closed"}],
    "getResumeUploads": [
        {"resumename": "Resume - Oct 2026.pdf", "uploadeddate": "2026-10-28", "status": "Under review"}],
    "getLibraryTransaction": [
        {"booktitle": "Introduction to Algorithms", "authorname": "Cormen",
         "bookid": 771, "issuedate": "2026-10-02", "duedate": "2026-11-15"}],
    "getHostelDetails": {"hostelname": "Block C - 3rd Floor", "roomno": "C-204", "messdays": "Mon-Sat"},
    "getTransportDetails": {"routename": "Route 12", "morningpickup": "07:15 AM", "eveningdrop": "05:45 PM"},
    "getViewNotificationListJson": [
        {"notificationtitle": "Midsem exam schedule released", "date": "2026-11-01",
         "time": "09:00", "body": "Academic calendar updated on the portal"}],
}

# fees ledger: (op, rows) — shapes from tests/unit/test_scope_fees.py
FEE_OPS = (
    ("getFeeDetails", [
        {"feedetails": "Registration Fee##10000.00##10000.00##13-Aug-2025##2025-2026##0"},
        {"feedetails": "Tuition Fees##200000.00##200000.00##13-Aug-2025##2025-2026##0"}]),
    ("getFinanceDetails", [
        {"amount": "111000.00", "vouchertype": "Receipt", "narration": "Fee receipt",
         "voucherdate": "2025-11-21", "vouchernumber": "17174"}]),
    ("getStudentExamFeesDetails", [
        {"partpaymentapplicable": 0, "studentname": "ZZ ZED", "startdate": "21-09-2026",
         "minamount": 3150, "amounttopay": 3150, "studentid": "999999", "paidamount": 0,
         "enddate": "25-11-2026", "penaltystatus": 0, "sno": "2440869", "officeid": "20",
         "amountwithoutpenalty": 3150, "penaltydate": "24-11-2026", "ischeckvisible": "t",
         "appln_category_id": "1"}]),
)

# profile.py _KEYMAP names, fabricated values.
PROFILE = {
    "father": "Ramesh Zed", "mother": "Sita Zed", "dob": "12-Jan-2008",
    "admitteddate": "01-Aug-2025", "address": "42 Test Street, Chennai",
    "pincode": "600001", "district": "Chennai", "state": "Tamil Nadu",
    "program": "B.Tech (Computer Science and Engineering)",
    "universityname": "SRM Institute of Science and Technology",
    "sectiondesc": "A", "batch": "2025-29", "facultyadvisor": "Dr. T. Advisor",
    "academicadvisor": "Prof. S. Mentor", "personal_email_id": "zz9999@example.com",
    "studentmobile": "9999999999",
}

# Ops the gates also touch: present but empty is a real answer, absent is not.
EMPTY_OPS = ("getCummulativeAttendance", "getSubjectwiseAttendance",
             "getInternalMarkDetails", "getJobQuestions",
             "getPlacementRegistrationDetailsList", "getPlacementWillingnessRegistrationOpen")


def _data(rel):
    with open(os.path.join(REPO, rel)) as f:
        return json.load(f)


def build(now=None):
    """The scope_json dict: every gating op answered."""
    now = now or int(time.time())
    blob = {op: {"data": _data(rel), "ts": now} for op, rel in FIXTURES.items()}
    blob.update({op: {"data": rows, "ts": now} for op, rows in CAMPUS_ROWS.items()})
    blob.update({op: {"data": rows, "ts": now} for op, rows in FEE_OPS})
    for op in ("getPersonalDetails", "getStudentPersonalDetails"):  # Tools gate op
        blob[op] = {"data": dict(PROFILE), "ts": now}
    for op in EMPTY_OPS:
        blob[op] = {"data": [], "ts": now}
    return blob


def inject(data_dir, netid="zz9999"):
    """Write the blob onto the seeded user's row. Fails loudly: a silent miss
    is the 5-of-9-panels bug this fixture exists to prevent."""
    now = int(time.time())
    blob = build(now)
    conn = sqlite3.connect(os.path.join(data_dir, "srm.db"))
    try:
        cur = conn.execute(
            "UPDATE users SET scope_json=?, scope_fetched_at=? WHERE netid=?",
            (json.dumps(blob), now, netid))
        conn.commit()
        if cur.rowcount != 1:
            raise RuntimeError(f"no users row for {netid} — seed first")
        stored = conn.execute("SELECT scope_json FROM users WHERE netid=?", (netid,)).fetchone()
    finally:
        conn.close()
    if not stored or not stored[0]:
        raise RuntimeError("scope_json injection failed — users row empty")
    return len(json.loads(stored[0]))


if __name__ == "__main__":  # self-check: blob builds, every gating op present
    sys.path.insert(0, REPO)
    b = build()
    need = ["getFeeDetails", "getFinanceDetails", "getStudentExamFeesDetails",
            "getPersonalDetails", "getHourwiseAttendance", "getExamDetails",
            "getStudentAllOfferedJobs", "getLibraryTransaction", "getHostelDetails",
            "getViewNotificationListJson"]
    missing = [k for k in need if not b.get(k, {}).get("data")]
    assert not missing, f"gating ops unanswered: {missing}"
    print(f"scope fixture OK: {len(b)} ops, {len(need)}/{len(need)} gating ops answered")
