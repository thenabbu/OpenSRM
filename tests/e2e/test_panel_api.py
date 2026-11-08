"""P50 — the four read APIs serve what the page renders, from one view model.

The panels were HTML-only, so the offline store (Dexie) had nothing to keep.
These endpoints exist to give it a typed source — and the only way that stays
true is if both consumers come from the same computation (views.dashboard.
panel_data). So the check is a PARITY check, not a shape check: for each panel,
read a value the page displays and assert the endpoint returns that same value.

Four groups:
  parity  — page text contains the API's value, per panel (one source of truth)
  auth    — anonymous gets 401 JSON, not the page's 302 to /login
  headers — Cache-Control: no-store on every success (PII)
  gating  — SCOPE blob cleared: page 404 AND api 404 (the page's own rule),
            and the ungated panel is untouched

Runs against the shared server from scripts/ci_e2e_http.sh with a FULL seed
(seed_rich + tests/_scope_fixture), like test_route_panels.
"""
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))  # flat _seed import style of the DUTs

BASE = os.environ.get("DUT_BASE", os.environ.get("BASE_URL", "http://127.0.0.1:18181")).rstrip("/")

PASS = FAIL = 0


def chk(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return the 3xx as-is — a redirect IS the answer for an anonymous page."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get(path, token=None, follow=True):
    """(status, body text, headers dict-lowercased)."""
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Cookie", f"srm_session={token}")
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace"), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), {k.lower(): v for k, v in e.headers.items()}


def api(path, token):
    st, body, hdr = get("/api/" + path, token)
    try:
        return st, json.loads(body), hdr
    except ValueError:
        return st, None, hdr


def esc(s):
    """Jinja's autoescape for the characters a value can carry."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&#34;").replace("'", "&#39;"))


def pct_disp(attended, max_hours):
    """Attendance % as the page prints it: truncated, never rounded."""
    if not max_hours:
        return None
    tenths = (attended * 1000) // max_hours
    return f"{tenths // 10}.{tenths % 10}"


def check_attendance(token):
    st, js, hdr = api("attendance", token)
    chk("api/attendance 200 ok:true", st == 200 and js.get("ok") is True, f"got {st}")
    chk("api/attendance carries Cache-Control: no-store",
        "no-store" in hdr.get("cache-control", ""), hdr.get("cache-control"))
    if st != 200 or not js.get("ok"):
        return
    d = js["data"]
    _, page, _ = get("/attendance", token)
    courses = d.get("courses") or []
    chk("api/attendance: courses present", len(courses) >= 7, f"{len(courses)} courses")
    # every displayed course: the code AND its percent, exactly as the meter
    # prints them (the gate drives the tint off the same truncated number)
    bad = []
    for c in courses:
        want = pct_disp(c["attended"], c["max_hours"])
        if want is None:
            continue
        if c.get("pct_disp") != want:
            bad.append(f"{c['code']} api={c.get('pct_disp')} expected={want}")
        if esc(c["code"]) not in page:
            bad.append(f"{c['code']} missing from page")
    chk("api/attendance: every course pct_disp is the truncated page figure", not bad, "; ".join(bad[:3]))
    # a concrete pair the page must show: the OLDEST-risk subject and its %
    worst = min((c for c in courses if c.get("pct_disp")), key=lambda c: c["pct"])
    shown = f">{worst['pct_disp']}%" in page or f">{worst['pct_disp']} %" in page
    chk(f"page /attendance shows {worst['code']} at {worst['pct_disp']}%",
        esc(worst["code"]) in page and shown, f"code={esc(worst['code']) in page} pct={shown}")
    # monthly bars: the page's own month label must be in both
    months = d.get("monthly") or []
    chk("api/attendance: monthly rows carry the page's labels",
        all(m.get("label") and esc(m["label"]) in page for m in months) if months else False,
        f"{[m.get('label') for m in months]}")
    # timetable is DATA here, never the HTML string the page gets
    tt = d.get("timetable") or {}
    chk("api/attendance: timetable is a structured grid, not HTML",
        isinstance(tt, dict) and all(isinstance(v, dict) for v in tt.values())
        and "<div" not in json.dumps(tt), f"{type(tt).__name__}")
    # and its slots agree with the page's own timetable data
    flat = [s for day in tt.values() for s in day.values()]
    chk("api/attendance: timetable slots match the page's rendered slots",
        all(esc(s["code"]) in page for s in flat), f"{len(flat)} slots")


def check_fees(token):
    st, js, hdr = api("fees", token)
    chk("api/fees 200 ok:true", st == 200 and js.get("ok") is True, f"got {st}")
    chk("api/fees carries Cache-Control: no-store", "no-store" in hdr.get("cache-control", ""))
    if st != 200 or not js.get("ok"):
        return
    d = js["data"]
    _, page, _ = get("/fees", token)
    due = d.get("due_disp")
    chk("api/fees: total outstanding is on the page", bool(due) and esc(due) in page, f"due_disp={due!r}")
    heads = [r["head"] for y in d.get("years") or [] for r in y["rows"]]
    chk("api/fees: every fee head is on the page",
        bool(heads) and all(esc(h) in page for h in heads), f"{heads[:3]}")
    amts = [r["amt"] for y in d.get("years") or [] for r in y["rows"]]
    chk("api/fees: a fee amount is exactly the page's money string",
        bool(amts) and all(esc(a) in page for a in amts), f"{amts[:3]}")
    ledger = [e["amt"] for e in d.get("ledger") or []]
    chk("api/fees: receipt ledger amounts are on the page",
        bool(ledger) and all(esc(a) in page for a in ledger), f"{ledger[:3]}")


def check_campus(token):
    st, js, hdr = api("campus", token)
    chk("api/campus 200 ok:true", st == 200 and js.get("ok") is True, f"got {st}")
    chk("api/campus carries Cache-Control: no-store", "no-store" in hdr.get("cache-control", ""))
    if st != 200 or not js.get("ok"):
        return
    d = js["data"]
    _, page, _ = get("/campus", token)
    titles = [c["title"] for c in d.get("cards") or []]
    chk("api/campus: show true with cards", d.get("show") is True and bool(titles), f"{titles}")
    chk("api/campus: every card title is on the page",
        all(esc(t) in page for t in titles), f"{titles}")
    titles_rows = [r["title"] for c in d.get("cards") or [] for r in c.get("rows") or []]
    chk("api/campus: a placement/library row title is on the page",
        bool(titles_rows) and all(esc(t) in page for t in titles_rows), f"{titles_rows[:3]}")


def check_academics(token):
    st, js, hdr = api("academics", token)
    chk("api/academics 200 ok:true", st == 200 and js.get("ok") is True, f"got {st}")
    chk("api/academics carries Cache-Control: no-store", "no-store" in hdr.get("cache-control", ""))
    if st != 200 or not js.get("ok"):
        return
    d = js["data"]
    _, page, _ = get("/academics", token)
    cg = (d.get("cgpa") or {})
    chk("api/academics: CGPA value is on the page",
        cg.get("value") is not None and esc(cg["value"]) in page, f"value={cg.get('value')!r}")
    chk("api/academics: credits line is exactly the page's",
        bool(cg.get("credits_disp")) and esc(cg["credits_disp"]) in page, f"{cg.get('credits_disp')!r}")
    courses = d.get("courses") or {}
    overall = courses.get("overall") or {}
    pair = f"{overall.get('acq')}/{overall.get('req')}"
    chk("api/academics: acquired/required credit pair is on the page",
        overall.get("req") and pair in page, f"{pair!r}")
    subs = [r["code"] for c in courses.get("cats") or []
            for r in (c.get("completed") or []) + (c.get("pending") or [])]
    chk("api/academics: every subject code on the tab is on the page",
        bool(subs) and all(esc(c) in page for c in subs), f"{subs[:3]} of {len(subs)}")


def check_auth():
    for p in ("attendance", "fees", "campus", "academics"):
        st, js, hdr = api(p, None)
        chk(f"api/{p}: anonymous -> 401 JSON (not 302 HTML)",
            st == 401 and js and js.get("ok") is False
            and hdr.get("content-type", "").startswith("application/json")
            and "location" not in hdr,
            f"{st} {hdr.get('content-type')} loc={hdr.get('location')}")
    # the page still redirects — the API is the only JSON surface
    st, _, hdr = get("/campus", follow=False)
    chk("page /campus still 302s to /login when anonymous",
        st == 302 and hdr.get("location", "").endswith("/login"), f"{st} {hdr.get('location')}")


def check_gated(token):
    """SCOPE blob cleared: the page 404s, the API 404s too — ONE rule."""
    import _scope_fixture
    data_dir = os.environ["DATA_DIR"]
    conn = sqlite3.connect(os.path.join(data_dir, "srm.db"))
    conn.execute("UPDATE users SET scope_json=NULL, scope_fetched_at=NULL WHERE netid='zz9999'")
    conn.commit()
    conn.close()
    try:
        for p in ("campus", "academics", "fees"):
            pst, _, _ = get("/" + p, token)
            st, js, hdr = api(p, token)
            chk(f"gated {p}: page 404 AND api 404 (same rule)", pst == 404 and st == 404,
                f"page={pst} api={st}")
            chk(f"gated {p}: 404 is JSON {{ok:false,error}}",
                js is not None and js.get("ok") is False and bool(js.get("error")), f"{js}")
            chk(f"gated {p}: 404 still sends no-store",
                "no-store" in hdr.get("cache-control", ""), hdr.get("cache-control"))
        st, js, _ = api("attendance", token)
        chk("gated: /api/attendance unaffected (200, its data needs no blob)",
            st == 200 and js.get("ok") is True and bool(js["data"]["courses"]), f"got {st}")
    finally:
        _scope_fixture.inject(data_dir)


def main():
    from _seed import mint_token, require_own_server, seed_rich
    require_own_server(BASE)
    token = mint_token()
    seed_rich()
    import _scope_fixture
    _scope_fixture.inject(os.environ["DATA_DIR"])

    st, js, _ = api("campus", token)
    if st != 200:
        print(f"  [FAIL] preflight: /api/campus 200 on a full seed (got {st}: {js})")
        print("\nPANEL API: not run — the server cannot show the gated panels "
              "(SCOPE_FEATURES closed?)")
        return 1

    print(" parity (api value == page value)")
    check_attendance(token)
    check_fees(token)
    check_campus(token)
    check_academics(token)
    print(" auth")
    check_auth()
    print(" gating")
    check_gated(token)
    print(f"\nPANEL API: {PASS + FAIL} items | PASS {PASS} | FAIL {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
