"""Dashboard route: the authenticated index page."""
from ..app import index, track_tab
from . import FlatBlueprint

bp = FlatBlueprint("dashboard", __name__)

bp.add_url_rule("/", view_func=index)
bp.add_url_rule("/api/track/tab", methods=["POST"], view_func=track_tab)
