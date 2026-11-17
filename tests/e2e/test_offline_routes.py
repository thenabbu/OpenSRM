#!/usr/bin/env python3
"""W6.3 + W7.5 — the network-cut suite: all nine routes offline, two-student
isolation, four SEPARATE logout-time wipe assertions, and W7's five exit
assertions (no HTML precached is asserted by tests/unit/test_sw_precache_no_html.py;
D, E and F below are the browser half).

Self-booting (test_dash_fit pattern): fresh DATA_DIR, rich seed + the SCOPE
fixture blob, gunicorn on a free port, require_own_server guard. Served bytes are
app/static/dist — the committed build — never a vite dev server, and the seed is
the scope-enabled one: without SCOPE_FEATURES + scope_json /campus /academics
/fees /tools 404 and the legs below would pass against four blank pages.

The seed env is DERIVED, not copied: SCOPE_FEATURES comes from
app.scope.ops.FEATURES, which is the registry the server itself gates on. CI
already exports the same list; this file only needs to agree with the app, so it
reads the app.

Legs
  A. nine routes: online load (island + rows, the positive control), cut the
     network, reload -> a document IS served (not the browser's error page and
     not the "no saved copy" 503), zero page exceptions, no personal data in the
     document, and:
       * the six Dexie-backed panels paint exactly the rows they painted online
         (`/` included, from its own cache path),
       * /tools and /settings are shell-only: measured, they are served another
         panel's shell, so the assertion is "no rows and no PII", named per route.
  B. two students on ONE device: A's rows cache, cookie swaps to B, B's page must
     paint B's rows and never A's — online AND with the network cut, which is the
     case a cache key without netid would fail. Plus the raw IndexedDB proof that
     each student's rows live under their own netid.
  C. logout: IndexedDB, Cache API, push subscription, Web Storage — four named
     assertions, each with its own positive control, so a partial wipe names
     itself instead of reading as "logout is broken".
  D. W7.5-3 on its OWN profile (Leg C's logout wiped the caches this leg needs):
     a deploy — renamed entry chunk in the precache manifest, bumped cache
     version — invalidates the pre-deploy caches on activate, and the first
     load's re-warm overwrites a shell that was deliberately poisoned BEFORE the
     deploy, so an offline navigation after it is the new shell. The poisoned
     shell is the positive control: without it "not stale" proves nothing.
  E. W7.5-4: a cold start with the network cut BEFORE the first navigation paints
     the shell — no reload, no update, nothing that the skipWaiting swap could
     have force-reloaded — plus the negative control that the same cold start
     with the shell cache emptied lands on the 503 page.
  F. W7.5-5: a push delivered through Chrome's own push plumbing still shows a
     notification after every leg above has run.

Run:
  PLAYWRIGHT_BROWSERS_PATH=/path/to/ms-playwright .venv/bin/python \
      tests/e2e/test_offline_routes.py
"""
import atexit
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
DATA = "/tmp/osrm-offroutes-dut"
os.environ["DATA_DIR"] = DATA
shutil.rmtree(DATA, ignore_errors=True)

# Path to the built service worker (served no-cache, so a rewrite is picked up on reload)
SW_PATH = REPO / "app" / "static" / "sw.js"

import tests._seed as seed_mod  # noqa: E402

seed_mod.seed_rich()  # base user + rich payloads + group/slot

# DERIVED, not hand-copied: the same registry the server gates on decides what
# the seed has to enable. An explicit SCOPE_FEATURES wins (CI exports one), and
# when it is absent the suite still enables exactly the feature set the app
# ships, so a new slug cannot make four routes 404 out from under this file.
from app.scope.ops import FEATURES  # noqa: E402

os.environ.setdefault("SCOPE_FEATURES", ",".join(FEATURES))
import tests._scope_fixture as scope_fixture  # noqa: E402

assert scope_fixture.inject(DATA) > 0, "scope fixture injected nothing"
TOKEN_A = seed_mod.mint_token()

# ── student B: a second account on the same device, with its own rows ────────
B_NETID = "zz8888"
B_NAME = "Student B"
B_COURSE = "B ONLY SUBJECT"
A_COURSE = "DATA STRUCTURES AND ALGORITHMS"
# What the DOM and the cached payloads are matched on: the course CODE. The
# description only renders inside the failure/expanded state on some viewports;
# the code is in every row in every view.
A_MARK = "21CSC201J"
B_MARK = "21ZZB001J"


def seed_student_b():
    from app import app as A

    personal = {**seed_mod.PERSONAL, "Section": "B",
                "Student Name": B_NAME, "Register No.": "RA2500000001"}
    att = {"courses": [{"code": "21ZZB001J", "description": B_COURSE,
                        "max_hours": "10", "attended": "9", "absent": "1"}],
           "period": {"from": "20/Jul/2026", "to": "13/Oct/2026"},
           "monthly": [{"month": "OCT / 2026", "present": "9", "absent": "1",
                        "od_present": "0", "od_absent": "0", "ml": "0"}],
           "daily_absent": {}}
    c = A.db()
    c.execute("""INSERT OR REPLACE INTO users(netid, password, personal_details_json,
                 attendance_json, last_fetch) VALUES(?, 'unused-by-tests', ?, ?, ?)""",
              (B_NETID, json.dumps(personal), json.dumps(att), int(time.time())))
    c.commit()
    row = c.execute("SELECT attendance_json FROM users WHERE netid=?", (B_NETID,)).fetchone()
    c.close()
    assert row and row[0] and B_COURSE in row[0], "student B seed did not land"


seed_student_b()
from app.app import make_session_token  # noqa: E402

TOKEN_B = make_session_token(B_NETID)

# ── the server ──────────────────────────────────────────────────────────────
GUNICORN = os.environ.get("GUNICORN") or os.path.join(os.path.dirname(sys.executable), "gunicorn")
if not os.path.isfile(GUNICORN):
    raise SystemExit(f"FAIL[guard]: missing {GUNICORN} (run with the repo .venv's python)")
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); PORT = _s.getsockname()[1]; _s.close()
srv = subprocess.Popen(
    [GUNICORN, "-w", "1", "--threads", "4", "-b", f"127.0.0.1:{PORT}", "app.app:app"],
    cwd=str(REPO), env={**os.environ, "PYTHONPATH": str(REPO)},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = f"http://127.0.0.1:{PORT}"

# ── expected offline content, per route ─────────────────────────────────────
# row selector = the island's ROW, same as tests/e2e/route_paint.py.
ROUTES = {
    # "/" is NOT one of the seven Dexie panels (dashboard is not in db.ts's
    # RECORD_SCHEMA), so offline it rebuilds only the widgets whose feeds the
    # device holds: measured 4 of 7 boxes online-vs-offline. Asserting equality
    # here would fail on a correct build; asserting "0" would pass on a blank
    # page. "partial" = at least one widget, never more than online.
    "/":           ("dashboard",  "[data-island=dashboard] .wbox",                "partial"),
    "/attendance": ("attendance", "[data-island=attendance] .mrow",               "cache"),
    "/timetable":  ("timetable",  "[data-island=timetable] .day-panel",           "cache"),
    "/marks":      ("marks",      "[data-island=marks] > div",                    "cache"),
    "/campus":     ("campus",     "[data-island=campus] .card",                   "cache"),
    "/academics":  ("academics",  "[data-island=academics] .acad-srow",           "cache"),
    "/fees":       ("fees",       "[data-island=fees] .grid-cols-\\[auto_1px_1fr_auto\\]", "cache"),
    # Measured 2026-11-16: /shell/tools answers 200 with the DASHBOARD panel's
    # markup (its gate is falsy once the shell blanks `tools`), and /settings has
    # no shell entry at all, so the ladder falls back to /shell/dashboard. Both
    # are therefore asserted as "a shell was served, zero rows, no PII" — not as
    # six-row panels, and not skipped.
    "/tools":      ("tools",      "[data-island=tools] > li",                     "shell"),
    "/settings":   ("settings",   "[data-island=settings] [data-copy]",           "shell"),
}

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def section(title):
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)), flush=True)


# ── browser helpers ────────────────────────────────────────────────────────
SETTLED_JS = """() => {
  const is = [...document.querySelectorAll('[data-island]')];
  return {n: is.length,
          done: is.filter(e => e.dataset.mountedAt || e.dataset.hydrated).length};
}"""

ALL_STORES_EMPTY_JS = """async () => {
  const names = (await indexedDB.databases()).map(d => d.name).filter(Boolean);
  // Open the APP database by name. `indexedDB.databases()` also lists
  // workbox-expiration, whose rows are cache bookkeeping, not a student's data.
  if (!names.includes('opensrm')) return {db: null, counts: {}};
  const db = await new Promise((res, rej) => {
    const rq = indexedDB.open('opensrm');
    rq.onsuccess = () => res(rq.result);
    rq.onerror = () => rej(rq.error);
  });
  const stores = [...db.objectStoreNames];
  const counts = {};
  for (const s of stores) {
    counts[s] = await new Promise((res, rej) => {
      const rq = db.transaction(s, 'readonly').objectStore(s).count();
      rq.onsuccess = () => res(rq.result);
      rq.onerror = () => rej(rq.error);
    });
  }
  db.close();
  return {db: "opensrm", counts};
}"""


def wait_settled(page, timeout_s=20):
    end = time.time() + timeout_s
    while time.time() < end:
        st = page.evaluate(SETTLED_JS)
        if st["n"] and st["done"] == st["n"]:
            return True
        page.wait_for_timeout(250)
    return False


def rows(page, sel, tries=30):
    n = 0
    for _ in range(tries):
        n = page.locator(sel).count()
        if n:
            return n
        page.wait_for_timeout(250)
    return n


def wait_controlled(page, timeout_s=20):
    end = time.time() + timeout_s
    while time.time() < end:
        if page.evaluate("() => navigator.serviceWorker.controller !== null"):
            return True
        page.wait_for_timeout(400)
    return False


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        profile = tempfile.mkdtemp(prefix="offroutes-")
        ctx = pw.chromium.launch_persistent_context(
            profile, headless=True,
            viewport={"width": 1280, "height": 900},
            args=["--no-first-run", "--no-default-browser-check"])
        try:
            run(ctx, pw)
        finally:
            ctx.close()

    fails = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(fails)}/{len(results)} PASS")
    return 1 if fails else 0


def run(ctx, pw):
    ctx.add_cookies([{"name": "srm_session", "value": TOKEN_A,
                      "domain": "127.0.0.1", "path": "/"}])
    page = ctx.new_page()
    page_errors = []
    page.on("pageerror", lambda e: page_errors.append(str(e).splitlines()[0][:120]))

    # ══ LEG A — nine routes with the network cut ═══════════════════════════
    section("A. network cut on all nine routes")
    page.goto(BASE + "/", wait_until="domcontentloaded")
    controlled = wait_controlled(page)
    check("A0: service worker takes control of the first page",
          controlled,
          "navigator.serviceWorker.controller" if controlled else
          "never controlled; registrations=%s" % page.evaluate(
              "async () => (await navigator.serviceWorker.getRegistrations()).length"))
    page.reload(wait_until="domcontentloaded")
    wait_settled(page)

    # Warm the eight shells; the suite asserts they are there rather than
    # trusting warmShells' log line.
    shell_keys = []
    for _ in range(40):
        shell_keys = page.evaluate(
            """async () => { const ks = await caches.keys();
                 const k = ks.find(n => n === 'opensrm-shell'); if (!k) return [];
                 const c = await caches.open(k);
                 return (await c.keys()).map(r => new URL(r.url).pathname).sort(); }""")
        if len(shell_keys) >= 8:
            break
        page.wait_for_timeout(400)
    check("A1: all eight panel shells are warmed before the cut",
          len(shell_keys) >= 8, f"{len(shell_keys)} shells: {shell_keys}")

    online_rows = {}
    for route, (island, sel, _mode) in ROUTES.items():
        page.goto(BASE + route, wait_until="domcontentloaded")
        wait_settled(page)
        n = rows(page, sel)
        online_rows[route] = n
        # POSITIVE CONTROL for the cut below: the route really had rows online.
        check(f"A2 {route}: paints {island} rows online",
              n > 0 and page.locator(f"[data-island={island}]").count() > 0, f"{n} rows")
    page_errors.clear()

    for route, (island, sel, mode) in ROUTES.items():
        page.goto(BASE + route, wait_until="domcontentloaded")
        wait_settled(page)
        time.sleep(0.6)
        ctx.set_offline(True)
        served = True
        try:
            page.reload(wait_until="domcontentloaded", timeout=25000)
        except Exception as exc:  # noqa: BLE001 — a browser error page is the failure mode
            served = False
            print(f"    {route}: offline reload raised {type(exc).__name__}: {exc}".splitlines()[0])
        page.wait_for_timeout(500)
        st = page.evaluate(
            """() => ({islands: [...document.querySelectorAll('[data-island]')].map(e => e.dataset.island),
                       text: document.body ? document.body.innerText.slice(0, 4000) : '',
                       html: document.documentElement.outerHTML.length})""")
        n = rows(page, sel, tries=20) if served else 0
        ctx.set_offline(False)

        check(f"A3 {route}: offline still serves a document",
              served and st["html"] > 2000, f"{st['html']} bytes of html")
        check(f"A4 {route}: offline is not the 'no saved copy' 503",
              "no saved copy" not in st["text"], "shell ladder reached a panel shell")
        if mode == "cache":
            check(f"A5 {route}: offline paints the same rows as online",
                  n == online_rows[route], f"offline {n} vs online {online_rows[route]}")
        elif mode == "partial":
            check(f"A5 {route}: offline paints some, never more than online",
                  0 < n <= online_rows[route],
                  f"offline {n} vs online {online_rows[route]} (dashboard is not a Dexie panel)")
        else:
            check(f"A5 {route}: offline is shell-only (no {island} rows)",
                  n == 0, f"{n} rows; islands={st['islands']}")
        check(f"A6 {route}: offline carries no personal data",
              not any(x and x in st["text"] for x in ("zz9999", B_NETID, "Test Student", B_NAME,
                                                      "RA2500000000")),
              "no netid / name / register number in the served document")
        check(f"A7 {route}: zero uncaught exceptions offline",
              not page_errors, "; ".join(page_errors[:2]))
        page_errors.clear()

    # ══ LEG B — two students, one device ═══════════════════════════════════
    section("B. second-student isolation on the same device")
    # The attendance panel's default view is the GRAPH, which draws no course
    # code. The table view prints it, and the code is the marker both students'
    # payloads carry, so the view is pinned before either page loads.
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.evaluate("() => localStorage.setItem('attView', 'table')")
    page.goto(BASE + "/attendance", wait_until="domcontentloaded")
    wait_settled(page)
    rows(page, "[data-island=attendance] .mrow")
    a_text = page.inner_text("body")
    check("B1: student A's page shows A's own course", A_MARK in a_text, "positive control")

    # Same profile, same IndexedDB, different account: the cookie swap a shared
    # tablet performs when the next student signs in.
    ctx.clear_cookies()
    ctx.add_cookies([{"name": "srm_session", "value": TOKEN_B,
                      "domain": "127.0.0.1", "path": "/"}])
    page.goto(BASE + "/attendance", wait_until="domcontentloaded")
    wait_settled(page)
    rows(page, "[data-island=attendance] .mrow")
    b_text = page.inner_text("body")
    check("B2: student B sees B's rows", B_MARK in b_text, "own data rendered")
    check("B3: student B never sees A's cached rows", A_MARK not in b_text,
          "no A course anywhere on B's page")

    # With the network cut, B's page can only be B's cache. This is the leg a
    # cache key without netid fails: B would paint A's attendance.
    ctx.set_offline(True)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    b_off = page.inner_text("body")
    n_b = rows(page, "[data-island=attendance] .mrow", tries=20)
    ctx.set_offline(False)
    check("B4: offline, student B still never sees A's rows", A_MARK not in b_off,
          f"{n_b} attendance rows on the offline page")
    # And nothing at all is the DESIGNED answer here: recallNetid()/recallGroupKey()
    # refuse to guess when the device holds more than one student's meta row
    # (session.ts: `metas.length === 1`), because guessing is how B would paint
    # A's rows from A's key. So the shared device asserts zero, and "B's cache is
    # still usable" is proved on a device that has only seen B (B8-B10 below).
    check("B5: two-student device offline paints nothing rather than guessing",
          n_b == 0, f"{n_b} rows; recall refuses with {2} meta rows")

    idb = page.evaluate("""async () => {
      const open = () => new Promise((res, rej) => {
        const rq = indexedDB.open('opensrm'); rq.onsuccess = () => res(rq.result);
        rq.onerror = () => rej(rq.error); });
      const db = await open();
      const out = {};
      for (const s of ['attendance', 'marks', 'timetable', 'fees', 'campus', 'academics']) {
        const all = await new Promise((res, rej) => {
          const rq = db.transaction(s, 'readonly').objectStore(s).getAll();
          rq.onsuccess = () => res(rq.result); rq.onerror = () => rej(rq.error); });
        out[s] = all.map(r => ({netid: r.netid, groupKey: r.groupKey,
                                body: JSON.stringify(r.payload)}));
      }
      db.close();
      return out;
    }""")
    leaks = [f"{store}:{r['netid']}" for store, rs in idb.items() for r in rs
             if r["netid"] == B_NETID and A_MARK in r["body"]]
    a_own = [r for r in idb["attendance"] if r["netid"] == "zz9999"]
    check("B6: every cached row is under its own netid's key", not leaks,
          f"{sum(len(v) for v in idb.values())} rows across 6 stores, leaks={leaks[:3]}")
    b_own = [r for r in idb["attendance"] if r["netid"] == B_NETID]
    check("B7: each student's rows are cached under their own netid and none overwrote the other",
          bool(a_own) and bool(b_own)
          and all(A_MARK in r["body"] for r in a_own)
          and all(B_MARK in r["body"] for r in b_own),
          f"{len(a_own)} attendance row(s) for zz9999, {len(b_own)} for {B_NETID}")

    # ══ LEG B2 — a device that has only ever seen student B ═══════════════
    section("B2. single-student device: B's cache is real, and it is only B's")
    b_only = pw.chromium.launch_persistent_context(
        tempfile.mkdtemp(prefix="offroutes-bonly-"), headless=True,
        viewport={"width": 1280, "height": 900},
        args=["--no-first-run", "--no-default-browser-check"])
    try:
        b_only.add_cookies([{"name": "srm_session", "value": TOKEN_B,
                             "domain": "127.0.0.1", "path": "/"}])
        bp = b_only.new_page()
        bp.goto(BASE + "/attendance", wait_until="domcontentloaded")
        wait_controlled(bp)
        bp.evaluate("() => localStorage.setItem('attView', 'table')")
        bp.reload(wait_until="domcontentloaded")
        wait_settled(bp)
        n_on = rows(bp, "[data-island=attendance] .mrow")
        b_on2 = bp.inner_text("body")
        b_only.set_offline(True)
        bp.reload(wait_until="domcontentloaded")
        bp.wait_for_timeout(800)
        n_off = rows(bp, "[data-island=attendance] .mrow", tries=20)
        b_off2 = bp.inner_text("body")
        b_only.set_offline(False)
        check("B8: single-student device paints B's rows online",
              n_on > 0 and B_MARK in b_on2, f"{n_on} rows")
        check("B9: single-student device paints the same rows offline",
              n_off == n_on and n_off > 0, f"offline {n_off} vs online {n_on}")
        check("B10: and never A's rows", A_MARK not in b_off2, "B's key only")
    finally:
        b_only.close()

    # ══ LEG C — logout leaves nothing ═════════════════════════════════════
    section("C. logout: IndexedDB, Cache API, push, Web Storage")
    # Positive controls first: everything below must be NON-empty before logout,
    # or "gone afterwards" is a statement about a store that was never used.
    pre = page.evaluate("""async () => {
      const names = (await indexedDB.databases()).map(d => d.name).filter(Boolean);
      const ks = await caches.keys();
      let shell = 0;
      for (const k of ks) {
        const c = await caches.open(k);
        shell += (await c.keys()).filter(r => new URL(r.url).pathname.startsWith('/shell/')).length;
      }
      return {dbs: names, caches: ks.length, shells: shell};
    }""")
    check("C0: pre-logout state is dirty on all four fronts (control)",
          pre["dbs"] and pre["shells"] >= 8,
          f"dbs={pre['dbs']} caches={pre['caches']} shell keys={pre['shells']}")
    page.evaluate("""() => { localStorage.setItem('attView', 'table');
                             sessionStorage.setItem('pwa-banner-dismissed', '1'); }""")

    # A push subscription cannot be created in headless Chromium (no push
    # service), so the worker gets one it WILL find — the assertion is that the
    # logout path really unsubscribes what it finds, not that Chrome's own
    # subscription vanished by itself.
    worker = None
    for _ in range(30):
        worker = next((w for w in (getattr(ctx, "service_workers", None) or []) if "sw.js" in w.url), None) \
            or next((w for w in page.workers if "sw.js" in w.url), None)
        if worker:
            break
        page.wait_for_timeout(400)
    check("C1: service worker handle available for the push assertion",
          worker is not None, "context.service_workers")
    unsub_stub = """() => {
      self.__unsub = false;
      self.registration.pushManager.getSubscription = async () => ({
        endpoint: 'https://fcm.googleapis.com/fcm/send/e2e-stub',
        unsubscribe: async () => { self.__unsub = true; return true; },
      });
    }"""
    if worker:
        worker.evaluate(unsub_stub)
        check("C2: a subscription IS present before logout (control)",
              worker.evaluate("() => self.registration.pushManager.getSubscription().then(s => !!s)"),
              "stubbed in the worker")

    # The logout control exists on ONE page (settings.html). Clicking it runs
    # onLogout in the page (Dexie + shells + Web Storage) BEFORE navigating, which
    # is the path a student takes; a bare GET /logout would only exercise the SW.
    page.goto(BASE + "/settings", wait_until="domcontentloaded")
    wait_settled(page)
    page.wait_for_selector("a[href='/logout']", timeout=15000)
    page.click("a[href='/logout']")
    page.wait_for_url(re.compile(r"/login"), timeout=20000)
    page.wait_for_timeout(1500)

    after = page.evaluate(ALL_STORES_EMPTY_JS)
    dirty = {k: v for k, v in (after["counts"] or {}).items() if v}
    # The wipe is capped at WIPE_CAP_MS and the navigation is released first, so
    # a slow device finishes it AFTER /login is on screen. Poll rather than
    # sampling one instant: an instant sample would call a slow wipe a leak.
    waited = 0.0
    while dirty and waited < 6:
        page.wait_for_timeout(500)
        waited += 0.5
        after = page.evaluate(ALL_STORES_EMPTY_JS)
        dirty = {k: v for k, v in (after["counts"] or {}).items() if v}
    check("C3: logout leaves no IndexedDB rows in any store",
          not dirty, f"db left={after['db']} rows={dirty or 'none'} after {waited:.1f}s")

    cached = page.evaluate("""async () => {
      const out = [];
      for (const name of await caches.keys()) {
        const c = await caches.open(name);
        for (const req of await c.keys()) {
          const p = new URL(req.url).pathname;
          let body = '', type = '';
          if (!/\\/static\\//.test(p)) {
            const r = await c.match(req);
            if (r) { type = r.headers.get('content-type') || '';
                     body = (await r.text()).slice(0, 20000); }
          }
          out.push({cache: name, path: p, type, body});
        }
      }
      return out;
    }""")
    shell_left = [e for e in cached if e["path"].startswith("/shell/")]
    html_left = [e for e in cached if "text/html" in e["type"]]
    pii_left = [e for e in cached if any(x in e["body"] for x in
                                         ("zz9999", B_NETID, "Test Student", B_NAME, "RA2500000000"))]
    check("C4: logout leaves no shell in the Cache API", not shell_left,
          f"{len(shell_left)} shell entries; {len(cached)} cache entries total")
    check("C5: logout leaves no HTML and no personal data in the Cache API",
          not html_left and not pii_left,
          f"html={len(html_left)} pii={[e['path'] for e in pii_left][:3]}")

    if worker:
        check("C6: logout unsubscribes the push subscription",
              worker.evaluate("() => self.__unsub === true"), "SW /logout route")

    storage = page.evaluate("() => ({l: localStorage.length, s: sessionStorage.length})")
    check("C7: logout leaves no Web Storage keys", storage == {"l": 0, "s": 0},
          f"localStorage={storage['l']} sessionStorage={storage['s']}")

    # ══ LEG D — W7.5-3: a deploy invalidates the old caches; no stale shell ══
    section("D. W7.5-3: a deploy invalidates the old caches, no stale shell")

    # A deploy is measured on a device that already has the app installed, so
    # this leg gets its own profile. Leg C's logout deleted every cache on
    # purpose and destroyed its session row, and workbox does not repopulate a
    # precache it never installed -- reusing that profile measures the teardown,
    # not a deploy. A fresh profile installs the worker exactly once, which is
    # the state a returning student is in.
    ctx = pw.chromium.launch_persistent_context(
        tempfile.mkdtemp(prefix="offroutes-deploy-"), headless=True,
        viewport={"width": 1280, "height": 900},
        args=["--no-first-run", "--no-default-browser-check"])
    ctx.add_cookies([{"name": "srm_session", "value": seed_mod.mint_token(),
                      "domain": "127.0.0.1", "path": "/"}])
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded")
    check("D0: a device that already has the app is controlled by the worker",
          wait_controlled(page), "navigator.serviceWorker.controller")
    page.reload(wait_until="domcontentloaded")
    wait_settled(page)
    warmed = []
    for _ in range(40):
        warmed = page.evaluate(
            """async () => { const ks = await caches.keys();
                 const k = ks.find(n => n === 'opensrm-shell'); if (!k) return [];
                 const c = await caches.open(k);
                 return (await c.keys()).map(r => new URL(r.url).pathname).sort(); }""")
        if len(warmed) >= 8:
            break
        page.wait_for_timeout(400)
    check("D0b: eight panel shells warmed on this device", len(warmed) >= 8,
          f"{len(warmed)} shells: {warmed}")

    # What a deploy changes, from the worker's point of view: a new precache
    # manifest (a renamed dist chunk) and a new activate, which drops every cache
    # outside its allow-list (sw-template.js:86 -- CACHE_NAME, workbox-precache*,
    # opensrm-shell). The CACHE_NAME constant alone is NOT the lever: it appears
    # only in that allow-list, so bumping it renames nothing. warmShells()
    # (shell.ts:117) is the second lever: it puts every shell unconditionally, so
    # the first online load after a deploy overwrites a stale shell rather than
    # serving it.
    STALE_MARK = "W75-STALE-SHELL-MARK"
    PROBE = "/static/dist/assets/app-w75deploy2.js"
    probe_abs = REPO / "app" / PROBE.lstrip("/")

    def cache_keys():
        return sorted(page.evaluate("async () => await caches.keys()"))

    def precache_entries():
        return page.evaluate(
            """async () => {
                const ks = await caches.keys();
                const pk = ks.find(k => k.startsWith('workbox-precache'));
                if (!pk) return null;
                const c = await caches.open(pk);
                return (await c.keys()).map(r => new URL(r.url).pathname).sort();
            }""") or []

    def shell_body(name):
        return page.evaluate(
            """async (n) => {
                const c = await caches.open('opensrm-shell');
                const r = await c.match('/shell/' + n);
                return r ? await r.text() : null;
            }""", name)

    def keep(k):
        # exactly sw-template.js:86
        return (k.startswith("workbox-precache") or k == "opensrm-shell"
                or k.startswith("opensrm-v"))

    v1_entries = precache_entries()
    entry = next((u for u in v1_entries
                  if u.startswith("/static/dist/assets/app-") and u.endswith(".js")), None)
    check("D1: pre-deploy precache lists the current entry chunk",
          bool(entry), f"{len(v1_entries)} entries, entry={entry}")

    # POSITIVE CONTROL: poison the shell cache the way a previous deploy left it,
    # and prove the poison is readable before the deploy. Without this the "not
    # stale" assertions below could pass because nothing was ever stale.
    # Re-poison until the read-back shows it: warmShells() is still writing the
    # eight shells for a moment after load, and one of those writes can land on
    # top of the poison (it did, once, in CI).
    for _ in range(10):
        page.evaluate(
            """async (mark) => {
                const c = await caches.open('opensrm-shell');
                const r = await c.match('/shell/attendance');
                if (!r) return;
                const body = await r.text();
                if (body.includes('<!--' + mark + '-->')) return;
                await c.put('/shell/attendance',
                            new Response(body + '<!--' + mark + '-->',
                                         {headers: {'Content-Type': 'text/html'}}));
            }""", STALE_MARK)
        if STALE_MARK in (shell_body("attendance") or ""):
            break
        page.wait_for_timeout(300)
    check("D2: a stale shell CAN be served from the cache before the deploy (control)",
          STALE_MARK in (shell_body("attendance") or ""), "stale mark readable")

    v1_keys = cache_keys()
    droppable = [k for k in v1_keys if not keep(k)]
    check("D3: before the deploy there are caches outside the activate allow-list",
          bool(droppable), f"{droppable} of {v1_keys}")

    # ── the deploy: the entry chunk is renamed, the version marker bumps ─────
    v1_sw = SW_PATH.read_text(encoding="utf-8")

    def restore_worker():
        # Crash-safe: a Playwright timeout inside this leg must not leave a
        # rewritten sw.js and a stray asset in the tree for the next run (it did
        # once, and every later run then measured the fixture).
        SW_PATH.write_text(v1_sw, encoding="utf-8")
        probe_abs.unlink(missing_ok=True)
    atexit.register(restore_worker)

    shutil.copy2(REPO / "app" / entry.lstrip("/"), probe_abs)
    v2_sw = v1_sw.replace('"url":"%s"' % entry, '"url":"%s"' % PROBE, 1)
    v2_sw = v2_sw.replace("opensrm-v69-", "opensrm-v75-")
    if PROBE not in v2_sw or v2_sw == v1_sw:
        raise SystemExit("FAIL[setup]: the deploy simulation changed nothing in sw.js")
    SW_PATH.write_text(v2_sw, encoding="utf-8")

    # A real client hits reload sooner or later. The W7.3c guard means the new
    # worker must WAIT there: skipWaiting only fires on a FIRST install. If it
    # swapped itself, the offline legs below would be measuring the swap's own
    # forced reload instead of the caches, and would prove nothing.
    page.reload(wait_until="domcontentloaded")
    wait_settled(page)
    state = {}
    for _ in range(50):
        state = page.evaluate(
            """async () => {
                const r = await navigator.serviceWorker.getRegistration();
                return {waiting: !!r.waiting, active: r.active ? r.active.state : null};
            }""")
        if state.get("waiting"):
            break
        page.wait_for_timeout(300)
    check("D4: the new worker WAITS instead of swapping itself (W7.3c guard holds)",
          bool(state.get("waiting")), f"{state}")

    # Now put the new build into service. Messaging the waiting worker and
    # swapping under the live page hung this leg twice on a navigation that never
    # completed (the same activate that must delete caches also re-enables
    # navigation preload), and the cache state either way is identical -- what
    # assertion 3 is about is the CACHES, not the transport of the update.
    # Unregister + reload re-installs the new worker as a first install (so the
    # W7.3c guard passes it straight through to activate) while the old caches
    # stay on disk exactly as a real update would leave them.
    page.evaluate(
        """async () => {
            const reg = await navigator.serviceWorker.getRegistration();
            if (reg) await reg.unregister();
        }""")
    page.reload(wait_until="domcontentloaded")
    dropped, v2_keys = None, []
    for _ in range(50):
        v2_keys = cache_keys()
        dropped = [k for k in droppable if k in v2_keys]
        if not dropped:
            break
        page.wait_for_timeout(300)
    check("D5: the bumped worker's activate invalidated the pre-deploy caches",
          not dropped,
          f"dropped {droppable} -> left {v2_keys}" if not dropped
          else f"still present: {dropped}")

    v2_entries = []
    for _ in range(40):
        v2_entries = precache_entries()
        if PROBE in v2_entries:
            break
        page.wait_for_timeout(300)
    check("D6: the new deploy's chunk is precached after activate",
          PROBE in v2_entries, f"{len(v2_entries)} entries")

    # ── no stale shell served after the deploy ──────────────────────────────
    # The first online load after the swap is the deploy's own re-warm. Then the
    # network is cut and the page navigates AGAIN: the swap is already behind us,
    # so an offline document cannot be the swap's forced reload -- the only bytes
    # in play are the ones in the caches.
    page.reload(wait_until="domcontentloaded")
    wait_settled(page)
    for _ in range(30):
        if STALE_MARK not in (shell_body("attendance") or ""):
            break
        page.wait_for_timeout(300)
    check("D7: the deploy's first load overwrote the stale shell in the cache",
          STALE_MARK not in (shell_body("attendance") or ""), "stale mark gone")

    ctx.set_offline(True)
    served = ""
    try:
        page.goto(BASE + "/attendance", wait_until="domcontentloaded", timeout=25000)
        served = page.content()
    finally:
        ctx.set_offline(False)
    check("D8: offline shell after the deploy is NOT the stale one",
          bool(served) and STALE_MARK not in served,
          f"stale mark in served document={STALE_MARK in served}")
    check("D9: offline shell after the deploy is a real attendance shell",
          'data-island="attendance"' in served, f"{len(served)} bytes")

    # restore the tree
    restore_worker()

    # ══ LEG E — W7.5-4: cold start with the network already cut ═════════════
    section("E. W7.5-4: cold start offline paints the app shell")

    def cold_offline(url):
        """A page opened with the network cut BEFORE its first navigation.

        No reload, no controllerchange, no warm page: this is the cold start a
        student gets when the phone wakes up with no signal.
        """
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e).splitlines()[0][:120]))
        ctx.set_offline(True)
        try:
            pg.goto(BASE + url, wait_until="domcontentloaded", timeout=25000)
            pg.wait_for_timeout(1200)
            st = pg.evaluate(
                """() => ({islands: [...document.querySelectorAll('[data-island]')]
                                                .map(e => e.dataset.island),
                           text: document.body ? document.body.innerText.slice(0, 4000) : '',
                           html: document.documentElement.outerHTML.length})""")
        finally:
            ctx.set_offline(False)
        pg.close()
        return st, errs

    st, errs = cold_offline("/attendance")
    check("E1: cold offline navigation returns a document",
          st["html"] > 2000, f"{st['html']} bytes")
    # The SW's 503 says "this device has no saved copy yet"; the app's own failure
    # copy says "there is no saved copy of this panel yet" (web/src/data/failure.ts).
    # Match the SW sentence exactly, or a failed island chunk reads as a 503.
    NO_COPY = "this device has no saved copy yet"
    check("E2: cold offline is the shell, not the 'no saved copy' 503",
          NO_COPY not in st["text"], "shell ladder reached a panel shell")
    check("E3: cold offline paints the attendance island",
          "attendance" in st["islands"], f"islands: {st['islands']}")
    check("E4: cold offline carries no personal data",
          not any(x and x in st["text"] for x in ("zz9999", "Test Student", "RA2500000000")),
          "no netid / name / register number in the served document")
    check("E5: cold offline zero uncaught exceptions",
          not errs, "; ".join(errs[:2]))

    # NEGATIVE CONTROL: empty the SHELL cache and repeat the identical cold
    # start. It must now fall through the ladder to the 503 page. Without this,
    # E1-E5 would pass for any document source and prove nothing about the
    # shell cache.
    page.evaluate(
        """async () => {
            const ks = await caches.keys();
            await Promise.all(ks.filter(k => k === 'opensrm-shell').map(k => caches.delete(k)));
        }""")
    st2, _ = cold_offline("/attendance")
    check("E6: negative control - with no shell cache the same cold start is the 503 page",
          NO_COPY in st2["text"], f"{st2['html']} bytes")

    # ══ LEG F — W7.5-5: push handler still present and functional ══════════════════
    section("F. W7.5-5: push handler intact after all above")
    
    # Re-use the worker handle from Leg C, or fetch a fresh one
    # A freshly loaded page in this profile: after Leg D re-registered the worker
    # and Leg E closed its cold-start pages, the long-lived page object no longer
    # reports a worker handle.
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded")
    wait_controlled(page)
    wait_settled(page)
    def active_worker():
        cands = [w for w in page.workers if "sw.js" in w.url]
        cands += [w for w in (ctx.service_workers or []) if "sw.js" in w.url]
        for w in reversed(cands):
            try:
                if w.evaluate("() => self.serviceWorker && self.serviceWorker.state"):
                    state = w.evaluate("() => self.serviceWorker.state")
                    if state == "activated":
                        return w
            except Exception:            # a redundant worker: evaluate throws
                continue
        return None

    worker = None
    for _ in range(30):
        worker = active_worker()
        if worker:
            break
        page.wait_for_timeout(300)
    check("F1: service worker handle available for push test",
          worker is not None,
          (worker.url if worker else "none") + f" (page.workers={len(page.workers)})")

    if worker:
        # A live pushManager is what the push handler needs to reach the device.
        # Asked as a boolean: the object itself does not survive serialisation.
        check("F2: pushManager present in worker",
              bool(worker.evaluate("() => !!self.registration.pushManager")),
              "self.registration.pushManager")

        # Deliver a synthetic push via CDP (sync API) and verify showNotification was called
        # Follow test_push_sw.py pattern: replace showNotification sink, then deliver
        worker.evaluate("""() => {
            self.__shown = []; self.__errs = [];
            self.addEventListener('unhandledrejection', e => self.__errs.push(String(e.reason)));
            self.registration.showNotification = (t, o) => {
                o = o || {};
                self.__shown.push({title: t, body: o.body, tag: o.tag, url: (o.data || {}).url});
                return Promise.resolve();
            };
        }""")

        # Find the SW registration ID via CDP
        cdp = ctx.new_cdp_session(page)
        regs = []
        # Listener FIRST: enable replays the existing registrations immediately,
        # so an attached-after handler sees nothing and every push leg reports
        # "no registration ID".
        cdp.on("ServiceWorker.workerRegistrationUpdated",
               lambda e: regs.extend(e.get("registrations") or []))
        cdp.send("ServiceWorker.enable")
        reg_id = None
        for _ in range(50):
            hit = next((r for r in regs if (r.get("scopeURL") or "").startswith(BASE) and not r.get("isDeleted")), None)
            if hit:
                reg_id = hit["registrationId"]
                break
            page.wait_for_timeout(200)
        
        if reg_id:
            payload = json.dumps({"title": "W7.5 Test", "body": "push intact", "tag": "w75-push", "url": "/"})
            cdp.send("ServiceWorker.deliverPushMessage", {"origin": BASE, "registrationId": reg_id, "data": payload})
            # Poll for the notification
            shown = []
            for _ in range(30):
                shown = worker.evaluate("() => self.__shown")
                if shown:
                    break
                page.wait_for_timeout(200)
            page.wait_for_timeout(200)
            errs = worker.evaluate("() => self.__errs")
            check("F3: synthetic push delivered and notification shown",
                  len(shown) == 1 and shown[0].get("title") == "W7.5 Test",
                  f"shown={shown} errs={errs}")
        else:
            check("F3: synthetic push delivered and notification shown",
                  False, "no SW registration ID found via CDP")

if __name__ == "__main__":
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), 0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise SystemExit("FAIL[guard]: own server never came up")
        seed_mod.require_own_server(BASE)
        sys.exit(main())
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()
