"""P3.1 — route isolation: each route renders ONLY its own panel.

Before P3.1 the dashboard was one document carrying all nine panels (81% of it
hidden). This suite is the regression guard for the split: if anyone re-merges
the panels, or a template starts including a sibling, this fails.

Runs against a live server with a FULL seed (seed_rich + tests/_scope_fixture)
so the four data-gated panels are eligible — the blob is built inside the repo,
so this works on a clean CI checkout.

Two passes, because the app's shape is data-dependent:
  full    — every route 200 and renders exactly its own panel.
  default — the same server, scope blob cleared: /campus /academics /fees
            /tools must 404, never 200 with an empty <main>.

DATA_DIR must be shared with the gunicorn under test. BASE_URL defaults to the
port the CI harness assigns.
"""
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)  # `tests` (and `app`) are packages of the repo root
sys.path.insert(0, os.path.join(REPO, "tests"))  # flat _seed import style of the DUTs

# CI starts gunicorn BEFORE this suite, so the module-level DATA_DIR cannot
# reach that server's env (it booted with the harness's fresh dir). The gate
# therefore reads SCOPE_FEATURES off the live server instead (below).
BASE = os.environ.get("BASE_URL", os.environ.get("DUT_BASE", "http://127.0.0.1:18181")).rstrip("/")

# route -> the ONE panel id that route is allowed to render
ROUTES = {
    "/": "dashboard",
    "/attendance": "attendance",
    "/timetable": "timetable",
    "/marks": "marks",
    "/campus": "campus",
    "/academics": "academics",
    "/fees": "fees",
    "/tools": "tools",
    "/settings": "settings",
}
GATED = ("/campus", "/academics", "/fees", "/tools")
# A seeded zz9999 always has these (timetable slots, marks, personal details),
# so the gate must not touch them.
PLENTY_ANYWAY = ("/", "/attendance", "/timetable", "/marks", "/settings")

PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def scope_ops(token):
    """Op count the SERVER under test reports for its feature set. CI starts
    gunicorn before this suite runs, so the module-level DATA_DIR (handed to
    us by the runner) never reached that process — but SCOPE_FEATURES is the
    server's own read-time gate, so ask the server rather than os.environ."""
    req = urllib.request.Request(BASE + "/api/scope/status")
    req.add_header("Cookie", f"srm_session={token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode()).get("ops", 0)


def seed_full(token):
    """Seed a user whose scope data makes all nine panels eligible."""
    import _scope_fixture
    from _seed import seed_rich
    seed_rich()
    _scope_fixture.inject(os.environ["DATA_DIR"])


def fetch(path, token):
    req = urllib.request.Request(BASE + path)
    req.add_header("Cookie", f"srm_session={token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def panels_in(html):
    """Panel ids present as id="tab-<name>". Cheap, no browser needed."""
    return {n for n in ROUTES.values() if f'id="tab-{n}"' in html}


def main_panels(html):
    """Panel ids INSIDE <main> — the nav and dock name every enabled tab, so
    only the main region answers "what did this route render?"."""
    m = re.search(r"<main\b.*?</main>", html, re.S)
    return {n for n in ROUTES.values() if f'id="tab-{n}"' in m.group(0)} if m else set()


def check_full(token):
    print(" full scope (seed_rich + tests/_scope_fixture)")
    for path, own in ROUTES.items():
        status, html = fetch(path, token)
        chk(f"{path} returns 200", status == 200, f"got {status}")
        found = main_panels(html)
        # one statement: the panel is there AND no sibling is — an empty page
        # fails here instead of passing the "no leak" check trivially
        chk(f"{path} renders its own panel ({own}) and nothing else",
            found == {own}, f"found {sorted(found)}")

    # the old single-document behaviour must be gone for good
    status, html = fetch("/", token)
    all_but_home = set(ROUTES.values()) - {"dashboard"}
    chk("home no longer ships the other eight panels",
        not (panels_in(html) & all_but_home),
        f"still ships {sorted(panels_in(html) & all_but_home)}")


def check_default(token):
    """No scope data: the gated routes must say so, and the nav must not offer
    a link that 404s. Restores the full blob afterwards."""
    import _scope_fixture
    print(" default data (scope blob cleared)")
    data_dir = os.environ["DATA_DIR"]
    conn = sqlite3.connect(os.path.join(data_dir, "srm.db"))
    conn.execute("UPDATE users SET scope_json=NULL, scope_fetched_at=NULL WHERE netid='zz9999'")
    conn.commit()
    conn.close()
    try:
        status, home = fetch("/", token)
        chk("/ still 200 with no scope data", status == 200, f"got {status}")
        for path in GATED:
            status, html = fetch(path, token)
            chk(f"{path} 404s instead of serving an empty page", status == 404, f"got {status}")
            rendered = main_panels(html)
            chk(f"{path} empty response carries no panel",
                not rendered, f"rendered {sorted(rendered)}")
        chk("nav hides every gated tab when its panel is empty",
            not any(f'href="{p}"' in home for p in GATED),
            f"still linked {[p for p in GATED if f'href=\"{p}\"' in home]}")
        for path in PLENTY_ANYWAY:
            status, _ = fetch(path, token)
            chk(f"{path} unaffected by the gate", status == 200, f"got {status}")
    finally:
        _scope_fixture.inject(data_dir)


def main():
    from _seed import mint_token
    token = mint_token()
    seed_full(token)
    # A green run must mean "the app renders", never "the description is off
    # because the server's SCOPE gate is closed". This is the exact shape of
    # the old vacuous pass: no scope injected -> 4 blank pages -> 0 siblings.
    chk("server under test has SCOPE features enabled (scope blob is enough data)",
        scope_ops(token) > 0, "SCOPE_FEATURES closed on the server under test")
    if FAIL:
        print("\nROUTE PANELS: not run — the server cannot show the gated panels")
        return 1
    check_full(token)
    check_default(token)
    print(f"\nROUTE PANELS: {PASS + FAIL} items | PASS {PASS} | FAIL {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
