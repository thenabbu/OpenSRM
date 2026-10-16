"""Internal/ops routes: health probe, metrics, no-cache static serving."""
from ..app import healthz, internal_metrics, static_no_cache
from . import FlatBlueprint

bp = FlatBlueprint("internal", __name__)

# audit 2026-09-27: Flask's built-in /static route is disabled in create_app
# (static_folder=None) because it registered the SAME rule as
# static_no_cache() and won the match, so that function never ran: no
# Service-Worker-Allowed header, no intended cache policy.
bp.add_url_rule("/static/<path:filename>", view_func=static_no_cache)
bp.add_url_rule("/healthz", view_func=healthz)
bp.add_url_rule("/internal/metrics", view_func=internal_metrics)
