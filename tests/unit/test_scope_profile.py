"""SCOPE profile enrichment suite (app/views/profile.py) — parser, Settings
field merge, feature gate.

Checks (mission contract):
  - getPersonalDetails parser accepts the fixture's bare top-level dict, the
    per-op {"data": ..., "ts": ...} store shape, and a {Status, Message, Data}
    envelope inside either (campus-contract defensive unwrap); feature off /
    wrong type -> {}.
  - family/academic field merge: present scope fields become rows (father,
    mother, dob, admitteddate, address, universityname, section, batch),
    empty facultyadvisor/academicadvisor -> the label is ABSENT (never ""),
    and any portal value beats the scope value (scope fills gaps only).
  - the merge never invents or overwrites template group keys: every scope
    label already exists in dashboard.html's Settings groups (no row that the
    template would silently drop), and the portal's header slots (Program,
    Semester, Section as the portal names them) are untouched.
  - feature gate off -> the Settings template input is today's personal dict.
  - the profile widget itself stays name + email + register number over the
    generated blobatar: no photo input, no course line (the widget's only
    remaining inputs are the ones it renders).

Self-contained: pure functions, no server, no network, no DB, no credentials
(the repo is public, AGENTS.md). Run: .venv/bin/python tests/unit/test_scope_profile.py
"""
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from app.views.profile import (  # noqa: E402
    FIELDS,
    merge_personal,
    scope_profile,
)

_ORIG = os.environ.get("SCOPE_FEATURES")


def _features(v):
    if v is None:
        os.environ.pop("SCOPE_FEATURES", None)
    else:
        os.environ["SCOPE_FEATURES"] = v


def _restore():
    _features(_ORIG)


# what the sync actually stores: users.scope_json["getPersonalDetails"] = {"data": ..., "ts": ...}
SCOPE_STORE = {"getPersonalDetails": {"data": {
    "father": "Uma Shanker Gupta", "mother": "Alpana Gupta",
    "dob": "28-Feb-2008", "admitteddate": "30-Jul-2025",
    "address": "B-35, MANAVSTHALI APARTMENTS, VASUNDHARA ENCLAVE, Delhi",
    "program": "B.Tech.-Computer Science and Engineering with specialization in Cloud Computing [UG - FT - ACADEMIC]",
    "universityname": "SRM Engineering College, Ghazhiabad (SRM Institute of Science and Technology)",
    "semester": "III SEMESTER", "sectiondesc": "A", "batch": "2025",
    "facultyadvisor": "", "academicadvisor": "",
    # present in the live payload; must NOT reach any template input
    "studentphoto": "QUJDRA==",
}, "ts": 1760000000}}


def t_parser_accepts_bare_dict_and_status_wrapper():
    # bare top-level dict (the live fixture's shape)
    bare = {"getPersonalDetails": dict(SCOPE_STORE["getPersonalDetails"]["data"])}
    assert scope_profile(bare, enabled=True)["father"] == "Uma Shanker Gupta"
    # per-op {"data", "ts"} store shape (what sync writes)
    assert scope_profile(SCOPE_STORE, enabled=True)["semester"] == "III SEMESTER"
    # {Status, Message, Data} envelope, bare and inside the data/ts wrapper
    env = {"getPersonalDetails": {"Status": "Success", "Message": "OK", "Data":
                                  dict(SCOPE_STORE["getPersonalDetails"]["data"])}}
    assert scope_profile(env, enabled=True)["mother"] == "Alpana Gupta"
    nested = {"getPersonalDetails": {"data": {"Status": "Success", "Data":
               {"sectiondesc": "A"}}, "ts": 1}}
    assert scope_profile(nested, enabled=True)["sectiondesc"] == "A"
    # nothing usable -> {}
    assert scope_profile({"getPersonalDetails": {"data": "No data found"}},
                         enabled=True) == {}
    assert scope_profile(None, enabled=True) == {}
    assert scope_profile(SCOPE_STORE, enabled=True) != {}


def t_parser_feature_gate_off_returns_empty():
    try:
        _features("campus")          # profile slug absent -> gate off
        assert scope_profile(SCOPE_STORE) == {}
        _features("all")
        assert scope_profile(SCOPE_STORE)["father"] == "Uma Shanker Gupta"
    finally:
        _restore()


def t_family_academic_group_rows_and_empty_advisor_absent():
    fields = SCOPE_STORE["getPersonalDetails"]["data"]
    personal = merge_personal({}, fields)
    for label in ("Father Name", "Mother Name", "Date of Birth", "Admitted On",
                  "Address", "University", "Section", "Batch", "Program (Full)"):
        assert label in personal, f"missing row: {label}"
    # render-if-present: empty advisors -> label ABSENT, never an empty value
    for label in ("Faculty Advisor", "Academic Advisor"):
        assert label not in personal, f"empty advisor rendered: {label}"
        assert label in FIELDS.values(), "advisor must stay in FIELDS so a campus WITH advisors renders it"
    # the photo is never a Settings row
    assert "studentphoto" not in personal and "QUJDRA==" not in personal.values()
    # portal values win; scope fills gaps only (never overwrites portal data)
    portal = {"Program": "Computer Science and Engineering [B.Tech]",
              "Address": "Portal Street 1", "Batch": "2025"}
    merged = merge_personal(portal, fields)
    assert merged["Program"] == portal["Program"]        # portal header slot untouched
    assert merged["Program (Full)"] == fields["program"] # scope long form is its own row
    assert merged["Address"] == portal["Address"]
    assert merged["Batch"] == portal["Batch"]
    assert merged["Father Name"] == fields["father"]
    # "-" placeholder and non-strings never render a row
    assert "Batch" not in merge_personal({}, {"batch": "-"})
    assert "Section" not in merge_personal({}, {"sectiondesc": 3})
    # gate off -> identical dict (same template inputs as today)
    assert merge_personal(portal, {}) == portal


def t_every_scope_label_lands_in_a_settings_group():
    """A scope label the template does not list is a silent no-op — pin the
    contract: every FIELDS value appears in dashboard.html's groups list."""
    html = (REPO / "app/templates/dashboard.html").read_text()
    block = re.search(r"\{% set groups = \[(.*?)\] %\}", html, re.S)
    assert block, "Settings groups list not found in dashboard.html"
    for label in FIELDS.values():
        assert f'"{label}"' in block.group(1), f"Settings group missing scope label: {label}"


def t_settings_copy_leaves_portal_keys_intact():
    fields = SCOPE_STORE["getPersonalDetails"]["data"]
    portal = {"Student Name": "Aarav Mehta", "Program": "CSE [B.Tech]",
              "Semester": "III SEMESTER", "Section": "A",
              "Register No.": "RA2511028039999"}
    merged = merge_personal(portal, fields)
    for k, v in portal.items():
        assert merged[k] == v, f"portal key rewritten: {k}"
    # section/batch fill the template slot only when the portal left it empty
    assert merged["Section"] == "A" and "Batch" in merged


def t_feature_gate_off_settings_input_identical_to_today():
    portal = {"Student Name": "Aarav Mehta", "Program": "CSE [B.Tech]",
              "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
              "Register No.": "RA2511028039999"}
    try:
        _features("hourwise,academics")     # profile slug off
        assert merge_personal(portal, scope_profile(SCOPE_STORE)) == portal
    finally:
        _restore()


def t_widget_renders_blobatar_name_email_regno_only():
    """The profile widget is the generated blobatar + name + email + register
    number. No photo <img>, no course/semester/section line — the correction
    that sent this PR back."""
    html = (REPO / "app/templates/partials/widgets/profile.html").read_text()
    assert "blobatar(" in html, "blobatar is the only avatar source"
    assert "<img" not in html and "photo" not in html.lower(), "photo path must not exist"
    assert "oneliner" not in html and "dash.program" not in html, "no course line in the widget"
    for need in ('{{ student_name or netid }}', 'dash.email', 'dash.reg_no'):
        assert need in html, f"widget lost: {need}"
    # and the route hands it nothing else
    app = (REPO / "app/app.py").read_text()
    assert "profile_photo" not in app and "oneliner" not in app, \
        "route still computes a photo/one-liner input"


TESTS = [
    ("parser: bare dict + data/ts + Status wrapper", t_parser_accepts_bare_dict_and_status_wrapper),
    ("parser: feature gate off -> {}", t_parser_feature_gate_off_returns_empty),
    ("groups: family/academic rows, empty advisor absent, portal wins", t_family_academic_group_rows_and_empty_advisor_absent),
    ("settings: every scope label lands in a group", t_every_scope_label_lands_in_a_settings_group),
    ("settings: portal keys intact, section/batch gap-fill", t_settings_copy_leaves_portal_keys_intact),
    ("feature gate off -> settings input identical to today", t_feature_gate_off_settings_input_identical_to_today),
    ("widget: blobatar + name + email + reg no, no photo, no course line", t_widget_renders_blobatar_name_email_regno_only),
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
    _restore()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed ({time.monotonic() - t0:.1f}s)")
    sys.exit(1 if failed else 0)
