#!/usr/bin/env python3
"""Gate: every class token the islands WRITE must exist in the CSS the app serves.

W7.3b measured the failure this guards: the update banner is built in
web/src/pwa/banner.ts with `fixed bottom-20 ...`, but both Tailwind entries are
`source(none)` with an explicit @source allow-list that did not list web/src —
so `bottom-20` was never compiled, `position:fixed` with `bottom:auto` fell back
to its STATIC position, and the button rendered 2400px down a 844px viewport.
Nothing failed: Tailwind emits no warning for a class it never saw, and the
existing unit suite (test_css_safelist.py) only checks classes that RENDER.

So: read the class literals out of web/src at their real write sites
(className/class=, classList.*, setAttribute('class', …)), and require each
token to carry a rule in app.css, the Vite dist CSS, or a template <style>
block. Missing => red, named, with the file that wrote it.

Break-proven both ways: plant an unknown class in web/src (red), or drop the
`@source` line and rebuild the CSS (red). --self-test re-proves the logic on
synthetic input on every run, so a green run cannot be a green because the
extractor matched nothing.

Run: PYTHONPATH=. python3 scripts/check_css_classes.py [--self-test]
"""
from __future__ import annotations

import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tokens that are real references to classes NO stylesheet defines. They are
# pre-existing (W7.2 era markup, dead in the legacy templates too) and are not
# part of the allow-list bug this gate exists for. Fixing them is a rename, not
# a CSS change — if one is fixed, delete its line here (the self-check below
# fails on a stale entry, so this list cannot rot silently).
DEAD_REFS = {
    "acad-cat", "acad-sem", "acad-srow", "pct-75", "tt-cell-sel",
}

# Where a class token may legitimately be written. Everything else (prose in
# comments, selectors, test-only strings) is not a shipped class reference.
SITES = (
    re.compile(r"""class(?:Name)?\s*=\s*(['"])((?:(?!\1)[^\\]|\\.)*)\1"""),
    re.compile(r"""className\s*=\s*\{([^}]*)\}"""),
    re.compile(r"""\.classList\.(?:add|remove|toggle|replace)\(([^)]*)\)"""),
    re.compile(r"""setAttribute\(\s*(['"])class\1\s*,\s*([^)]*)\)"""),
)
QUOTED = re.compile(r"""['"`]([^'"`]*)['"`]""")
NOT_A_TOKEN = set("{}$=?'`;<>|#@,")


def class_names(css: str) -> set[str]:
    """Class names defined by a stylesheet, unescaped (.hover\\:x:hover -> hover:x)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: set[str] = set()
    i = 0
    while True:
        i = css.find(".", i)
        if i < 0:
            return out
        # '.' in a number (1.5, .25rem) is not a class; '.' inside a compound
        # selector (.tt-grid-cell.tt-cell-hover) IS — compound is why this is a
        # next-char test and not a prev-char one.
        if i + 1 < len(css) and css[i + 1].isdigit():
            i += 1
            continue
        j, name = i + 1, []
        while j < len(css):
            c = css[j]
            if c == "\\" and j + 1 < len(css):
                name.append(css[j + 1])
                j += 2
                continue
            if c.isalnum() or c in "_-":
                name.append(c)
                j += 1
                continue
            break
        if name:
            out.add("".join(name))
        i = j if j > i + 1 else i + 1


def scrubbed_tokens(text: str) -> set[str]:
    """Class tokens in an expression: quoted literals, split, junk dropped."""
    toks: set[str] = set()
    for lit in QUOTED.findall(text):
        for t in lit.split():
            if len(t) > 1 and not (set(t) & NOT_A_TOKEN):
                toks.add(t)
    return toks


def source_tokens(src_root: str) -> dict[str, set[str]]:
    """{token: {files that write it}} for every real class write site in web/src."""
    written: dict[str, set[str]] = {}
    for path in sorted(glob.glob(os.path.join(src_root, "**", "*"), recursive=True)):
        if not path.endswith((".ts", ".tsx")) or ".test." in path:
            continue
        text = open(path, encoding="utf-8").read()
        for site in SITES:
            for m in site.finditer(text):
                for t in scrubbed_tokens(m.group(0)):
                    written.setdefault(t, set()).add(os.path.relpath(path, REPO))
    return written


def known_classes() -> tuple[set[str], list[str]]:
    # One stylesheet ships: the Vite bundle. The legacy app/static/app.css and
    # its standalone build were deleted when the theme moved into the daisyUI
    # plugin config, so only dist/assets/app-*.css is a source of truth.
    files = sorted(glob.glob(os.path.join(REPO, "app", "static", "dist", "assets", "app-*.css")))
    known: set[str] = set()
    for f in files:
        known |= class_names(open(f, encoding="utf-8").read())
    for tpl in glob.glob(os.path.join(REPO, "app", "templates", "**", "*.html"), recursive=True):
        # Stylesheets are not the only home of a class: base.html and
        # settings.html carry hand-written <style> blocks no Tailwind entry sees.
        for block in re.findall(r"<style[^>]*>(.*?)</style>", open(tpl, encoding="utf-8").read(), re.S):
            known |= class_names(block)
    return known, files


def main() -> int:
    src_root = os.path.join(REPO, "web", "src")
    known, css_files = known_classes()
    written = source_tokens(src_root)
    fails: list[str] = []

    def check(name, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
        if not ok:
            fails.append(name)

    # positive control: the extractor must find the exact string that started
    # this card, and the CSS must know the utilities around it. Without this a
    # broken extractor would report "0 missing" forever.
    check("extractor finds the banner class string",
          {"bottom-20", "shadow-lg", "alert-info"} <= written.keys(),
          f"files={sorted(written.get('bottom-20', []))}")
    check("positive control: 'fixed' is defined in the served CSS", "fixed" in known)

    stale = sorted(t for t in DEAD_REFS if t in known or t not in written)
    check("DEAD_REFS is neither stale nor unused", not stale, f"stale={stale}")

    missing = {t: f for t, f in written.items() if t not in known and t not in DEAD_REFS}
    check(f"all {len(written) - len(DEAD_REFS & written.keys())} web/src class tokens exist in the served CSS",
          not missing,
          "; ".join(f"{t} ({', '.join(sorted(f))})" for t, f in sorted(missing.items())))

    print(f"\nknown classes={len(known)} css files={len(css_files)} "
          f"tokens written={len(written)} dead-refs allowed={len(DEAD_REFS)}")
    if fails:
        print("FAILED:", ", ".join(fails))
        return 1
    print("ok check_css_classes")
    return 0


def self_test() -> int:
    """Prove the two halves on synthetic input: extraction and the miss test."""
    toks = scrubbed_tokens("el.className = 'alert bottom-999 flex-1'")
    ok = {"alert", "bottom-999", "flex-1"} <= toks
    known = class_names(".alert{}.flex-1{}.hover\\:bg-x:hover{}")
    ok &= known == {"alert", "flex-1", "hover:bg-x"}
    ok &= "bottom-999" not in known
    print("self-test:", "PASS" if ok else "FAIL", sorted(toks), sorted(known))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
