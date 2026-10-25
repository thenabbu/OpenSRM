"""create_app factory suite — import side effects moved into the factory.

Contract (block A16 / refactor-app-factory):
  * create_app(config) with a typed AppConfig (app/config.py) — env read once
  * data-dir + secret creation, schema migrations and the OCR prewarm thread
    live INSIDE create_app (OCR_PREWARM=0 opts out of the prewarm)
  * the module-level app keeps `gunicorn app.app:app` and the set-DATA_DIR-
    before-import contract working (test C1 fresh-DB boot included)
  * two create_app calls with different data dirs give ISOLATED apps:
    each boots its own schema, owns its own secret, and a session cookie
    minted for app A is refused by app B (cookies live in the DB)

Self-contained: temp DATA_DIRs, seed and mint inside; no server, no
network, no portal. Runner style: check(name, ok, detail) (test_healthz).
"""
import atexit
import os
import shutil
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

TMP = tempfile.mkdtemp(prefix="osrm-factory-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["DATA_DIR"] = TMP          # module-level app boots here
os.environ["OCR_PREWARM"] = "0"       # opt out of the prewarm for this suite

import app.app as A                    # noqa: E402  (import runs create_app())
import app.db as DB                   # noqa: E402
from app.config import AppConfig       # noqa: E402
from app.migrations import _registry   # noqa: E402  (derive, never pin a literal)

FAILS = []
TOTAL = [0]


def check(name, ok, detail=""):
    TOTAL[0] += 1
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


# fabricated netids only — the repo is public (AGENTS.md)
NETID_A = "zz9999"
NETID_B = "xx0001"


def make_config(dirpath):
    return AppConfig(data_dir=dirpath,
                     db_path=os.path.join(dirpath, "srm.db"),
                     secret_path=os.path.join(dirpath, "secret"),
                     prewarm_ocr=False)


def seed_user(app_obj, netid):
    """Insert a users row through the app's OWN db resolution."""
    import json
    with app_obj.app_context():
        with DB.transaction() as c:
            c.execute("INSERT OR REPLACE INTO users(netid, password, personal_details_json, last_fetch) "
                      "VALUES(?, 'unused-by-tests', ?, 0)",
                      (netid, json.dumps({"Student Name": netid.title()})))


def mint(app_obj, netid):
    with app_obj.app_context():
        return A.make_session_token(netid)


def cookie_rows(path):
    import sqlite3
    c = sqlite3.connect(path)
    n = c.execute("SELECT count(*) FROM cookies").fetchone()[0]
    c.close()
    return n


# the app-config snapshot reads env exactly once per app (fresh dir -> what
# the env named; hand-built configs below never touch env)
check("config: from_env snapshots DATA_DIR env", AppConfig.from_env().data_dir == TMP)
check("config: from_env honours OCR_PREWARM=0", AppConfig.from_env().prewarm_ocr is False)

# ── fresh-dir boot (C1, per app): dir did not exist, create_app makes it ──
DIR_A = os.path.join(TMP, "a")
DIR_B = os.path.join(TMP, "b")
a1 = A.create_app(make_config(DIR_A))
a2 = A.create_app(make_config(DIR_B))
check("fresh boot: data dirs created", os.path.isdir(DIR_A) and os.path.isdir(DIR_B))
check("fresh boot: per-app secret files", os.path.isfile(os.path.join(DIR_A, "secret"))
      and os.path.isfile(os.path.join(DIR_B, "secret")))
check("fresh boot: per-app DBs exist", os.path.isfile(os.path.join(DIR_A, "srm.db"))
      and os.path.isfile(os.path.join(DIR_B, "srm.db")))
_max_ver = max(m["version"] for m in _registry)
for tag, d in (("a", DIR_A), ("b", DIR_B)):
    import sqlite3
    c = sqlite3.connect(os.path.join(d, "srm.db"))
    v = c.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
    c.close()
    check(f"fresh boot: app {tag} schema migrated to registry max", v == _max_ver, f"v{v} == v{_max_ver}")

# ── two apps are distinct instances, neither is the module app ──────────
check("isolation: distinct Flask objects", a1 is not a2 and a1 is not A.app and a2 is not A.app)
check("isolation: per-app DB_PATH config", a1.config["DB_PATH"] != a2.config["DB_PATH"]
      and a1.config["DB_PATH"] == os.path.join(DIR_A, "srm.db"))
check("isolation: per-app secret keys", a1.secret_key != a2.secret_key)

# ── full route surface registered by the factory (no forgotten route) ───
EXPECTED = {
    "/", "/api/marks", "/api/feedback/fill", "/static/<path:filename>", "/login",
    "/api/login", "/api/refresh", "/api/login/preflight", "/api/login/progress",
    "/api/timetable", "/api/timetable/history", "/marks/tag", "/internal/push/tick",
    "/healthz", "/internal/metrics", "/api/push/status", "/api/push/subscribe",
    "/api/push/unsubscribe", "/api/push/settings", "/api/push/test", "/api/push/receipt",
    "/api/account/delete", "/logout",
}
got = {r.rule for r in a1.url_map.iter_rules()} - {"/avatar", "/avatar/<name>"}  # blobatar's routes
check("factory: every app route registered", got == EXPECTED,
      f"missing={sorted(EXPECTED - got)} extra={sorted(got - EXPECTED)}")
r_login = [r for r in a1.url_map.iter_rules() if r.rule == "/api/login"][0]
check("factory: /api/login methods preserved", r_login.methods == {"POST", "OPTIONS"},
      str(r_login.methods))

# ── blueprint split (A17): endpoints stay BARE, views stay app.app's ────
# FlatBlueprint (app/blueprints/__init__.py) skips Flask's `<bp>.<endpoint>`
# prefixing; this pins it. Every rule maps to its flat-app endpoint name AND
# the app.app view function it must keep calling.
EXPECTED_EP = {
    "/": {("index", "index")},
    "/api/marks": {("api_marks", "api_marks")},
    "/api/feedback/fill": {("api_feedback_fill", "api_feedback_fill")},
    "/static/<path:filename>": {("static_no_cache", "static_no_cache")},
    "/login": {("login", "login")},
    "/api/login": {("api_login", "api_login")},
    "/api/refresh": {("api_refresh", "api_refresh")},
    "/api/login/preflight": {("api_login_preflight", "api_login_preflight")},
    "/api/login/progress": {("api_login_progress", "api_login_progress")},
    "/api/timetable": {("api_get_timetable", "api_get_timetable"),
                       ("api_save_timetable", "api_save_timetable")},
    "/api/timetable/history": {("api_timetable_history", "api_timetable_history")},
    "/marks/tag": {("marks_tag", "marks_tag")},
    "/internal/push/tick": {("push_tick", "push_tick")},
    "/healthz": {("healthz", "healthz")},
    "/internal/metrics": {("internal_metrics", "internal_metrics")},
    "/api/push/status": {("push_status", "push_status")},
    "/api/push/subscribe": {("push_subscribe", "push_subscribe")},
    "/api/push/unsubscribe": {("push_unsubscribe", "push_unsubscribe")},
    "/api/push/settings": {("push_settings", "push_settings")},
    "/api/push/test": {("push_test", "push_test")},
    "/api/push/receipt": {("push_receipt", "push_receipt")},
    "/api/account/delete": {("account_delete", "account_delete")},
    "/logout": {("logout", "logout")},
}
got_ep = {}
for r in a1.url_map.iter_rules():
    if r.rule in ("/avatar", "/avatar/<name>"):
        continue
    v = a1.view_functions.get(r.endpoint)
    got_ep.setdefault(r.rule, set()).add((r.endpoint, getattr(v, "__name__", "-")))
_bad_ep = sorted(k for k in set(got_ep) | set(EXPECTED_EP)
                 if got_ep.get(k) != EXPECTED_EP.get(k))
check("factory: endpoints unprefixed + views unchanged (blueprint split)",
      got_ep == EXPECTED_EP, f"differs={_bad_ep[:4]}")

# ── the data isolation: seed + mint inside one app, the other must refuse ──
seed_user(a1, NETID_A)
tok_a = mint(a1, NETID_A)
check("isolation: cookie minted into app A's DB only",
      cookie_rows(os.path.join(DIR_A, "srm.db")) == 1
      and cookie_rows(os.path.join(DIR_B, "srm.db")) == 0)

c1 = a1.test_client()
c1.set_cookie("srm_session", tok_a)   # gotcha: Cookie header in headers= is dropped
r = c1.get("/")
check("isolation: app A serves its own user", r.status_code == 200 and NETID_A.encode() in r.data,
      f"status={r.status_code}")

c2 = a2.test_client()
c2.set_cookie("srm_session", tok_a)
r = c2.get("/")
check("isolation: app B refuses A's cookie", r.status_code == 302 and "/login" in r.headers.get("Location", ""),
      f"status={r.status_code} loc={r.headers.get('Location')}")

seed_user(a2, NETID_B)
tok_b = mint(a2, NETID_B)
c2.set_cookie("srm_session", tok_b)
r = c2.get("/")
check("isolation: app B serves its own user", r.status_code == 200 and NETID_B.encode() in r.data,
      f"status={r.status_code}")
c1.set_cookie("srm_session", tok_b)
r = c1.get("/")
check("isolation: app A refuses B's cookie", r.status_code == 302, f"status={r.status_code}")

# ── db path resolution: per-app inside an app context, module default out ──
check("resolution: outside any app context -> module default",
      DB._db_path() == A.DB_PATH, DB._db_path())
with a2.app_context():
    check("resolution: inside app B's context -> app B's DB",
          DB._db_path() == os.path.join(DIR_B, "srm.db"), DB._db_path())

# ── module-level app keeps its contracts (gunicorn app.app:app + C1 boot) ──
rm = A.app.test_client()
check("module app: healthz serves (import-boot contract)",
      rm.get("/healthz").status_code == 200)
r = rm.get("/")
check("module app: unauth / still gates to /login", r.status_code == 302)
check("module app: booted the module DATA_DIR schema",
      os.path.isfile(os.path.join(TMP, "srm.db")))

# ── prewarm opt-out: no captcha prewarm thread when config says no ───────
check("prewarm: OCR_PREWARM=0 leaves no prewarm thread",
      not any(t.name == "srm-captcha-prewarm" for t in threading.enumerate()))

print()
print("=" * 72)
print(f"APP FACTORY: {TOTAL[0]} items | PASS {TOTAL[0] - len(FAILS)} | FAIL {len(FAILS)}")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
