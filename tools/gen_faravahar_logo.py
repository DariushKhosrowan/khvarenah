#!/usr/bin/env python3
"""Generate the Khvarenah Faravahar-inspired emblem (gold-on-black SVG → PNG).

Built only from SVG primitives that cairosvg renders reliably with gradient
fills (circle/ellipse/line/polygon/rect) — avoid <path> with multiple cubic
Bézier (C) commands + gradient, which crashes cairosvg's bounding-box parser.

Outputs:
  khvarenah/assets/golden.png      — 1024×1024 app emblem
  khvarenah/assets/khvarenah.svg   — vector source
  docs/golden.png                  — copy for the site / og:image
"""
import cairosvg
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "khvarenah" / "assets"
DOCS = ROOT / "docs"
ASSETS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)

S = 1024
C = S / 2
GOLD_L = "#ffd996"
GOLD_M = "#e6b941"
GOLD_D = "#8a6515"
BLACK = "#0c0b08"
EDGE = GOLD_D

defs = """
<defs>
  <linearGradient id="gold" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#ffd996"/>
    <stop offset="0.5" stop-color="#e6b941"/>
    <stop offset="1" stop-color="#8a6515"/>
  </linearGradient>
  <radialGradient id="halo" cx="0.5" cy="0.5" r="0.5">
    <stop offset="0" stop-color="#e6b941" stop-opacity="0.35"/>
    <stop offset="0.7" stop-color="#e6b941" stop-opacity="0.08"/>
    <stop offset="1" stop-color="#ffd996" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="disc" cx="0.5" cy="0.42" r="0.62">
    <stop offset="0" stop-color="#ffd996"/>
    <stop offset="0.7" stop-color="#e6b941"/>
    <stop offset="1" stop-color="#8a6515"/>
  </radialGradient>
</defs>
"""

parts = []

# halo
parts.append(f'<circle cx="{C}" cy="{C}" r="470" fill="url(#halo)"/>')

# radiant rays
for i in range(24):
    a = 2 * math.pi * i / 24
    r1, r2 = 178, 282
    x1, y1 = C + r1 * math.cos(a), C + r1 * math.sin(a)
    x2, y2 = C + r2 * math.cos(a), C + r2 * math.sin(a)
    parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="url(#gold)" stroke-width="6" stroke-linecap="round" opacity="0.5"/>')

rows = [
    [(120, -150, 8, 62, 22, .92), (205, -175, 10, 70, 24, .92), (290, -195, 12, 76, 26, .92), (375, -205, 15, 72, 25, .92), (450, -195, 18, 60, 22, .92)],
    [(90, -95, 10, 74, 24, 1), (180, -115, 14, 86, 27, 1), (275, -130, 17, 92, 29, 1), (370, -132, 21, 88, 28, 1), (455, -118, 24, 72, 24, 1), (520, -95, 27, 56, 20, 1)],
    [(60, -40, 14, 88, 25, 1), (150, -55, 18, 100, 28, 1), (245, -62, 22, 108, 30, 1), (340, -58, 27, 104, 29, 1), (430, -40, 32, 86, 25, 1), (510, -10, 38, 64, 20, 1)],
]
right = []
for row in rows:
    for (dx, dy, a, rx, ry, op) in row:
        right.append(f'<ellipse cx="{C+dx:.1f}" cy="{C+dy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'fill="url(#gold)" stroke="{EDGE}" stroke-width="2.5" opacity="{op}" '
                    f'transform="rotate({a:.1f} {C+dx:.1f} {C+dy:.1f})"/>')
parts.append(f'<g id="wing">{ "".join(right) }</g>')
parts.append(f'<use href="#wing" transform="translate({S},0) scale(-1,1)"/>')

# tail feathers
for (dx, dy, a, rx, ry) in [(-70, 120, -28, 42, 130), (0, 130, -30, 44, 145), (70, 120, -32, 42, 130)]:
    parts.append(f'<ellipse cx="{C+dx:.1f}" cy="{C+dy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
                f'fill="url(#gold)" stroke="{EDGE}" stroke-width="3" '
                f'transform="rotate({a:.1f} {C+dx:.1f} {C+dy:.1f})"/>')

# sacred flames
def flame(dx, dy, h, w, ang):
    parts.append(f'<ellipse cx="{C+dx:.1f}" cy="{C+dy:.1f}" rx="{w:.1f}" ry="{h:.1f}" '
                f'fill="url(#gold)" opacity="0.85" '
                f'transform="rotate({ang:.1f} {C+dx:.1f} {C+dy:.1f})"/>')
flame(-150, 200, 95, 26, -8)
flame(0, 195, 125, 30, 0)
flame(150, 200, 95, 26, 8)

# central disc + rings
parts.append(f'<circle cx="{C}" cy="{C}" r="128" fill="url(#disc)" stroke="{EDGE}" stroke-width="4"/>')
parts.append(f'<circle cx="{C}" cy="{C}" r="163" fill="none" stroke="url(#gold)" stroke-width="14"/>')
parts.append(f'<circle cx="{C}" cy="{C}" r="183" fill="none" stroke="{EDGE}" stroke-width="3" opacity="0.8"/>')

# figure
parts.append(f'<polygon points="{C-30:.0f},{C-84:.0f} {C-24:.0f},{C-112:.0f} {C-12:.0f},{C-92:.0f} {C:.0f},{C-120:.0f} {C+12:.0f},{C-92:.0f} {C+24:.0f},{C-112:.0f} {C+30:.0f},{C-84:.0f}" '
            f'fill="url(#gold)" stroke="{EDGE}" stroke-width="2"/>')
parts.append(f'<circle cx="{C}" cy="{C-58}" r="26" fill="url(#gold)" stroke="{EDGE}" stroke-width="3"/>')
parts.append(f'<rect x="{C-27:.0f}" y="{C+6:.0f}" width="54" height="9" rx="4" fill="{EDGE}"/>')
parts.append(f'<polygon points="{C-30:.0f},{C-30:.0f} {C-26:.0f},{C+52:.0f} {C+26:.0f},{C+52:.0f} {C+30:.0f},{C-30:.0f}" '
            f'fill="url(#gold)" stroke="{EDGE}" stroke-width="3"/>')
for sign in (-1, 1):
    x = C + sign * 22
    x2 = C + sign * 78
    x3 = C + sign * 74
    parts.append(f'<polygon points="{x:.0f},{C-16:.0f} {x2:.0f},{C-24:.0f} {x3:.0f},{C-6:.0f} {x:.0f},{C-2:.0f}" '
                f'fill="url(#gold)" stroke="{EDGE}" stroke-width="2"/>')

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{S}" height="{S}" viewBox="0 0 {S} {S}">'
       f'<rect width="{S}" height="{S}" fill="{BLACK}"/>'
       f'{defs}{ "".join(parts) }</svg>')

(ASSETS / "khvarenah.svg").write_text(svg)
cairosvg.svg2png(bytestring=svg.encode(), write_to=str(ASSETS / "golden.png"), output_width=S, output_height=S)
import shutil
shutil.copyfile(ASSETS / "golden.png", DOCS / "golden.png")
print("wrote", ASSETS / "golden.png", ASSETS / "khvarenah.svg", DOCS / "golden.png")
