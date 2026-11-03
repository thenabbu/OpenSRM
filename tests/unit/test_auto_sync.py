#!/usr/bin/env python3
"""The dashboard must refresh stale portal data on its own.

Before this, `fetch_attendance` was only reachable from /api/refresh and
/api/login — a user who never pressed the button kept yesterday's numbers and
saw "(8h ago)" forever. These checks pin the decision logic so a future change
cannot silently drop the kick, while never letting a suite touch the portal.
"""
import os
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

print(f"\n{15 - len(fails)}/15 passed")
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("ok  auto-sync suite")
