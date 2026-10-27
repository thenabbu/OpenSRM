# Diagrams — how OpenSRM diagrams are built

Every diagram in this repo is a **pre-rendered image committed next to its
source**, never a GitHub-rendered mermaid block. This document is the
guideline for anyone (agent or human) changing one.

## Why not mermaid

GitHub's mermaid engine reflows blocks at its own scale: measured on the live
README, a 1063-px-wide layout rendered inside a 758-px iframe (~10.7 px
effective text, labels wrapped into narrow columns). No source-level layout
fixes that — nested `direction` inside subgraphs is a no-op in mermaid v11
(identical 568×140 output with and without). Pre-rendered PNGs give exact
grid, font and arrow control and render identically everywhere.

## Files

| File | Role |
|---|---|
| `scripts/build_arch_diagram.py` | Generates the source HTML with hard asserts (4px grid, text fit, ≤14-char arrow labels). Edit nodes/edges here. |
| `docs/architecture.html` | Generated source of truth — self-contained, viewable in any browser, header comment carries the regen commands. |
| `docs/architecture.png` | The asset README embeds (`@2`, 1920×1200 for the 960×600 canvas). |
| `README.md` → Architecture | Embeds the PNG (`width="100%"`). |

## Workflow

```bash
python3 scripts/build_arch_diagram.py            # regenerates docs/architecture.html (fails on grid/text/label violations)
python3 <diagram-design-skill>/scripts/export_png.py docs/architecture.html docs/architecture.png 2
python3 <diagram-design-skill>/scripts/self_check.py docs/architecture.html
DATA_DIR="$(mktemp -d)" .venv/bin/python tests/unit/test_audit_findings.py   # 72/72 — pins README doc claims
```

Hermes agents: load the `diagram-design` skill and follow its
**import-mermaid** workflow (extract IR → editorial redraw, never renderer
coordinates). Dials: `doc-inline` (960×600) · `balanced` · `mixed`. For a new
diagram type, the skill's `references/type-*.md` owns layout grammar.

## Design rules (earned the hard way — do not relax)

**Canvas and type** (doc-inline preset, standard ramp):

- `viewBox` is exactly `0 0 960 600`; every node origin, width, height, gap
  and padding is divisible by **4**.
- Node name 12px sans 600 · sublabel 9px mono · arrow label 8px mono ·
  eyebrow 8px mono tracked 0.14em. Text fit budget: **0.60em/char sans,
  0.62em/char mono** — a label wider than its box minus 16px fails the build.
- Node boxes `rx=6`, min height 48, min gap between nodes 24.

**Arrow semantics** — every kind used must appear in the legend's `ARROWS`
row:

- Solid muted = runtime flow · double-headed = HTTP request + response ·
  blue (`info` token) = external HTTPS · dashed = optional path.
- HTTP boundaries are **bidirectional** (browser ⇄ edge ⇄ routes) and
  responses leave through the same entry point — no separate "return" arrow
  around the canvas.
- Connectors are orthogonal only: two-bend elbows at `r=8`, straight lines
  only when endpoints share x or y, ports ≥8px from corners, ≥12px between
  ports sharing an edge. Labels sit beside vertical segments / above
  horizontal ones with a **6–10px gap** on an opaque mask, never over a node
  and never longer than **14 characters**.

**Content** — what belongs in a box:

- Component names describe *responsibility*, not files: no `app/...` paths,
  no formIds, no percentages, no schema versions, no TTLs in boxes. Those are
  facts for README prose and the Configuration tables (operational detail is
  a separate view from system architecture).
- Split a combined box only where the code genuinely splits it (e.g. rate
  limits + portal budget live in `app/state.py` and are their own node;
  session guards sit with routes). A repository/data-access node exists
  because `app/db.py` is the one place all SQL lives — never draw a layer
  the code doesn't have.
- Use precise nouns: *login sessions* (cookies table) vs *portal cache*
  (`portal_sessions`) are not "sessions" generically. Configuration gates are
  named in the legend (`SRM_EGRESS_URL set`), never drawn as connections.
- Label DB edges with their direction (`PERSIST`, `READ + WRITE`); label
  persistence as a **persistent volume** so the DB never reads as ephemeral
  container storage.

**Skin** — openSRM tokens (from DESIGN.md Appendix A; `python3` oklch→sRGB):

| Role | Hex / value | Source |
|---|---|---|
| paper | `#161616` | base-100 `oklch(20% 0 0)` |
| node fill | `#090909` | base-200 `oklch(14% 0 0)` — darker than paper (inverted stack) |
| borders / rules | `#242424` | base-300 `oklch(26% 0 0)` — lighter than paper |
| ink / accent | `#ffffff` | base-content / accent (white is the one accent) |
| text ladder | white at 60% / 50% | DESIGN §2.5 opacity ladder |
| external link | `#0082ce` | `info oklch(58% .158 241.966)` |

Treatments: input = white@10% fill + white@50% stroke · external = white@3%
+ white@30% · backend = node fill + rule border · core = white@10% + solid
white 1.4 (**max 2 core/accent nodes per diagram**) · optional = external +
dashed `4,3`.

**Legend** — bottom 60px strip only: hairline separator, then `TYPES` row
(component treatments used) and `ARROWS` row (every arrow kind). Nothing
floats inside the diagram area.

## Verification (all required before pushing)

1. `build_arch_diagram.py` exits 0 (grid, text-fit and label asserts).
2. `self_check.py` passes (accessible-SVG contract, single-file safety).
3. Vision review at **1920 and 890px** — SHIP verdict, no label/arrow
   complaints; 890 is the README display width, check it explicitly.
4. `test_audit_findings.py` still 72/72 (it pins README doc claims —
   e.g. `opensrm-v40` must stay exactly once, in the PWA bullet).
5. Commit `architecture.html` + `architecture.png` + generator changes
   together; if README copy changed, refresh
   `docs/screenshots/readme/after-branch-readme-render.png` evidence.
