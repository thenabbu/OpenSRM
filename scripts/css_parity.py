#!/usr/bin/env python3
"""CSS parity gate for the Preact rewrite (unit P2.1).

Proves the Vite + Tailwind v4 build output (app/static/dist/assets/app-*.css)
is semantically equivalent to the committed legacy build
(app/static/app.css) on the dimensions the cascade depends on:

  1 sheets-present   every hand-written selector (timetable/motion/gaze) is
                     still present in the dist
  2 hand-unlayered   every hand-written prelude (sheets + src.css) has a
                     copy at layer depth 0 (outside any @layer). A framework
                     twin at the same prelude inside a layer (e.g. the
                     Tailwind `cursor-copy` utility vs the hand `.cursor-copy`
                     rule) is harmless — only a missing depth-0 copy fails.
  3 cascade-order    (a) every daisyUI component rule is at an EARLIER byte
                          offset than the first depth-0 hand rule;
                      (b) the sheets appear in source order
                          timetable -> motion -> gaze (their first depth-0
                          rule offsets must be increasing). Reordering the
                          @import lines in web/tailwind.css breaks (b).
  4 components       daisyUI components the app uses are still emitted
  5 keyframes        every sheet @keyframes name is still emitted
  6 size-backstop    dist CSS is >= 80% of the legacy file size (guards
                     against a silent near-empty build)
  7 no-missing-class every class token in the legacy file appears in the dist

Self-test: checks 1-3 also run against the legacy file itself. If the
parser misclassifies the known-good reference, the gate fails on the
reference instead of silently passing a broken build.

Usage: css_parity.py [path/to/dist.css]
  With no argument the single app/static/dist/assets/app-*.css is used.

The minifier may merge/split selector lists — the gate compares selectors,
classes, byte order and keyframes, never raw bytes.
Read-only. Exits 0 on PASS, 1 on any violation.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "app" / "static" / "app.css"
DIST_GLOB = "app-*.css"
SHEETS = ["timetable.css", "motion.css", "gaze.css"]
ENTRIES = ["src.css"]
COMPONENTS = {
    "btn", "card", "badge", "alert", "collapse", "progress", "input",
    "modal", "dock", "tabs", "navbar", "stats", "table", "select",
    "textarea", "radio", "checkbox", "toggle", "avatar", "indicator",
    "join", "segmented", "divider", "skeleton", "menu", "dropdown",
    "toast", "rating", "stepper", "accordion", "timeline",
}


# ── CSS scanning ────────────────────────────────────────────────────────────

def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def norm(sel: str) -> str:
    s = re.sub(r"\s*([>+~])\s*", r"\1", sel)
    s = re.sub(r"\s*,\s*", ",", s)
    # the minifier collapses ::before/::after to :before/:after
    s = re.sub(r"::(before|after)\b", r":\1", s)
    # and strips quotes from attribute values: [a="b"] -> [a=b]
    s = re.sub(r'\[([a-zA-Z-]+)\s*([~|^$*]?=)\s*["\']([^"\']*)["\']\s*\]',
               r"[\1\2\3]", s)
    return re.sub(r"\s+", " ", s).strip()


def split_selectors(prelude: str):
    """Split a top-level selector list on commas (bracket/paren aware)."""
    out, cur, depth = [], "", 0
    for ch in prelude:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [norm(s) for s in (o.strip() for o in out) if s.strip()]


def scan(css: str):
    """Flat scanner for minified CSS.

    Returns (rules, keyframes). A rule is {start, layer_depth, prelude} where
    layer_depth counts enclosing @layer blocks. @keyframes frames are NOT
    rules; @media/@supports etc. are transparent blocks (not layers).
    """
    css = strip_comments(css)
    rules, kfs = [], []
    i, n, depth = 0, len(css), 0
    stack = []  # kinds: 'layer' | 'block' | 'kf' | 'skip'
    pre_start = 0
    while i < n:
        c = css[i]
        if c == "{":
            pre = norm(css[pre_start:i].strip())
            last = pre.split(";")[-1].strip() if ";" in pre else pre
            if last.startswith("@keyframes"):
                m = re.match(r"@keyframes\s+([\w-]+)", last)
                if m:
                    kfs.append(m.group(1))
                stack.append("kf")
            elif last.startswith("@layer"):
                stack.append("layer")
            elif re.match(r"@(media|supports|container|starting-style|scope|document)", last):
                stack.append("block")
            elif last.startswith("@"):
                stack.append("skip")  # @property, @font-face, ...
            elif "kf" not in stack:
                rules.append({
                    "start": pre_start,
                    "layer_depth": sum(1 for k in stack if k == "layer"),
                    "prelude": last,
                })
            depth += 1
            i += 1
            pre_start = i
            continue
        if c == "}":
            depth -= 1
            if stack and depth == len(stack) - 1:
                stack.pop()
            i += 1
            pre_start = i
            continue
        i += 1
    return rules, kfs


def parse_entry(path: Path):
    """Full rule preludes + split selectors + keyframe names of a source sheet."""
    rules, kfs = scan(strip_comments(path.read_text(encoding="utf-8")))
    preludes, sels = set(), set()
    for r in rules:
        preludes.add(r["prelude"])
        sels.update(split_selectors(r["prelude"]))
    return preludes, sels, set(kfs)


# ── checks ──────────────────────────────────────────────────────────────────

def class_tokens(css: str):
    return set(re.findall(r"\.([a-zA-Z][\w-]*)", css))


def rule_class_tokens(prelude: str):
    toks = set()
    for sel in split_selectors(prelude):
        toks |= set(re.findall(r"\.([a-zA-Z][\w-]*)", sel))
    return toks


def sheet_first_d0(rules, sheet_preludes):
    """Min start offset of a rule from this sheet at layer depth 0."""
    first = None
    for r in rules:
        if r["prelude"].startswith("@") or r["layer_depth"] != 0:
            continue
        if r["prelude"] in sheet_preludes:
            if first is None or r["start"] < first:
                first = r["start"]
    return first


def daisy_component_last(rules, hand_preludes, hand_sels):
    """Max start offset of a daisyUI component rule.

    A rule counts as a daisyUI component rule when some class token is a
    component name AND it is not one of the hand-written rules (matched by
    full prelude or sheet selector — the hand dock-button rules
    `.dock button*` contain the `dock` token and are hand-written).
    """
    last = None
    for r in rules:
        if r["prelude"].startswith("@"):
            continue
        if r["prelude"] in hand_preludes:
            continue
        if any(s in hand_sels for s in split_selectors(r["prelude"])):
            continue
        if rule_class_tokens(r["prelude"]) & COMPONENTS:
            if last is None or r["start"] > last:
                last = r["start"]
    return last


def structural_checks(css: str, label: str):
    """Checks 1-3 on one file. Returns a list of failure strings."""
    rules, kfs = scan(css)
    hpre, hsels, hkfs = set(), set(), set()
    sheet_prels = {}
    for name in SHEETS:
        p, s, k = parse_entry(ROOT / "app" / "static" / name)
        hpre |= p
        hsels |= s
        hkfs |= k
        sheet_prels[name] = p
    pp, ps, pk = parse_entry(ROOT / "app" / "static" / "src.css")
    hand_preludes = hpre | pp

    fails = []

    # 1 sheets-present
    all_sels = set()
    for r in rules:
        all_sels.update(split_selectors(r["prelude"]))
    missing = hsels - all_sels
    if missing:
        fails.append(f"{label}: 1 sheets-present: {len(missing)} sheet "
                     f"selectors missing, e.g. {sorted(missing)[:5]}")

    # 2 hand-unlayered: per-prelude existence at depth 0
    d0 = [r for r in rules if r["layer_depth"] == 0
          and not r["prelude"].startswith("@")]
    d0_preludes = {r["prelude"] for r in d0}
    d0_sel_parts = set()
    for r in d0:
        d0_sel_parts.update(split_selectors(r["prelude"]))
    missing_unlayered = []
    for p in sorted(hand_preludes):
        if p.startswith("@"):
            continue
        if p in d0_preludes:
            continue
        # minifier may have split the selector list into separate rules
        if all(s in d0_sel_parts for s in split_selectors(p)):
            continue
        missing_unlayered.append(p)
    if missing_unlayered:
        fails.append(f"{label}: 2 hand-unlayered: "
                     f"{len(missing_unlayered)} hand rules have no depth-0 "
                     f"copy, e.g. {missing_unlayered[:3]}")
    n_hand = sum(1 for r in d0 if r["prelude"] in hand_preludes)
    return fails, rules, kfs, hand_preludes, hsels, sheet_prels, n_hand


def run_checks(new_css: str, old_css: str):
    """Run all checks of dist (new_css) against legacy (old_css)."""
    n_fails, new_rules, new_kfs, hand_preludes, hsels, sheet_prels, n_hand = \
        structural_checks(new_css, "dist")
    o_fails, old_rules, old_kfs, _, _, _, ref_hand = \
        structural_checks(old_css, "legacy-self-test")
    fails = n_fails + o_fails

    floor = max(15, ref_hand // 2)
    if n_hand < floor:
        fails.append(f"dist: 2 hand-unlayered: only {n_hand} hand rules at "
                     f"depth 0 (legacy has {ref_hand}; floor {floor}) — "
                     f"entry not compiled?")

    # 3 cascade-order
    def order_and_daisy(rules, who):
        firsts = {name: sheet_first_d0(rules, prels)
                  for name, prels in sheet_prels.items()}
        missing_sheets = [n for n in SHEETS if firsts[n] is None]
        if missing_sheets:
            fails.append(f"{who}: 3 cascade-order: no depth-0 rule for "
                         f"sheet(s) {missing_sheets}")
            return
        d_last = daisy_component_last(rules, hand_preludes, hsels)
        h_first = min(firsts.values())
        if d_last is None:
            fails.append(f"{who}: 3 cascade-order: no daisyUI component "
                         f"rule found")
        elif d_last >= h_first:
            fails.append(f"{who}: 3 cascade-order: daisyUI component rule "
                         f"at byte {d_last} is not before first depth-0 "
                         f"hand rule at byte {h_first} — framework/sheet "
                         f"order changed")
        got = sorted(SHEETS, key=lambda nm: firsts[nm])
        if got != SHEETS:
            fails.append(f"{who}: 3 cascade-order: sheet order is {got} "
                         f"but must be {SHEETS} — @import order changed")

    order_and_daisy(new_rules, "dist")
    order_and_daisy(old_rules, "legacy-self-test")

    n, o = len(new_css), len(old_css)

    # 4 components
    old_tokens = class_tokens(old_css)
    new_tokens = class_tokens(new_css)
    required = [c for c in sorted(COMPONENTS) if c in old_tokens]
    missing_comp = [c for c in required if c not in new_tokens]
    if missing_comp:
        fails.append(f"dist: 4 components: daisyUI components missing from "
                     f"dist: {missing_comp}")

    # 5 keyframes
    hkfs = set()
    for name in SHEETS:
        _, _, k = parse_entry(ROOT / "app" / "static" / name)
        hkfs |= k
    _, _, pk = parse_entry(ROOT / "app" / "static" / "src.css")
    missing_kf = sorted((hkfs | pk) - set(new_kfs))
    if missing_kf:
        fails.append(f"dist: 5 keyframes: missing @keyframes in dist: "
                     f"{missing_kf}")

    # 6 size-backstop
    if n < 0.8 * o:
        fails.append(f"dist: 6 size-backstop: dist {n}B < 80% of legacy "
                     f"{o}B — suspiciously small")

    # 7 no-missing-class
    missing_cls = sorted(old_tokens - new_tokens)
    if missing_cls:
        fails.append(f"dist: 7 no-missing-class: {len(missing_cls)} class "
                     f"tokens lost, e.g. {missing_cls[:10]}")

    return fails, n_hand


def main():
    if not OLD.exists():
        print("css_parity: FAIL — legacy app/static/app.css missing")
        return 1
    old_css = OLD.read_text(encoding="utf-8")

    if len(sys.argv) > 1:
        dist_files = [Path(sys.argv[1])]
    else:
        dist_files = sorted((ROOT / "app" / "static" / "dist" / "assets")
                            .glob(DIST_GLOB))
    if len(dist_files) != 1 or not dist_files[0].exists():
        print(f"css_parity: FAIL — expected exactly one {DIST_GLOB} "
              f"(run scripts/build-web.sh first); found "
              f"{[str(f) for f in dist_files]}")
        return 1
    new_css = dist_files[0].read_text(encoding="utf-8")
    print(f"css_parity: {OLD} ({len(old_css)}B) vs {dist_files[0]} "
          f"({len(new_css)}B)")

    fails, n_hand = run_checks(new_css, old_css)
    for f in fails:
        print(f"css_parity: FAIL — {f}")
    if fails:
        print(f"css_parity: FAIL ({len(fails)} violation(s))")
        return 1

    print(f"css_parity: PASS — {len(SHEETS)} sheets present in source "
          f"order, {n_hand} hand rules at depth 0, daisyUI before hand "
          f"sheets, components + keyframes intact, no class tokens lost")
    return 0


if __name__ == "__main__":
    sys.exit(main())
