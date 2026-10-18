"""Campus tab suite — shape-driven SCOPE parsers, self-hiding cards, gates.

Checks (mission contract):
  - envelope parser: every alive-empty fixture (Error + message, Success +
    "No data found") -> [] with no exception; real Data (JSON string, list,
    dict) -> rows; garbage -> [] (never a 500).
  - defensive row renderer: a synthetic placement list with 4 unknown keys
    renders ALL of its values with no KeyError — unit level and through the
    real template; keyword detection for title/company/status/date/id, and
    the notification field detection on the documented names
    (notificationId/notificationtitle/notificationdate/notificationtime)
    plus the unknown-key fallback.
  - feature gates: each slug off -> its card absent; all off -> no tab
    registration (rendered HTML carries no tab-campus panel, no navbar
    button, no dock entry); an alive-empty scope -> same hidden navbar.

Self-contained: temp DATA_DIR, seeded inside the test, the eight captured
scope_campus fixtures live in tests/fixtures/scope_campus/; no server, no
network, no credentials (fabricated netid — repo is public, AGENTS.md).
Run: .venv/bin/python tests/test_scope_campus.py
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# verify76 forbids test DBs in-tree; the dir must outlive this module's
# import (checks run after it), so mkdtemp + atexit cleanup, not `with`.
_td = tempfile.mkdtemp(prefix="osrm-campus-")
atexit.register(shutil.rmtree, _td, True)
os.environ["DATA_DIR"] = _td          # direct assignment: stale env must not win
os.environ["OCR_PREWARM"] = "0"
os.environ.pop("SCOPE_FEATURES", None)  # every gate check owns its env

from app import app as A  # noqa: E402  (DATA_DIR first)
from app.views.campus import campus_view, kv_rows, line_row, rows  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "scope_campus"
NETID = "zz9999"                               # fabricated — repo is public
PERSONAL = {"Program": "B.Tech", "Batch": "2025", "Semester": "III SEMESTER",
            "Section": "A", "Student Name": "Test Student"}

# synthetic season payload (MARKED SYNTHETIC — no live SCOPE data exists)
SYNTHETIC = {
    "getStudentAllOfferedJobs": {"Status": "Success", "Data": json.dumps([
        {"jobTitle": "SDE Intern", "companyName": "Acme Corp", "status": "Open",
         "appliedDate": "12-10-2026", "jobId": "J1", "stipend": "25000",
         "unknownField": "kept-in-details"}])},
    "getLibraryTransaction": {"Status": "Success", "Data": json.dumps([
        {"bookTitle": "Clean Code", "issueDate": "01-10-2026",
         "returnDate": "15-10-2026", "bookId": "B77"}])},
    "getHostelDetails": {"Status": "Success",
                         "Data": json.dumps({"roomNo": "412", "blockName": "C"})},
    "getTransportDetails": {"Status": "Success",
                            "Data": json.dumps({"routeNumber": "SRM-1", "stopName": "Gate 2"})},
    "getViewNotificationListJson": {"Status": "Success", "Data": json.dumps([
        {"notificationId": "9", "notificationtitle": "Older notice",
         "notificationdate": "01-10-2026", "notificationtime": "09:00"},
        {"notificationId": "7", "notificationtitle": "Newer notice",
         "notificationdate": "14-10-2026", "notificationtime": "11:30"}])},
}
SYNTHETIC_AS_SYNC = {k: {"data": v, "ts": 1} for k, v in SYNTHETIC.items()}


def fx(name):
    """A captured alive-empty fixture payload (tests/fixtures/scope_campus)."""
    return json.loads((FIXTURES / f"{name}.txt").read_text())


def set_scope(scope):
    c = A.db()
    c.execute("UPDATE users SET scope_json=? WHERE netid=?",
              (json.dumps(scope), NETID))
    c.commit(); c.close()


def features(spec):
    os.environ["SCOPE_FEATURES"] = spec


def GET():
    cl = A.app.test_client()
    cl.set_cookie("srm_session", TOKEN)
    return cl.get("/").get_data(as_text=True)


c = A.db()
c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
             last_fetch, scope_json, scope_fetched_at)
             VALUES(?,?,?,?,?,?)""",
          (NETID, "x", json.dumps(PERSONAL), int(time.time()), "{}", 0))
c.commit(); c.close()
TOKEN = A.make_session_token(NETID)


# ── envelope parser ────────────────────────────────────────────────────────
def t_alive_empty_fixtures_parse_to_empty():
    for name in ("library", "hostel", "transport", "notifications",
                 "placement-jobs", "placement-required", "placement-reject-reasons",
                 "placement-resumes"):
        got = rows(fx(name))
        assert got == [], f"{name} -> {got!r}"


def t_real_envelope_shapes_parse():
    envelope = {"Status": "Success", "Message": "ok",
                "Data": json.dumps([{"a": 1}, {"b": 2}])}
    assert [sorted(r) for r in rows(envelope)] == [["a"], ["b"]]
    assert rows({"Status": "Success", "Data": [{"a": 1}]}) == [{"a": 1}]
    assert rows({"Status": "Success", "Data": {"room": "412"}}) == [{"room": "412"}]
    assert rows([{"a": 1}, "junk", None]) == [{"a": 1}]


def t_garbage_never_raises():
    for junk in (None, 0, 3.5, True, "", "not json", '{"a":', {"Data": "oops"},
                 {"Status": "Error"}):
        assert rows(junk) == [], f"{junk!r} -> {rows(junk)!r}"


# ── defensive row renderer ─────────────────────────────────────────────────
def t_unknown_keys_keep_every_value():
    synthetic = [{"zebraCount": "1", "quokka": "2", "flux": "3", "note": "4"}]
    view = campus_view({"getStudentAllOfferedJobs": synthetic}, {"placement"})
    r = view["cards"][0]["rows"][0]
    kept = [r["title"]] + [v for _, v in r["extras"]]
    assert set(kept) == {"1", "2", "3", "4"}, r
    # and through the real template: every value still in the HTML
    set_scope({"getStudentAllOfferedJobs": synthetic}); features("placement")
    html = GET()
    for v in ("1", "2", "3", "4"):
        assert f">{v}<" in html, f"value {v} missing from render"


def t_placement_field_detection():
    r = line_row(json.loads(SYNTHETIC["getStudentAllOfferedJobs"]["Data"])[0])
    assert r["title"] == "SDE Intern", r
    assert r["sub"] == "Acme Corp", r
    assert r["badge"] == "Open", r
    assert "12-10-2026" in r["meta"] and "J1" in r["meta"] and "25000" in r["meta"], r
    assert ("unknownField", "kept-in-details") in r["extras"], r


def t_notification_field_detection_and_fallback():
    rows_doc = [json.loads(SYNTHETIC["getViewNotificationListJson"]["Data"])[0]]
    r = line_row(rows_doc[0], meta_pred=lambda k: "date" in k or "time" in k)
    assert r["title"] == "Older notice", r
    assert r["meta"] == "01-10-2026 · 09:00", r
    assert ("notificationId", "9") in r["extras"], r
    # fallback: unknown key names still surface every value, no KeyError
    fb = line_row({"headline": "Title here", "stamp": "14-10-2026", "blob": "<x>"})
    assert fb["title"] == "Title here" and fb["extras"], fb
    assert {v for _, v in fb["extras"]} >= {"14-10-2026", "<x>"}, fb


def t_kv_rows_humanise_labels():
    pairs = rows({"Status": "Success", "Data": json.dumps({"roomNo": "412",
                                                           "blockName": "C",
                                                           "emptyField": ""})})
    got = kv_rows(pairs[0])
    assert got == [("Room No", "412"), ("Block Name", "C")], got


# ── cards, ordering, newest-first ──────────────────────────────────────────
def t_cards_in_contract_order():
    view = campus_view(SYNTHETIC_AS_SYNC, {"placement", "library", "campus"})
    titles = [c["title"] for c in view["cards"]]
    assert titles == ["Placement", "Library", "Hostel & transport", "Notifications"], titles
    assert view["show"] is True


def t_notifications_newest_first():
    view = campus_view(SYNTHETIC_AS_SYNC, {"campus"})
    card = next(c for c in view["cards"] if c["title"] == "Notifications")
    titles = [r["title"] for r in card["rows"]]
    assert titles == ["Newer notice", "Older notice"], titles


def t_rendered_full_tab_carries_every_value():
    set_scope(SYNTHETIC_AS_SYNC); features("all")
    html = GET()
    assert 'id="tab-campus"' in html and 'id="tab-campus-tab"' in html
    assert 'data-tab="campus"' in html          # mobile dock entry too
    for title in ("Placement", "Library", "Hostel &amp; transport", "Notifications"):
        assert f"<h3 class=\"text-base font-semibold\">{title}</h3>" in html, title
    for v in ("SDE Intern", "Acme Corp", "kept-in-details", "Clean Code", "B77",
              "412", "SRM-1", "Gate 2", "Newer notice", "Older notice"):
        assert v in html, f"{v!r} missing"
    i, j = html.find("Newer notice"), html.find("Older notice")
    assert 0 < i < j, "notifications not newest-first in the render"


# ── feature gates ──────────────────────────────────────────────────────────
def t_each_slug_off_hides_only_its_card():
    want = {"placement": "Placement", "library": "Library", "campus": "Hostel & transport"}
    for slug, title in want.items():
        feats = {"placement", "library", "campus"} - {slug}
        titles = [c["title"] for c in campus_view(SYNTHETIC_AS_SYNC, feats)["cards"]]
        assert title not in titles, f"{slug} off still renders {title}: {titles}"
        if slug == "campus":   # campus slug owns two cards (hostel+transport, notes)
            assert "Notifications" not in titles, titles
        assert titles, f"{slug} off emptied the whole tab"


def t_all_features_off_registers_no_tab():
    assert campus_view(SYNTHETIC_AS_SYNC, set())["show"] is False
    set_scope(SYNTHETIC_AS_SYNC); features("off")
    html = GET()
    assert 'id="tab-campus"' not in html, "tab registered with every slug off"
    assert 'data-tab="campus"' not in html, "dock entry registered with every slug off"


def t_alive_empty_scope_hides_the_tab():
    set_scope({op: {"data": fx(name), "ts": 1} for op, name in (
        ("getStudentAllOfferedJobs", "placement-jobs"),
        ("getLibraryTransaction", "library"),
        ("getHostelDetails", "hostel"),
        ("getTransportDetails", "transport"),
        ("getViewNotificationListJson", "notifications"))})
    features("all")                       # every slug ON, payload alive-empty
    html = GET()
    assert 'id="tab-campus"' not in html, "alive-empty scope must hide the tab"
    assert 'data-tab="campus"' not in html
    for leak in ("No data found", "No Library Transactions", "Error while fetching"):
        assert leak not in html, f"alive-empty message leaked into the UI: {leak}"


TESTS = [
    ("alive-empty fixtures -> [] (never an error)", t_alive_empty_fixtures_parse_to_empty),
    ("envelope Data as string/list/dict -> rows", t_real_envelope_shapes_parse),
    ("garbage payloads -> [] (never raises)", t_garbage_never_raises),
    ("4 unknown keys keep every value (unit + render)", t_unknown_keys_keep_every_value),
    ("placement field detection (title/company/status/date/id)", t_placement_field_detection),
    ("notification documented names + fallback", t_notification_field_detection_and_fallback),
    ("hostel/transport kv humanised labels", t_kv_rows_humanise_labels),
    ("cards in contract order", t_cards_in_contract_order),
    ("notifications newest-first", t_notifications_newest_first),
    ("full tab renders every value", t_rendered_full_tab_carries_every_value),
    ("each slug off -> only its card(s) absent", t_each_slug_off_hides_only_its_card),
    ("all slugs off -> no tab registration", t_all_features_off_registers_no_tab),
    ("alive-empty scope -> hidden navbar", t_alive_empty_scope_hides_the_tab),
]

if __name__ == "__main__":
    failed = 0
    t0 = time.monotonic()
    for name, fn in TESTS:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed ({time.monotonic() - t0:.1f}s)")
    sys.exit(1 if failed else 0)
