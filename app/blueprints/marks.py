"""Marks routes: the internal-marks API and component tagging."""
from ..app import api_marks, marks_tag
from . import FlatBlueprint

bp = FlatBlueprint("marks", __name__)

bp.add_url_rule("/api/marks", view_func=api_marks)
bp.add_url_rule("/marks/tag", methods=["POST"], view_func=marks_tag)
