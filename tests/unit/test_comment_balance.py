#!/usr/bin/env python3
"""CSS comment balance across the stylesheet sources and inline template blocks.

A scripted edit that deletes a block comment's opener (or its closer) does not
fail a build -- the browser silently swallows everything after the orphan until
the next `*/`, so a rule set quietly disappears. The rule this pins is the
existing prose one: after any scripted CSS/JS edit, `grep -c "/*"` must equal
`grep -c "*/"`.

Scoped to `.css` sources and `/* */` inside templates. String literals are
stripped first so a `/*` inside a quoted URL cannot create a false failure.

Run: .venv/bin/python tests/unit/test_comment_balance.py
"""
import pathlib
import re
import sys

R = pathlib.Path(__file__).resolve().parents[2]
FILES = sorted(
    list((R / "app/static").glob("*.css"))
    + list((R / "app/templates").rglob("*.html"))
)


def strip_strings(s):
    s = re.sub(r'"(?:[^"\\]|\\.)*"', '""', s)
    s = re.sub(r"'(?:[^'\\]|\\.)*'", "''", s)
    return s


def main():
    ok = fails = 0
    bad = []
    for f in FILES:
        if not f.exists():
            continue
        body = strip_strings(f.read_text(errors="replace"))
        if f.suffix == ".html":
            # Only CSS comments exist inside <style> blocks; strip the markup so a
            # `<!-- -->` or a stray URL cannot count.
            blocks = re.findall(r"<style[^>]*>(.*?)</style>", body, re.S | re.I)
            body = "\n".join(blocks)
            if not body.strip():
                continue
        opens = body.count("/*")
        closes = body.count("*/")
        if opens == closes:
            ok += 1
        else:
            fails += 1
            bad.append((f.relative_to(R), opens, closes))
    for rel, o, c in bad:
        print(f"  FAIL {rel}: {o} '/*' vs {c} '*/'")
    print(f"\ncomment-balance: {ok + fails} files, {ok} ok, {fails} failed")
    print("ok   comment balance" if fails == 0 else "FAIL comment balance")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
