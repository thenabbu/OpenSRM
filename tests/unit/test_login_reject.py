"""One runnable check for login-rejection classification + sync-quota ordering.

Covers the 2026-09-30 prod incident:
  * a wrong password was reported as "captcha unreadable" and retried 3x per
    request, burning the portal's own 3-attempts-per-NetID lockout;
  * "Sync in progress" rejections consumed the per-netid sync quota, so three
    busy clicks locked an account that had never synced.

Portal wording below is verbatim from live responses captured 2026-09-30
(alert markup + message only — no page markup, no credentials, no PII).
Offline: `_req` is stubbed, so this suite never reaches the SRM portal.
"""
import ast
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# A10: offline — a held slot must refuse instantly (busy), never sit out the
# real SYNC_QUEUE_WAIT_S default; read per-request by fetch_attendance.
os.environ.setdefault("SYNC_QUEUE_WAIT_S", "0")

with tempfile.TemporaryDirectory() as td:   # test_audit_findings forbids test DBs in-tree
    os.environ["DATA_DIR"] = td
    from app import app as A
    from app import http_scraper as H

# The login page's own tokens. These are what made the old loose
# "captcha AND invalid" match fire on EVERY rejection — keep them in the
# fixture so a "simplified" classifier fails here, not in prod.
PAGE = ('<div class="invalid-feedback">Enter valid password</div>'
        '<input id="secure_captcha" name="captcha"><label>Captcha</label>')

CRED_ALERT = ("Invalid login credentials The user ID or password entered is "
              "invalid.The login attempt was unsuccessful. You have 2 out of 3 "
              "login attempts remaining.")
CAPTCHA_ALERT = "Invalid captcha. "


def rej(alert):
    return (f"<html>{PAGE}<div class=\"alert-icon-content\">"
            f"<h6 class=\"alert-heading\">Alert</h6>{alert}</div></html>")


calls = {"portal_fail": 0}
helpers = {"portal_fail_once": lambda: calls.__setitem__("portal_fail", calls["portal_fail"] + 1),
           "portal_ok": lambda: None, "save_session": lambda *a: None,
           "load_session": lambda *a: None, "clear_session": lambda *a: None,
           "set_progress": lambda *a: None}


def classify(body, attempt=1):
    """Run the real _post_login classifier over a canned response body."""
    orig = H._req
    H._req = lambda *a, **k: ("https://sp.srmist.edu.in/HRDSystem.jsp" if "HRDSystem" in body
                              else "https://sp.srmist.edu.in/LoginServlet", body.encode())
    try:
        ctx = {"t0": 0, "hp": "ph_db", "dfield": "dom", "cfield": "cptoken",
               "rdelim": "|", "ocr": "ab12cd"}
        return H._post_login(None, ctx, "zz9999", "pw", "https://sp.srmist.edu.in",
                             {}, helpers, None, attempt=attempt)
    finally:
        H._req = orig


# ── 1. classification on the three real portal outcomes ─────────────────────
_creds = classify(rej(CRED_ALERT))
assert _creds[0] == "fail" and _creds[1]["error"] == "invalid credentials — check your NetID/password", \
    "bad password must be a credentials failure, not a captcha retry"
assert _creds[1]["kind"] == "bad_credentials", f"typed kind required: {_creds[1]}"
assert calls["portal_fail"] == 0, "credentials failure is not a portal rate-limit event"

assert classify(rej(CRED_ALERT), attempt=3)[0] == "fail", \
    "credentials failure must never burn captcha retries"
assert classify(rej(CAPTCHA_ALERT), attempt=1) == ("retry", None), "bad captcha retries"
_cap3 = classify(rej(CAPTCHA_ALERT), attempt=3)
assert (_cap3[0] == "fail"
        and _cap3[1]["error"] == "login failed after 3 attempts — captcha unreadable"
        and _cap3[1]["kind"] == "bad_credentials"), "3rd captcha failure gives up"

silent = classify(PAGE)      # page re-rendered with NO alert at all
assert silent[0] == "fail" and "without an error" in silent[1]["error"], \
    "the silent-rejection branch must be reachable (it was unreachable before)"
assert silent[1]["kind"] == "portal_cooldown", f"silent rejection = portal cooldown: {silent[1]}"
assert calls["portal_fail"] == 1, "silent rejection arms the portal cooldown"
assert classify("<html>HRDSystem.jsp</html>") == ("ok", None), "success path untouched"

# tripwire: the old loose condition still matches the credentials body — this is
# WHY the classifier must key on the portal's alert text, not on page tokens
low = rej(CRED_ALERT).lower()
assert "captcha" in low and "invalid" in low, "fixture lost the tokens that caused the bug"
assert "invalid captcha" not in low, "credentials body must not contain the captcha phrase"

# ── 2. alert extraction (the log line that makes prod debuggable) ────────────
assert H._portal_alert(rej(CRED_ALERT)) == CRED_ALERT.strip()
assert H._portal_alert(rej(CAPTCHA_ALERT)) == CAPTCHA_ALERT.strip()
assert H._portal_alert(PAGE) == ""

# ── 3. sync quota is only consumed by syncs that can actually run ───────────
netid = "zzquota"
A._login_attempts.pop(netid, None)

acquired = A._scrape_lock.acquire(blocking=False)
assert acquired, "scrape lock unexpectedly held before the busy test"
try:
    busy = [A.fetch_attendance(netid, "pw") for _ in range(3)]
finally:
    A._scrape_lock.release()
assert all("Sync in progress" in r["error"] for r in busy), busy
assert netid not in A._login_attempts, "busy rejections must not consume the quota"

A.portal_health.cooldown_until = time.time() + 60
cd = A.fetch_attendance(netid, "pw")
A.portal_health.cooldown_until = 0
assert "rate-limiting our server" in cd["error"], cd
assert netid not in A._login_attempts, "cooldown rejections must not consume the quota"

A._portal_attempts[:] = [time.time()] * (A._PORTAL_CAP + 1)
bud = A.fetch_attendance(netid, "pw")
A._portal_attempts.clear()
assert "Too many portal requests" in bud["error"], bud
assert netid not in A._login_attempts, "budget rejections must not consume the quota"

A._login_attempts[netid] = [time.time() - 540] * 3   # window nearly expired
den = A.fetch_attendance(netid, "pw")
assert "Too many sync attempts" in den["error"], den
assert "10 minutes" not in den["error"], \
    f"countdown must reflect the real window, got: {den['error']}"
assert len(A._login_attempts[netid]) == 3, "denied request must not append a 4th timestamp"
cd_txt = A._netid_retry_text(netid)
assert cd_txt.endswith("seconds") and 50 <= int(cd_txt.split()[0]) <= 60, cd_txt
assert A._retry_text(time.time() - 3500, 3600) == "2 minutes"

# ── 4. audit run-1: success-only quota charge + budget floor + per-IP share ──
# admission is check-only: a wrong-password guess can't spend the victim's quota
A._login_attempts.pop("zzvictim", None)
assert A._check_rate("zzvictim") is True, "fresh account must be admitted"
assert "zzvictim" not in A._login_attempts, "admission must not charge (charge = success only)"
for _ in range(3):
    A._charge_rate("zzvictim")
assert A._check_rate("zzvictim") is False, "3 charged syncs must deny the 4th"
A._login_attempts.pop("zzvictim", None)

A._portal_attempts.clear(); A._portal_attempts_auth.clear(); A._portal_ip.clear()
# per-IP share: one rotating source can hold at most _PORTAL_IP_CAP tokens
for _ in range(A._PORTAL_IP_CAP):
    assert A._check_portal_budget("1.2.3.4") is True
assert A._check_portal_budget("1.2.3.4") is False, "per-IP share cap must reject"
assert len(A._portal_attempts) == A._PORTAL_IP_CAP, "rejected attempt must spend no token"
assert A._check_portal_budget("5.6.7.8") is True, "other IPs must still be admitted"
A._portal_attempts.clear(); A._portal_ip.clear()
# auth floor: unauth work can never drain the reserved refresh tokens
n = 0
while len(A._portal_attempts) < A._PORTAL_CAP - A._PORTAL_AUTH_FLOOR:
    assert A._check_portal_budget(f"9.9.9.{n}") is True
    n += 1
assert A._check_portal_budget("2.2.2.2") is False, "unauth must stop at CAP-FLOOR"
assert A._check_portal_budget("3.3.3.3", authorized=True) is True, "refresh floor must stay reachable"
assert A._check_portal_budget("4.4.4.4", authorized=True) is True, "auth draws from full CAP"
A._portal_attempts.clear(); A._portal_attempts_auth.clear(); A._portal_ip.clear()

# ── 5. preflight admission: atomic, bounded, no discriminator (audit run-1 #7/#14)
cl = A.app.test_client()
A._preflight_last.clear(); A._preflight_ip.clear()
# ip cap: 10 hits in-window -> 429, no thread spawned, no token spent
A._preflight_ip["127.0.0.1"] = [time.time()] * 10
r = cl.post("/api/login/preflight", json={"netid": "zzrate"})
assert r.status_code == 429, r.data
assert A._portal_attempts == [] and A._portal_attempts_auth == [] \
    and A._portal_attempts_pf == [], "429 must spend no budget token"
A._preflight_ip.clear()
# cooldown: identical {ok:true} to a fresh start — no cooldown discriminator
A._preflight_last["zzpref"] = time.time()
r = cl.post("/api/login/preflight", json={"netid": "zzpref"})
assert r.status_code == 200 and r.get_json() == {"ok": True}, r.data
assert "cooldown" not in r.get_json(), "per-netid discriminator must not leak"
# busy: a parked waiter makes the queue non-empty -> 503, no thread (all
# paths here are no-spawn, so this offline suite never reaches the portal).
# A10 redefined the refusal from `_scrape_lock.locked()` to queue depth > 0.
A._sync_queue.append(A._QueueWaiter(1))
try:
    r = cl.post("/api/login/preflight", json={"netid": "zzbusy"})
finally:
    A._sync_queue.pop()
assert r.status_code == 503, r.data
assert "zzbusy" not in A._preflight_last, "a refused preflight must not be recorded"
assert A._portal_attempts_pf == [], "the 503 must spend no preflight budget token"
# aggregate eviction: stale buckets die on the next admission sweep
A._preflight_last["zzold"] = time.time() - 700
A._preflight_ip["9.9.9.9"] = [time.time() - 700]
r = cl.post("/api/login/preflight", json={"netid": "zzpref"})  # cooldown path sweeps first
assert "zzold" not in A._preflight_last, "stale netid keys must be evicted"
assert "9.9.9.9" not in A._preflight_ip, "drained ip buckets must be evicted"
A._preflight_last.clear(); A._preflight_ip.clear()

# ── 6. captcha data-src confined to the portal host (audit run-1 #9) ─────
from app import http_scraper as H  # noqa: E402
BASE0 = f"https://{H.PORTAL_HOST}"
assert H._captcha_url("/captcha.jpg", BASE0) == f"https://{H.PORTAL_HOST}/captcha.jpg"
assert H._captcha_url(f"https://{H.PORTAL_HOST}/captcha.jpg", BASE0) == f"https://{H.PORTAL_HOST}/captcha.jpg"
# egress rewrite still works for an absolute portal URL (audit's existing behaviour)
assert H._captcha_url(f"https://{H.PORTAL_HOST}/captcha.jpg", "https://egress.example") \
    == "https://egress.example/captcha.jpg"
assert H._captcha_url("https://egress.example/captcha.jpg", "https://egress.example") \
    == "https://egress.example/captcha.jpg"
for bad in ("file:///etc/passwd", "http://169.254.169.254/x",
            "https://attacker.example/HRDSystem.jsp", "captcha.jpg"):
    try:
        H._captcha_url(bad, BASE0)
        raise AssertionError(f"data-src {bad!r} must be rejected")
    except H.HttpScraperError:
        pass

# ── 7. progress reads are attempt-token bound (audit run-1 #13) ─────────
r = cl.post("/api/login/progress", json={"netid": "zz9999"})
assert r.status_code == 400, f"netid-keyed reads must be gone, got {r.status_code}"
r = cl.post("/api/login/progress", json={"attempt": "abc123"})
assert r.status_code == 200 and r.get_json() == {"step": "", "pct": 0}, r.data
A._set_progress("abc123", "Reading captcha…", 60, netid="zz9999")
r = cl.post("/api/login/progress", json={"attempt": "abc123"})
assert r.get_json().get("step") == "Reading captcha…", r.data
r = cl.post("/api/login/progress", json={"attempt": "abc123<script>"})
assert r.status_code == 400, "attempt must be alnum-only"
A._login_progress.clear()

# ── 8. CF headers gated by edge secret, not client-assertable (#18) ─────
A.CF_EDGE_SECRET = ""
with A.app.test_request_context(headers={"cf-ray": "r1", "CF-Connecting-IP": "6.6.6.6"}):
    assert A._behind_cf() is False, "bare cf-ray must not confer edge trust"
    assert A._client_ip() != "6.6.6.6", "client-asserted IP must be ignored"
    assert A._cookie_secure() is False, "Secure flag must not be client-forgeable"
A.CF_EDGE_SECRET = "edge-s3cret"
with A.app.test_request_context(headers={"X-Edge-Secret": "edge-s3cret",
                                         "CF-Connecting-IP": "6.6.6.6",
                                         "X-Forwarded-Proto": "https"}):
    assert A._behind_cf() is True, "matching edge secret must confer trust"
    assert A._client_ip() == "6.6.6.6"
    assert A._cookie_secure() is True
with A.app.test_request_context(headers={"X-Edge-Secret": "wrong", "cf-ray": "r2"}):
    assert A._behind_cf() is False, "wrong secret must not confer trust"
A.CF_EDGE_SECRET = ""


# ── 9. typed sync results: kind→status differential, old vs new ─────────────
# The classifier this PR deletes (_login_error_code) matched substrings of
# the message text; the replacement is the kind→status table. The old
# classifier is kept here VERBATIM as the "old" side of the differential.
# The inventory is an AST walk of every {'ok': False} producer in app.py +
# http_scraper.py, so the differential covers ALL of them: typed producers
# must agree old-vs-new on every rendered message, route producers must
# carry a literal status or a kind-table lookup, and any other producer
# shape fails this suite (no new untyped return can slip past).
REPO = Path(__file__).resolve().parent.parent.parent


def _old_login_error_code(err):
    e = err.lower()
    if "invalid credentials" in e or "login failed" in e:
        return 401
    if "too many" in e or "rate-limit" in e:  # per-netid cap, per-IP cap, portal cooldown
        return 429
    return 503


# f-string holes rendered with a value each site can actually produce; every
# site's classifier-relevant words live in its constants, so one render each
# is enough (and the differential proves exactly that).
_HOLES = {
    "_netid_retry_text(netid)": "55 seconds",
    "int(cooldown / 60) + 1": "5",
    "MAX_CAPTCHA_RETRIES": "5",
    "last_err": "invalid captcha (read: ab12cd)",
    "last_err or 'silent rejection'": "portal rate-limited (silent rejection)",
}


def _render_msg(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(v.value)
            else:
                out.append(_HOLES.get(ast.unparse(v.value), "N"))
        return "".join(out)
    return None


def _is_fail(node):
    return (isinstance(node, ast.Dict) and
            any(isinstance(k, ast.Constant) and k.value == "ok" and
                isinstance(v, ast.Constant) and v.value is False
                for k, v in zip(node.keys, node.values)))


def _status_ok(node, f, depth=0):
    """Route status is an int literal or a sync_status() lookup (or a name
    bound to one in the same function) — never message-derived."""
    if depth > 4:
        return False
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sync_status":
        return True
    if isinstance(node, ast.Name) and f is not None:
        args = f.args
        pos = list(getattr(args, "posonlyargs", [])) + list(args.args)
        binds = {}
        for a, dv in zip(pos[len(pos) - len(args.defaults):], args.defaults):
            binds[a.arg] = dv
        for a, dv in zip(args.kwonlyargs, args.kw_defaults):
            if dv is not None:
                binds[a.arg] = dv
        for st in ast.walk(f):
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                binds[st.targets[0].id] = st.value
        v = binds.get(node.id)
        return v is not None and _status_ok(v, f, depth + 1)
    return False


typed, route, problems = [], [], []
for rel in ("app/app.py", "app/http_scraper.py"):
    text = (REPO / rel).read_text()
    tree = ast.parse(text)
    parents = {}
    for n in ast.walk(tree):
        for ch in ast.iter_child_nodes(n):
            parents[ch] = n
    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def enclosing(node):
        best = None
        for f in funcs:
            if f.lineno <= node.lineno <= (f.end_lineno or f.lineno):
                if best is None or f.lineno >= best.lineno:
                    best = f
        return best

    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "sync_error":
            kind = (n.args[0].value if n.args and isinstance(n.args[0], ast.Constant)
                    and isinstance(n.args[0].value, str) else None)
            msg = _render_msg(n.args[1]) if len(n.args) > 1 else None
            if kind is None or msg is None:
                problems.append(f"{rel}:{n.lineno}: sync_error site with non-literal kind/message")
            else:
                typed.append((rel, n.lineno, kind, msg))
            continue
        if isinstance(n, ast.Dict) and _is_fail(n):
            f = enclosing(n)
            if f is not None and f.name == "sync_error":
                continue  # the result-type constructor itself
            p = parents.get(n)
            if isinstance(p, ast.Tuple) and isinstance(parents.get(p), ast.Return):
                if not _status_ok(p.elts[1], enclosing(p)):
                    problems.append(f"{rel}:{n.lineno}: status neither literal nor kind-table lookup: "
                                    f"{ast.unparse(p.elts[1])}")
                route.append((rel, n.lineno))
            else:
                problems.append(f"{rel}:{n.lineno}: failure producer with no kind and no literal status")

assert not problems, "producer inventory problems:\n  " + "\n  ".join(problems)
assert typed, "no typed sync_error producers found — inventory broken"
assert set(A.KIND_STATUS) == {"bad_credentials", "rate_limited", "portal_cooldown",
                              "busy", "portal_down", "markup_changed", "internal"}, \
    f"kind table changed: {sorted(A.KIND_STATUS)}"
# the differential: old substring classifier vs new kind table, per producer
for rel, lineno, kind, msg in typed:
    old, new = _old_login_error_code(msg), A.KIND_STATUS[kind]
    assert old == new, (f"OLD/NEW status diverge at {rel}:{lineno}: kind={kind} "
                        f"old={old} new={new} msg={msg!r}")
seen = {k for _, _, k, _ in typed}
assert seen == set(A.KIND_STATUS), \
    f"kinds never produced: {sorted(set(A.KIND_STATUS) - seen)}; unknown: {sorted(seen - set(A.KIND_STATUS))}"
# untyped failure (a bare test stub) keeps the old fallback status
assert A.sync_status({"ok": False, "error": "x"}) == 503, "untyped failure must fall back to 503"
# the grep proof, as a test: no message-substring matching left in app/
_combined = (REPO / "app/app.py").read_text() + (REPO / "app/http_scraper.py").read_text()
assert "_login_error_code" not in _combined, "message-substring classifier must be gone"
for _pat in (r'\["error"\]\.lower\(', r'\["error"\]\.startswith',
             r'\["error"\]\.endswith', r'in res\["error"\]'):
    assert not re.search(_pat, _combined), f"error-text matching remains: {_pat}"
assert route, "no literal-status route producers found — inventory broken"
print(f"  ok  typed-results differential: {len(typed)} typed producers, "
      f"{len(route)} literal-status producers, old == new everywhere")

print("ok  login rejection classifier + sync quota ordering + typed-results differential")
