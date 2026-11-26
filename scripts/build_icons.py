#!/usr/bin/env python3
"""Render the OneSRM mark into the PWA icon set.

Sources of truth are the SVGs in ``design/icons/``. Nothing is redrawn, and no
raster is ever resized: every output is rendered from the vector at its own
pixel size, so a 16px favicon is a 16px render, not a shrunken 512.

  onesrm-icon.svg                 full-art: big letters, square, opaque
                                  -> icon-192/512/1024, Windows tiles, splashes
  onesrm-icon-chamfer.svg         same art with 24px cut corners
                                  -> favicon.svg, favicon.ico   (alpha KEPT:
                                     a tab icon may be transparent)
  icon-maskable.svg               letters scaled 1.25x about the centre, so the
                                  farthest corner sits at 37.6% of the width,
                                  inside the web 40% safe circle
                                  -> icon-maskable-192/512/1024,
                                     apple-touch-icon  (alpha DROPPED: iOS
                                     paints transparency black)
  onesrm-adaptive-*.svg           the two layers icon-maskable.svg is built from

Spec: ``notes/ICONS.md``. Proof: ``scripts/check_icons.py`` (IHDR sizes, alpha,
safe zone, template wiring).

Renderer: cairosvg in the repo venv. The runtime image has neither the renderer
nor the SVGs, so outputs are committed. Run only when the mark changes:

    python3 scripts/build_icons.py               # writes app/static/
    python3 scripts/build_icons.py --out DIR     # preview into DIR
"""
from __future__ import annotations

import argparse
import io
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'app', 'static')
DESIGN = os.path.join(ROOT, 'design', 'icons')

FULL = os.path.join(DESIGN, 'onesrm-icon.svg')          # square, big letters
CHAMFER = os.path.join(DESIGN, 'onesrm-icon-chamfer.svg')  # cut corners, alpha
MASK = os.path.join(DESIGN, 'icon-maskable.svg')        # safe-zone letters

BG = (17, 17, 17)          # #111111 = manifest background_color/theme_color
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


def render(svg: str, side: int, opaque: bool = True) -> Image.Image:
    """Rasterise `svg` at exactly `side` px.

    `opaque=True` flattens onto #111111 and returns RGB: the PWA and apple
    icons must carry no alpha at all, because iOS paints transparency black.
    `opaque=False` returns RGBA so a cut-corner favicon keeps its transparent
    corners — a tab icon sits on the browser's own background.
    """
    import cairosvg

    png = cairosvg.svg2png(url=svg, output_width=side, output_height=side)
    art = Image.open(io.BytesIO(png)).convert('RGBA')
    if art.size != (side, side):
        raise SystemExit(f'{svg} rendered {art.size}, expected {(side, side)}')
    if not opaque:
        return art
    base = Image.new('RGB', (side, side), BG)
    base.paste(art, (0, 0), art)
    return base


def plate(size: tuple[int, int], src: Image.Image, frac: float) -> Image.Image:
    """The mark scaled to `frac` of the short side, centred on a #111 plate.

    Splashes and non-square tiles are pictures with margins, not tiles a
    launcher crops, so they take a plate.
    """
    w, h = size
    base = Image.new('RGB', (w, h), BG)
    side = int(round(min(w, h) * frac))
    base.paste(src.resize((side, side), Image.LANCZOS), ((w - side) // 2, (h - side) // 2))
    return base


def save(im: Image.Image, out: str, name: str) -> None:
    path = os.path.join(out, name)
    im.save(path, 'PNG', optimize=True)
    print(f'  {name:32} {im.size[0]}x{im.size[1]}  {os.path.getsize(path)}B')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=STATIC, help='output directory')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for svg in (FULL, CHAMFER, MASK):
        if not os.path.exists(svg):
            raise SystemExit(f'design source missing: {svg}')

    print('manifest any (full-art mark, letters nearly fill the square):')
    for side in (192, 512, 1024):
        save(render(FULL, side), args.out, f'icon-{side}.png')

    print('maskable (safe-zone letters, full-bleed - the launcher supplies the mask):')
    for side in (192, 512, 1024):
        save(render(MASK, side), args.out, f'icon-maskable-{side}.png')

    print('apple-touch-icon (180, opaque - iOS paints transparency black):')
    save(render(MASK, 180), args.out, 'apple-touch-icon.png')

    print('favicon.svg (chamfered art, transparent corners kept):')
    path = os.path.join(args.out, 'favicon.svg')
    with open(CHAMFER, encoding='utf-8') as fh:
        body = fh.read()
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)
    print(f'  favicon.svg                      512x512    {os.path.getsize(path)}B')

    print('favicon.ico (multi-frame, each frame its own render, alpha kept):')
    frames = render(CHAMFER, max(FAVICON), opaque=False)
    path = os.path.join(args.out, 'favicon.ico')
    frames.save(path, sizes=[(s, s) for s in FAVICON])
    print(f'  favicon.ico {FAVICON} frames  {os.path.getsize(path)}B')

    print('windows tiles (full-bleed square / mark on #111 when not square):')
    for w, h in TILES:
        im = (render(FULL, w) if w == h
              else plate((w, h), render(FULL, 512), TILE_WIDE_FRAC))
        save(im, args.out, f'icon-{w}x{h}.png' if w != h else f'icon-{w}.png')

    print('ios splash (mark on #111, portrait):')
    small = render(FULL, 512)
    for w, h in SPLASHES:
        save(plate((w, h), small, SPLASH_FRAC), args.out, f'apple-splash-{w}x{h}.png')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
