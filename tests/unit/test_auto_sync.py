#!/usr/bin/env python3
"""The dashboard must refresh stale portal data on its own.

Before this, `fetch_attendance` was only reachable from /api/refresh and
/api/login — a user who never pressed the button kept yesterday's numbers and
saw "(8h ago)" forever. These checks pin the decision logic so a future change
cannot silently drop the kick, while never letting a suite touch the portal.
"""
import os
import pathlib
import re
import sys
import tempfile
import time

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import app.auto_sync as auto  # noqa: E402

fails = []


def check(label, got, want):
    if got != want:
        fails.append(label)
        print(f"  [FAIL] {label}: got {got!r}, want {want!r}")
    else:
        print(f"  [PASS] {label}")


print("auto-sync: staleness window")
for raw, want in [(None, 900), ("0", 0), ("-5", 0), ("60", 60), (" 120 ", 120), ("junk", 900)]:
    if raw is None:
        os.environ.pop("AUTO_SYNC_STALE_S", None)
    else:
        os.environ["AUTO_SYNC_STALE_S"] = raw
    check(f"AUTO_SYNC_STALE_S={raw!r}", auto._stale_after_s(), want)

print("\nauto-sync: kick decisions (no network)")

# disabled -> never kicks
os.environ["AUTO_SYNC_STALE_S"] = "0"
check("disabled never kicks", auto.auto_sync_kick_if_stale("ng2776"), False)

# no netid -> never kicks
os.environ.pop("AUTO_SYNC_STALE_S", None)
check("empty netid never kicks", auto.auto_sync_kick_if_stale(""), False)

# A stale row kicks at most once (single-flight per account), and a fresh row
# never kicks. Patch the two seams so nothing reaches the portal.
from app import db as _db  # noqa: E402

_calls = []
auto_thread_started = []


class _FakeThread:
    def __init__(self, target=None, daemon=None, name=None):
        auto_thread_started.append(name)

    def start(self):
        pass  # never run the body: it would hit the portal


_real_thread = auto.threading.Thread
auto.threading.Thread = _FakeThread


class _ImmediateThread(_FakeThread):
    """Runs the job inline so the kick body is exercised, not just scheduled."""

    def __init__(self, target=None, daemon=None, name=None):
        auto_thread_started.append(name)
        self._target = target

    def start(self):
        self._target()

os.environ["AUTO_SYNC_STALE_S"] = "900"

_db.user_last_fetch = lambda netid: {"last_fetch": int(time.time()) - 5000}
kicked = auto.auto_sync_kick_if_stale("ng2776")
check("stale data kicks a refresh", kicked, True)
check("kick started exactly one thread", auto_thread_started, ["srm-auto-sync"])
check("second immediate kick is suppressed (single-flight)",
      auto.auto_sync_kick_if_stale("ng2776"), False)

auto._running.clear()
auto_thread_started.clear()
_db.user_last_fetch = lambda netid: {"last_fetch": int(time.time()) - 60}
check("fresh data does not kick", auto.auto_sync_kick_if_stale("ng2776"), False)
check("no thread for fresh data", auto_thread_started, [])

_db.user_last_fetch = lambda netid: {"last_fetch": 0}
auto._running.clear()
check("never-synced kicks", auto.auto_sync_kick_if_stale("ng2776"), True)

auto.threading.Thread = _real_thread

# The checks above replace Thread with a fake, so `_run` — the body that does
# the actual work — never executed and a broken import inside it was invisible
# (prod logged "cannot import name 'decrypt_pw' from 'app.db'" on every kick,
# silently, for as long as the file existed). Run `_run` for real: portal and
# DB are stubbed, so this asserts the wiring, not the network.
# routes_sync can't be imported standalone (circular: it imports the facade,
# the facade imports it back, and it is marked first-party so it only resolves
# through the facade). Stand a stub module in sys.modules so the body's own
# `from .routes_sync import _refresh_core` executes for real — that import
# statement is exactly what the suite is checking.
print("auto-sync: the kick body actually runs")
_ran = []
auto._running.clear()

import sys as _sys  # noqa: E402
import re  # noqa: E402

_facade_src = (pathlib.Path(__file__).resolve().parents[2] / "app" / "app.py").read_text()

_import_error = None
try:
    from app.crypto import decrypt_pw as _dp  # noqa: F401  — the name the body needs
    from app.db import user_password as _up  # noqa: F401
except ImportError as e:  # noqa: BLE001
    _import_error = f"{type(e).__name__}: {e}"
check("the names the kick body imports resolve", _import_error, None)

# `_run` swallows every exception into a warning log; capture it so a broken
# import fails the suite instead of passing silently the way prod did.
_warnings = []
_infos = []
auto.log.warning = lambda *a, **k: _warnings.append(a[0] % a[1:])
auto.log.info = lambda *a, **k: _infos.append(a[0] % a[1:])


def _refresh_core(netid, pw, source):
    _ran.append((netid, pw, source))
    # The SUCCESS shape _refresh_core actually returns: a bare payload, not a
    # tuple. A stub that returns a tuple would hide the KeyError(0) this suite
    # is here to catch.
    return {"ok": True}


# Any name app.py re-exports from the stubbed module has to exist on it, or the
# facade's own `from .routes_sync import ...` trips over the same missing name.
# Callables get a distinct stub function: blueprint registration reads
# `view_func.__name__`, so a bare None explodes at import.
_reexported = {
    _n.strip().rstrip(",")
    for _blk in re.findall(r"from \.routes_sync import \(([^)]*)\)", _facade_src)
    for _n in _blk.splitlines()
    if _n.strip() and not _n.strip().startswith("#")
}
_stub_mod = type(_sys)("app.routes_sync")  # a real module: sys.modules wants one
for _name in _reexported:
    _fn = (lambda _n: (lambda *a, **k: None))(_name)
    _fn.__name__ = _name
    setattr(_stub_mod, _name, _fn)
_stub_mod._refresh_core = _refresh_core
_sys.modules["app.routes_sync"] = _stub_mod

# Patch the DB seam at CALL time: auto_sync does its own function-scope
# `from .db import user_password`, so rebinding app.db's attribute here is what
# the body will resolve. A real round-trip ciphertext, so the decrypt in the
# body has to actually succeed rather than fall into the re-login branch.
from app.crypto import encrypt_pw as _enc_pre  # noqa: E402
_db.user_password = lambda netid: {"password": _enc_pre("ciphertext")}

auto.threading.Thread = _ImmediateThread
auto.auto_sync_kick_if_stale("ng2776")
check("kick body logged no failure", _warnings, [])
check("kick body ran the refresh (one call)", len(_ran), 1)
check("kick body passed the decrypted password", _ran[0][1] if _ran else None, "ciphertext")
check("a successful refresh logs ok=True", any("ok=True" in w for w in _infos), True)
check("a successful refresh logs no failure", _warnings, [])

# The decrypt itself: a real ciphertext round-trips, and the module the body
# imports it from is the leaf crypto module (importing it from db is what broke
# prod — that name never existed there).
from app.crypto import encrypt_pw as _enc  # noqa: E402
check("decrypt_pw round-trips a real ciphertext", _dp(_enc("hunter2")), "hunter2")

print(f"\n{20 - len(fails)}/20 passed")
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("ok  auto-sync suite")
