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
from contextlib import contextmanager
from typing import Optional

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
        return f"{ts} {record.levelname} {record.name} {msg}{extra}"


def setup_logging():
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    root.handlers.clear()
    fmt = _Formatter()
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    logging.getLogger("opensrm").info("logging.level=%s initialized", LOG_LEVEL)


def log_with_kv(logger: logging.Logger, level: int, msg: str, **kv):
    record = logger.makeRecord(logger.name, level, "(setup)", 0, msg, (), None)
    record.kv = kv
    logger.handle(record)


@contextmanager
def timed(name: str, logger: Optional[logging.Logger] = None):
    _logger = logger or logging.getLogger("opensrm")
    t0 = time.monotonic()
    yield
    ms = int((time.monotonic() - t0) * 1000)
    log_with_kv(_logger, logging.INFO, name, duration_ms=ms)
