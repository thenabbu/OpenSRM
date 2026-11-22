#!/usr/bin/env python3
"""The icon gate: the manifest, the template references and the files on disk all
agree, in pixels you can measure.

Three separate lies this catches, because each has shipped here before:

* the manifest declares a size the file is not (a 1024x1024 maskable declared
  512x512 installed badly on Android for months);
* a template points at an icon that does not exist, or at a splash whose media
  query does not describe it (so the launch screen never matches a device);
* a generated file is referenced by nobody — an orphan that looks like coverage.

Dimensions are read from the IHDR chunk of the PNG bytes, never from the file
name. Run stand-alone or from scripts/gates.sh; CI runs this exact line. Exits 1
on any FAIL.

The last thing it does is PROVE IT CAN FAIL: a synthetic tree is broken in four
ways and the same validator must reject each. A gate never seen red is not a gate.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
import tempfile

from PIL import Image, ImageChops, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'app', 'static')
TEMPLATES = os.path.join(ROOT, 'app', 'templates')
HEAD_PARTIAL = 'partials/pwa_head.html'

SAFE_RADIUS = 0.4   # maskable safe circle: inner 80% of the canvas
BRIGHT = 200        # artwork ink vs the dark background fill
BG = (17, 17, 17)   # #111111, the manifest's background_color / theme_color
FAVICON_FRAMES = {16, 24, 32, 48}
APPLE_TOUCH = (180, 180)
BADGE = (96, 96)
# Rows notes/ICONS.md §3 pins; the [unit 8.2] 33-file set the manifest+head carry.
TILES = {'icon-44.png': (44, 44), 'icon-50.png': (50, 50), 'icon-71.png': (71, 71),
         'icon-150.png': (150, 150), 'icon-310.png': (310, 310),
         'icon-310x150.png': (310, 150), 'icon-620x300.png': (620, 300)}


# ── byte-level facts ─────────────────────────────────────────────────────────

def png_size(path: str) -> tuple[int, int] | None:
    """(w, h) from the IHDR chunk. None if the bytes are not a PNG."""
    with open(path, 'rb') as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        return None
    return struct.unpack('>II', head[16:24])


def ico_frames(path: str) -> set[int]:
    """Widths of every frame in the ICO directory (0 means 256)."""
    with open(path, 'rb') as fh:
        data = fh.read()
    if data[:4] != b'\x00\x00\x01\x00':
        return set()
    count = struct.unpack('<H', data[4:6])[0]
    return {data[6 + i * 16] or 256 for i in range(count)}


def opaque(path: str) -> bool:
    """True when no pixel is even slightly transparent (iOS paints gaps black)."""
    im = Image.open(path)
    if im.mode not in ('RGBA', 'LA', 'P'):
        return True
    alpha = im.convert('RGBA').getchannel('A')
    return alpha.getextrema()[0] == 255


def safe_zone(path: str) -> tuple[int, int, float]:
    """(mark px, px outside the safe circle, radius) — computed in C, not in a loop.

    Kept as a MEASUREMENT for the report line only. It is NOT the maskable gate
    any more: see bleed() for why "nothing outside the safe circle" is the wrong
    rule for a tile-shaped mark.
    """
    im = Image.open(path).convert('RGB')
    n = im.size[0]
    bright = im.convert('L').point(lambda v: 255 if v > BRIGHT else 0)
    circle = Image.new('L', (n, n), 0)
    c, r = n / 2, SAFE_RADIUS * n
    ImageDraw.Draw(circle).ellipse([c - r, c - r, c + r, c + r], fill=255)
    # subtract() is 255 only where ink sits outside the circle: one histogram.
    out_px = ImageChops.subtract(bright, circle).histogram()[255]
    return bright.histogram()[255], out_px, r


def bleed(path: str) -> tuple[int, int]:
    """(canvas side, art width in px) of the artwork that reaches the edges.

    A maskable icon is a picture the LAUNCHER crops: it applies its own shape and
    keeps only the inner 80% circle. So the artwork must FILL the canvas — the
    mask then becomes its outline. A mark that stops short of the edge is a plate
    floating in a field, and the field is what a user sees as a thick ring around
    the logo once Android draws its mask over it. That defect shipped: the mark
    was circle-clipped to 69% of the canvas and every installed icon had the ring.

    "Fills the canvas" is measured as a bounding box over ALL four corners, not
    as "pixels that differ from #111111". A two-tone split tile is half #111111
    by design, so the differ-from-background test reported a full-bleed icon as
    75% wide and would have forced us to pad the icon with the very plate this
    rule exists to forbid. The ring defect still fails: a disc-clipped mark
    leaves the plate colour in the corners.
    """
    im = Image.open(path).convert('RGB')
    side = im.size[0]
    corner = im.getpixel((0, 0))
    bbox = ImageChops.difference(im, Image.new('RGB', im.size, corner)).convert('L') \
        .point(lambda v: 255 if v > 6 else 0).getbbox()
    if bbox is None:
        return side, 0
    # A full-bleed tile paints every corner a background colour of its OWN art
    # (here: white left, #111 right), so the box must be taken over all four
    # corners, not one.
    for corner in (im.getpixel((side - 1, 0)), im.getpixel((0, side - 1)),
                   im.getpixel((side - 1, side - 1))):
        other = ImageChops.difference(im, Image.new('RGB', im.size, corner)).convert('L') \
            .point(lambda v: 255 if v > 6 else 0).getbbox()
        if other is None:
            continue
        bbox = (min(bbox[0], other[0]), min(bbox[1], other[1]),
                max(bbox[2], other[2]), max(bbox[3], other[3]))
    return side, max(bbox[2] - bbox[0], bbox[3] - bbox[1])


# ── every check, as a function of a root so the self-test can re-point it ────

def validate(root: str) -> list[str]:
    """Return the list of failures for the tree at `root`. Empty means clean."""
    fails: list[str] = []

    def bad(label: str, detail: str = '') -> None:
        fails.append(f'{label}{" — " + detail if detail else ""}')

    static = os.path.join(root, 'app', 'static')
    templates = os.path.join(root, 'app', 'templates')
    manifest_path = os.path.join(static, 'manifest.json')

    if not os.path.exists(manifest_path):
        return [f'manifest.json missing at {manifest_path}']
    man = json.load(open(manifest_path, encoding='utf-8'))
    icons = man.get('icons') or []
    if not icons:
        bad('manifest declares at least one icon')

    declared: dict[str, tuple[int, int]] = {}
    for entry in icons:
        name = os.path.basename(entry['src'])
        path = os.path.join(static, name)
        if not os.path.exists(path):
            bad(f'{name} exists', entry['src'])
            continue
        try:
            want = tuple(int(v) for v in entry['sizes'].split('x'))
        except ValueError:
            bad(f'{name} sizes parses', entry['sizes'])
            continue
        actual = png_size(path)
        if actual is None:
            bad(f'{name} is a PNG', 'no PNG magic / IHDR')
            continue
        if actual != want:
            bad(f'{name} real pixels == manifest', f'declared {want}, file {actual}')
        if entry.get('type') != 'image/png':
            bad(f'{name} type is image/png', str(entry.get('type')))
        if os.path.getsize(path) == 0:
            bad(f'{name} non-empty')
        declared[name] = actual
        if entry.get('purpose') == 'maskable':
            side, art = bleed(path)
            if art < side * 0.98:
                bad(f'{name} mark fills the canvas (maskable)',
                    f'artwork spans {art}px of {side} — a mark that stops short reads as a ring')

    # Chromium installability is a POSITIVE requirement: both sizes, both purposes.
    for size in ('192x192', '512x512'):
        if not any(e['sizes'] == size and e.get('purpose') == 'any' for e in icons):
            bad(f'manifest has a {size} purpose=any icon (Chromium installability)')
    if not any(e.get('purpose') == 'maskable' and
               max(int(v) for v in e['sizes'].split('x')) >= 512 for e in icons):
        bad('manifest has a maskable icon at 512 or larger (Android adaptive)')
    for name, size in TILES.items():
        if name not in declared:
            bad(f'manifest declares the Windows tile {name}')

    # Files the templates use but the manifest cannot declare (iOS ignores it).
    for name, size in (('apple-touch-icon.png', APPLE_TOUCH), ('icon-badge.png', BADGE),
                       ('logo-rect.png', (1500, 500))):
        path = os.path.join(static, name)
        if not os.path.exists(path):
            bad(f'{name} exists')
            continue
        actual = png_size(path)
        if actual != size:
            bad(f'{name} real pixels', f'expected {size}, file {actual}')
        if name == 'apple-touch-icon.png' and not opaque(path):
            bad('apple-touch-icon.png is opaque', 'iOS paints transparency black')

    ico = os.path.join(static, 'favicon.ico')
    frames = ico_frames(ico) if os.path.exists(ico) else set()
    if not FAVICON_FRAMES <= frames:
        bad('favicon.ico has the multi-size frames',
            f'want {sorted(FAVICON_FRAMES)}, got {sorted(frames)}')

    # ── template wiring ──────────────────────────────────────────────────────
    partial = os.path.join(templates, HEAD_PARTIAL)
    if not os.path.exists(partial):
        return fails + [f'{HEAD_PARTIAL} missing']
    head = open(partial, encoding='utf-8').read()
    splashes = {}
    media_re = re.compile(
        r'device-width:\s*(\d+)px\).*?device-height:\s*(\d+)px\).*?'
        r'-webkit-device-pixel-ratio:\s*([\d.]+)\).*?orientation:\s*portrait')
    for href, media in re.findall(
            r'<link rel="apple-touch-startup-image" href="{{ asset\(\'([^\']+)\'\) }}" media="([^"]+)"',
            head):
        m = media_re.search(media)
        path = os.path.join(static, href)
        if not m:
            bad(f'{href} media query is a portrait device query', media)
            continue
        if not os.path.exists(path):
            bad(f'{href} exists')
            continue
        actual = png_size(path)
        dw, dh, sf = int(m.group(1)), int(m.group(2)), float(m.group(3))
        expect = (round(dw * sf), round(dh * sf))
        if actual != expect:
            bad(f'{href} matches its media query',
                f'query {dw}x{dh}@{sf} = {expect}, file {actual}')
        splashes[href] = actual
    if not splashes:
        bad('the head partial wires apple-touch-startup-image links')

    for meta in ('apple-mobile-web-app-capable', 'apple-mobile-web-app-status-bar-style',
                 'apple-mobile-web-app-title', 'msapplication-TileColor',
                 'msapplication-TileImage', 'apple-touch-icon', 'rel="manifest"'):
        if meta not in head:
            bad(f'head partial carries {meta}')

    for tmpl in sorted(os.listdir(templates)):
        if not tmpl.endswith('.html'):
            continue
        src = open(os.path.join(templates, tmpl), encoding='utf-8').read()
        if tmpl == 'base.html':
            if HEAD_PARTIAL.split('/')[-1] not in src:
                bad('base.html includes the head partial')
            continue
        if tmpl == 'login.html':
            if HEAD_PARTIAL.split('/')[-1] not in src:
                bad('login.html includes the head partial')
            continue
        # every in-app page must reach the head block through base.html
        if 'extends "base.html"' not in src:
            bad(f'{tmpl} extends base.html (else it gets no apple/ms/icon tags)')

    # every static icon a template names must exist, at the size it claims
    refs: dict[str, tuple[int, int] | None] = {}
    head_path = os.path.join(templates, HEAD_PARTIAL)
    scan = [head_path] + [os.path.join(templates, t) for t in sorted(os.listdir(templates))
                          if t.endswith('.html')]
    for path in scan:
        if not os.path.isfile(path):
            continue
        src = open(path, encoding='utf-8').read()
        for asset_href, raw_href, sizes in re.findall(
                r'(?:href|src|content)="(?:\{\{ asset\(\'([^\']+)\'\) \}\}|/static/([\w.-]+\.(?:png|ico)))'
                r'(?:\?v=[^"]*)?"'
                r'(?:\s+sizes="(\d+x\d+)")?',
                src):
            href = asset_href or raw_href
            if raw_href:
                # An unversioned /static/<image> is never edge-cached on this zone
                # (cf-cache-status: BYPASS), so every page load re-fetches an
                # unchanging image through the origin. #163 fixed the head block and
                # dashboard.html; a template that inlines the same file later
                # reintroduces it (base.html did). Enforce the asset() form.
                bad(f'{os.path.basename(path)} serves {raw_href} unversioned',
                    "wrap it in asset('<file>')")
            refs.setdefault(href, None)
            if sizes:
                refs[href] = tuple(int(v) for v in sizes.split('x'))
    for href, sizes in sorted(refs.items()):
        path = os.path.join(static, href)
        if not os.path.exists(path):
            bad(f'template reference {href} exists')
            continue
        if sizes and href.endswith('.png') and png_size(path) != sizes:
            bad(f'template reference {href} matches sizes={sizes[0]}x{sizes[1]}',
                f'file is {png_size(path)}')

    # nothing generated may sit unreferenced, and the old splash names must stay gone
    named_by_manifest = set(declared)
    for name in sorted(os.listdir(static)):
        if name.startswith('apple-touch-startup-'):
            bad(f'{name} is an orphaned splash (renamed to apple-splash-*)')
        if not (name.startswith('apple-splash-') or name.startswith('icon-')):
            continue
        if name in named_by_manifest or name in refs or name == 'icon-badge.png':
            continue
        bad(f'{name} is referenced by the manifest or a template', 'orphan')
    return fails


# ── the positive control: break the mechanism, watch the check fail ─────────

def self_test() -> list[str]:
    """Build a clean fixture, then plant 4 defects. Each MUST be rejected."""
    tmp = tempfile.mkdtemp(prefix='icons-selftest-')
    problems: list[str] = []
    try:
        static = os.path.join(tmp, 'app', 'static')
        tdir = os.path.join(tmp, 'app', 'templates', 'partials')
        os.makedirs(static)
        os.makedirs(tdir)
        src = Image.new('RGB', (1024, 1024), (17, 17, 17))
        # The fixture mark is a FULL-BLEED tile, like app/static/icon-1024.png: one
        # white half running to the canvas edge, one dark half, and a glyph. A
        # centred white square on #111 would make every maskable icon in the
        # fixture fail the new bleed rule and prove nothing about the rule.
        ImageDraw.Draw(src).rectangle([0, 0, 474, 1023], fill=(255, 255, 255))
        ImageDraw.Draw(src).rectangle([475, 0, 1023, 1023], fill=(0, 0, 0))
        ImageDraw.Draw(src).rectangle([560, 400, 700, 620], fill=(255, 255, 255))
        marks = {}
        for name, side in [('icon-192.png', 192), ('icon-512.png', 512),
                           ('icon-1024.png', 1024), ('icon-maskable-192.png', 192),
                           ('icon-maskable-512.png', 512), ('apple-touch-icon.png', 180),
                           ('icon-badge.png', 96), ('logo-rect.png', None)] + list(TILES.items()):
            im = (Image.new('RGB', (1500, 500), (17, 17, 17)) if side is None
                  else src.resize((side, side) if isinstance(side, int) else side, Image.LANCZOS))
            im.save(os.path.join(static, name))
            marks[name] = im.size
        src.resize((48, 48), Image.LANCZOS).save(
            os.path.join(static, 'favicon.ico'), sizes=[(s, s) for s in FAVICON_FRAMES])
        for w, h in [(750, 1334)]:
            src.resize((w, h), Image.LANCZOS).save(os.path.join(static, f'apple-splash-{w}x{h}.png'))

        def write_tree(splash_media=(375, 667, 2), declared_512='512x512'):
            icons = [{'src': f'/static/{n}', 'sizes': f'{s[0]}x{s[1]}', 'type': 'image/png',
                      'purpose': ('maskable' if 'maskable' in n else 'any')}
                     for n, s in marks.items()
                     if n not in ('apple-touch-icon.png', 'icon-badge.png', 'logo-rect.png')]
            for e in icons:
                if e['src'].endswith('icon-512.png'):
                    e['sizes'] = declared_512
            json.dump({'icons': icons}, open(os.path.join(static, 'manifest.json'), 'w'))
            dw, dh, sf = splash_media
            open(os.path.join(tdir, 'pwa_head.html'), 'w').write(
                '<link rel="manifest" href="/static/manifest.json">\n'
                '<link rel="apple-touch-icon" href="{{ asset(\'apple-touch-icon.png\') }}">\n'
                '<link rel="icon" type="image/x-icon" href="{{ asset(\'favicon.ico\') }}">\n'
                '<link rel="icon" type="image/png" sizes="192x192" href="{{ asset(\'icon-192.png\') }}">\n'
                '<meta name="apple-mobile-web-app-capable" content="yes">\n'
                '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n'
                '<meta name="apple-mobile-web-app-title" content="OpenSRM">\n'
                '<meta name="msapplication-TileColor" content="#111111">\n'
                '<meta name="msapplication-TileImage" content="{{ asset(\'icon-150.png\') }}">\n'
                f'<link rel="apple-touch-startup-image" href="{{{{ asset(\'apple-splash-750x1334.png\') }}}}"'
                f' media="(device-width: {dw}px) and (device-height: {dh}px) and'
                f' (-webkit-device-pixel-ratio: {sf}) and (orientation: portrait)">\n')
            open(os.path.join(tmp, 'app', 'templates', 'base.html'), 'w').write(
                '{% include "partials/pwa_head.html" %}')
            open(os.path.join(tmp, 'app', 'templates', 'login.html'), 'w').write(
                '{% include "partials/pwa_head.html" %}')
            open(os.path.join(tmp, 'app', 'templates', 'home.html'), 'w').write(
                '{% extends "base.html" %}')

        write_tree()
        clean = validate(tmp)
        if clean:
            problems.append(f'positive control broken: a clean fixture failed {clean[:3]}')

        write_tree(declared_512='512x513')
        if not any('real pixels == manifest' in f for f in validate(tmp)):
            problems.append('positive control broken: a wrong declared size passed')

        write_tree(splash_media=(430, 932, 3))   # query describes a 1290x2796 file
        if not any('matches its media query' in f for f in validate(tmp)):
            problems.append('positive control broken: a wrong splash media query passed')

        write_tree()
        src.resize((16, 16), Image.LANCZOS).save(
            os.path.join(static, 'favicon.ico'))   # single frame, the old defect
        if not any('favicon.ico has the multi-size frames' in f for f in validate(tmp)):
            problems.append('positive control broken: a 1-frame favicon passed')

        write_tree()
        # The shipped defect: the mark circle-clipped into a disc on a square
        # plate, so 69% of the canvas is artwork and the rest is the plate the
        # launcher shows as a ring. This is the exact icon that was on the device.
        disc = Image.new('RGB', (1024, 1024), BG)
        m = Image.new('L', (1024, 1024), 0)
        r = 0.345 * 1024
        ImageDraw.Draw(m).ellipse([512 - r, 512 - r, 512 + r, 512 + r], fill=255)
        disc.paste(src, (0, 0), m)
        disc.resize((512, 512), Image.LANCZOS).save(
            os.path.join(static, 'icon-maskable-512.png'))
        if not any('mark fills the canvas (maskable)' in f for f in validate(tmp)):
            problems.append('positive control broken: a disc-clipped maskable passed')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return problems


def main() -> int:
    print(f'icon gate — {os.path.relpath(ROOT)}')
    fails = validate(ROOT)
    for f in fails:
        print('FAIL  ' + f)
    print(f'manifest/files/templates: {len(fails)} FAIL')

    control = self_test()
    for f in control:
        print('FAIL  ' + f)
    print('positive control (gate proven able to fail):',
          'PASS' if not control else f'{len(control)} FAIL')

    total = len(fails) + len(control)
    print('\nRESULT:', 'ALL PASS' if not total else f'{total} FAIL')
    return 0 if not total else 1


if __name__ == '__main__':
    sys.exit(main())
