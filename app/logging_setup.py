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
    """POST WARNING+ opensrm lines to an ntfy topic (env NTFY_ALERT_URL).
    So no error goes unseen: the alerter is the tripwire when nobody is
    tailing the log. Rate-limited to 1/min — a failure storm must not
    become a notification storm; ponytail: drops the rest of the storm.
    ponytail: best-effort by design — emit() must never raise or log
    (logging a logging failure recurses); next event retries."""
    _MIN_INTERVAL = 60.0

    def __init__(self, url):
        super().__init__(level=logging.WARNING)
        self.url = url
        self._last = 0.0

    def emit(self, record):
        now = time.monotonic()
        if now - self._last < self._MIN_INTERVAL:
            return
        self._last = now
        try:
            msg = f"OpenSRM {record.levelname} {record.name}: {record.getMessage()}"[:400]
            req = urllib.request.Request(self.url, data=msg.encode("utf-8"), method="POST")
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:
            pass


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



