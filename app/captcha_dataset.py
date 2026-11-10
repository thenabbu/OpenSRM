"""CAPTCHA dataset capture — a labelled pair per login attempt the portal judged.

Navya's shape (2026-11-10):

    <DATA_DIR>/captcha-dataset/success/<correct ocr>.<ext>   portal ACCEPTED
    <DATA_DIR>/captcha-dataset/failed/<what ddddocr read>.<ext> portal said
                                                             "Invalid captcha"

The portal's own verdict is the only label that cannot lie — a vision model's
opinion is not ground truth (measured: ddddocr beat mistral-large-4 on 5 of 6
human-checked images, so any "they agree" metric understates the solver).

What counts as a FAILURE is read off the pipeline, never guessed:

  http_scraper._post_login  -> `"invalid captcha" in rhtml.lower()`
  scraper._do_login         -> `"invalid captcha" in err_lower`

Only those two branches mean "the OCR answer was rejected". Deliberately NOT
captured as failures:
  - `invalid credentials` — the captcha may well have been CORRECT; the label
    would be a lie and the portal then counts it against the 3-attempts lockout
  - silent rejection / captcha expired — the portal never judged the text
  - OCR empty — there is no answer to label

Rules that keep it honest:
  * Only inside a scrape scope (`_sync_ctx`), so a preflight solved for a
    visitor who never submits stores nothing.
  * Success is committed where the pipeline already knows it won (HRDSystem).
  * Byte-identical images are deduped per folder; a cap writes `.full`.
  * Never raises into the login path.

Toggle: CAPTCHA_DATASET=1 (env, read per call).
"""
import hashlib
import logging
import os
import threading

log = logging.getLogger("opensrm.captcha_dataset")

MAX_FILES = 100_000          # ~1.2 KB each -> ~120 MB per folder ceiling
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
        "image/svg+xml": "svg", "image/webp": "webp"}

# Anything that is not a plain filename character becomes nothing. A CAPTCHA
# answer is alnum; this exists because the same string reaches a path in two
# places (write() here, /internal/captcha in observability). A whitelist is the
# only sanitiser static analysis accepts (py/path-injection).
_NAME_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def safe_name(text):
    """A bare filename stem: whitelist, never blacklist. Empty -> \"\"."""
    return "".join(c for c in str(text) if c in _NAME_SAFE)[:64]


_ctx = None          # contextvars.ContextVar, created lazily
_ctx_lock = threading.Lock()
_seen = {}           # folder -> set of sha256[:16] written by THIS process
_seen_lock = threading.Lock()


def enabled():
    return os.environ.get("CAPTCHA_DATASET", "").strip().lower() in ("1", "true", "yes", "on")


def dataset_dir(folder=None):
    """<DATA_DIR>/captcha-dataset[/success|/failed]."""
    root = os.path.join(os.environ.get("DATA_DIR", "/app/data"), "captcha-dataset")
    return os.path.join(root, folder) if folder else root


def begin():
    """Start a recording scope for THIS thread/context. Paired with clear()."""
    global _ctx
    if _ctx is None:
        with _ctx_lock:
            if _ctx is None:
                import contextvars
                _ctx = contextvars.ContextVar("opensrm_captcha_dataset", default=None)
    _ctx.set({"img": None})


def clear():
    if _ctx is not None:
        _ctx.set(None)


def offer(img_bytes, ocr, content_type=None):
    """Stage a (image, ocr) pair for the CURRENT attempt, replacing the last."""
    if _ctx is None or not enabled():
        return
    try:
        s = _ctx.get()
    except LookupError:
        return
    if s is None or not img_bytes or not ocr:
        return
    ext = _EXT.get((content_type or "").split(";")[0].strip().lower())
    if ext is None:   # no trustworthy header (playwright canvas) -> sniff, then png
        ext = "jpg" if img_bytes[:3] == b"\xff\xd8\xff" else "png"
    s["img"] = (bytes(img_bytes), str(ocr).strip(), ext)


def commit():
    """Login SUCCEEDED — the staged pair is the one the portal accepted."""
    _flush("success")


def reject():
    """The portal answered "Invalid captcha" — the staged read was wrong."""
    _flush("failed")


def _flush(folder):
    if _ctx is None:
        return
    try:
        s = _ctx.get()
    except LookupError:
        return
    if not s or not s.get("img"):
        return
    write(*s["img"], folder=folder)


def write(img_bytes, ocr, ext="png", folder="success"):
    """Write one pair. Never raises; returns the path written or None."""
    if not enabled():
        return None
    digest = None
    try:
        safe = safe_name(ocr)
        if not safe:
            return None
        digest = hashlib.sha256(img_bytes).hexdigest()[:16]
        with _seen_lock:
            seen = _seen.setdefault(folder, set())
            if digest in seen:
                return None
            if len(seen) > 5000:        # ponytail: process-lifetime dedupe memory
                seen.clear()
            seen.add(digest)
        d = dataset_dir(folder)
        os.makedirs(d, exist_ok=True)
        try:
            if sum(len(f) for _r, _dd, f in os.walk(d)) >= MAX_FILES:
                marker = os.path.join(d, ".full")
                if not os.path.exists(marker):
                    open(marker, "w").close()
                    log.warning("captcha dataset full at %d files dir=%s", MAX_FILES, d)
                return None
        except OSError:
            pass
        path = os.path.join(d, f"{safe}.{ext}")
        # The whitelist already makes traversal impossible; this proves the
        # result still resolves inside the folder before anything is opened.
        if os.path.dirname(os.path.realpath(path)) != os.path.realpath(d):
            log.warning("captcha dataset refused out-of-dir path ocr=%r", ocr)
            return None
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(img_bytes)
        os.replace(tmp, path)
        if digest:
            _note_seen(digest, folder)
        return path
    except Exception as e:      # a dataset write must never break a login
        log.warning("captcha dataset write failed ocr=%r err=%r", ocr, e)
        return None


def _note_seen(digest, folder):
    """One captcha_seen row, tagged success/failed, for pacing + a quick ratio."""
    try:
        from .db import insert_captcha_seen
        insert_captcha_seen(digest, folder)
    except Exception as e:
        log.debug("captcha_seen insert failed err=%r", e)
