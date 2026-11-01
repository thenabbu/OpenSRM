"""Passwords at rest + the data dir that owns the current work.

Extracted from app/app.py (facade pump, phase 1). This module is a LEAF: it
imports nothing from app.app, so app.py can import it without a cycle. The
names are re-exported from app.app, so `from app.app import decrypt_pw`
(tests, scripts, rotate_fernet_key.py) keeps working unchanged.

Key material never leaves this module except as ciphertext.
"""
import logging
import os
import secrets

from flask import current_app, has_app_context

log = logging.getLogger("opensrm")

# module global (not a dict cell) so app/app.py can re-export the same object
# and tests can reset it: `A._fernet = None`.
_fernet = None


def default_data_dir():
    """DATA_DIR the boot config chose. app/app.py mirrors this as its module
    constant; kept here so the crypto path never imports app.app."""
    from .config import AppConfig
    return AppConfig.from_env().data_dir


def _active_data_dir():
    """The data dir that owns the CURRENT work: the serving app's config
    when a Flask app context is active (per-app fernet keys, the legacy
    timetable import during create_app), else the module default."""
    if has_app_context():
        d = current_app.config.get("DATA_DIR")
        if d:
            return d
    return default_data_dir()


def _load_secret(secret_path):
    """One app's session-signing secret: created on first boot, read-only
    after (moved out of import time into create_app)."""
    if not os.path.exists(secret_path):
        with open(secret_path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(secret_path, 0o600)
    return open(secret_path).read().strip()


def fernet_keys():
    """Key bytes get_fernet() is built from, shared with
    scripts/rotate_fernet_key.py so the tool and the app can never
    disagree about which keys are live.

    Returns (keys, from_env): FERNET_KEYS env (comma-separated, FIRST key
    is the primary/encrypting key) wins when set — rotation keeps keys off
    the data volume; otherwise the single persisted DATA_DIR/fernet.key
    (generated on first use), exactly as before."""
    from cryptography.fernet import Fernet
    parts = [k.strip().encode() for k in os.environ.get("FERNET_KEYS", "").split(",") if k.strip()]
    if parts:
        return parts, True
    key_path = os.path.join(_active_data_dir(), "fernet.key")
    if os.path.exists(key_path):
        return [open(key_path, "rb").read()], False
    key = Fernet.generate_key()
    with open(key_path, "wb") as f:
        f.write(key)
    os.chmod(key_path, 0o600)
    return [key], False


def get_fernet():
    """Lazy-init the data-at-rest cipher so restarts don't lose data.

    FERNET_KEYS set -> MultiFernet: the FIRST key encrypts, every key
    decrypts (old ciphertext stays readable during/after rotation).
    Otherwise -> single Fernet from DATA_DIR/fernet.key, default unchanged.

    The cache is read/written through THIS module (not a re-exported name), so
    `app.app._fernet = None` cannot desync it. Reset it with
    `app.crypto.reset_fernet()` — app.app reset_fernet() is the same function."""
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet, MultiFernet
        keys, from_env = fernet_keys()
        if from_env:
            try:
                _fernet = MultiFernet([Fernet(k) for k in keys])
            except ValueError as e:
                # config error, not corrupt data: name the env var, never echo a key
                raise RuntimeError("FERNET_KEYS contains an invalid key (%s)" % e) from None
        else:
            _fernet = Fernet(keys[0])
    return _fernet


def reset_fernet():
    """Drop the cached cipher so the next get_fernet() re-reads the keys
    (key rotation, and tests that swap FERNET_KEYS mid-process)."""
    global _fernet
    _fernet = None


def encrypt_pw(pw):
    return get_fernet().encrypt(pw.encode()).decode()


def decrypt_pw(blob):
    try:
        return get_fernet().decrypt(blob.encode()).decode()
    except Exception as e:
        log.warning("stored password unreadable — user must re-login: %r", e)
        return ""
