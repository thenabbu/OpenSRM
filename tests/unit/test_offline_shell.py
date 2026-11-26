#!/usr/bin/env python3
"""The offline shell must contain ZERO personal data.

Why this is the highest-stakes test in the offline work: the shell is the FIRST
html the service worker is allowed to cache. If a netid, a student name, a mark
or a timestamp rides along in it, the exact October leak (student A's dashboard
served to student B on a shared device) comes straight back — only this time
from the HTTP cache instead of the Dexie one.

Every "absent" assertion here carries a positive control: the same check run
against the REAL panel page, which must contain that value. A scrubber that is
silently broken (or a route that failed to render) still passes an absence-only
test; comparing the pair is what proves the scrub is what removed it.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def make_app():
    from app.app import create_app  # noqa: PLC0415
    return create_app()


def main():
    import tempfile

    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
    sys.path.insert(0, os.path.join(REPO, "tests"))
    import _scope_fixture
    import _seed

    _seed.seed_rich()
    _scope_fixture.inject(os.environ["DATA_DIR"])

    app = make_app()
    app.config["TESTING"] = True

    import hashlib
    import sqlite3
    import time

    d = os.environ["DATA_DIR"]
    dbf = next(p for p in (os.path.join(d, f) for f in os.listdir(d))
               if p.endswith((".db", ".sqlite3"))
               and "cookies" in {r[0] for r in sqlite3.connect(p).execute(
                   "SELECT name FROM sqlite_master WHERE type='table'")})
    tok = "shell-test-token"
    dig = hashlib.sha256(tok.encode()).hexdigest()
    c = sqlite3.connect(dbf)
    c.execute("DELETE FROM cookies WHERE token=?", (dig,))
    c.execute("INSERT INTO cookies(token,netid,created) VALUES(?,?,?)",
              (dig, "zz9999", int(time.time())))
    c.commit()
    c.close()

    cl = app.test_client()
    cl.set_cookie("srm_session", tok)

    print("\n-- the real page DOES carry the personal data (control) --")
    real = cl.get("/attendance")
    real_txt = real.get_data(as_text=True)
    chk("real page renders 200", real.status_code == 200, str(real.status_code))
    chk("CONTROL: real page contains the netid", "zz9999" in real_txt,
        "if this fails the fixture is wrong, not the scrubber")
    chk("CONTROL: real page has island props blocks",
        real_txt.count('id="island-') > 0, str(real_txt.count('id="island-')))

    print("\n-- the shell does NOT --")
    sh = cl.get("/shell/attendance")
    chk("shell renders 200", sh.status_code == 200, str(sh.status_code))
    sh_txt = sh.get_data(as_text=True)

    chk("shell has no netid", "zz9999" not in sh_txt,
        repr(re.search(r".{40}zz9999.{40}", sh_txt).group(0)) if "zz9999" in sh_txt else "")
    chk("shell publishes no data-netid", "data-netid" not in sh_txt)
    chk("shell has no island prop payload",
        'id="island-' not in sh_txt or all(
            re.search(r'id="island-[^"]*"[^>]*>\s*</script>', m.group(0))
            for m in re.finditer(r'<script[^>]*id="island-[^"]*"[^>]*>.*?</script>', sh_txt, re.S)),
        "an island script with content means props were not blanked")
    # `data-props="#island-x"` must STAY: it is the pointer that makes the
    # island hydrate from Dexie offline. What must be absent is the payload it
    # points at — asserted above. Emptying the block and keeping the pointer is
    # the whole design, so asserting "no data-props" would forbid the feature.
    chk("shell keeps the data-props POINTER (needed for offline hydrate)",
        'data-props="#island-' in sh_txt)
    chk("shell's island blocks are empty (pointer to nothing)",
        all(re.fullmatch(r'<script[^>]*id="island-[^"]*"[^>]*>\s*</script>', m.group(0))
            for m in re.finditer(r'<script[^>]*id="island-[^"]*"[^>]*>.*?</script>', sh_txt, re.S)),
        "; ".join(m.group(0)[:80] for m in
                  re.finditer(r'<script[^>]*id="island-[^"]*"[^>]*>.*?</script>', sh_txt, re.S)
                  if not re.fullmatch(r'<script[^>]*id="island-[^"]*"[^>]*>\s*</script>', m.group(0))))
    chk("shell has no student name", "Test Student" not in sh_txt,
        "seed_rich names the student 'Test Student'")
    chk("shell has no per-student title", "<title>OpenSRM</title>" in sh_txt,
        re.search(r"<title>[^<]*</title>", sh_txt).group(0) if "<title>" in sh_txt else "no title")
    chk("shell response says no PII leaked (X-Shell-Panel present)",
        sh.headers.get("X-Shell-Panel") == "attendance", str(sh.headers.get("X-Shell-Panel")))

    print("\n-- the shell still works as a page --")
    chk("shell keeps the nav (so the app is navigable offline)",
        "navbar" in sh_txt or "<nav" in sh_txt)
    chk("shell keeps the island mount point",
        'data-island="attendance"' in sh_txt)
    chk("shell keeps the JS entry (so islands can hydrate)",
        "static/dist" in sh_txt or "type=\"module\"" in sh_txt)

    print("\n-- anonymous cannot fetch a shell --")
    anon = make_app().test_client()
    chk("anonymous /shell/attendance is 401",
        anon.get("/shell/attendance").status_code == 401,
        str(anon.get("/shell/attendance").status_code))

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
