"""One runnable check for _exams_view (the dashboard card's view model).

The view model reads the clock (countdown, month label), so every fixture date
here is built from a `today` the caller supplies and the module's clock is
pinned to that same value for the run. Nothing is anchored to the real
calendar: the dates are relative, so this file cannot expire, and the bottom of
the file runs it under several clocks to prove that.
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# test_audit_findings forbids test-DB files in the repo root / tests dir
with tempfile.TemporaryDirectory() as td:
    os.environ["DATA_DIR"] = td
    from app.app import _exams_view
    from app.views import dashboard as _dashboard

    def check(today):
        """Every assertion, with the fixture dates derived from `today`."""
        _real_dt, _real_date = _dashboard.datetime, _dashboard.date

        class FrozenDateTime(_real_dt):
            @classmethod
            def now(cls, tz=None):
                return cls(today.year, today.month, today.day, 12, 0, 0)

        class FrozenDate(_real_date):
            @classmethod
            def today(cls):
                return _real_date(today.year, today.month, today.day)

        _dashboard.datetime, _dashboard.date = FrozenDateTime, FrozenDate
        try:
            # Two exams on the 12th and 14th of NEXT month: same month by
            # construction (single-month label), and the gap is 12-42 days, so
            # the countdown is strictly positive whatever `today` is.
            m1 = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            d1, d2 = m1 + timedelta(days=11), m1 + timedelta(days=13)
            s1, s2 = d1.strftime("%d-%m-%Y"), d2.strftime("%d-%m-%Y")

            rows = [
                {"code": "21MAB206T", "name": "NUMERICAL METHODS AND ANALYSIS",
                 "date": s1, "session": "AN"},
                {"code": "21CSC201J", "name": "DATA STRUCTURES AND ALGORITHMS",
                 "date": s2, "session": "AN"},
            ]
            v = _exams_view(json.loads(json.dumps(rows)))   # round-trip like the DB does
            assert v is not None
            assert [r["short"] for r in v["rows"]] == [d1.strftime("%d %b"),
                                                       d2.strftime("%d %b")], v["rows"]
            assert [r["day"] for r in v["rows"]] == [str(d1.day), str(d2.day)]
            assert v["rows"][0]["dow"] == d1.strftime("%a"), v["rows"][0]["dow"]
            assert v["rows"][0]["name_disp"] == "Numerical Methods And Analysis"
            assert v["label"] == d1.strftime("%b %Y"), v["label"]
            assert v["days_until"] == (d1 - today).days, v["days_until"]
            assert v["days_until"] > 0, v["days_until"]      # exam is still ahead
            assert v["rows"][0]["session_disp"] == "AN"      # FN/AN shown as students know them
            assert _exams_view([{"code": "X", "name": "A B", "date": s1,
                                 "session": "ZZ"}])["rows"][0]["session_disp"] == "ZZ"
            # junk date falls back to the raw value, never crashes
            v2 = _exams_view([{"code": "X", "name": "A B", "date": "junk", "session": "FN"}])
            assert v2["rows"][0]["short"] == "junk" and v2["rows"][0]["dow"] == ""
            # month-range label when rows span months: last day of next month,
            # then 3 days into the following one. Asserted by prefix/suffix so
            # it holds on both the same-year ("Dec-Jan 2027") and the
            # cross-year ("Dec 2026-Jan 2027") form without copying either.
            end1 = (m1 + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            m2d = end1 + timedelta(days=3)
            v3 = _exams_view([{"code": "X", "name": "A B",
                               "date": end1.strftime("%d-%m-%Y"), "session": "AN"},
                              {"code": "Y", "name": "C D",
                               "date": m2d.strftime("%d-%m-%Y"), "session": "AN"}])
            assert "\u2013" in v3["label"], v3["label"]
            assert v3["label"].startswith(end1.strftime("%b")), v3["label"]
            assert v3["label"].endswith(m2d.strftime("%b %Y")), v3["label"]
            # source badge: slot-carrying rows = official; slotless = scribe estimate
            assert v["source"] == "Estimated", v["source"]              # all slotless
            v4 = _exams_view([{"code": "X", "name": "A B", "date": s1,
                               "session": "AN", "slot": "02:00-05:00"},
                              {"code": "Y", "name": "C D", "date": s2, "session": "AN"}])
            assert v4["source"] == "Official + est.", v4["source"]      # mixed
            v5 = _exams_view([{"code": "X", "name": "A B", "date": s1,
                               "session": "AN", "slot": "02:00-05:00"}])
            assert v5["source"] == "Official", v5["source"]             # all official
            # hall/seat pass through to the card rows (room allotment display)
            v6 = _exams_view([{"code": "X", "name": "A B", "date": s1, "session": "AN",
                               "slot": "02:00-05:00", "hall": "12", "seat": "08"}])
            assert v6["rows"][0]["hall"] == "12" and v6["rows"][0]["seat"] == "08", v6["rows"][0]
            assert _exams_view([]) is None
        finally:
            _dashboard.datetime, _dashboard.date = _real_dt, _real_date

    # Several clocks, so a date-relative file that quietly re-expires shows up
    # here instead of in CI on some future morning. The year-end one is the
    # tightest case: on the 31st the next 12th is only 12 days away.
    _today = date.today()
    for _clock in (_today, _today + timedelta(days=40),
                   date(2026, 12, 31), date(2027, 3, 15)):
        check(_clock)
        print(f"ok  exams view model (clock={_clock})")
