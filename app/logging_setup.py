"""Structured logging setup for OpenSRM.

Call once at startup:
    from logging_setup import setup_logging
    setup_logging()

Log format:
    2026-09-22T16:00:00 INFO opensrm.http method=GET path=/api/marks status=200 duration_ms=45
"""
import logging
import os
import sys
import threading
import time
import urllib.request

LOG_DIR = os.environ.get("DATA_DIR", "/app/data")
LOG_FILE = os.path.join(LOG_DIR, "opensrm.log")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


class _Formatter(logging.Formatter):
    """Compact: TIMESTAMP LEVEL name message key=value ..."""
    def format(self, record):
        ts = self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
        msg = record.getMessage()
        extra = ""
        if hasattr(record, "kv"):
            extra = " " + " ".join(f"{k}={v}" for k, v in record.kv.items())
        out = f"{ts} {record.levelname} {record.name} {msg}{extra}"
        if record.exc_info:
            out += "\n" + self.formatException(record.exc_info)   # never swallow tracebacks
        return out


class NtfyHandler(logging.Handler):
    """POST real faults to an ntfy topic (env NTFY_ALERT_URL): ERROR+ records
    or any record whose kv carries status>=500. Routine 4xx (typo'd password,
    bot 404, portal-busy 429) stays file-only — a tripwire that pages on typos
    trains the operator to ignore it. Rate-limited to 1/min — a failure storm
    must not become a notification storm; ponytail: drops the rest of the storm.
    ponytail: best-effort by design — emit() must never raise or log
    (logging a logging failure recurses)."""
    _MIN_INTERVAL = 60.0

    def __init__(self, url):
        super().__init__(level=logging.WARNING)
        self.url = url
        self._last = 0.0

    def emit(self, record):
        try:
            st = int(getattr(record, "kv", {}).get("status", 0))
        except (TypeError, ValueError):
            st = 0
        if record.levelno < logging.ERROR and st < 500:
            return
        now = time.monotonic()
        if now - self._last < self._MIN_INTERVAL:
            return
        self._last = now
        try:
            msg = f"OpenSRM {record.levelname} {record.name}: {record.getMessage()}"
            if hasattr(record, "kv"):
                # an alert that says only "request" tells nothing — the kv
                # (path/status/error) IS the cause the tripwire exists for
                msg += " " + " ".join(f"{k}={v}" for k, v in record.kv.items())
            msg = msg[:400]
            req = urllib.request.Request(self.url, data=msg.encode("utf-8"), method="POST")
        except Exception:
            return
        # POST off the logging hot path: Handler.handle() holds self.lock for
        # the whole emit, so a synchronous 5s urlopen (ntfy outage) stalled
        # request threads — gunicorn runs 8 threads sharing this lock.
        # A failed send re-arms the window in 10s instead of eating the next
        # 60s of alerts, and the 10s floor still bounds a dead-ntfy storm.
        def _send():
            try:
                urllib.request.urlopen(req, timeout=2).close()
            except Exception:
                self._last = time.monotonic() - self._MIN_INTERVAL + 10.0
        threading.Thread(target=_send, daemon=True).start()


def setup_logging():
    # audit 2026-10-07: levelling the ROOT at DEBUG opened every library's
    # debug channel (PIL/urllib3/asyncio: 346 junk lines in 15 prod days).
    # Root stays at INFO; only the opensrm.* tree obeys LOG_LEVEL.
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    logging.getLogger("opensrm").setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    # opensrm.portal stays DEBUG even at prod INFO: the incident recipes
    # (invalid_captcha, step=post, silent_rejection, preflight detail) read
    # this namespace — its volume is ~190 lines/day, keep the forensics.
    logging.getLogger("opensrm.portal").setLevel(logging.DEBUG)
    root.handlers.clear()
    fmt = _Formatter()
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        # audit 2026-10-07: plain FileHandler grew unbounded (7.2MB in 15 days,
        # 95% of the data volume that also holds srm.db). Daily rotation,
        # 14 days kept = the forensic window prod investigations actually use.
        from logging.handlers import TimedRotatingFileHandler
        fh = TimedRotatingFileHandler(LOG_FILE, when="midnight", backupCount=14,
                                      encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as e:
        # audit 2026-10-07: a missing/unwritable log file was itself silent —
        # prime suspect for "errors sometimes logged, sometimes missed"
        logging.getLogger("opensrm").warning("log file unavailable: %r", e)
    alert_url = os.environ.get("NTFY_ALERT_URL", "").strip()
    if alert_url:
        logging.getLogger("opensrm").addHandler(NtfyHandler(alert_url))
    logging.getLogger("opensrm").info("logging.level=%s initialized", LOG_LEVEL)


def log_with_kv(logger: logging.Logger, level: int, msg: str, **kv):
    if not logger.isEnabledFor(level):
        # Logger.handle() (unlike debug()/info()/warning()) BYPASSES the
        # logger's own level check — without this gate every kv record
        # ignores LOG_LEVEL: the healthcheck's "DEBUG" demoted lines still
        # wrote at prod INFO (the 86% noise cut never took effect).
        return
    record = logger.makeRecord(logger.name, level, "(setup)", 0, msg, (), None)
    record.kv = kv
    logger.handle(record)



