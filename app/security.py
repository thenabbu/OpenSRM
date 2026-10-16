"""Shared route decorators.

`require_login` guards authenticated views across several route groups
(dashboard, marks, auth sync, feedback, account deletion), so it lives
here instead of any single blueprint.
"""
from functools import wraps

from flask import redirect


def require_login(f):
    # The app module is imported at decorator-application time (once per
    # view, during app import), not per request: app/app.py imports this
    # module at the top of its import block — before `get_current_user`
    # exists — and the blueprint modules import their views from app.app,
    # so a module-level `from .app import get_current_user` here would
    # deadlock on either entry order. The ATTRIBUTE lookup happens at call
    # time on purpose: tests patch `app.app.get_current_user` to simulate a
    # session vanishing mid-request, and the decorator must see the patch
    # (same module-globals resolution the pre-split app.py had).
    from . import app as _app

    @wraps(f)
    def w(*a, **kw):
        if not _app.get_current_user():
            return redirect("/login")
        return f(*a, **kw)
    return w
