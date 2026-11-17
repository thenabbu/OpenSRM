#!/usr/bin/env python3
"""Resample the OpenSRM mark into the PWA icon set.

Source of truth: ``app/static/icon-1024.png`` (1024x1024). Nothing here is
redrawn — every output is a LANCZOS resample of that one file, or of the
circle-clipped plate built from it. The rows this script writes are the rows in
``notes/ICONS.md`` §3; ``scripts/check_icons.py`` proves the result (real IHDR
sizes, template wiring, safe zone).

Outputs are committed (assets are built ahead of time; the runtime image has no
Node/Pillow). Run only when the mark changes:

    python3 scripts/build_icons.py             # writes app/static/
    python3 scripts/build_icons.py --out DIR   # preview into DIR, compare first
"""
from __future__ import annotations

import argparse
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'app', 'static')
SRC = os.path.join(STATIC, 'icon-1024.png')

BG = (17, 17, 17)          # #111111 = manifest background_color/theme_color
SAFE_R = 0.345             # mark radius as a fraction of the canvas: inside the
                           # 40%-radius maskable safe circle with AA margin.
SPLASH_FRAC = 0.40         # mark width on a splash, fraction of splash width
TILE_WIDE_FRAC = 0.70      # mark height on a non-square Windows tile
FAVICON = (16, 24, 32, 48)

# 23 portrait device classes: apple-fallback-data.json (pwa-asset-generator),
# 59 devices collapse to these. `notes/ICONS.md` §4 carries the sf and devices.
SPLASHES = [
    (640, 1136), (750, 1334), (828, 1792), (1080, 2340), (1125, 2436),
    (1170, 2532), (1179, 2556), (1206, 2622), (1242, 2208), (1242, 2688),
    (1260, 2736), (1284, 2778), (1290, 2796), (1320, 2868), (1488, 2266),
    (1536, 2048), (1620, 2160), (1640, 2360), (1668, 2224), (1668, 2388),
    (1668, 2420), (2048, 2732), (2064, 2752),
]

# Microsoft Edge Level 2 tiles, 1x scale (44 app, 71 small, 150 medium,
# 310x150 wide, 310 large, 50 store logo, 620x300 splash).
TILES = [(44, 44), (50, 50), (71, 71), (150, 150), (310, 310),
         (310, 150), (620, 300)]


def load_source() -> Image.Image:
    return Image.open(SRC).convert('RGB')


def plate(size: tuple[int, int], src: Image.Image, frac: float) -> Image.Image:
    """The mark circle-clipped at SAFE_R, scaled to `frac` of the short side."""
    w, h = size
    base = Image.new('RGB', (w, h), BG)
    disc = int(round(min(w, h) * frac))
    mark = circle_clip(src, disc)
    base.paste(mark, ((w - disc) // 2, (h - disc) // 2))
    return base


def circle_clip(src: Image.Image, side: int) -> Image.Image:
    """Clip the mark to a circle of radius SAFE_R x side, over an opaque plate.

    Built at the source resolution then resized, which is the treatment the
    shipped maskable pair already carries (reproduces icon-maskable-512.png to
    within 0.2% RMSE — verified when this script was written).
    """
    n = src.size[0]
    mask = Image.new('L', (n, n), 0)
    c, r = n / 2, SAFE_R * n
    ImageDraw.Draw(mask).ellipse([c - r, c - r, c + r, c + r], fill=255)
    composited = Image.new('RGB', (n, n), BG)
    composited.paste(src, (0, 0), mask)
    return composited.resize((side, side), Image.LANCZOS)


def save(im: Image.Image, out: str, name: str) -> None:
    path = os.path.join(out, name)
    im.save(path, 'PNG', optimize=True)
    print(f'  {name:32} {im.size[0]}x{im.size[1]}  {os.path.getsize(path)}B')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=STATIC, help='output directory')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    src = load_source()
    if src.size != (1024, 1024):
        raise SystemExit(f'source is {src.size}, expected 1024x1024')

    print('apple-touch-icon (180, opaque - iOS paints transparency black):')
    save(circle_clip(src, 180), args.out, 'apple-touch-icon.png')

    print('maskable (circle-clipped mark, r=%.3f):' % SAFE_R)
    save(circle_clip(src, 512), args.out, 'icon-maskable-512.png')
    save(circle_clip(src, 1024), args.out, 'icon-maskable-1024.png')

    print('windows tiles (full-bleed square / mark on #111 when not square):')
    for w, h in TILES:
        im = (src.resize((w, h), Image.LANCZOS) if w == h
              else plate((w, h), src, TILE_WIDE_FRAC))
        save(im, args.out, f'icon-{w}x{h}.png' if w != h else f'icon-{w}.png')

    print('ios splash (mark on #111, portrait):')
    for w, h in SPLASHES:
        save(plate((w, h), src, SPLASH_FRAC), args.out, f'apple-splash-{w}x{h}.png')

    print('favicon (multi-frame):')
    ico = src.resize((max(FAVICON), max(FAVICON)), Image.LANCZOS)
    path = os.path.join(args.out, 'favicon.ico')
    ico.save(path, sizes=[(s, s) for s in FAVICON])
    print(f'  favicon.ico {FAVICON} frames  {os.path.getsize(path)}B')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
