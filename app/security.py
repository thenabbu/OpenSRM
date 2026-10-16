"""Shared route decorators.

`require_login` guards authenticated views across several route groups
(dashboard, marks, auth sync, feedback, account deletion), so it lives
here instead of any single blueprint.
"""
from functools import wraps

from flask import redirect


def require_login(f):
    # The app import happens at decorator-application time (once per view,
    # during app import), not per request: app/app.py imports this module
    # at the top of its import block — before `get_current_user` exists —
    # and the blueprint modules import their views from app.app, so a
    # module-level `from .app import get_current_user` here would deadlock
    # on either entry order. By the time any @require_login runs,
    # app.app has defined get_current_user already.
    from .app import get_current_user

    @wraps(f)
    def w(*a, **kw):
        if not get_current_user():
            return redirect("/login")
        return f(*a, **kw)
    return w
