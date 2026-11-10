"""CAPTCHA dataset capture — one labelled pair per successful portal login.

Navya's ask (2026-11-10): every time a login actually SUCCEEDS, keep the image
the portal served and the OCR string that was submitted, so the same solver can
later be retrained/evaluated on real traffic instead of synthetic guesses.

Design (see references/captcha-dataset.md in the opensrm skill for the why):

  * Best-effort only. Nothing here may raise into the login path, cost a
    request, or change a response. Every entry point is wrapped.
  * The recording is SCOPED to a contextvar that only the scrape flow sets
    (`_sync_ctx`), same trick app/scraper.py uses for portal-fail counting —
    so a preflight solved for a visitor who never submits a password stores
    NOTHING (that image was never validated against the portal).
  * ONLY a confirmed success writes a file: `HRDSystem` in the final URL (http
    pipeline) or the post-login URL check (playwright). A wrong-password login
    carries a correct captcha but is not evidence about the solver, and in the
    http pipeline a verified captcha whose credentials failed answers "retry"
    with the same context — 3 copies of the same image — so the last attempt
    wins.
  * Filenames are `<ocr>.<ext>` in one flat folder, byte-identical pairs
    deduped by sha256 of the image (session reuse and repeated logins in one
    process hit the same bytes). Collisions on OCR text are what a dataset
    wants: two images labelled the same string.
  * File size + count are capped so an unattended box cannot fill the volume.

Toggle: CAPTCHA_DATASET=1 (env, read per call so ops can flip without a
rebuild). Unset/0 = the module costs one env lookup and returns.
"""
import hashlib
import logging
import os
import threading

log = logging.getLogger("opensrm.captcha_dataset")

MAX_FILES = 100_000                       # ~1.2 KB each -> ~120 MB ceiling
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
        "image/svg+xml": "svg", "image/webp": "webp"}

_ctx = None          # contextvars.ContextVar, created lazily (py3.14 ok either way)
_ctx_lock = threading.Lock()
_seen = set()        # sha256[:16] already written by THIS process
_seen_lock = threading.Lock()


def enabled():
    return os.environ.get("CAPTCHA_DATASET", "").strip().lower() in ("1", "true", "yes", "on")


def dataset_dir():
    """<DATA_DIR>/captcha-dataset — the app's volume, so it survives restarts."""
    root = os.environ.get("DATA_DIR", "/app/data")
    return os.path.join(root, "captcha-dataset")


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
    """Stage a (image, ocr) pair. Overwrites the previous offer in this scope."""
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
    """A login just succeeded — write the staged pair, keep it staged as a
    candidate (a mid-scrape relogin may certify the same image again)."""
    if _ctx is None:
        return
    try:
        s = _ctx.get()
    except LookupError:
        return
    if not s or not s.get("img"):
        return
    write(*s["img"])


def write(img_bytes, ocr, ext="png"):
    """Write one pair + log the solved-image digest. Never raises; returns the
    path written or None."""
    if not enabled():
        return None
    digest = None
    try:
        safe = "".join(c for c in ocr if 32 <= ord(c) < 127).replace("/", "_").strip()
        if not safe:
            return None
        digest = hashlib.sha256(img_bytes).hexdigest()[:16]
        with _seen_lock:
            if digest in _seen:
                return None
            if len(_seen) > 5000:      # ponytail: process-lifetime dedupe memory
                _seen.clear()
            _seen.add(digest)
        d = dataset_dir()
        os.makedirs(d, exist_ok=True)
        try:
            if sum(len(f) for _r, _dd, f in os.walk(d)) >= MAX_FILES:
                if not os.path.exists(os.path.join(d, ".full")):
                    open(os.path.join(d, ".full"), "w").close()
                    log.warning("captcha dataset full at %d files dir=%s — stop capturing",
                                MAX_FILES, d)
                return None
        except OSError:
            pass
        path = os.path.join(d, f"{safe}.{ext}")
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(img_bytes)
        os.replace(tmp, path)
        if digest:
            _note_seen(digest)
        return path
    except Exception as e:      # a dataset write must never break a login
        log.warning("captcha dataset write failed ocr=%r err=%r", ocr, e)
        return None


def _note_seen(digest):
    """One captcha_seen row. Same transaction the login flow already uses
    (persist_sync runs after the scrape), so this deduped INSERT is free."""
    try:
        from .db import insert_captcha_seen
        insert_captcha_seen(digest, "login")
    except Exception as e:
        log.debug("captcha_seen insert failed err=%r", e)
