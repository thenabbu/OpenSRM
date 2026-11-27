#!/usr/bin/env python3
"""DUT: a FIRST sign-in must end up with the SCOPE nav without a manual reload.

The reported bug (Nov 2026): a new user signs in and sees only SP data; the
SCOPE-backed pages (Academics / Fees / Tools / Campus) appear only after they
refresh the page by hand.

The mechanism, so this test asserts the right thing:
  * /api/login returns as soon as the SP scrape lands and fires the SCOPE sync
    in the BACKGROUND, then the browser navigates to "/" immediately;
  * so "/" is rendered while scope_json is still empty, and base.html's
    `{% if academics %}` / `{% if tools %}` gates the nav entries OFF — they are
    ABSENT from the markup, not merely empty;
  * refreshing islands cannot reveal a route that is not in the DOM, which is
    why only a manual reload ever fixed it.

So this test does what the server does, in the same order: paint the dashboard
with NO scope blob, THEN write the blob and let the client's own poll notice.
It asserts on nav presence AFTER that, with no page.reload() anywhere.

Run: DATA_DIR=... DUT_BASE=http://127.0.0.1:P python tests/e2e/test_scope_first_paint.py
Needs a LIVE gunicorn on DUT_BASE sharing DATA_DIR; with no server listening it
ABORTS — an abort is not a pass.
"""
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # _fees_seed
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18181")
DATA_DIR = os.environ.get("DATA_DIR", "")

from tests._seed import mint_token, require_own_server, seed_rich

require_own_server(BASE)

FAILS, PASSES = [], []


def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  <- {detail}" if not cond and detail else ""))


# The op payloads a finished sync leaves behind.
#
# WHICH ops is asked of the RUNNING SERVER (/api/scope/status `ops` is a count;
# the tests below assert against that same count), never of this process's own
# registry: the server decides SCOPE_FEATURES, and a DUT that computes its own
# set writes a blob that is missing an op the server wants — which keeps
# scope_needs_sync() true, keeps the page 'stale', and makes a working fix look
# broken. That is exactly how this test lied during development.
#
# The ROWS come from tests/fixtures/scope (captured from the real backend)
# because the nav gates are the panel VIEW MODELS, not op presence.
_FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tests", "fixtures", "scope")

# Op names the server can want, taken from the app's catalog. The SUBSET that is
# actually enabled is discovered from the server below.
ROWS = {
    "getExamDetails": "exam-details.json",
    "getStudentExamProvisionalResult": "exam-provisional.json",
    "getStudentExamRevaluationResult": "exam-revaluation.json",
}

# These ops have no JSON fixture; their shapes live in Python in the fees DUT,
# which is the source of truth for what the fees view model accepts. Importing
# them beats copying row shapes into a second place that can silently rot.
def _row_data(op):
    try:
        import _fees_seed as F
    except Exception:
        return None
    return {"getFeeDetails": getattr(F, "DUES_FEES", None),
            "getFinanceDetails": getattr(F, "FIN", None)}.get(op)


def _make_blob(op_names):
    """A finished sync's blob for exactly `op_names`: {op: {"data", "ts"}}.

    Each entry is a BARE payload (sync.py stores `{"data": <the op's own
    Data>, "ts": ...}`) — wrapping the SOAP envelope here makes every view
    model read the wrong level and return None, hiding the nav with a
    perfectly "complete" blob.
    """
    out = {}
    for op in op_names:
        fx = ROWS.get(op)
        if fx:
            with open(os.path.join(_FIX, fx), encoding="utf-8") as fh:
                out[op] = {"data": json.load(fh), "ts": int(time.time())}
        else:
            shared = _row_data(op)
            out[op] = {"data": shared if shared is not None else [],
                       "ts": int(time.time())}
    return out


def write_scope_blob(op_names, netid="zz9999"):
    blob = _make_blob(op_names)
    c = db()
    c.execute("UPDATE users SET scope_json=?, scope_fetched_at=? WHERE netid=?",
              (json.dumps(blob), int(time.time()), netid))
    c.commit()
    c.close()
    return len(blob)


def db():
    c = sqlite3.connect(os.path.join(DATA_DIR, "srm.db"))
    c.row_factory = sqlite3.Row
    return c




def clear_scope(netid="zz9999"):
    c = db()
    c.execute("UPDATE users SET scope_json='{}', scope_fetched_at=NULL WHERE netid=?", (netid,))
    c.commit()
    c.close()


def server_ops(token):
    """The op names the RUNNING server wants, straight from /api/scope/status.

    Never derived locally: SCOPE_FEATURES is the server's to decide, and a blob
    built from this process's own registry is missing whatever the server has
    enabled beyond it — which pins the account 'stale' and fails a working fix.
    """
    import urllib.request
    req = urllib.request.Request(BASE + "/api/scope/status")
    req.add_header("Cookie", f"srm_session={token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.load(r)
    ops = body.get("op_names")
    assert ops, f"server did not report op_names: {body}"
    return ops


NAV = {
    "academics": 'a[href="/academics"]',
    "fees": 'a[href="/fees"]',
    "tools": 'a[href="/tools"]',
}


def nav_present(page):
    return {k: page.locator(sel).count() for k, sel in NAV.items()}


def main():
    from playwright.sync_api import sync_playwright

    seed_rich()
    clear_scope()                      # THE first-sign-in state
    token = mint_token()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        ctx.add_cookies([{"name": "srm_session", "value": token, "url": BASE}])
        # /api/scope/status: let the real endpoint answer, but keep the page
        # painting with no blob long enough to reproduce the report.
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded")

        before = nav_present(page)
        print("  nav before the SCOPE data lands:", before)
        check("reproduces the report: no SCOPE nav on a first paint with no blob",
              all(v == 0 for v in before.values()), str(before))
        check("the SP data IS there (the half of the report that always worked)",
              page.locator('[data-island="dashboard"]').count() == 1)

        # The background sync finishes. NO page.reload() on purpose: the bug was
        # that only a reload helped, so a reload here would prove nothing.
        written = write_scope_blob(server_ops(token))
        body = page.locator("body").get_attribute("data-scope-sync")

        # The page polls /api/scope/status itself (startScopePoll, main.ts) and
        # adopts the nav when the blob lands. A page that arrived 'complete'
        # has no poll armed — which is the honesty check below, not a workaround:
        # a first sign-in ALWAYS arrives mid-sync because /api/login fires the
        # trigger one line before the browser navigates to "/".
        check("the blob we wrote covers every op the server wants",
              written > 0, f"{written} ops")
        check("the page arrived mid-sync, so its poll is armed (first-sign-in state)",
              body in ("stale", "running"), f"data-scope-sync={body!r}")

        try:
            page.wait_for_selector('a[href="/academics"]', timeout=25000)
        except Exception:
            pass

        after = nav_present(page)
        print("  nav after the SCOPE data lands:", after)
        check("Academics nav appears without a reload", after["academics"] > 0, str(after))
        check("Fees nav appears without a reload", after["fees"] > 0, str(after))
        check("Tools nav appears without a reload", after["tools"] > 0, str(after))
        # Two bars, not three: base.html renders the desktop navbar and the
        # dock for academics/fees, but the dock has NO tools entry (it caps at
        # five tabs and Settings lives in the gear) — asserting 3 was this
        # test's own bug, not the app's.
        check("both bars that carry it got it (desktop navbar + dock)",
              after["academics"] == 2, f"academics anchors = {after['academics']}")
        check("the dock entry for Academics is a working link",
              page.locator('.dock a[href="/academics"]').count() == 1)

        # The user can actually use it: follow the Tools row to a real page.
        page.goto(BASE + "/tools", wait_until="domcontentloaded")
        check("/tools renders its rows once the blob is there",
              page.locator('[data-tool-slug]').count() >= 1,
              f"rows={page.locator('[data-tool-slug]').count()}")

        # The "loading" state only exists DURING a sync: with the blob gone and
        # nothing running, /tools is honestly a 404 again (the page's own gate,
        # which /api/tools/island now shares). Assert that pairing, not a
        # message that must never appear once the sync is over.
        clear_scope()
        r = page.goto(BASE + "/tools", wait_until="domcontentloaded")
        check("no blob and no sync: /tools is the honest 404, not a blank 200",
              r is not None and r.status == 404, f"status={r.status if r else None}")
        api = page.evaluate("fetch('/api/tools/island').then(r=>r.status)")
        check("...and its API agrees with the page (404 too, one rule)",
              api == 404, f"api={api}")

        browser.close()

    print(f"\n{len(PASSES)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED: " + "; ".join(FAILS))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
