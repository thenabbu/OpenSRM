#!/usr/bin/env python3
"""Generate docs/architecture.html — diagram-design import-mermaid redraw, rev2.

Rev2 applies the architecture review (P0/P1):
  - arrow semantics defined + legend explains arrows (solid=runtime flow,
    bidir=HTTP request+response, blue=external HTTPS, dashed=optional path)
  - HTTP boundary explicit: Dashboard <-> Edge <-> Flask routes (bidirectional)
  - egress proxy ON the path with two alternative legs: solid = direct
    (default), dashed = via proxy "when set" (SRM_EGRESS_URL named in legend
    as config, not drawn as a connection)
  - "Sessions + limits" split where genuinely separate in code: rate limits +
    portal budget (app/state.py) is its own node; app sessions live in SQLite
    (labelled), progress stream sits with routes (its endpoint)
  - data-access layer added (app/db.py repository exists) so parsers never
    write the DB directly; read/write edges labelled
  - SQLite labelled persistent volume; login sessions vs portal session cache
    disambiguated in sublabels
  - operational shorthand removed from nodes (formIds, 5%->92%, schema v17,
    @24h) — those live in README prose/Config tables; code-dir refs removed
Dials: doc-inline 960x600 · balanced · mixed. Skin: openSRM (praised, unchanged).
Regen: python3 /opt/data/skills/creative/diagram-design/scripts/export_png.py <this> out.png 2
"""
import math, sys

def oklch_to_hex(L, C, Hdeg):
    h = math.radians(Hdeg); a, b = C*math.cos(h), C*math.sin(h)
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

PAPER   = oklch_to_hex(0.20, 0, 0)      # openSRM base-100
NODE_BG = oklch_to_hex(0.14, 0, 0)      # base-200 (inverted stack: darker than paper)
RULE    = oklch_to_hex(0.26, 0, 0)      # base-300 (lighter than paper)
INK, MUTED, SOFT = '#ffffff', 'rgba(255,255,255,0.60)', 'rgba(255,255,255,0.50)'
RULE_A  = 'rgba(255,255,255,0.16)'
ACCENT, ACC_T = '#ffffff', 'rgba(255,255,255,0.10)'
LINK    = oklch_to_hex(0.58, 0.158, 241.966)   # openSRM info = external link colour
EXT_F, EXT_S = 'rgba(255,255,255,0.03)', 'rgba(255,255,255,0.30)'
IN_F,  IN_S  = 'rgba(255,255,255,0.10)', 'rgba(255,255,255,0.50)'
F_SANS, F_MONO, F_SERIF = "'Geist', system-ui, sans-serif", "'Geist Mono', ui-monospace, monospace", "'Instrument Serif', serif"
W, H = 960, 600
errors = []
def grid(*vals):
    for v in vals:
        if v % 4: errors.append(f"off-grid: {v}")
def tw(text, size, mono=False, track=0.0):
    return len(text) * (size * (0.62 if mono else 0.60) + size*track)
def fit(text, size, box_w, mono=False, node=""):
    w = tw(text, size, mono)
    if w > box_w - 16: errors.append(f"overflow {node}: {w:.0f} > {box_w-16} ({text!r})")

svg = []
def add(s): svg.append(s)

add(f'<rect width="100%" height="100%" fill="{PAPER}"/>')
add(f'''<defs>
<marker id="arch-arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/></marker>
<marker id="arch-arrow-start" markerWidth="8" markerHeight="6" refX="1" refY="3" orient="auto"><polygon points="8 0, 0 3, 8 6" fill="{MUTED}"/></marker>
<marker id="arch-arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{LINK}"/></marker>
<marker id="arch-arrow-link-start" markerWidth="8" markerHeight="6" refX="1" refY="3" orient="auto"><polygon points="8 0, 0 3, 8 6" fill="{LINK}"/></marker>
<marker id="arch-arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{ACCENT}"/></marker>
</defs>''')

# ---- container zone (before arrows) ----
ZX, ZY, ZW, ZH = 440, 120, 476, 404
grid(ZX, ZY, ZW, ZH)
zl = "OPENSRM CONTAINER · FLASK + GUNICORN :8083"
zmw = math.ceil((tw(zl, 8, True, 0.14) + 16 + 3)/4)*4
add(f'<rect x="{ZX}" y="{ZY}" width="{ZW}" height="{ZH}" rx="8" fill="rgba(255,255,255,0.02)" stroke="{RULE_A}" stroke-width="0.8"/>')
add(f'<rect x="{ZX+8}" y="{ZY+4}" width="{zmw}" height="12" rx="2" fill="{PAPER}"/>')
add(f'<text x="{ZX+8+zmw//2}" y="{ZY+13}" fill="{SOFT}" font-size="8" font-family="{F_MONO}" text-anchor="middle" letter-spacing="0.14em">{zl}</text>')

def path(d, color=MUTED, dash=None, bidir=False, link=False, sw=1.2):
    st = f'fill="none" stroke="{color}" stroke-width="{sw}"'
    if dash: st += f' stroke-dasharray="{dash}"'
    mk = 'arch-arrow-link' if link else 'arch-arrow'
    st += f' marker-end="url(#{mk})"'
    if bidir:
        mks = 'arch-arrow-link-start' if link else 'arch-arrow-start'
        st += f' marker-start="url(#{mks})"'
    add(f'<path d="{d}" {st}/>')

def alabel(x, y, w, text, color=SOFT):
    if len(text) > 14: errors.append(f"arrow label >14ch: {text}")
    grid(x, y, w)
    add(f'<rect x="{x}" y="{y}" width="{w}" height="12" rx="2" fill="{PAPER}"/>')
    add(f'<text x="{x+w//2}" y="{y+9}" fill="{color}" font-size="8" font-family="{F_MONO}" text-anchor="middle" letter-spacing="0.06em">{text}</text>')

# ---- arrows (before nodes) ----
# top strip: Dashboard(24,48,176x48) Edge(224,48,144x48) Proxy(472,48,152x48)
#            Portal(712,48,176x48) Scope(712,356,176x48)
# middle:    routes(456,152,196x48) throttle(456,240,196x48) pipeline(676,240,224x48)
# left:      parsers(456,352,196x48) data-access(456,456,196x48)
# right:     store(676,352,224x48)
grid(24,48,176,224,144,472,152,712,176,356)
path("M 200,72 H 224", color=LINK, bidir=True, link=True)                       # Dashboard <-> Edge (external HTTPS)
path("M 296,96 V 144 H 548 Q 556,144 556,152", bidir=True)                      # Edge -> routes (HTTP boundary, in-app)
path("M 552,200 V 240")                                                          # routes -> throttle
path("M 652,264 H 676")                                                          # throttle -> portal pipeline
path("M 424,176 H 424,264 H 456", bidir=True)                                    # routes <-> SCOPE client (in-container)
# portal pipeline top -> portal (default direct path, bidir external HTTPS)
path("M 824,240 V 96", color=LINK, bidir=True, link=True)
# portal pipeline top -> proxy (optional detour, dashed, config-gated)
path("M 752,240 V 112 Q 752,104 744,104 H 680 Q 672,104 672,96 V 96", color=LINK, dash="5,4", link=True)
path("M 680,72 H 712", color=LINK, dash="5,4", link=True)                       # proxy -> portal
# SCOPE client -> SCOPE backend (direct, no proxy leg exists)
path("M 800,264 V 356", color=LINK, bidir=True, link=True)
# portal pipeline -> parsers -> data access -> store
path("M 744,288 V 300 Q 744,308 736,308 H 600 Q 592,308 592,316 V 328 Q 592,336 584,336 H 652")
path("M 554,400 V 456")                                                          # parsers -> data access
path("M 652,480 H 676", bidir=True)                                              # data access <-> store
# SCOPE client writes its own ops through the same data access layer
path("M 900,264 V 300 Q 900,308 892,308 H 868 Q 860,308 860,316 V 448 Q 860,456 852,456 H 652")
# routes <-> data access via the left channel (reads/writes stored app data)
path("M 456,176 H 432 Q 424,176 424,184 V 480 Q 424,488 432,488 H 456", bidir=True)

# ---- arrow labels ----
alabel(756, 180, 56, "WHEN SET")          # beside proxy leg
alabel(756, 208, 56, "HTTPS")             # beside direct portal leg
alabel(700, 300, 32, "PERSIST")           # beside pipeline -> parsers
alabel(596, 424, 80, "READ + WRITE")      # beside data-access <-> store

# ---- nodes ----
def node(x, y, w, h, name, subs, fill, stroke, sw=1, dash=None):
    grid(x, y, w, h)
    fit(name, 12, w, node=name)
    for s in subs: fit(s, 9, w, mono=True, node=name)
    block = 12 + 13*len(subs)
    top = y + (h - block)//2
    a = f' stroke-dasharray="{dash}"' if dash else ''
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{a}/>')
    by = top + 11
    add(f'<text x="{x+w//2}" y="{by}" fill="{INK}" font-size="12" font-weight="600" font-family="{F_SANS}" text-anchor="middle">{name}</text>')
    by += 13
    for s in subs:
        add(f'<text x="{x+w//2}" y="{by}" fill="{MUTED}" font-size="9" font-family="{F_MONO}" text-anchor="middle">{s}</text>')
        by += 13

node(24, 48, 176, 48, "Dashboard", ["Jinja2 · daisyUI · JS"], IN_F, IN_S)
node(224, 48, 144, 48, "Cloudflare edge", ["HTTPS · tunnel"], EXT_F, EXT_S)
node(472, 48, 152, 48, "Egress proxy", ["optional · CF worker"], EXT_F, EXT_S, sw=1, dash="4,3")
node(712, 48, 176, 48, "SRM student portal", ["sp.srmist.edu.in"], EXT_F, EXT_S)
node(712, 356, 176, 48, "SCOPE backend", ["SRM app · SOAP"], EXT_F, EXT_S)
node(456, 152, 196, 48, "Flask routes + views", ["session guards · progress", "Jinja renders HTML"], NODE_BG, RULE)
node(456, 240, 196, 48, "Rate limits + budget", ["per-netid · per-IP · budget"], NODE_BG, RULE)
node(676, 240, 224, 48, "Portal pipeline", ["captcha preflight while you type", "reuses cached portal session"], ACC_T, ACCENT, sw=1.4)
node(456, 352, 196, 48, "Pure parsers", ["HTML + SCOPE JSON → view data"], NODE_BG, RULE)
node(676, 352, 224, 48, "SQLite store", ["srm.db · persistent volume", "portal + SCOPE blobs"], ACC_T, ACCENT, sw=1.4)
node(456, 456, 196, 48, "Data access", ["one repository for all SQL"], NODE_BG, RULE)

# ---- legend: two rows in the bottom strip ----
add(f'<line x1="40" y1="540" x2="920" y2="540" stroke="{RULE_A}" stroke-width="0.8"/>')
add(f'<text x="40" y="558" fill="{SOFT}" font-size="8" font-family="{F_MONO}" letter-spacing="0.14em">TYPES</text>')
lx = 112
def sw_item(label, fill, stroke, dash=None, sw=1, y=548):
    global lx
    lx = math.ceil(lx/4)*4
    if dash:
        add(f'<line x1="{lx}" y1="{y+6}" x2="{lx+20}" y2="{y+6}" stroke="{stroke}" stroke-width="1.4" stroke-dasharray="4,3"/>')
        lx += 28
    else:
        add(f'<rect x="{lx}" y="{y}" width="16" height="12" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
        lx += 22
    w = math.ceil(tw(label, 8, True, 0.14))
    add(f'<text x="{lx}" y="{y+10}" fill="{MUTED}" font-size="8" font-family="{F_MONO}" letter-spacing="0.14em">{label}</text>')
    lx = math.ceil((lx + w + 28)/4)*4
sw_item("INPUT", IN_F, IN_S)
sw_item("EXTERNAL", EXT_F, EXT_S)
sw_item("BACKEND", NODE_BG, RULE)
sw_item("CORE", ACC_T, ACCENT, sw=1.4)
sw_item("OPTIONAL", None, EXT_S, dash="4,3")
if lx > 920: errors.append(f"legend row1 overflows: {lx}")

add(f'<text x="40" y="578" fill="{SOFT}" font-size="8" font-family="{F_MONO}" letter-spacing="0.14em">ARROWS</text>')
lx = 112
def arrow_item(kind, label, color=MUTED):
    global lx
    lx = math.ceil(lx/4)*4
    y = 574
    if kind == "solid":
        add(f'<line x1="{lx}" y1="{y}" x2="{lx+24}" y2="{y}" stroke="{color}" stroke-width="1.4" marker-end="url(#arch-arrow)"/>')
    elif kind == "bidir":
        add(f'<line x1="{lx}" y1="{y}" x2="{lx+24}" y2="{y}" stroke="{color}" stroke-width="1.4" marker-end="url(#arch-arrow)" marker-start="url(#arch-arrow-start)"/>')
    elif kind == "dashed":
        add(f'<line x1="{lx}" y1="{y}" x2="{lx+24}" y2="{y}" stroke="{color}" stroke-width="1.2" stroke-dasharray="5,4" marker-end="url(#arch-arrow-link)"/>')
    lx += 32
    w = math.ceil(tw(label, 8, True, 0.14))
    add(f'<text x="{lx}" y="{y+4}" fill="{MUTED}" font-size="8" font-family="{F_MONO}" letter-spacing="0.14em">{label}</text>')
    lx = math.ceil((lx + w + 28)/4)*4
arrow_item("solid", "RUNTIME FLOW")
arrow_item("bidir", "REQUEST + RESPONSE")
arrow_item("solid", "EXTERNAL HTTPS", color=LINK)
arrow_item("dashed", "OPTIONAL — SRM_EGRESS_URL set", color=LINK)
if lx > 920: errors.append(f"legend row2 overflows: {lx}")

if errors:
    print("BUILD FAILED:"); [print(" -", e) for e in errors]; sys.exit(1)

out = sys.argv[1] if len(sys.argv) > 1 else "docs/architecture.html"
open(out, "w").write(f'''<!doctype html>
<!-- source of truth for docs/architecture.png — diagram-design import-mermaid redraw rev2
     (applies the architecture review: arrow semantics + legend, explicit HTTP boundary,
      proxy as alternative path with config gate, state.py limits split out, app/db.py
      repository node, persistent-volume label, ops shorthand moved to README prose)
     dials: doc-inline 960x600 · balanced · mixed · skin: openSRM (DESIGN.md Appendix A)
     regen: python3 /opt/data/skills/creative/diagram-design/scripts/export_png.py <this file> out.png 2 -->
<html lang="en">
<head>
<meta charset="utf-8">
<title>OpenSRM — data flow architecture</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  body {{ margin:0; background:{PAPER}; color:{INK}; font-family:{F_SANS}; }}
  .wrap {{ padding:32px; }}
  .eyebrow {{ font-family:{F_MONO}; font-size:8px; letter-spacing:.18em; text-transform:uppercase; color:{SOFT}; }}
  h1 {{ font-family:{F_SERIF}; font-weight:400; font-size:28px; margin:6px 0 20px; }}
  .diagram-container {{ width:100%; overflow-x:auto; }}
  svg {{ width:100%; min-width:{W}px; display:block; }}
  @media print {{ .diagram-container {{ overflow-x:visible; }} svg {{ min-width:0; }} }}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">OpenSRM · internals</div>
  <h1>Two sources, one dashboard — portal and SCOPE</h1>
  <div class="diagram-container">
    <svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="architecture-title architecture-desc" xmlns="http://www.w3.org/2000/svg">
      <title id="architecture-title">OpenSRM data flow architecture</title>
      <desc id="architecture-desc">The browser reaches Flask through the Cloudflare edge over HTTPS; routes guarded by sessions and rate limits drive two data sources: the portal pipeline, which scrapes the SRM student portal directly by default or through the optional egress proxy, and the zero-dependency SCOPE client, which calls the SOAP backend of SRM's own mobile app. Both feed the parsers, everything is persisted through a single data-access repository into SQLite on a persistent volume, and routes render responses with Jinja.</desc>
{chr(10).join(svg)}
    </svg>
  </div>
</div>
</body>
</html>
''')
print("OK ->", out, "· legend rows end x:", lx)
print(f"tokens: paper={PAPER} node={NODE_BG} rule={RULE} link={LINK}")
