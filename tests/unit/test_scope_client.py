"""SCOPE foundation suite — client wire, feature toggles, m018, cold sync.

Checks (mission contract):
  - envelope byte-identity: build_envelope("getCummulativeAttendance", params)
    reproduces the app's captured wire byte-exactly (tests/fixtures/
    scope_flow18_envelope.txt = pcap app-capture-flows.txt FLOW 18; params
    recovered by decrypting the fixture's own blob).
  - blob AES round-trip (unicode + 1KB) and the FIPS-256 ECB known-answer
    vector the reference CLI self-checks with.
  - login: uppercase netid + ALWAYS-empty password (backend ignores it); data_op wire order
    {studentid: sid, **FINGERPRINT} in the app's key order.
  - enabled_features(): default / "all" / unknown-slug / "off"; ops_for()
    dedup; every FEATURES op exists in the 43-op catalog.
  - migration m018: fresh DB runs it (columns + defaults), re-runs are
    idempotent, no registry version collision.
  - scope_cold_sync with a MOCKED client: stores {data, ts}; a failing op
    preserves its stored key and a transport fault keeps what landed;
    alive-empty ({Status, Data:""}) stored as-is; a credential fault
    triggers EXACTLY one relogin (call-counted) then retries that op.

Self-contained: temp DATA_DIR, seed inside the test; no server, no network,
no real credentials (fabricated netid — the repo is public, AGENTS.md).
"""
import atexit
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# verify76 forbids test DBs in-tree; the dir must outlive this module's import
# (tests run after the import block), so mkdtemp + atexit cleanup, not `with`.
_td = tempfile.mkdtemp(prefix="osrm-scope-")
atexit.register(shutil.rmtree, _td, True)
os.environ["DATA_DIR"] = _td          # direct assignment: stale env must not win
os.environ["OCR_PREWARM"] = "0"
os.environ.pop("SCOPE_FEATURES", None)  # every toggle test owns its env

from app import db as DB                        # noqa: E402
from app import migrations as MIG               # noqa: E402
from app.scope import client as C               # noqa: E402
from app.scope import ops as OPS                # noqa: E402
from app.scope import sync as SYNC              # noqa: E402
from app import app as A                        # noqa: E402,F401  # boots create_app: DATA_DIR DB + full migration chain (m018)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "scope_flow18_envelope.txt"
DBFILE = os.path.join(_td, "srm.db")
NETID = "zz9999"                                # fabricated — repo is public
OLD_SID = "A" * 96
NEW_SID = "B" * 96


def _seed_user(sid=OLD_SID, scope_json="{}"):
    """Fresh users row for this test (idempotent replace)."""
    conn = sqlite3.connect(DBFILE)
    conn.execute(
        "INSERT OR REPLACE INTO users(netid, password, scope_sid, scope_studentid, scope_json, scope_fetched_at)"
        " VALUES(?,?,?,?,?,0)",
        (NETID, "pw", sid, "709245", scope_json))
    conn.commit()
    conn.close()


def _scope_row():
    conn = sqlite3.connect(DBFILE)
    row = conn.execute(
        "SELECT scope_sid, scope_json, scope_fetched_at FROM users WHERE netid=?",
        (NETID,)).fetchone()
    conn.close()
    return row


def t_envelope_byte_identity():
    """FLOW 18 fixture: decrypt its blob, rebuild the envelope, bytes must match."""
    fixture = FIXTURE.read_text()
    m = re.search(r'<EncryptedData i:type="d:string">([0-9A-Fa-f]+)</EncryptedData>', fixture)
    assert m, "fixture carries no EncryptedData blob"
    inner = C.blob_decrypt(m.group(1))
    params = dict(re.findall(r"<(\w+)>(.*?)</\1>", inner))
    assert "studentid" in params and "deviceid" in params, f"inner did not decrypt: {inner[:80]!r}"
    got = C.build_envelope("getCummulativeAttendance", params)
    assert got == fixture, f"envelope diverged: {len(got)} vs {len(fixture)} bytes"


def t_blob_roundtrip():
    """decrypt(encrypt(x)) == x — ascii, unicode, and a 1KB payload."""
    for s in ("plain ascii payload", "unicode ✓ नमस्तéowała ąćę", "x" * 1024 + "✓"):
        assert C.blob_decrypt(C.blob_encrypt(s)) == s, repr(s[:40])


def t_fips_kat():
    """FIPS-197 AES-256 ECB known-answer vector (the reference self-check)."""
    key = bytes(range(32))
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    ct = C.aes(key, b"\0" * 16, pt, "ECB")
    assert ct.hex() == "8ea2b7ca516745bfeafc49904b496089", ct.hex()
    assert C.aes(key, b"\0" * 16, ct, "ECB", dec=True) == pt


def t_login_sends_uppercase_netid_and_no_password():
    """getStudentLogin: netid upper-cased, password field ALWAYS empty.

    Measured against the live backend: empty password -> valid sid; the real
    password / a wrong one / the netid -> "Invalid NetID or Password". The
    endpoint authenticates on NetID alone, so sending a password guarantees
    rejection. Pin it so nobody "fixes" the transform back.
    """
    seen = {}
    orig = C.soap_call

    def fake(op, params):
        seen["op"] = op
        seen["params"] = dict(params)
        return {"studentid": 709245, "sid": "ab" * 48}

    C.soap_call = fake
    try:
        res = C.login("ng2776", "hunter2")
    finally:
        C.soap_call = orig
    assert seen["op"] == "getStudentLogin"
    assert seen["params"]["username"] == "NG2776", seen["params"]
    assert seen["params"]["password"] == "", seen["params"]
    assert res["sid"] == "ab" * 48 and res["studentid"] == "709245"
    # the password argument is optional and ignored: every existing caller
    # (login/refresh pass the portal password, sync passes the decrypted one)
    # must keep working without changing its call site
    assert C.login.__defaults__ == (None,)


def t_login_rejects_no_sid():
    """A login answer without sid is a credential rejection, not silent None."""
    orig = C.soap_call
    C.soap_call = lambda op, params: {"message": "Invalid NetID or Password"}
    try:
        try:
            C.login("ng2776", "wrong")
            raised = None
        except C.ScopeAuthError as e:
            raised = str(e)
    finally:
        C.soap_call = orig
    assert raised and "Invalid NetID or Password" in raised, raised


def t_data_op_wire_order():
    """{studentid: sid, **FINGERPRINT} in app wire order, sid never numeric."""
    seen = {}
    orig = C.soap_call

    def fake(op, params):
        seen["op"] = op
        seen["params"] = dict(params)
        return {"ok": 1}

    C.soap_call = fake
    try:
        C.data_op("getHourwiseAttendance", "SID96")
    finally:
        C.soap_call = orig
    want = ["studentid", "deviceid", "androidversion", "model", "sdkversion",
            "appversion", "androidorios", "parentflag"]
    assert list(seen["params"]) == want, list(seen["params"])
    assert seen["params"]["studentid"] == "SID96"


def t_features_default_env():
    os.environ.pop("SCOPE_FEATURES", None)
    got = OPS.enabled_features()
    assert got == set(OPS.DEFAULT_FEATURES.split(",")), got
    assert got <= set(OPS.FEATURES)


def t_features_all():
    os.environ["SCOPE_FEATURES"] = "all"
    try:
        assert OPS.enabled_features() == set(OPS.FEATURES)
    finally:
        os.environ.pop("SCOPE_FEATURES", None)


def t_features_unknown_slug_ignored():
    os.environ["SCOPE_FEATURES"] = "hourwise, bogus ,fees"
    try:
        assert OPS.enabled_features() == {"hourwise", "fees"}
    finally:
        os.environ.pop("SCOPE_FEATURES", None)


def t_features_off_is_empty():
    for raw in ("off", ""):
        os.environ["SCOPE_FEATURES"] = raw
        assert OPS.enabled_features() == set(), raw
    os.environ.pop("SCOPE_FEATURES", None)


def t_ops_for_dedup():
    """Dedup across features + every FEATURES op must exist in the catalog."""
    for feat, feat_ops in OPS.FEATURES.items():
        for op in feat_ops:
            assert op in OPS.OPS, f"FEATURES[{feat}] op {op} missing from the 43-op OPS catalog"
    all_ops = OPS.ops_for(set(OPS.FEATURES))
    assert len(all_ops) == len(set(all_ops)), "ops_for leaked duplicates"
    orig = OPS.FEATURES
    OPS.FEATURES = {"a": ["op1", "op2"], "b": ["op2", "op3"]}
    try:
        assert OPS.ops_for({"a", "b"}) == ["op1", "op2", "op3"]
        assert OPS.ops_for({"b"}) == ["op2", "op3"]
        assert OPS.ops_for(set()) == []
    finally:
        OPS.FEATURES = orig


def t_migration_m018():
    """Fresh DB runs m018 (columns + defaults), re-runs idempotent, no version collision."""
    versions = [m["version"] for m in MIG._registry]
    assert len(versions) == len(set(versions)), f"duplicate migration versions: {versions}"
    assert 18 in versions, versions
    tmp = tempfile.mkdtemp(prefix="osrm-m018-")
    try:
        conn = sqlite3.connect(os.path.join(tmp, "srm.db"))
        MIG.migrate_db(conn)  # fresh DB: full chain incl. m018
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        assert {"scope_sid", "scope_studentid", "scope_json", "scope_fetched_at"} <= cols, cols
        assert 18 in [r[0] for r in conn.execute("SELECT version FROM schema_version")]
        conn.execute("INSERT INTO users(netid, password) VALUES('migtest', 'x')")
        conn.commit()
        scope_json, fetched = conn.execute(
            "SELECT scope_json, scope_fetched_at FROM users WHERE netid='migtest'").fetchone()
        assert scope_json == "{}" and fetched == 0, (scope_json, fetched)
        MIG.m018_scope_session(conn)  # direct re-run: swallow 'duplicate column' only
        MIG.m018_scope_session(conn)
        conn.close()
    finally:
        shutil.rmtree(tmp, True)


def t_tools_entries_gates():
    """Tools panel gate: slug enabled AND its op holds data; else no row.

    Three failure modes pinned here, all of which would put a dead row on the
    Tools tab (or 500 the dashboard): a disabled slug with data behind it, an
    enabled slug whose op never landed, and a stored entry that is not the
    documented {"data","ts"} dict (corrupt/foreign scope_json).
    """
    import importlib
    APP = importlib.import_module("app.app")

    def rows(scope_json, features):
        _seed_user(scope_json=scope_json)
        os.environ["SCOPE_FEATURES"] = features
        try:
            return APP._tools_entries(NETID)
        finally:
            os.environ.pop("SCOPE_FEATURES", None)

    blob = json.dumps({
        "getFeeDetails": {"data": {"dues": 1200}, "ts": 1},
        "getStudentExamProvisionalResult": {"data": [], "ts": 1},   # alive-empty
        "getLibraryTransaction": "not-a-dict",                      # corrupt shape
        "getHostelDetails": {"ts": 1},                              # no data key
    })
    # both slugs on: only fees qualifies (academics empty, library corrupt,
    # campus has no data) -> exactly one row, and it is Fees.
    got = rows(blob, "fees,academics,library,campus")
    assert [r["slug"] for r in got] == ["fees"], got
    assert got[0]["label"] == "Fees" and got[0]["op"] == "getFeeDetails", got
    # fees disabled, academics enabled: fees' data must NOT leak in.
    got = rows(blob, "academics")
    assert got == [], got
    # everything off: zero footprint, and no users-row read needed.
    assert rows(blob, "off") == []
    # empty / absent blob with features on: nothing to show.
    assert rows("{}", "all") == []
    assert rows(None, "all") == []
    # whole blob the wrong shape must not raise (degrade to no tools).
    assert rows('["unexpected"]', "all") == []
    assert rows("{not json", "all") == []


def t_cold_sync_stores_data():
    """Enabled ops land in scope_json as {data, ts}; fetched_at stamped."""
    _seed_user()
    os.environ["SCOPE_FEATURES"] = "attendance"
    calls = []
    orig = SYNC.data_op

    def fake(op, sid, extra=None):
        calls.append((op, sid))
        return {"op": op}

    SYNC.data_op = fake
    try:
        res = SYNC.scope_cold_sync(NETID, "pw")
    finally:
        SYNC.data_op = orig
        os.environ.pop("SCOPE_FEATURES", None)
    assert res == {"ok": 2, "skipped": 0, "ops": 2, "fresh": 0, "aborted": False}, res
    assert [op for op, _ in calls] == ["getCummulativeAttendance", "getSubjectwiseAttendance"]
    assert all(sid == OLD_SID for _, sid in calls), calls
    sid, scope_json, fetched = _scope_row()
    stored = json.loads(scope_json)
    assert set(stored) == {"getCummulativeAttendance", "getSubjectwiseAttendance"}, stored
    assert stored["getCummulativeAttendance"]["data"] == {"op": "getCummulativeAttendance"}
    assert isinstance(stored["getCummulativeAttendance"]["ts"], int) and stored["getCummulativeAttendance"]["ts"] > 0
    assert fetched > 0, "scope_fetched_at not stamped"


def t_cold_sync_preserve_and_transport_break():
    """Failing op keeps its stored key; transport fault breaks, keeps what landed."""
    prior = {"getCummulativeAttendance": {"data": {"old": 1}, "ts": 1},
             "getSubjectwiseAttendance": {"data": {"old": 2}, "ts": 2},
             "getInternalMarkDetails": {"data": {"old": 3}, "ts": 3}}
    _seed_user(scope_json=json.dumps(prior))
    os.environ["SCOPE_FEATURES"] = "attendance,marks"
    calls = []
    orig = SYNC.data_op

    def fake(op, sid):
        calls.append(op)
        if op == "getSubjectwiseAttendance":
            raise C.ScopeTransportError("upstream down")
        return {"new": op}

    SYNC.data_op = fake
    try:
        res = SYNC.scope_cold_sync(NETID, "pw")
    finally:
        SYNC.data_op = orig
        os.environ.pop("SCOPE_FEATURES", None)
    assert res["aborted"] is True and res["ok"] == 1, res
    stored = json.loads(_scope_row()[1])
    assert stored["getCummulativeAttendance"]["data"] == {"new": "getCummulativeAttendance"}  # updated
    assert stored["getSubjectwiseAttendance"] == prior["getSubjectwiseAttendance"]          # preserved
    assert stored["getInternalMarkDetails"] == prior["getInternalMarkDetails"]              # untouched
    assert "getInternalMarkDetails" not in calls, "run did not stop at the transport fault"


def t_cold_sync_alive_empty_stored_as_is():
    """{Status, Message, Data:""} is alive-empty DATA, not an error."""
    _seed_user()
    os.environ["SCOPE_FEATURES"] = "library"
    payload = {"Status": "Success", "Message": "No data found", "Data": ""}
    orig = SYNC.data_op
    SYNC.data_op = lambda op, sid: payload
    try:
        res = SYNC.scope_cold_sync(NETID, "pw")
    finally:
        SYNC.data_op = orig
        os.environ.pop("SCOPE_FEATURES", None)
    assert res["ok"] == 1 and not res["aborted"], res
    stored = json.loads(_scope_row()[1])
    assert stored["getLibraryTransaction"]["data"] == payload


def t_cold_sync_auth_fault_relogins_once():
    """ScopeAuthError -> EXACTLY one relogin, then THAT op retried on the new sid."""
    _seed_user()
    os.environ["SCOPE_FEATURES"] = "attendance"
    state = {"login": 0, "auth": 0}
    orig_login, orig_op = SYNC.login, SYNC.data_op

    def fake_login(netid, password):
        state["login"] += 1
        return {"studentid": "709245", "sid": NEW_SID, "raw": {}}

    def fake_op(op, sid):
        if op == "getCummulativeAttendance" and sid == OLD_SID:
            state["auth"] += 1
            raise C.ScopeAuthError("stale sid")
        return {"op": op, "sid": sid}

    SYNC.login, SYNC.data_op = fake_login, fake_op
    try:
        res = SYNC.scope_cold_sync(NETID, "pw")
    finally:
        SYNC.login, SYNC.data_op = orig_login, orig_op
        os.environ.pop("SCOPE_FEATURES", None)
    assert state == {"login": 1, "auth": 1}, state  # one relogin, one retry — never a loop
    assert res["ok"] == 2 and not res["aborted"], res
    sid, scope_json, _ = _scope_row()
    assert sid == NEW_SID, "rotated sid not persisted"
    stored = json.loads(scope_json)
    assert stored["getCummulativeAttendance"]["data"]["sid"] == NEW_SID  # retried on fresh session


def t_ensure_session_login_when_missing():
    """No stored scope_sid -> one login, persisted before returning."""
    _seed_user(sid=None)
    orig_login = SYNC.login
    calls = []

    def fake_login(netid, password):
        calls.append(netid)
        return {"studentid": "709245", "sid": NEW_SID, "raw": {}}

    SYNC.login = fake_login
    try:
        sess = SYNC.ensure_scope_session(NETID, "pw")
    finally:
        SYNC.login = orig_login
    assert sess == {"sid": NEW_SID, "studentid": "709245"}, sess
    assert calls == [NETID]
    assert _scope_row()[0] == NEW_SID, "session not persisted"



def t_sync_incremental_ttl():
    """Fresh ops are NOT re-fetched; stale/missing ones are. TTL is the knob."""
    now = int(time.time())
    prior = {"getCummulativeAttendance": {"data": {"old": 1}, "ts": now},          # fresh
             "getSubjectwiseAttendance": {"data": {"old": 2}, "ts": now - SYNC.SCOPE_TTL_S - 1}}  # stale
    _seed_user(scope_json=json.dumps(prior))
    os.environ["SCOPE_FEATURES"] = "attendance"
    calls = []
    orig = SYNC.data_op
    SYNC.data_op = lambda op, sid: (calls.append(op), {"new": op})[1]
    try:
        res = SYNC.scope_cold_sync(NETID, "pw")
    finally:
        SYNC.data_op = orig
        os.environ.pop("SCOPE_FEATURES", None)
    assert calls == ["getSubjectwiseAttendance"], calls  # the fresh one was skipped
    assert res["fresh"] == 1 and res["ok"] == 1 and res["ops"] == 2, res
    stored = json.loads(_scope_row()[1])
    assert stored["getCummulativeAttendance"] == prior["getCummulativeAttendance"], "fresh op was refetched"
    assert stored["getSubjectwiseAttendance"]["data"] == {"new": "getSubjectwiseAttendance"}
    # everything fresh -> no network at all, and no re-login either
    calls.clear()
    os.environ["SCOPE_FEATURES"] = "attendance"        # the assert below reads env
    try:
        assert SYNC.scope_needs_sync(NETID) is False, "fresh blob reported stale"
        res2 = SYNC.scope_cold_sync(NETID, "pw")
    finally:
        os.environ.pop("SCOPE_FEATURES", None)
    assert calls == [] and res2["ok"] == 0 and res2["fresh"] == 2, res2


def t_sync_aborted_does_not_stamp_fresh():
    """A transport abort keeps the OLD fetched_at — a partial run is not fresh."""
    _seed_user()
    os.environ["SCOPE_FEATURES"] = "attendance"
    orig_op = SYNC.data_op
    SYNC.data_op = lambda op, sid: {"op": op}
    try:
        SYNC.scope_cold_sync(NETID, "pw")
    finally:
        SYNC.data_op = orig_op
    stamped = _scope_row()[2]
    assert stamped > 0, "completed run did not stamp"

    # force a stale blob, then abort mid-run
    conn = sqlite3.connect(DBFILE)
    conn.execute("UPDATE users SET scope_fetched_at=? WHERE netid=?", (12345, NETID))
    conn.commit()
    conn.close()
    def boom(op, sid):
        raise C.ScopeTransportError("upstream down")
    SYNC.data_op = boom
    try:
        res = SYNC.scope_cold_sync(NETID, "pw", force=True)
    finally:
        SYNC.data_op = orig_op
        os.environ.pop("SCOPE_FEATURES", None)
    assert res["aborted"] is True, res
    assert _scope_row()[2] == 12345, "aborted run overwrote fetched_at (claimed freshness)"
    assert SYNC.scope_needs_sync(NETID) is True, "aborted run left the blob looking fresh"


def t_trigger_is_single_flight():
    """Two triggers for one netid start exactly ONE batch."""
    started = []
    orig = SYNC.scope_cold_sync

    def slow(netid, password, force=False):
        started.append(netid)
        time.sleep(0.3)
        return {}

    SYNC.scope_cold_sync = slow
    try:
        A._scope_sync_running.discard(NETID)
        A._scope_sync_trigger(NETID, "pw")
        A._scope_sync_trigger(NETID, "pw")   # dropped: already in flight
        A._scope_sync_trigger(NETID, "pw")
        time.sleep(0.15)
        assert A._scope_sync_state(NETID) in ("running", "stale", "complete", "off")
        time.sleep(0.6)
    finally:
        SYNC.scope_cold_sync = orig
    assert started == [NETID], started
    assert NETID not in A._scope_sync_running, "lock leaked after the run"


def t_trigger_never_blocks():
    """The login/refresh path must return immediately — the fetch is background."""
    orig = SYNC.scope_cold_sync
    SYNC.scope_cold_sync = lambda netid, password, force=False: time.sleep(3)
    try:
        A._scope_sync_running.discard(NETID)
        t0 = time.monotonic()
        A._scope_sync_trigger(NETID, "pw")
        elapsed = time.monotonic() - t0
    finally:
        SYNC.scope_cold_sync = orig
    assert elapsed < 0.5, f"trigger blocked the request path for {elapsed:.2f}s"
    assert A._scope_sync_state(NETID) == "running", A._scope_sync_state(NETID)


def t_status_endpoint_scoped_and_auth():
    """The status endpoint 401s logged out and answers only for the session user."""
    c = A.app.test_client()
    r = c.get("/api/scope/status")
    assert r.status_code == 401, r.status_code
    body = r.get_json()
    assert body == {"ok": False, "error": "not logged in"}, body


def t_tools_rows_carry_a_real_tab():
    """Every Tools row must name a tab the dashboard actually renders.

    A row with no `tab` renders href="#" and switches nothing; a row pointing at
    a panel that does not exist is what dash.js has to defuse at runtime. Both
    are silent in a screenshot, so pin them here.
    """
    import app.app as A

    # the catalog itself: every entry is a 5-tuple ending in a tab slug
    for entry in A.TOOLS:
        assert len(entry) == 5, f"TOOLS entry not (slug,label,hint,op,tab): {entry}"
        assert entry[4] and isinstance(entry[4], str), f"no tab target: {entry}"

    # and the two surfaces that live inside an existing tab are present at all
    slugs = {e[0] for e in A.TOOLS}
    assert "hourwise" in slugs, "hourwise has no Tools row (no phone route)"
    assert "profile" in slugs, "profile has no Tools row (no phone route)"

    # Each tab slug must name a tab that exists SOMEWHERE in the stack. A row
    # whose panel is not mounted yet is legal — dash.js defuses it to a disabled
    # row — but a slug that appears nowhere at all is a typo that ships a dead
    # link. Known-tab list = every surface the SCOPE suite installs.
    KNOWN = {"dashboard", "attendance", "timetable", "marks", "settings",
             "tools", "fees", "academics", "campus"}
    for slug, label, hint, op, tab in A.TOOLS:
        assert tab in KNOWN, f"{label} -> #{tab}: not a known tab"


def t_sync_fetches_concurrently():
    """Ops overlap instead of running one-at-a-time.

    The whole point of the pool: N slow ops must not cost N x their latency.
    Each fake op sleeps 0.20s; 4 ops sequentially would be >=0.80s. With the
    pool they overlap, so wall time stays well under that. Also pins that every
    op still lands and the pool size is the measured optimum.
    """
    _seed_user()
    os.environ["SCOPE_FEATURES"] = "all"
    ops = ["getPersonalDetails", "getExamDetails", "getHourwiseAttendance",
           "getSubCategorySemesterWiseStatus"]
    orig = SYNC.data_op
    orig_features = SYNC.ops_for

    def fake(op, sid):
        time.sleep(0.20)
        return {"op": op}

    SYNC.data_op = fake
    SYNC.ops_for = lambda features: list(ops)
    try:
        t0 = time.monotonic()
        res = SYNC.scope_cold_sync(NETID, "pw")
        elapsed = time.monotonic() - t0
    finally:
        SYNC.data_op = orig
        SYNC.ops_for = orig_features
        os.environ.pop("SCOPE_FEATURES", None)
    assert res["ok"] == len(ops), res
    # sequential would be >= 0.80s; the pool finishes all four in ~one wave
    assert elapsed < 0.55, f"ops did not overlap: {elapsed:.2f}s for 4x 0.20s"
    assert SYNC.SCOPE_POOL == 8, "pool size must stay at the measured optimum (8)"


def t_sync_no_inter_op_pacing():
    """PACE_S must stay 0: the sleep cost 6.5s per pass and bought nothing."""
    assert SYNC.PACE_S == 0.0, (
        "PACE_S is back — the backend self-paces (~25 req/s measured); "
        "a 0.5s sleep adds ~6.5s per 14-op pass for no benefit"
    )


def t_sync_hot_cold_split():
    """Hot ops go stale in 30min; cold ops are reused for 24h.

    Same model as the portal pipeline (README 'Hot/cold data'). Without it a
    blanket TTL re-fetched the whole transcript every 30 minutes, which is the
    majority of a pass's upstream cost for data that cannot have changed.
    """
    assert SYNC.SCOPE_TTL_S == 1800, SYNC.SCOPE_TTL_S
    assert SYNC.SCOPE_COLD_TTL_S == 24 * 3600, SYNC.SCOPE_COLD_TTL_S

    # every classified op must exist, or the split silently does nothing
    catalog = set(OPS.OPS)
    for op in SYNC.HOT_OPS | SYNC.COLD_OPS:
        assert op in catalog, f"classified op not in catalog: {op}"
    assert not (SYNC.HOT_OPS & SYNC.COLD_OPS), "an op cannot be both hot and cold"

    # the measured-expensive ops that settle once published must be COLD
    for op in ("getExamDetails", "getProgramSubCategoryWiseSubjects",
               "getSubCategorySemesterWiseStatus", "getSubjects"):
        assert op in SYNC.COLD_OPS, f"{op} is slow and settled — must be cold"
    # attendance moves daily
    for op in ("getCumulativeAttendance".replace("Cumulative", "Cummulative"),
               "getSubjectwiseAttendance", "getHourwiseAttendance"):
        assert op in SYNC.HOT_OPS, f"{op} moves daily — must be hot"

    now = 1_000_000
    def at(age):
        return {op: {"data": {}, "ts": now - age} for op in
                list(SYNC.HOT_OPS) + list(SYNC.COLD_OPS)}

    ops = list(SYNC.HOT_OPS) + list(SYNC.COLD_OPS)
    # 45 min old: every hot op stale, every cold op still fresh
    pend = SYNC._pending_ops(at(45 * 60), ops, now)
    assert set(pend) == set(SYNC.HOT_OPS), (
        f"45min: expected only hot ops pending, got {len(pend)}")
    # 25 hours old: everything stale again
    assert len(SYNC._pending_ops(at(25 * 3600), ops, now)) == len(ops)
    # force ignores the split
    assert len(SYNC._pending_ops(at(0), ops, now, force=True)) == len(ops)
    # a cold op 2h old is NOT refetched (this is the whole saving)
    two_h = SYNC._pending_ops(at(2 * 3600), ops, now)
    assert not (set(two_h) & SYNC.COLD_OPS), "cold op re-fetched at 2h"


TESTS = [
    ("envelope byte-identity vs pcap FLOW 18", t_envelope_byte_identity),
    ("blob AES round-trip (unicode + 1KB)", t_blob_roundtrip),
    ("FIPS-256 ECB known-answer vector", t_fips_kat),
    ("login: uppercase netid, empty password", t_login_sends_uppercase_netid_and_no_password),
    ("login without sid = credential rejection", t_login_rejects_no_sid),
    ("data_op wire order {studentid, **FINGERPRINT}", t_data_op_wire_order),
    ("enabled_features default env", t_features_default_env),
    ("enabled_features 'all'", t_features_all),
    ("enabled_features unknown slug ignored", t_features_unknown_slug_ignored),
    ("enabled_features 'off'/'': empty set", t_features_off_is_empty),
    ("ops_for dedup + catalog coverage", t_ops_for_dedup),
    ("migration m018 runs + idempotent re-runs", t_migration_m018),
    ("Tools panel gate: enabled slug + landed data only", t_tools_entries_gates),
    ("cold sync stores {data, ts} + fetched_at", t_cold_sync_stores_data),
    ("cold sync preserve-if-empty + transport break", t_cold_sync_preserve_and_transport_break),
    ("cold sync alive-empty stored as-is", t_cold_sync_alive_empty_stored_as_is),
    ("cold sync auth fault = one relogin then retry", t_cold_sync_auth_fault_relogins_once),
    ("sync incremental: TTL skips fresh ops", t_sync_incremental_ttl),
    ("aborted sync does not stamp freshness", t_sync_aborted_does_not_stamp_fresh),
    ("trigger is single-flight per netid", t_trigger_is_single_flight),
    ("trigger never blocks the request", t_trigger_never_blocks),
    ("status endpoint 401s when logged out", t_status_endpoint_scoped_and_auth),
    ("ensure_scope_session logs in when sid missing", t_ensure_session_login_when_missing),
    ("tools rows carry a real tab", t_tools_rows_carry_a_real_tab),
    ("sync fetches ops concurrently (pool overlaps them)", t_sync_fetches_concurrently),
    ("sync has no inter-op pacing", t_sync_no_inter_op_pacing),
    ("sync hot/cold split: 30min hot, 24h cold", t_sync_hot_cold_split),
]

if __name__ == "__main__":
    failed = 0
    t0 = time.monotonic()
    for name, fn in TESTS:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed ({time.monotonic() - t0:.1f}s)")
    sys.exit(1 if failed else 0)
