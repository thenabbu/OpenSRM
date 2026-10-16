"""Feedback routes: the opt-in mid-sem feedback autofill endpoint."""
from ..app import api_feedback_fill
from . import FlatBlueprint

bp = FlatBlueprint("feedback", __name__)

bp.add_url_rule("/api/feedback/fill", methods=["POST"], view_func=api_feedback_fill)
