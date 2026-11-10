"""The offline shell: a PII-free copy of a panel page.

Why this exists
---------------
`app/static/sw.js` refuses to cache rendered HTML — a cached dashboard shown to
the next student on a shared device is exactly the leak fixed in audit run-1
#12. The consequence was that offline, every navigation got a generic 503, so
the IndexedDB cache the app spends the whole session filling could never be
read back: a reload never reached the app at all.

The fix is to cache a **shell**: the real page with every piece of personal data
removed. Nav, layout, static asset links and the island mounts survive — those
are identical for every student. Rows do not: no props, no name, no netid, no
numbers. The rows are, and remain, only in IndexedDB keyed by netid.

So an offline visit loads the shell, the islands ask Dexie for *their own*
netid's rows, and a different student on the same device simply misses (their
netid is not the stored key). Nothing personal is ever in the HTTP cache.
"""
import re

from flask import Response

from ..app import get_current_user
from ..views.dashboard import shell as _shell

# (pattern, replacement) applied to the rendered page. Each one removes a piece
# of personal data that the real page carries. Order matters: the more specific
# patterns run before the looser ones.
_SCRUB = (
    # The island prop payloads: `<script type="application/json" id="island-x">…`
    (re.compile(r'(<script[^>]*id="island-[^"]*"[^>]*>).*?(</script>)', re.S), r"\1\2"),
    # data-props="#island-x" — without this the island would try to parse an
    # empty block and log an invalid-props warning on every offline load.
    (re.compile(r'\s+data-props="#[^"]*"'), ""),
    # The sync-age caption's own props + text (a timestamp is personal data:
    # "synced 2 min ago" tells an observer when this student was last active).
    (re.compile(r'(<span[^>]*data-island="sync-age"[^>]*>).*?(</span>)', re.S), r"\1\2"),
    (re.compile(r'\stitle="\d{4}-\d{2}-\d{2}[^"]*"'), ""),
    # `data-netid="ng2776"` on <body>: the cache key must not be published in a
    # page that sits in the HTTP cache. The app learns its netid from /api/me
    # on a shell load instead (session.ts falls back to that).
    (re.compile(r'\s+data-netid="[^"]*"'), ""),
    # The student's own netid anywhere else (meta description, og:title, title).
    (re.compile(r"(<title>OpenSRM)[^<]*(</title>)"), r"\1\2"),
    (re.compile(r'(content="OpenSRM)[^"]*(")'), r"\1\2"),
    (re.compile(r'(content=")[^"]*(")<!-- netid in description -->'), r"\1\2"),
)

# Anything that still looks like a netid after scrubbing means the page leaked.
_NETID_LIKE = re.compile(r'\b[a-z]{2}\d{4,}\b')


def _scrub(html: str) -> str:
    for pat, repl in _SCRUB:
        html = pat.sub(repl, html)
    return html


def api_shell(panel: str = "dashboard"):
    """`GET /shell/<panel>` — the panel page with every personal value blanked.

    The blanking happens in the VIEW MODEL (views/dashboard.py:shell()), not by
    scrubbing rendered HTML: `presentation()` never receives the rows, so there
    is no page that ever contained PII to scrub out. A regex pass over rendered
    output is the fragile version of this — it silently misses a field the day
    someone adds one to a template.

    `_assert_no_pii` still runs as a belt: if anything netid-shaped survives into
    the response, the route refuses to serve it rather than letting the service
    worker cache it.

    Requires a session: a shell exists for a logged-in student's next visit.
    Anonymous callers get 401 like every other panel endpoint.
    """
    netid = get_current_user()
    if not netid:
        return Response('{"ok":false,"error":"not logged in"}', status=401,
                        mimetype="application/json")

    resp = _shell(panel)
    body = resp.get_data(as_text=True) if hasattr(resp, "get_data") else str(resp)

    leaked = _NETID_LIKE.search(body)
    if leaked:
        return Response(
            f'{{"ok":false,"error":"shell leaked personal data: {leaked.group(0)}"}}',
            status=500, mimetype="application/json")

    r = Response(body, mimetype="text/html")
    r.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    r.headers["X-Shell-Panel"] = panel
    return r


from . import FlatBlueprint  # noqa: E402  (mirrors the other blueprints)

bp = FlatBlueprint("shell", __name__)

# One real `def` per route: FlatBlueprint derives the endpoint from __name__,
# so lambdas collide ("overwriting an existing endpoint function: <lambda>").
def shell_dashboard():
    return api_shell("dashboard")


def shell_attendance():
    return api_shell("attendance")


def shell_timetable():
    return api_shell("timetable")


def shell_marks():
    return api_shell("marks")


def shell_campus():
    return api_shell("campus")


def shell_academics():
    return api_shell("academics")


def shell_fees():
    return api_shell("fees")


def shell_tools():
    return api_shell("tools")


def shell_settings():
    return api_shell("settings")


bp.add_url_rule("/shell/", view_func=shell_dashboard)
bp.add_url_rule("/shell/attendance", view_func=shell_attendance)
bp.add_url_rule("/shell/timetable", view_func=shell_timetable)
bp.add_url_rule("/shell/marks", view_func=shell_marks)
bp.add_url_rule("/shell/campus", view_func=shell_campus)
bp.add_url_rule("/shell/academics", view_func=shell_academics)
bp.add_url_rule("/shell/fees", view_func=shell_fees)
bp.add_url_rule("/shell/tools", view_func=shell_tools)
bp.add_url_rule("/shell/settings", view_func=shell_settings)
