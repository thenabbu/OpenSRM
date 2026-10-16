"""Dashboard route: the authenticated index page."""
from ..app import index
from . import FlatBlueprint

bp = FlatBlueprint("dashboard", __name__)

bp.add_url_rule("/", view_func=index)
