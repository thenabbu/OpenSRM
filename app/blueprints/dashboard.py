"""Dashboard route: the authenticated index page (P3.1: nine real panels)."""
from ..app import index, track_tab
from ..views.dashboard import (
    academics,
    attendance,
    campus,
    fees,
    marks,
    settings,
    timetable,
    tools,
)
from . import FlatBlueprint

bp = FlatBlueprint("dashboard", __name__)

bp.add_url_rule("/", view_func=index)
bp.add_url_rule("/attendance", view_func=attendance)
bp.add_url_rule("/timetable", view_func=timetable)
bp.add_url_rule("/marks", view_func=marks)
bp.add_url_rule("/campus", view_func=campus)
bp.add_url_rule("/academics", view_func=academics)
bp.add_url_rule("/fees", view_func=fees)
bp.add_url_rule("/tools", view_func=tools)
bp.add_url_rule("/settings", view_func=settings)
bp.add_url_rule("/api/track/tab", methods=["POST"], view_func=track_tab)
