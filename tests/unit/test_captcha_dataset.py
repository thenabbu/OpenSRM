"""CAPTCHA dataset capture — success/ and failed/ folders, plus the solver fix.

The contract that matters:
  * an ACCEPTED login writes <success>/<correct ocr>.<ext>
  * a portal-judged WRONG read writes <failed>/<what ddddocr said>.<ext>
  * anything that is not a captcha verdict (wrong password, rate limit,
    expired, empty OCR) writes NOTHING to failed/ — that label would be a lie
  * nothing at all is written outside a scrape scope

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
from app.captcha import sanitize_captcha  # noqa: E402

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
    shutil.rmtree(cds.dataset_dir(), ignore_errors=True)
    os.environ["CAPTCHA_DATASET"] = "1"
    cds.begin()


def _names(folder):
    d = cds.dataset_dir(folder)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


# ── success folder ──────────────────────────────────────────────────────────
def t_success_named_by_correct_ocr():
    _reset()
    cds.offer(PNG, "aywbmn")
    assert _names("success") == [], "staging alone must not write"
    cds.commit()
    assert _names("success") == ["aywbmn.png"], _names("success")
    with open(os.path.join(cds.dataset_dir("success"), "aywbmn.png"), "rb") as f:
        assert f.read() == PNG, "stored bytes must be the exact portal image"
    cds.clear()


def t_success_does_not_touch_failed():
    _reset()
    cds.offer(PNG, "good12")
    cds.commit()
    assert _names("failed") == [], "a success must never write a failed sample"
    cds.clear()


# ── failed folder ───────────────────────────────────────────────────────────
def t_reject_named_by_ddddocr_read():
    _reset()
    cds.offer(PNG, "vs9jnr")     # what the solver returned
    cds.reject()
    assert _names("failed") == ["vs9jnr.png"], _names("failed")
    assert _names("success") == [], "a reject must never write a success sample"
    cds.clear()


def t_later_attempt_replaces_earlier():
    """attempt 1 rejected, attempt 2 accepted: each lands in its own folder
    with its OWN answer, never the first attempt's name in the wrong place."""
    _reset()
    cds.offer(PNG, "wrong1")
    cds.reject()
    cds.offer(PNG + b"x", "right2")
    cds.commit()
    assert _names("failed") == ["wrong1.png"], _names("failed")
    assert _names("success") == ["right2.png"], _names("success")
    cds.clear()


def t_same_bytes_deduped_per_folder():
    _reset()
    cds.offer(PNG, "aaaaaa")
    cds.reject()
    cds.reject()
    assert len(_names("failed")) == 1, _names("failed")
    cds.clear()


def t_disabled_writes_nothing():
    _reset()
    os.environ.pop("CAPTCHA_DATASET", None)
    cds.begin()
    cds.offer(PNG, "zzzzzz")
    cds.commit()
    cds.offer(PNG, "zzzzzz")
    cds.reject()
    assert not os.path.exists(cds.dataset_dir()), "toggle off must write nothing"
    cds.clear()


def t_no_scope_no_write():
    """A preflight solved for a visitor who never submits: no scope -> nothing."""
    _reset()
    cds.clear()
    cds.offer(PNG, "nosave")
    cds.commit()
    cds.offer(PNG, "nosave")
    cds.reject()
    assert not os.path.exists(cds.dataset_dir()), "uncertified captcha must never be written"
    cds.clear()


def t_path_separator_defused():
    _reset()
    cds.offer(PNG, "../../etc/passwd")
    cds.commit()
    names = _names("success")
    # '.' and '/' are not in the whitelist, so they are DROPPED — the name can
    # neither escape the folder nor look like a path.
    assert names == ["etcpasswd.png"], names
    assert os.path.dirname(os.path.join(cds.dataset_dir("success"), names[0])) == cds.dataset_dir("success")
    cds.clear()


# ── the solver fix ──────────────────────────────────────────────────────────
def t_sanitize_strips_unissued_glyphs():
    assert sanitize_captcha("vs9jn+") == "vs9jn", "a '+' can never be a portal character"
    assert sanitize_captcha("ab.cd ") == "abcd"
    assert sanitize_captcha("AbC123") == "AbC123", "case must survive — the portal accepts it"
    assert sanitize_captcha("") == ""


# ── the route ───────────────────────────────────────────────────────────────
def t_route_auth_fails_closed():
    seed()
    os.environ["CAPTCHA_SECRET"] = "s3cret"
    cl = A.app.test_client()
    assert cl.get("/internal/captcha").status_code == 401
    assert cl.get("/internal/captcha", headers={"X-Captcha-Token": "nope"}).status_code == 401
    r = cl.get("/internal/captcha", headers={"X-Captcha-Token": "s3cret"})
    assert r.status_code == 200, r.data
    assert "success" in r.get_json() and "failed" in r.get_json(), r.get_json()


def t_route_writes_into_the_named_folder():
    seed()
    os.environ["CAPTCHA_SECRET"] = "s3cret"
    h = {"X-Captcha-Token": "s3cret"}
    cl = A.app.test_client()
    # a distinct image per call: write() dedupes identical bytes per folder
    img2 = PNG + b"route-test"
    r = cl.post("/internal/captcha", headers=h,
                json={"image_b64": base64.b64encode(img2).decode(),
                      "text": "qqww12", "folder": "failed"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert os.path.basename(os.path.dirname(r.get_json()["path"])) == "failed"

    assert cl.post("/internal/captcha", headers=h,
                   json={"image_b64": "aGk=", "text": "x", "folder": "nope"}).status_code == 400
    assert cl.post("/internal/captcha", headers=h,
                   json={"image_b64": "aGk=", "text": "x", "ext": "sh"}).status_code == 400
    assert cl.post("/internal/captcha", headers=h, json={"text": "x"}).status_code == 400
    os.environ.pop("CAPTCHA_SECRET", None)


for _n, _f in sorted(list(globals().items())):
    if _n.startswith("t_") and callable(_f):
        check(_n[2:], _f)

print(f"\n{len(FAILS)} failed / {TOTAL[0]} checks" if FAILS else f"\nall {TOTAL[0]} checks passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
