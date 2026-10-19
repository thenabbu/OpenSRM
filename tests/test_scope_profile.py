"""SCOPE profile enrichment suite (app/views/profile.py) — parser, photo
validation, settings field merge, dashboard one-liner, feature gate.

Checks (mission contract):
  - getPersonalDetails parser accepts the fixture's bare top-level dict, the
    per-op {"data": ..., "ts": ...} store shape, and a {Status, Message, Data}
    envelope inside either (campus-contract defensive unwrap); feature off /
    wrong type -> {}.
  - studentphoto validation: a good JPEG base64 (and a valid byte prefix of
    it, line-wrapped) renders a data: URI; garbage, non-JPEG payloads, bad
    padding and a >300KB decode all skip (empty string, never an exception);
    stored portal photo_b64 wins over the scope photo, feature off -> "".
  - family/academic field merge: present scope fields become rows (father,
    mother, dob, admitteddate, address, universityname, section, batch),
    empty facultyadvisor/academicadvisor -> the label is ABSENT (never ""),
    and any portal value beats the scope value (scope fills gaps only).
  - feature gate off -> every profile-widget template input is today's
    (personal dict identical, no photo URI, no one-liner).
  - one-liner: scope fields first, portal's existing values as fallback,
    "" when neither has anything; program capped so the line stays one row.

Self-contained: pure functions, no server, no network, no DB, no credentials
(the repo is public, AGENTS.md). Run: .venv/bin/python tests/test_scope_profile.py
"""
import base64
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.views.profile import (  # noqa: E402
    MAX_PHOTO_BYTES,
    FIELDS,
    merge_personal,
    oneliner,
    photo_uri,
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


# A JPEG-shaped payload: real magic, EOS marker, big enough that truncation
# and the size cap are testable without shipping anyone's photo (public repo).
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 512 + b"\xff\xd9"
JPEG_B64 = base64.b64encode(JPEG).decode()

# what the sync actually stores: users.scope_json["getPersonalDetails"] = {"data": ..., "ts": ...}
SCOPE_STORE = {"getPersonalDetails": {"data": {
    "father": "Uma Shanker Gupta", "mother": "Alpana Gupta",
    "dob": "28-Feb-2008", "admitteddate": "30-Jul-2025",
    "address": "B-35, MANAVSTHALI APARTMENTS, VASUNDHARA ENCLAVE, Delhi",
    "program": "B.Tech.-Computer Science and Engineering with specialization in Cloud Computing [UG - FT - ACADEMIC]",
    "universityname": "SRM Engineering College, Ghazhiabad (SRM Institute of Science and Technology)",
    "semester": "III SEMESTER", "sectiondesc": "A", "batch": "2025",
    "facultyadvisor": "", "academicadvisor": "",
    "studentphoto": JPEG_B64,
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


def t_photo_jpeg_magic_and_size_cap():
    # good payload -> data: URI
    uri = photo_uri(None, {"studentphoto": JPEG_B64}, enabled=True)
    assert uri == "data:image/jpeg;base64," + JPEG_B64, uri
    # a valid BYTE PREFIX of it (any length, incl. line-wrapped) still passes
    for cut in (8, 100, len(JPEG_B64) - 4):
        prefix = JPEG_B64[:cut]
        wrapped = prefix[:40] + "\n" + prefix[40:]
        got = photo_uri(None, {"studentphoto": prefix}, enabled=True)
        assert got.endswith(prefix), (cut, got[:40])
        assert photo_uri(None, {"studentphoto": wrapped}, enabled=True) \
            .endswith(prefix.replace("\n", "")), cut
    # garbage / wrong magic / bad padding -> skip silently (empty string)
    for bad in ("not base64!!", base64.b64encode(b"hello world").decode(),
                "AAA", JPEG_B64[:len(JPEG_B64) - 1]):
        got = photo_uri(None, {"studentphoto": bad}, enabled=True)
        assert got == "", (bad[:20], got[:40])
    # size cap: decoded > 300KB is skipped (ponytail: resize-on-sync upgrade)
    big = base64.b64encode(b"\xff\xd8" + b"\x00" * (MAX_PHOTO_BYTES + 1)).decode()
    assert photo_uri(None, {"studentphoto": big}, enabled=True) == ""
    assert photo_uri(None, {"studentphoto": JPEG_B64}, enabled=True) != ""


def t_photo_portal_first_then_scope_then_empty():
    portal = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x11" * 64).decode()
    both = {"studentphoto": JPEG_B64}
    # portal photo wins over the scope photo (never double-source, order fixed)
    assert photo_uri({"photo_b64": portal}, both, enabled=True) == \
        "data:image/jpeg;base64," + portal
    # portal empty/unusable -> scope photo; both unusable -> "" (blobatar SVG)
    assert photo_uri({"photo_b64": ""}, both, enabled=True).endswith(JPEG_B64)
    assert photo_uri({"photo_b64": "garbage"}, both, enabled=True).endswith(JPEG_B64)
    assert photo_uri(None, {"studentphoto": "junk"}, enabled=True) == ""
    # feature off -> no URI at all: today's rendering (blobatar) untouched
    assert photo_uri({"photo_b64": portal}, both, enabled=False) == ""


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


def t_oneliner_scope_first_portal_fallback():
    fields = SCOPE_STORE["getPersonalDetails"]["data"]
    portal = {"Program": "Computer Science and Engineering [B.Tech]",
              "Semester": "III SEMESTER", "Section": "A"}
    line = oneliner(fields, portal, enabled=True)
    # degree token + ellipsis: the WHOLE line fits one row (branch lives in Settings)
    assert line == "B.Tech… · III SEMESTER · Section A", line
    # scope empty -> existing portal sources still compose the line
    # (bracketed portal form '[B.Tech]' resolves to the same degree token)
    fallback = oneliner({}, portal, enabled=True)
    assert fallback == "B.Tech… · III SEMESTER · Section A", fallback
    # no degree token anywhere -> plain program, capped to one row, "…" marks it
    plain = oneliner({}, dict(portal, Program="Integrated M.Sc Physics"), enabled=True)
    assert plain.startswith("Integrated M.Sc Physics · ") and "…" not in plain.split(" · ")[0]
    long_ = oneliner({}, dict(portal, Program="X" * 40), enabled=True)
    assert long_.split(" · ")[0].endswith("…") and len(long_.split(" · ")[0]) <= 31
    # nothing anywhere -> "" (widget renders no line, never a bare separator)
    assert oneliner({}, {}, enabled=True) == ""
    assert oneliner({"father": "x"}, {}, enabled=True) == ""
    # feature off -> "" even with data on the table
    assert oneliner(fields, portal, enabled=False) == ""


def t_feature_gate_off_widget_context_identical_to_today():
    """The profile widget's template inputs with the feature off must be
    exactly today's: the portal personal dict unchanged, no photo URI, no
    one-liner -> the partial renders the blobatar SVG and its two lines."""
    portal = {"Student Name": "Aarav Mehta", "Program": "CSE [B.Tech]",
              "Batch": "2025", "Semester": "III SEMESTER", "Section": "A",
              "Register No.": "RA2511028039999"}
    try:
        _features("hourwise,academics")     # profile slug off
        fields = scope_profile(SCOPE_STORE)
        inputs = {
            "personal": merge_personal(portal, fields),
            "profile_photo": photo_uri({"photo_b64": JPEG_B64}, fields),
            "dash_oneliner": oneliner(fields, portal),
        }
        assert inputs["personal"] == portal
        assert inputs["profile_photo"] == ""
        assert inputs["dash_oneliner"] == ""
    finally:
        _restore()


TESTS = [
    ("parser: bare dict + data/ts + Status wrapper", t_parser_accepts_bare_dict_and_status_wrapper),
    ("parser: feature gate off -> {}", t_parser_feature_gate_off_returns_empty),
    ("photo: jpeg magic + byte prefix + 300KB cap", t_photo_jpeg_magic_and_size_cap),
    ("photo: portal first, scope fallback, off -> empty", t_photo_portal_first_then_scope_then_empty),
    ("groups: family/academic rows, empty advisor absent, portal wins", t_family_academic_group_rows_and_empty_advisor_absent),
    ("one-liner: scope first, portal fallback, cap", t_oneliner_scope_first_portal_fallback),
    ("feature gate off -> widget inputs identical to today", t_feature_gate_off_widget_context_identical_to_today),
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
