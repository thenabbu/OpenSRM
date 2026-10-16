"""Web Push routes: subscription/settings API + the cron tick endpoint."""
from ..app import (
    push_receipt,
    push_settings,
    push_status,
    push_subscribe,
    push_test,
    push_tick,
    push_unsubscribe,
)
from . import FlatBlueprint

bp = FlatBlueprint("push", __name__)

bp.add_url_rule("/internal/push/tick", methods=["POST"], view_func=push_tick)
bp.add_url_rule("/api/push/status", view_func=push_status)
bp.add_url_rule("/api/push/subscribe", methods=["POST"], view_func=push_subscribe)
bp.add_url_rule("/api/push/unsubscribe", methods=["POST"], view_func=push_unsubscribe)
bp.add_url_rule("/api/push/settings", methods=["POST"], view_func=push_settings)
bp.add_url_rule("/api/push/test", methods=["POST"], view_func=push_test)
bp.add_url_rule("/api/push/receipt", methods=["POST"], view_func=push_receipt)
