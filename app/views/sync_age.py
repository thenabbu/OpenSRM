"""The navbar sync caption — server-side render + island props (P4.1).

The caption used to be client-only: dash.js filled every `.sync-line` span at
load and re-ran a 60s setInterval. P4.1 makes it progressive enhancement: the
server paints the same text/classes into the span, marks it as a `sync-age`
island, and the Preact island re-ages it after hydration. dash.js is untouched;
its explicit renders (start of a refresh, end of one) still win, because the
island's tick preserves the legacy text it finds in the span.

Props travel exactly as notes/ISLAND_CONTRACT.md specifies:

    <span data-island="sync-age" ...></span>
    <script type="application/json" id="island-sync-age">{"ts":...,"full":...}</script>

The data block is inert (never executed), so it passes `script-src 'self'`.
One block serves ALL sync-age spans on a page: main.ts hands each mount point
the config rather than reading a per-span id (a <span> cannot contain the
<script>, which is why the contract's block sits beside it, not inside it).

The age buckets are pinned by tests/e2e/test_navbar.py's age table and mirrored
in web/src/lib/syncAge.ts — client and server must agree, or hydration would
repaint different text and shift the layout.
"""
import json
import time

from markupsafe import Markup

FRESH_S = 300


def caption(ts: int, now: float | None = None) -> str:
    """(15m ago) / (2h ago) / (2d ago) / Never synced / '' while fresh."""
    now = time.time() if now is None else now
    diff = (int(now) - ts) if ts else 0
    if not ts:
        return "Never synced"
    if diff < FRESH_S:
        return ""
    if diff < 3600:
        return "(%dm ago)" % (diff // 60)
    if diff < 86400:
        return "(%dh ago)" % (diff // 3600)
    return "(%dd ago)" % (diff // 86400)


def island_props(ts: int, full: str) -> Markup:
    """The inert JSON data block an island reads its props from."""
    payload = json.dumps({"ts": int(ts or 0), "full": full, "busy": None},
                         separators=(",", ":"))
    # '<' is the only character that can terminate or unbalance the block
    # (a '</script' or '<!--' inside the JSON); '\u003c' is the same JSON value
    payload = payload.replace("<", "\\u003c")
    return Markup('<script type="application/json" id="island-sync-age">%s</script>' % payload)
