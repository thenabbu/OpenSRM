"""P3.1 — route isolation: each route renders ONLY its own panel.

Before P3.1 the dashboard was one document carrying all nine panels (81% of it
hidden). This suite is the regression guard for the split: if anyone re-merges
the panels, or a template starts including a sibling, this fails.

Runs against a live server with a FULL seed (seed_rich + the fabricated scope
blob the golden harness uses) so the four data-gated panels are eligible.

DATA_DIR must be shared with the gunicorn under test. BASE_URL defaults to the
port the CI harness assigns.
"""
import importlib.util
import os
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:18181").rstrip("/")

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

PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def seed_full():
    """Seed a user whose scope data makes all nine panels eligible."""
    from tests._seed import seed_rich
    seed_rich()
    data_dir = os.environ["DATA_DIR"]
    cap_path = os.path.join(
        os.path.dirname(REPO), "..", "missions", "opensrm-preact",
        "scripts", "capture.py")
    cap_path = "/opt/data/missions/opensrm-preact/scripts/capture.py"
    if os.path.exists(cap_path):
        spec = importlib.util.spec_from_file_location("cap", cap_path)
        cap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cap)
        cap.inject_scope(data_dir)


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
    out = set()
    for name in ROUTES.values():
        if f'id="tab-{name}"' in html:
            out.add(name)
    return out


def main():
    from tests._seed import mint_token
    seed_full()
    token = mint_token()

    for path, own in ROUTES.items():
        status, html = fetch(path, token)
        chk(f"{path} returns 200", status == 200, f"got {status}")
        found = panels_in(html)
        chk(f"{path} renders its own panel ({own})", own in found, f"found {sorted(found)}")
        strays = found - {own}
        chk(f"{path} leaks no sibling panel", not strays,
            f"leaked {sorted(strays)}")

    # the old single-document behaviour must be gone for good
    status, html = fetch("/", token)
    all_but_home = set(ROUTES.values()) - {"dashboard"}
    chk("home no longer ships the other eight panels",
        not (panels_in(html) & all_but_home),
        f"still ships {sorted(panels_in(html) & all_but_home)}")

    print(f"\nROUTE PANELS: {PASS + FAIL} items | PASS {PASS} | FAIL {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
