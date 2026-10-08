#!/usr/bin/env python3
"""DUT: Teachers (faculty map) card renders on the dashboard home tab.

Run (server must be up on DUT_BASE with the SAME DATA_DIR):
  DATA_DIR=/tmp/osrm-fb-dut gunicorn -w 1 --threads 4 -b 127.0.0.1:18177 app.app:app &
  DATA_DIR=/tmp/osrm-fb-dut DUT_BASE=http://127.0.0.1:18177 .venv/bin/python tests/test_feedback_dut.py

Seeds a FABRICATED faculty map + courses (synthetic staff names, never real
portal ids), asserts the card renders (header, badge, staff, code chips,
visibility), asserts the empty-map negative control, and screenshots both
viewports to /tmp/fb-dut-shots/.
"""
import json
import os
import sys
import time

BASE = os.environ.get("DUT_BASE")
DATA_DIR = os.environ.get("DATA_DIR")
if not BASE or not DATA_DIR:
    sys.exit("FAIL: pass DATA_DIR + DUT_BASE inline on every invocation (no setdefault)")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
PLAYWRIGHT_BROWSERS_PATH = os.environ.get(
    "PLAYWRIGHT_BROWSERS_PATH", "/opt/data/cache/scratch/pw-browsers")

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name} {detail}")


FACULTY = {
    "DATA STRUCTURES AND ALGORITHMS": {
        "subject_id": "90001",
        "staff": [["50001", "Dr.Test Alpha-Theory"], ["50002", "Dr.Test Beta-Theory"]]},
    "PROFESSIONAL ETHICS": {
        "subject_id": "90002",
        "staff": [["50003", "Dr.Test Gamma-Practical"]]},
    "GHOST SUBJECT": {"subject_id": "90003", "staff": [["0", "Unknown"]]},
}
COURSES = [{"code": "21CSC201J", "name": "DATA STRUCTURES AND ALGORITHMS", "credits": 4},
           {"code": "21LEM201T", "name": "PROFESSIONAL ETHICS", "credits": 0}]
PERSONAL = {"Program": "Computer Science and Engineering Cloud Computing [B.Tech]",
            "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
            "Student Name": "Test Student", "Register No.": "RA2500000000"}


def seed():
    from app import app as A
    now = int(time.time())
    c = A.db()
    c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
                 attendance_json, faculty_map_json, last_fetch) VALUES(?,?,?,?,?,?)""",
              ("ng2776", "unused-by-tests", json.dumps(PERSONAL),
               json.dumps({"courses": COURSES, "monthly": [], "period": None, "daily_absent": {}}),
               json.dumps(FACULTY), now))
    c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
                 attendance_json, faculty_map_json, last_fetch) VALUES(?,?,?,?,?,?)""",
              ("zz9999", "unused-by-tests", json.dumps(PERSONAL),
               json.dumps({"courses": COURSES, "monthly": [], "period": None, "daily_absent": {}}),
               "{}", now))
    c.commit(); c.close()


def run():
    from playwright.sync_api import sync_playwright

    from app.app import make_session_token
    tok = make_session_token("ng2776")
    tok2 = make_session_token("zz9999")
    os.makedirs("/tmp/fb-dut-shots", exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=None,
                                     args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies([{"name": "srm_session", "value": tok, "url": BASE}])
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="networkidle")
        content = page.content()

        check("Teachers header", "Teachers" in content)
        check("badge count 2 (Unknown hidden)", ">2</span>" in content or "2</span>" in content)
        check("staff name rendered", "Dr.Test Alpha" in content)
        check("second staff rendered", "Dr.Test Beta" in content)
        check("kind label (Practical)", "(Practical)" in content)
        check("code chip", "21CSC201J" in content and "21LEM201T" in content)
        check("source footnote", "From the mid-sem feedback form" in content)
        # subject names title-cased
        check("subject title-case", "Data Structures And Algorithms" in content)

        # ── CTA button opens the explainer modal; modal shows exact plan ──
        check("CTA rendered", "Auto-fill mid-sem feedback" in content)
        check("no inline preview details anymore", "fb-plan" not in content)
        check("modal in DOM (closed)", page.locator("#fb-modal").get_attribute("open") is None)
        page.locator("#fb-cta").click()
        page.wait_for_selector("#fb-modal[open]")
        check("modal opens on CTA click", page.locator("#fb-modal").get_attribute("open") is not None)
        mcontent = page.locator("#fb-modal").inner_text()
        check("modal explains opt-in", "Opt-in" in mcontent)
        check("modal lists mechanics", "EXCELLENT" in mcontent and 'comment is "none"' in mcontent)
        check("modal shows teacher", "Dr.Test Alpha (Theory)" in mcontent)
        check("modal shows comment none", 'comment “none”' in mcontent)
        check("modal per-subject list", "Data Structures And Algorithms" in mcontent)
        box = page.locator("#fb-modal").bounding_box()
        check("modal visible", box is not None and box["height"] > 100, str(box))
        # touch targets inside the modal
        h = page.evaluate("() => document.getElementById('fb-submit').getBoundingClientRect().height")
        check("confirm button ~44px touch target", h >= 42, str(h))  # btn-sm min-h-11: 42-44px rendered
        page.screenshot(path="/tmp/fb-dut-shots/modal_desktop.png")

        # card visible: the source footnote lives inside the card — a real
        # bounding box proves the card painted (None = display:none ancestor)
        foot = page.get_by_text("From the mid-sem feedback form")
        fbox = foot.bounding_box()
        check("card visible", fbox is not None and fbox["height"] > 0 and fbox["width"] > 100, str(fbox))
        hdr = page.get_by_text("Teachers", exact=True)
        hbox = hdr.bounding_box()
        check("header visible", hbox is not None and hbox["height"] > 0, str(hbox))

        # negative control: user with empty faculty map must NOT render the card
        ctx2 = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx2.add_cookies([{"name": "srm_session", "value": tok2, "url": BASE}])
        page2 = ctx2.new_page()
        page2.goto(BASE + "/", wait_until="networkidle")
        content2 = page2.content()
        check("negative control: no Teachers card", "From the mid-sem feedback form" not in content2)
        check("negative control: no CTA", "fb-cta" not in content2)
        check("negative control: page still renders", "Subjects" in content2 or "Attendance" in content2)

        # clean PR screenshot: modal open, no interaction yet
        page.screenshot(path="/tmp/fb-dut-shots/dash_desktop.png", full_page=True)

        # opt-in confirm with NO cached portal session -> honest 400, no portal contact
        page.locator("#fb-submit").click()
        page.wait_for_function(
            "() => { const t = document.getElementById('fb-status').textContent;"
            " return t.includes('session') || t.includes('failed') || t.includes('error'); }")
        status = page.locator("#fb-status").text_content() or ""
        check("submit reports honest error (no session)",
              "session expired" in status, repr(status))
        check("status styled as error",
              "text-error" in (page.locator("#fb-status").get_attribute("class") or ""))
        check("error toast shown", not page.locator("#error-toast").evaluate("el => el.classList.contains('hidden')"))
        check("button re-enabled", page.locator("#fb-submit").is_enabled())

        # mobile viewport
        mctx = browser.new_context(viewport={"width": 393, "height": 851}, device_scale_factor=2.75)
        mctx.add_cookies([{"name": "srm_session", "value": tok, "url": BASE}])
        mpage = mctx.new_page()
        mpage.goto(BASE + "/", wait_until="networkidle")
        mpage.locator("#fb-cta").click()  # modal open in the shot; overflow sees the worst case
        mpage.screenshot(path="/tmp/fb-dut-shots/dash_mobile.png", full_page=True)
        # horizontal overflow check at 393
        overflow = mpage.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check("no horizontal overflow @393", overflow <= 0, f"scrollWidth-clientWidth={overflow}")
        browser.close()


seed()
run()
print(f"\n{'ALL PASS' if not FAILS else 'FAILED: %s' % FAILS}")
sys.exit(1 if FAILS else 0)
