"""Timetable routes: official-grid API, edit history, save (editor-gated)."""
from ..app import api_get_timetable, api_save_timetable, api_timetable_history
from . import FlatBlueprint

bp = FlatBlueprint("timetable", __name__)

bp.add_url_rule("/api/timetable", methods=["GET"], view_func=api_get_timetable)
bp.add_url_rule("/api/timetable/history", methods=["GET"], view_func=api_timetable_history)
bp.add_url_rule("/api/timetable", methods=["POST"], view_func=api_save_timetable)
