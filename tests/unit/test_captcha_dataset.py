"""CAPTCHA dataset capture — staging, success-only writes, dedupe, the route.

The contract that matters: a pair is written ONLY on a confirmed login, and
only inside a scrape scope (so a preflight solved for a visitor who never
submits stores nothing). Everything else is bookkeeping on top of that.

Offline: temp DATA_DIR, no portal, no network.
Runner style: check(name, fn) + dynamic TOTAL (test_metrics / test_healthz).
"""
import atexit
import base64
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

TMP = tempfile.mkdtemp(prefix="osrm-captcha-ds-")
os.environ["DATA_DIR"] = TMP
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

from _seed import seed  # noqa: E402

from app import app as A  # noqa: E402
from app import captcha_dataset as cds  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

FAILS = []
TOTAL = [0]


def check(name, fn):
    TOTAL[0] += 1
    try:
        fn()
        print(f"  ok  {name}")
    except AssertionError as e:
        FAILS.append(name)
        print(f"FAIL  {name}: {e}")
    except Exception as e:
        FAILS.append(name)
        print(f"FAIL  {name}: raised {type(e).__name__}: {e}")


def _reset():
    cds._seen.clear()
    d = cds.dataset_dir()
    shutil.rmtree(d, ignore_errors=True)
    os.environ["CAPTCHA_DATASET"] = "1"
    cds.begin()
    return d


# ── the capture contract ────────────────────────────────────────────────────
def t_success_writes_ocr_named_image():
    d = _reset()
    cds.offer(PNG, "aywbmn")
    assert not os.path.exists(d), "staging alone must not write"
    cds.commit()
    p = os.path.join(d, "aywbmn.png")
    assert os.path.exists(p), f"missing {p}"
    with open(p, "rb") as f:
        assert f.read() == PNG, "stored bytes must be the exact portal image"
    cds.clear()


def t_later_attempt_overwrites_earlier():
    d = _reset()
    cds.offer(PNG, "wrong1")            # attempt 1: rejected -> "retry"
    cds.offer(PNG + b"x", "right2")     # attempt 2: accepted
    cds.commit()
    assert sorted(os.listdir(d)) == ["right2.png"], os.listdir(d)
    cds.clear()


def t_second_commit_deduped():
    d = _reset()
    cds.offer(PNG, "aaaaaa")
    cds.commit()
    cds.commit()                        # mid-scrape relogin, same bytes
    assert len(os.listdir(d)) == 1, os.listdir(d)
    cds.clear()


def t_disabled_toggle_writes_nothing():
    _reset()
    os.environ.pop("CAPTCHA_DATASET", None)
    cds.begin()
    cds.offer(PNG, "zzzzzz")
    cds.commit()
    assert not os.path.exists(cds.dataset_dir()), "toggle off must write nothing"
    cds.clear()


def t_no_scope_no_write():
    """A preflight solved for a visitor who never submits: no scope -> nothing."""
    d = _reset()
    cds.clear()
    cds.offer(PNG, "nosave")
    cds.commit()
    assert not os.path.exists(d), "an uncertified captcha must never be written"
    cds.clear()


def t_path_separator_defused():
    d = _reset()
    cds.offer(PNG, "../../etc/passwd")
    cds.commit()
    # '/' becomes '_' so the name cannot escape the directory; dots are fine
    assert os.listdir(d) == [".._.._etc_passwd.png"], os.listdir(d)
    assert os.path.dirname(os.path.join(d, os.listdir(d)[0])) == d
    cds.clear()


def t_captcha_seen_row_written():
    _reset()
    cds.offer(PNG, "seen01")
    cds.commit()
    cds.clear()
    from app.db import captcha_seen_since
    assert captcha_seen_since(0)["n"] >= 1, "a written pair must log one captcha_seen row"


# ── the route ───────────────────────────────────────────────────────────────
def t_route_auth_fails_closed():
    seed()
    os.environ["CAPTCHA_SECRET"] = "s3cret"
    cl = A.app.test_client()
    assert cl.get("/internal/captcha").status_code == 401, "no header must be 401"
    assert cl.get("/internal/captcha", headers={"X-Captcha-Token": "nope"}).status_code == 401
    r = cl.get("/internal/captcha", headers={"X-Captcha-Token": "s3cret"})
    assert r.status_code == 200, r.data
    assert r.get_json()["dir"].endswith("captcha-dataset"), r.get_json()


def t_route_writes_and_validates():
    seed()
    os.environ["CAPTCHA_SECRET"] = "s3cret"
    h = {"X-Captcha-Token": "s3cret"}
    cl = A.app.test_client()
    r = cl.post("/internal/captcha", headers=h,
                json={"image_b64": base64.b64encode(PNG).decode(), "text": "qqww12"})
    assert r.status_code == 200, r.get_data(as_text=True)
    path = r.get_json()["path"]
    assert os.path.exists(path), path
    assert cl.post("/internal/captcha", headers=h, json={"text": "x"}).status_code == 400
    assert cl.post("/internal/captcha", headers=h,
                   json={"image_b64": "!!", "text": "x"}).status_code == 400
    assert cl.post("/internal/captcha", headers=h,
                   json={"image_b64": "aGk=", "text": "x", "ext": "sh"}).status_code == 400
    os.environ.pop("CAPTCHA_SECRET", None)


for _n, _f in sorted(list(globals().items())):
    if _n.startswith("t_") and callable(_f):
        check(_n[2:], _f)

print(f"\n{len(FAILS)} failed / {TOTAL[0]} checks" if FAILS else f"\nall {TOTAL[0]} checks passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
