"""Typed boot configuration — the environment is read once, here.

AppConfig.from_env() snapshots the boot knobs (DATA_DIR, OCR_PREWARM) at
construction and create_app(config) consumes the snapshot: importing the
app module no longer reads env or touches the filesystem outside the
factory. Deliberately NOT moved into this snapshot: request-time knobs
(rate limits, TIMETABLE_EDITOR, SYNC_* windows, secrets such as
FERNET_KEYS/METRICS_SECRET/PUSH_TICK_SECRET) stay env-per-call reads by
design — ops flips them without a reboot.

app/app.py keeps module-level DATA_DIR/DB_PATH mirrors of the DEFAULT
app's config: db.py's lazy `from .app import DB_PATH` falls back to them
outside an app context (scripts, CLI tools, background threads), and
tests that set DATA_DIR before import keep working unchanged.
"""
import os
from dataclasses import dataclass


def _flag(raw, default):
    """unset/empty -> default; otherwise true on 1/true/yes/on (any case)."""
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class AppConfig:
    """One app's boot inputs. Paths derive from data_dir so a hand-built
    config (tests: two apps, two dirs) can never disagree with itself."""

    data_dir: str
    db_path: str
    secret_path: str
    prewarm_ocr: bool = True

    @classmethod
    def from_env(cls) -> "AppConfig":
        data_dir = os.environ.get("DATA_DIR", "/app/data")
        return cls(
            data_dir=data_dir,
            db_path=os.path.join(data_dir, "srm.db"),
            secret_path=os.path.join(data_dir, "secret"),
            prewarm_ocr=_flag(os.environ.get("OCR_PREWARM"), True),
        )
