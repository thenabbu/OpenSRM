#!/usr/bin/env python3
"""The icon gate: every icon the manifest declares exists, is a PNG, is exactly
the size it claims, and a maskable one keeps its mark inside the safe zone.

Run stand-alone or from scripts/gates.sh. Exits 1 on any FAIL.
Reads the manifest, never a second hand-kept list.
"""
from __future__ import annotations

import json
import math
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'app', 'static')
MANIFEST = os.path.join(STATIC, 'manifest.json')
SAFE_RADIUS = 0.4  # inner 80% circle, as a fraction of the canvas
BRIGHT = 200       # artwork ink vs the dark background fill

fails: list[str] = []


def check(cond: bool, label: str, detail: str = '') -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not cond:
        fails.append(label)


def safe_zone(path: str) -> None:
    """Every bright pixel of the maskable icon must sit inside the inner 80% circle."""
    im = Image.open(path).convert('RGBA')
    n = im.size[0]
    cx = cy = n / 2
    limit = SAFE_RADIUS * n
    mark = outside = 0
    for y in range(n):
        for x in range(n):
            if max(im.getpixel((x, y))[:3]) > BRIGHT:
                mark += 1
                if math.hypot(x + 0.5 - cx, y + 0.5 - cy) > limit:
                    outside += 1
    check(mark > 0 and outside == 0,
          f'{os.path.basename(path)} mark inside inner-80% circle',
          f'({mark} mark px, {outside} outside r={limit:.1f})')


def main() -> int:
    icons = json.load(open(MANIFEST))['icons']
    print(f'{"icon":34} {"declared":10} {"actual":10} result')
    for entry in icons:
        path = os.path.join(ROOT, 'app', entry['src'].lstrip('/'))
        want = tuple(int(v) for v in entry['sizes'].split('x'))
        name = os.path.basename(path)
        if not os.path.exists(path):
            check(False, f'{name} exists', entry['src'])
            continue
        im = Image.open(path)
        actual = im.size
        ok = im.format == 'PNG' and actual == want and os.path.getsize(path) > 0
        check(ok, f'{name} {want[0]}x{want[1]} PNG non-empty',
              f'{actual[0]}x{actual[1]} {im.format} {os.path.getsize(path)}B')
        if entry.get('purpose') == 'maskable':
            safe_zone(path)

    # Not in the manifest but precached by sw.js / used by push: keep them honest.
    for name, size in (('apple-touch-icon.png', 180), ('icon-badge.png', 96)):
        path = os.path.join(STATIC, name)
        check(os.path.exists(path) and Image.open(path).size == (size, size),
              f'{name} {size}x{size} PNG')

    print('\nRESULT:', 'ALL PASS' if not fails else f'{len(fails)} FAIL')
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
