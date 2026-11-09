"""P7.1 read path, server side: `<body data-netid>` is the cache key.

Checks:
  - layout.session_netid() passes a valid netid through and BLANKS anything
    that is not the netid grammar (that value keys a student's IndexedDB rows,
    so a junk value must never reach the page).
  - every page template that renders a <body> consumes it — login.html must not.
  - presentation() actually passes it (source check — the render needs a DB).

Self-contained: no server, no DB, no DATA_DIR.
Run: .venv/bin/python tests/unit/test_readpath_netid.py
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.views.layout import session_netid  # noqa: E402

TEMPLATES = REPO / "app" / "templates"


def test_valid_netid_passes_through():
    assert session_netid("ng2776") == "ng2776"
    assert session_netid("ab") == "ab"          # shortest legal
    assert session_netid("a" * 20) == "a" * 20  # longest legal


def test_anything_off_grammar_is_blanked():
    # Each of these would become a cache key if it reached the page.
    for junk in (None, "", "   ", "NG2776", "ng 2776", 'ng"2776', "ng<2776",
                 "ng2776<script>", "a", "a" * 21, "ng-2776", "ng2776\n"):
        assert session_netid(junk) == "", f"{junk!r} must not survive as a cache key"


def test_every_account_template_emits_data_netid():
    emitted, missing = [], []
    for f in sorted(TEMPLATES.glob("*.html")):
        body = re.search(r"<body[^>]*>", f.read_text())
        if not body:
            continue
        (emitted if "data-netid" in body.group(0) else missing).append(f.name)

    # Positive control: the set is not empty and includes the island pages —
    # an empty `emitted` would make the assertions below assert nothing.
    assert "fees.html" in emitted and "home.html" in emitted, emitted
    assert len(emitted) >= 9, emitted
    # login.html is pre-auth: no netid exists there, so it must not claim one.
    assert missing == ["login.html"], f"pages without data-netid: {missing}"


def test_presentation_passes_the_sanitised_value():
    """The template reads `data_netid`; nothing else may define it."""
    src = (REPO / "app" / "views" / "dashboard.py").read_text()
    assert "data_netid=session_netid(netid)" in src
    assert "from .layout import LAYOUT, WIDGETS, session_netid" in src


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("ALL PASS")
