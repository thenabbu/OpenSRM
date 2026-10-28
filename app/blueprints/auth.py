"""Auth routes: login form, sync entry points, logout, account deletion."""
from ..app import (
    account_delete,
    api_login,
    api_login_preflight,
    api_login_progress,
    api_refresh,
    api_scope_status,
    login,
    logout,
)
from . import FlatBlueprint

bp = FlatBlueprint("auth", __name__)

bp.add_url_rule("/login", view_func=login)
bp.add_url_rule("/api/login", methods=["POST"], view_func=api_login)
bp.add_url_rule("/api/refresh", methods=["POST"], view_func=api_refresh)
bp.add_url_rule("/api/login/preflight", methods=["POST"], view_func=api_login_preflight)
bp.add_url_rule("/api/login/progress", methods=["POST"], view_func=api_login_progress)
bp.add_url_rule("/api/scope/status", methods=["GET"], view_func=api_scope_status)
bp.add_url_rule("/logout", view_func=logout)
bp.add_url_rule("/api/account/delete", methods=["POST"], view_func=account_delete)
