#!/usr/bin/env python3
"""Generate docs/architecture.html — OpenSRM data flow, rev3 (geometry from boxes).

Rev2 wrote every arrow path by hand (`M 456,176 H 432 Q 424,176 …`) for the
pre-SCOPE node layout. When SCOPE was added the nodes moved and those numbers
did not: connectors ended in empty canvas, ran behind boxes they did not join,
and the SCOPE node was painted on top of the SQLite store (a text read of the
shipped PNG showed "SQLite store backend" with "SCOPE" bleeding through its
sublabels).

Rev3 derives everything instead:

  * NODES holds the only hand-written coordinates. Each connector gets its
    ports from `facing()`, fanned per edge when several share it, and its path
    from `elbow()` — rounded right-angle elbows, always perpendicular to the
    edge it leaves and enters.
  * Each arrow label is placed beside its own segment, on an opaque mask, 6px
    clear of the stroke.
  * `build()` fails the build on: a port off its box edge, a segment crossing a
    non-endpoint box, a label mask within 6px of any stroke, a label overlapping
    a node or another label, two nodes overlapping, off-grid coordinates and
    text that overflows its box. The old drift happened because nothing checked.

Layout: two zones by tier (browser | container), sources along one row inside
the container, the store the single terminal node bottom right.
Dials: doc-inline 1040x640 · balanced · mixed. Skin: openSRM (unchanged).

Regen: python3 scripts/build_arch_diagram.py docs/architecture.html
       python3 <diagram-design skill>/scripts/export_png.py docs/architecture.html docs/architecture.png 2
"""
import math
import sys

# ── skin: DESIGN.md Appendix A (this palette is the part that already worked)
def oklch_to_hex(L, C, Hdeg):
    h = math.radians(Hdeg); a, b = C * math.cos(h), C * math.sin(h)
    l_, m_, s_ = L + 0.3963377774*a + 0.2158037573*b, L - 0.1055613458*a - 0.0638541728*b, L - 0.0894841775*a - 1.2914855480*b
    l, m, s = l_**3, m_**3, s_**3
    r = +4.0767416621*l - 3.3077115913*m + 0.2309699292*s
    g = -1.2684380046*l + 2.6097574011*m - 0.3413193965*s
    bl = -0.0041960863*l - 0.7034186147*m + 1.7076147010*s
    def enc(x):
        x = max(0.0, min(1.0, x))
        x = 12.92*x if x <= 0.0031308 else 1.055*(x**(1/2.4)) - 0.055
        return round(max(0, min(255, int(x*255 + 0.5))))
    return '#%02x%02x%02x' % (enc(r), enc(g), enc(bl))

PAPER   = oklch_to_hex(0.20, 0, 0)
NODE_BG = oklch_to_hex(0.14, 0, 0)
RULE    = oklch_to_hex(0.26, 0, 0)
INK, MUTED, SOFT = '#ffffff', 'rgba(255,255,255,0.62)', 'rgba(255,255,255,0.50)'
RULE_A  = 'rgba(255,255,255,0.16)'
ACCENT, ACC_T = '#ffffff', 'rgba(255,255,255,0.10)'
LINK    = oklch_to_hex(0.58, 0.158, 241.966)
EXT_F, EXT_S = 'rgba(255,255,255,0.03)', 'rgba(255,255,255,0.30)'
IN_F,  IN_S  = 'rgba(255,255,255,0.10)', 'rgba(255,255,255,0.50)'
F_SANS  = "'Geist', system-ui, sans-serif"
F_MONO  = "'Geist Mono', ui-monospace, monospace"
F_SERIF = "'Instrument Serif', serif"
W, H = 1024, 640
LEGEND_Y = 566
R = 8          # elbow radius
GAP = 6        # label mask → stroke gap (rule 2: 6–10px)
PORT_MIN = 12  # two ports on one edge (rule 4)

errors = []


def on_grid(*vals):
    for v in vals:
        if v % 4:
            errors.append(f"off-grid value {v}")


def text_w(text, size, mono=False):
    return len(text) * (size * (0.62 if mono else 0.60))


# ── content: the ONLY hand-written coordinates in this file
# kind → (fill, stroke, stroke-width, dash)
STYLES = {
    "input":    (IN_F, IN_S, 1.0, None),
    "external": (EXT_F, EXT_S, 1.0, None),
    "backend":  (NODE_BG, RULE, 1.0, None),
    "core":     (ACC_T, ACCENT, 1.4, None),
    "optional": (EXT_F, EXT_S, 1.0, "4,3"),
}

# Four columns share one x/width each (COL), and rows share one y/height (ROW),
# so no box can drift out of alignment with its neighbours.
# Columns share one x/width, rows one y/height — no box can drift out of line.
COL = {"A": (32, 216), "B": (296, 216), "C": (600, 200), "D": (836, 176)}
ROW = {"1": (104, 64), "2": (184, 64), "3": (264, 64),
       "4": (344, 64), "5": (424, 64), "6": (504, 64)}


def cell(col, row, kind, name, subs):
    x, w = COL[col]
    y, h = ROW[row]
    return dict(box=(x, y, w, h), kind=kind, name=name, subs=subs)


def tall(col, row, height, kind, name, subs):
    x, w = COL[col]
    y, _ = ROW[row]
    return dict(box=(x, y, w, height), kind=kind, name=name, subs=subs)


NODES = {
    # left: the client
    "browser":  cell("A", "1", "input", "Your browser", ["PWA · phone, laptop"]),
    # right: the two SRM systems this app reads
    "portal":   cell("D", "1", "external", "SRM student portal", ["HTML · captcha"]),
    "proxy":    cell("D", "2", "optional", "Egress proxy", ["when configured"]),
    "scope":    cell("D", "4", "external", "SCOPE backend", ["SOAP · double AES"]),
    # centre: the app, one vertical spine
    "edge":     cell("B", "1", "external", "Cloudflare edge", ["HTTPS"]),
    "routes":   cell("B", "2", "backend", "Flask routes + views",
                     ["session guards", "Jinja renders HTML"]),
    "limits":   cell("B", "3", "backend", "Rate limits + budget",
                     ["per netid · per IP · budget"]),
    "pipeline": cell("B", "4", "core", "Portal pipeline",
                     ["captcha preflight", "session reuse"]),
    "scopec":   cell("C", "4", "core", "SCOPE client", ["stdlib · 8-way pool"]),
    "parsers":  cell("B", "5", "backend", "Parsers", ["HTML + SCOPE JSON", "→ view data"]),
    "access":   cell("B", "6", "backend", "Data access", ["one repository"]),
    "store":    cell("C", "6", "core", "SQLite store", ["srm.db · volume"]),
}


def anchor(node):
    """Where an external lane can tap a right-column box on its left edge."""
    x, y, w, h = NODES[node]["box"]
    return (x, y + h // 2)


# id, from, to, style, colour, label, label_side, bidir, lane(x) | entry(node) | exit(node)
# `lane` pins the vertical run to a free corridor; `exit`/`entry` name the box
# edge the route taps when the geometric facing is not the one that reads right.
EDGES = [
    ("e1",  "browser",  "edge",     "solid",  "link",  "HTTPS",        "above", True),
    ("e2",  "edge",     "routes",   "solid",  "muted", None,           None,    True),
    ("e3",  "routes",   "limits",   "solid",  "muted", None,           None,    False),
    ("e4",  "limits",   "pipeline", "solid",  "muted", None,           None,    False),
    ("e5",  "pipeline", "parsers",  "solid",  "muted", "PERSIST",      "left",  False),
    # the app's calls to SRM leave the spine's right edge on one shared lane (560)
    ("e6",  "pipeline", "portal",   "solid",  "link",  "DIRECT",       "left",  True, 560),
    ("e7",  "pipeline", "proxy",    "dashed", "link",  "WHEN SET",     "left",  False, 560),
    ("e8",  "proxy",    "portal",   "dashed", "link",  None,           None,    False),
    ("e9",  "scopec",   "scope",    "solid",  "link",  "SOAP",         "left",  True,  560),
    ("e13", "access",   "store",    "solid",  "muted", "READ + WRITE", "above", True),
    ("e10", "routes",   "scopec",   "solid",  "muted", None,           None,    True),
    ("e11", "scopec",   "parsers",  "solid",  "muted", None,           None,    False),
    ("e12", "parsers",  "access",   "solid",  "muted", None,           None,    False),
]


# ── router
def side_points(box, side, n):
    """Attach points on one edge, fanned at L*k/(n+1) — corners never used."""
    x, y, w, h = box
    if side in ("top", "bottom"):
        L, y0 = w, (y if side == "top" else y + h)
        return [(round(x + L*(k+1)/(n+1)), y0) for k in range(n)]
    L, x0 = h, (x if side == "left" else x + w)
    return [(x0, round(y + L*(k+1)/(n+1))) for k in range(n)]


def facing(src, dst):
    sx, sy, sw, sh = src
    dx, dy, dw, dh = dst
    scx, scy = sx + sw/2, sy + sh/2
    dcx, dcy = dx + dw/2, dy + dh/2
    if abs(dcx - scx) >= abs(dcy - scy):
        return ("right", "left") if dcx > scx else ("left", "right")
    return ("bottom", "top") if dcy > scy else ("top", "bottom")


def elbow(p, q, r=R, lane=None):
    """Orthogonal path p → q with rounded corners; returns (d, segments).

    `lane` pins the vertical run to that x (a free corridor between columns)
    and makes it the dominant leg — a vertical-first route, which is what a
    call to a source overhead actually is.
    """
    (px, py), (qx, qy) = p, q
    if py == qy:
        pts = [p, q]
    elif px == qx:
        pts = [p, q]
    elif lane is not None and lane not in (px, qx):
        pts = [p, (lane, py), (lane, qy), q]
    elif abs(qx - px) >= abs(qy - py):
        mx = round((px + qx) / 2)
        pts = [p, (mx, py), (mx, qy), q]
    else:
        my = round((py + qy) / 2)
        pts = [p, (px, my), (qx, my), q]
    d = f"M {pts[0][0]},{pts[0][1]}"
    for i in range(1, len(pts) - 1):
        a, m, b = pts[i-1], pts[i], pts[i+1]
        rr = min(r, abs(m[0]-a[0])//2, abs(m[1]-a[1])//2,
                 abs(b[0]-m[0])//2, abs(b[1]-m[1])//2)
        if rr <= 0:
            d += f" L {m[0]},{m[1]}"
            continue
        ax = m[0] - rr if a[0] > m[0] else (m[0] + rr if a[0] < m[0] else m[0])
        ay = m[1] - rr if a[1] > m[1] else (m[1] + rr if a[1] < m[1] else m[1])
        bx = m[0] + rr if b[0] > m[0] else (m[0] - rr if b[0] < m[0] else m[0])
        by = m[1] + rr if b[1] > m[1] else (m[1] - rr if b[1] < m[1] else m[1])
        d += f" L {ax},{ay} Q {m[0]},{m[1]} {bx},{by}"
    d += f" L {pts[-1][0]},{pts[-1][1]}"
    segs = [(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) for i in range(len(pts)-1)]
    return d, segs


def seg_hits_box(seg, box):
    x1, y1, x2, y2 = seg
    bx, by, bw, bh = box
    x1, x2 = sorted((x1, x2)); y1, y2 = sorted((y1, y2))
    if x1 == x2:
        return bx < x1 < bx + bw and y1 < by + bh and y2 > by
    return by < y1 < by + bh and x1 < bx + bw and x2 > bx


def mask_clear(m, own, pending):
    """True when a label mask clears every stroke by GAP, every node (its own
    endpoints too — a label inside a box reads as a sublabel) and every other
    label. Used by placement so the gate rarely has to fire."""
    mx, my, mw, mh = m
    for q in pending:
        for (ax, ay, bx, by) in q["segs"]:
            if ax == bx:
                if min(ay, by) <= my + mh and max(ay, by) >= my:
                    if min(abs(mx - ax), abs(mx + mw - ax)) < GAP:
                        return False
            else:
                if min(ax, bx) <= mx + mw and max(ax, bx) >= mx:
                    if min(abs(my - ay), abs(my + mh - ay)) < GAP:
                        return False
    for n in NODES.values():
        bx, by, bw, bh = n["box"]
        if mx < bx + bw and mx + mw > bx and my < by + bh and my + mh > by:
            return False
    for q in pending:
        if q is own or not q.get("mask"):
            continue
        ox, oy, ow, oh = q["mask"]
        if mx < ox + ow and mx + mw > ox and my < oy + oh and my + mh > oy:
            return False
    return True


def build():
    pending = []
    for edge in EDGES:
        eid, a, b, style, colour, label, lside, bidir = edge[:8]
        lane = edge[8] if len(edge) > 8 else None
        sa, sb = facing(NODES[a]["box"], NODES[b]["box"])
        pending.append(dict(id=eid, a=a, b=b, style=style, colour=colour,
                            label=label, lside=lside, bidir=bidir, sa=sa,
                            sb=sb, lane=lane))

    for end in ("a", "b"):
        need = {}
        for p in pending:
            need[(p[end], p["s" + end])] = need.get((p[end], p["s" + end]), 0) + 1
        points = {}
        for (node, side), n in need.items():
            box = NODES[node]["box"]
            span = box[2] if side in ("top", "bottom") else box[3]
            if n > 1 and span / (n + 1) < PORT_MIN:
                errors.append(f"{node}.{side}: {n} ports in {span}px — under {PORT_MIN}px apart")
            points[(node, side)] = side_points(box, side, n)
        for p in pending:
            p["p" if end == "a" else "q"] = points[(p[end], p["s" + end])].pop(0)

    for p in pending:
        sa, sb = NODES[p["a"]]["box"], NODES[p["b"]]["box"]
        for pt, box, role in ((p["p"], sa, "source"), (p["q"], sb, "target")):
            if not (box[0] <= pt[0] <= box[0]+box[2] and box[1] <= pt[1] <= box[1]+box[3]):
                errors.append(f"{p['id']}: {role} port {pt} is not on {p['a' if role=='source' else 'b']}'s edge")
        p["d"], p["segs"] = elbow(p["p"], p["q"], lane=p["lane"])
        for seg in p["segs"]:
            for nid, n in NODES.items():
                if nid not in (p["a"], p["b"]) and seg_hits_box(seg, n["box"]):
                    errors.append(f"{p['id']}: segment {seg} transits {nid}")

    for p in pending:
        if not p["label"]:
            p["mask"] = None
            continue
        if len(p["label"]) > 14:
            errors.append(f"{p['id']}: label {p['label']!r} over 14 chars")
        tw = math.ceil(text_w(p["label"], 8, mono=True) * 1.12) + 4
        th = 12
        segs = [s for s in p["segs"] if s[0] != s[2] or s[1] != s[3]]
        segs.sort(key=lambda s: -max(abs(s[2]-s[0]), abs(s[3]-s[1])))
        cands = []
        # every segment, tried in order of length; each offers both sides and a
        # few positions along itself, so one crowded stretch never starves a label
        for (x1, y1, x2, y2) in segs:
            if y1 == y2:                                  # horizontal run
                lo, hi = sorted((x1, x2))
                for frac in (0.5, 0.35, 0.65, 0.2, 0.8):
                    cxm = round(lo + (hi - lo) * frac)
                    cands.append((cxm - tw//2, y1 - th - GAP))
                    cands.append((cxm - tw//2, y1 + GAP))
            else:                                          # vertical run
                lo, hi = sorted((y1, y2))
                for frac in (0.5, 0.35, 0.65, 0.2, 0.8):
                    cym = round(lo + (hi - lo) * frac)
                    cands.append((x1 - tw - GAP, cym - th//2))
                    cands.append((x1 + GAP, cym - th//2))
        p["mask"] = None
        for (mx, my) in cands:
            m = (mx, my, tw, th)
            if not mask_clear(m, p, pending):
                continue
            p["mask"] = m
            break
        if p["mask"] is None:
            errors.append(f"{p['id']}: no clear label position for {p['label']!r}")

    for p in pending:
        m = p["mask"]
        if not m:
            continue
        mx, my, mw, mh = m
        for q in pending:
            for (ax, ay, bx, by) in q["segs"]:
                if ax == bx:
                    in_span = min(ay, by) <= my + mh and max(ay, by) >= my
                    dgap = min(abs(mx - ax), abs(mx + mw - ax))
                else:
                    in_span = min(ax, bx) <= mx + mw and max(ax, bx) >= mx
                    dgap = min(abs(my - ay), abs(my + mh - ay))
                if in_span and dgap < GAP:
                    errors.append(f"{p['id']}: mask {m} sits {dgap}px from a stroke")
        for nid, n in NODES.items():
            bx, by, bw, bh = n["box"]
            if mx < bx + bw and mx + mw > bx and my < by + bh and my + mh > by:
                errors.append(f"{p['id']}: mask {m} overlaps node {nid}")
        for q in pending:
            if q is p or not q["mask"]:
                continue
            ox, oy, ow, oh = q["mask"]
            if mx < ox + ow and mx + mw > ox and my < oy + oh and my + mh > oy:
                errors.append(f"{p['id']}: mask overlaps {q['id']}'s label")

    joined = {p["a"] for p in pending} | {p["b"] for p in pending}
    for nid in NODES:
        if nid not in joined:
            errors.append(f"{nid}: orphan node — no connector touches it")

    ids = list(NODES)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = NODES[ids[i]]["box"], NODES[ids[j]]["box"]
            if a[0] < b[0]+b[2] and a[0]+a[2] > b[0] and a[1] < b[1]+b[3] and a[1]+a[3] > b[1]:
                errors.append(f"nodes overlap: {ids[i]} / {ids[j]}")
    for nid, n in NODES.items():
        on_grid(*n["box"])
        x, y, w, h = n["box"]
        if text_w(n["name"], 12) > w - 16:
            errors.append(f"{nid}: name overflows its box")
        for s in n["subs"]:
            if text_w(s, 9, mono=True) > w - 16:
                errors.append(f"{nid}: sublabel {s!r} overflows its box")
    return pending


# ── render
def render(pending):
    out = []
    add = out.append
    add(f'<rect width="100%" height="100%" fill="{PAPER}"/>')
    add(f'''<defs>
<marker id="arch-arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/></marker>
<marker id="arch-arrow-start" markerWidth="8" markerHeight="6" refX="1" refY="3" orient="auto"><polygon points="8 0, 0 3, 8 6" fill="{MUTED}"/></marker>
<marker id="arch-arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{LINK}"/></marker>
<marker id="arch-arrow-link-start" markerWidth="8" markerHeight="6" refX="1" refY="3" orient="auto"><polygon points="8 0, 0 3, 8 6" fill="{LINK}"/></marker>
</defs>''')

    for zx, zy, zw, zh, label in ((16, 80, 248, 112, "YOUR DEVICE"),
                                  (320, 80, 696, 528, "OPENSRM · FLASK + GUNICORN")):
        lw = math.ceil(text_w(label, 8, mono=True) * 1.1) + 16
        add(f'<rect x="{zx}" y="{zy}" width="{zw}" height="{zh}" rx="8" fill="rgba(255,255,255,0.02)" stroke="{RULE_A}" stroke-width="0.8"/>')
        add(f'<rect x="{zx+8}" y="{zy+2}" width="{lw}" height="12" rx="2" fill="{PAPER}"/>')
        add(f'<text x="{zx+8+lw//2}" y="{zy+11}" fill="{SOFT}" font-size="8" font-family="{F_MONO}" text-anchor="middle" letter-spacing="0.14em">{label}</text>')

    for p in pending:                                     # arrows behind boxes
        stroke = LINK if p["colour"] == "link" else MUTED
        mk = "arch-arrow-link" if p["colour"] == "link" else "arch-arrow"
        st = f'fill="none" stroke="{stroke}" stroke-width="{1.2 if p["style"] == "solid" else 1}"'
        if p["style"] == "dashed":
            st += ' stroke-dasharray="5,4"'
        st += f' marker-end="url(#{mk})"'
        if p["bidir"]:
            st += f' marker-start="url(#{mk}-start)"'
        add(f'<path d="{p["d"]}" {st}/>')

    for p in pending:                                     # labels over their masks
        if not p["mask"]:
            continue
        mx, my, mw, mh = p["mask"]
        add(f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="2" fill="{PAPER}"/>')
        add(f'<text x="{mx+mw//2}" y="{my+9}" fill="{SOFT}" font-size="8" font-family="{F_MONO}" text-anchor="middle" letter-spacing="0.06em">{p["label"]}</text>')

    for nid, n in NODES.items():                          # nodes last
        x, y, w, h = n["box"]
        fill, stroke, sw, dash = STYLES[n["kind"]]
        da = f' stroke-dasharray="{dash}"' if dash else ''
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>')
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{da}/>')
        ty = y + (h - (12 + 13*len(n["subs"])))//2 + 11
        add(f'<text x="{x+w//2}" y="{ty}" fill="{INK}" font-size="12" font-weight="600" font-family="{F_SANS}" text-anchor="middle">{n["name"]}</text>')
        ty += 13
        for s in n["subs"]:
            add(f'<text x="{x+w//2}" y="{ty}" fill="{MUTED}" font-size="9" font-family="{F_MONO}" text-anchor="middle">{s}</text>')
            ty += 13

    add(f'<line x1="32" y1="{LEGEND_Y-14}" x2="{W-32}" y2="{LEGEND_Y-14}" stroke="{RULE_A}" stroke-width="0.8"/>')
    add(f'<text x="32" y="{LEGEND_Y+2}" fill="{SOFT}" font-size="8" font-family="{F_MONO}" letter-spacing="0.14em">BOXES</text>')
    lx = 96

    def item(label, fill, stroke, sw=1.0, dash=None):
        nonlocal lx
        da = f' stroke-dasharray="{dash}"' if dash else ''
        add(f'<rect x="{lx}" y="{LEGEND_Y-8}" width="16" height="12" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{da}/>')
        lx += 22
        add(f'<text x="{lx}" y="{LEGEND_Y+2}" fill="{MUTED}" font-size="8" font-family="{F_MONO}" letter-spacing="0.10em">{label}</text>')
        lx += math.ceil(text_w(label, 8, mono=True) * 1.1) + 26

    item("BROWSER", IN_F, IN_S)
    item("SRM SYSTEM", EXT_F, EXT_S)
    item("APP CODE", NODE_BG, RULE)
    item("PIPELINE + STORE", ACC_T, ACCENT, sw=1.4)
    item("OPTIONAL", EXT_F, EXT_S, dash="4,3")
    if lx > W - 32:
        errors.append(f"legend row 1 overflows: {lx}")

    add(f'<text x="32" y="{LEGEND_Y+30}" fill="{SOFT}" font-size="8" font-family="{F_MONO}" letter-spacing="0.14em">LINES</text>')
    lx = 96

    def arrow_item(kind, label, colour):
        nonlocal lx
        y = LEGEND_Y + 26
        c = LINK if colour == "link" else MUTED
        mk = "arch-arrow-link" if colour == "link" else "arch-arrow"
        if kind == "bidir":
            add(f'<line x1="{lx}" y1="{y}" x2="{lx+24}" y2="{y}" stroke="{c}" stroke-width="1.4" marker-end="url(#{mk})" marker-start="url(#{mk}-start)"/>')
        elif kind == "dashed":
            add(f'<line x1="{lx}" y1="{y}" x2="{lx+24}" y2="{y}" stroke="{c}" stroke-width="1.2" stroke-dasharray="5,4" marker-end="url(#{mk})"/>')
        else:
            add(f'<line x1="{lx}" y1="{y}" x2="{lx+24}" y2="{y}" stroke="{c}" stroke-width="1.4" marker-end="url(#{mk})"/>')
        lx += 32
        add(f'<text x="{lx}" y="{y+4}" fill="{MUTED}" font-size="8" font-family="{F_MONO}" letter-spacing="0.10em">{label}</text>')
        lx += math.ceil(text_w(label, 8, mono=True) * 1.1) + 26

    arrow_item("solid", "FLOW", "muted")
    arrow_item("bidir", "REQUEST + RESPONSE", "muted")
    arrow_item("solid", "SRM CALLS", "link")
    arrow_item("dashed", "OPTIONAL PATH", "link")
    if lx > W - 32:
        errors.append(f"legend row 2 overflows: {lx}")
    return "\n".join(out)


DESC = ("Your browser reaches the OpenSRM container through the Cloudflare edge. Inside it, Flask "
        "routes hand work to two independent sources: the portal pipeline, which fetches the SRM "
        "student portal directly or through the optional egress proxy, and the SCOPE client, which "
        "calls the SOAP backend behind SRM's mobile app. Both feed the parsers, everything is "
        "written through one data-access layer into the SQLite store, and the routes render pages "
        "from that store.")

PAGE = '''<!doctype html>
<!-- source of truth for docs/architecture.png — every connector is derived from the box
     coordinates in NODES and gated by build() before this file is written.
     dials: doc-inline 1040x640 · balanced · mixed · skin: openSRM (DESIGN.md Appendix A)
     regen: python3 scripts/build_arch_diagram.py docs/architecture.html
            python3 <diagram-design skill>/scripts/export_png.py docs/architecture.html docs/architecture.png 2 -->
<html lang="en">
<head>
<meta charset="utf-8">
<title>OpenSRM — data flow architecture</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  body { margin:0; background:%(paper)s; color:%(ink)s; font-family:%(sans)s; }
  .wrap { padding:32px; }
  .eyebrow { font-family:%(mono)s; font-size:8px; letter-spacing:.18em; text-transform:uppercase; color:%(soft)s; }
  h1 { font-family:%(serif)s; font-weight:400; font-size:28px; margin:6px 0 20px; }
  .diagram-container { width:100%%; overflow-x:auto; }
  svg { width:100%%; min-width:%(w)dpx; display:block; }
  @media print { .diagram-container { overflow-x:visible; } svg { min-width:0; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">OpenSRM · internals</div>
  <h1>Two sources, one store — how a sync flows</h1>
  <div class="diagram-container">
    <svg viewBox="0 0 %(w)d %(h)d" width="%(w)d" height="%(h)d" role="img" aria-labelledby="arch-title arch-desc" xmlns="http://www.w3.org/2000/svg">
      <title id="arch-title">OpenSRM data flow — portal and SCOPE into one store</title>
      <desc id="arch-desc">%(desc)s</desc>
%(body)s
    </svg>
  </div>
</div>
</body>
</html>
'''


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "docs/architecture.html"
    pending = build()
    body = render(pending)
    if errors:
        print("BUILD FAILED — geometry/content gate:")
        for e in dict.fromkeys(errors):
            print("  -", e)
        return 1
    open(out, "w").write(PAGE % dict(paper=PAPER, ink=INK, sans=F_SANS, mono=F_MONO,
                                     serif=F_SERIF, soft=SOFT, w=W, h=H,
                                     desc=DESC, body=body))
    print(f"OK -> {out} · {len(NODES)} nodes · {len(pending)} connectors · "
          f"{sum(1 for p in pending if p['mask'])} labels · all geometry checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
