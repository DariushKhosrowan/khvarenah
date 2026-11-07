#!/usr/bin/env python3
"""Khvarenah brand emblem — sacred flame + Faravahar wings (Pillow only).

Implements the design spec from the DeepSeek bridge:

  KHVARENAH — Emblem Specification (1024x1024):
  1. bg        full black #0a0705
  2. halo      warm radial glow centered (512,512), rgba(255,224,150,.16)->0
  3. rays      24-ray sunburst (even long r=450, odd short r=390), gold grad
  4. wings     left/right Faravahar wing arcs, 5 tapered curved feathers each
  5. disc_ring gold ring r=156 #a67c1a, highlight stroke #ffe096
  6. disc_core black disc r=136 (flame substrate), inner gold edge
  7. star8     16-point subtle near-black star on the core (outer 108/inner 54)
  8. flame_outer sacred flame (atar) — 12-point gold polygon
  9. flame_inner hot white-gold core — 10-point polygon
 10. frame     thin outer border ring r=492 #b8862b

Produces:
  * khvarenah/assets/golden.png     — 1024x1024 square app emblem
  * docs/golden.png                 — copy for the site / og-image
  * docs/favicon.png                — 128x128 rounded favicon
  * docs/apple-touch-icon.png       — 180x180
  * docs/og-image.png               — 1200x630 social card
"""
from __future__ import annotations

import math
import pathlib
from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "khvarenah" / "assets"
DOCS = ROOT / "docs"

# Palette (from spec)
BLACK = (10, 7, 5)          # #0a0705
DEEP = (166, 124, 26)       # #a67c1a
MID = (212, 167, 68)        # #d4a744
LIGHT = (255, 224, 150)     # #ffe096
DARK = (26, 15, 5)          # #1a0f05
FRAME = (184, 134, 43)      # #b8862b

SIZE = 1024
CX = CY = 512


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _grad_color(t):
    """Gold gradient 0..1: deep -> light."""
    return _lerp(DEEP, LIGHT, t)


def _composite(base, layer):
    return Image.alpha_composite(base, layer)


def _render_radial_halo(size):
    """Warm radial glow: rgba(255,224,150,.16) at center -> 0 at r=510."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = im.load()
    c = size / 2
    rmax = 510
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - c, y - c)
            t = min(1.0, d / rmax)
            # quadratic falloff for a soft halo
            a = int(40 * (1 - t) ** 2)
            px[x, y] = (255, 224, 150, a)
    return im


def _feather_polygon(root, tip):
    """Tapered curved feather blade from root to tip (spec §4)."""
    pts = []
    steps = 12
    ax = tip[0] - root[0]
    ay = tip[1] - root[1]
    # perpendicular unit vector
    length = math.hypot(ax, ay) or 1
    px = -ay / length
    py = ax / length
    upper, lower = [], []
    for i in range(steps + 1):
        t = i / steps
        cx = root[0] + t * ax
        cy = root[1] + t * ay - 12 * math.sin(math.pi * t)
        w = 30 * (1 - t) + 2 * t
        half = w / 2
        upper.append((cx + px * half, cy + py * half))
        lower.append((cx - px * half, cy - py * half))
    return upper + lower[::-1]


def make_flame():  # (outer_poly, inner_poly)
    outer = [
        (512, 398), (538, 438), (556, 488), (564, 545), (554, 595),
        (534, 620), (512, 628), (490, 620), (470, 595), (460, 545),
        (468, 488), (486, 438),
    ]
    inner = [
        (512, 470), (526, 500), (535, 540), (538, 575), (532, 600),
        (512, 612), (492, 600), (486, 575), (489, 540), (498, 500),
    ]
    return outer, inner


def make_emblem(size: int = 1024) -> Image.Image:
    n = size
    c = n / 2
    s = n / 1024.0  # scale factor from the 1024 spec

    def P(x, y):
        return (round(x * s), round(y * s))

    def R(r):
        return round(r * s)

    # --- layer 1: bg ---
    im = Image.new("RGBA", (n, n), (*BLACK, 255))

    # --- layer 2: halo ---
    halo = _render_radial_halo(n)
    im = _composite(im, halo)

    # --- layer 3: rays (24-ray sunburst) ---
    rays = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    for i in range(24):
        angle = math.radians(i * 15)
        long_ray = i % 2 == 0
        tip_r = R(450) if long_ray else R(390)
        base_r = R(150)
        bh = R(8) if long_ray else R(6)
        th = R(1)
        cos, sin = math.cos(angle), math.sin(angle)
        # base point on the disc edge
        bx, by = c + cos * base_r, c + sin * base_r
        tx, ty = c + cos * tip_r, c + sin * tip_r
        # perpendicular for half-width
        bpx, bpy = -sin * bh, cos * bh
        tpx, tpy = -sin * th, cos * th
        rd.polygon(
            [(bx + bpx, by + bpy), (tx + tpx, ty + tpy),
             (tx - tpx, ty - tpy), (bx - bpx, by - bpy)],
            fill=(*_grad_color(0.15 + 0.85 * (tip_r / 450)), 255))
    im = _composite(im, rays)

    # --- layer 4: wings ---
    wings = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wings)
    left_roots = [(355, 462), (352, 487), (350, 512), (352, 537), (355, 562)]
    left_tips = [(148, 398), (122, 458), (108, 512), (122, 566), (148, 626)]
    for root, tip in zip(left_roots, left_tips):
        poly = _feather_polygon(P(*root), P(*tip))
        grade = (root[1] - 398) / (626 - 398)
        wd.polygon(poly, fill=(*_lerp(DEEP, LIGHT, grade), 255))
    # mirror right wing across x = c
    for root, tip in zip(left_roots, left_tips):
        rroot = (2 * c - root[0], root[1])
        rtip = (2 * c - tip[0], tip[1])
        poly = _feather_polygon(P(*rroot), P(*rtip))
        grade = (root[1] - 398) / (626 - 398)
        wd.polygon(poly, fill=(*_lerp(DEEP, LIGHT, grade), 255))
    im = _composite(im, wings)

    # --- layer 5: disc_ring ---
    ring = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ring_d = ImageDraw.Draw(ring)
    # soft outer bloom
    ring_d.ellipse([c - R(170), c - R(170), c + R(170), c + R(170)],
                   outline=(*DEEP, 56), width=R(6))
    ring_d.ellipse([c - R(156), c - R(156), c + R(156), c + R(156)],
                   fill=(*DEEP, 255))
    ring_d.ellipse([c - R(154), c - R(154), c + R(154), c + R(154)],
                   outline=(*LIGHT, 255), width=R(2))
    im = _composite(im, ring)

    # --- layer 6: disc_core ---
    core = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    core_d = ImageDraw.Draw(core)
    core_d.ellipse([c - R(136), c - R(136), c + R(136), c + R(136)],
                   fill=(*BLACK, 255))
    core_d.ellipse([c - R(134), c - R(134), c + R(134), c + R(134)],
                   outline=(*MID, 255), width=R(1))
    im = _composite(im, core)

    # --- layer 7: 16-point subtle star ---
    star = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    star_d = ImageDraw.Draw(star)
    star_pts = []
    for k in range(16):
        angle = math.radians(k * 22.5)
        r = R(108) if k % 2 == 0 else R(54)
        # y-flipped for Pillow (screen y grows downward), so sin is negated
        star_pts.append((c + math.cos(angle) * r, c - math.sin(angle) * r))
    star_d.polygon(star_pts, fill=(*DARK, 255))
    im = _composite(im, star)

    # --- layer 8/9: flame ---
    outer_poly, inner_poly = make_flame()
    flame = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    flame_d = ImageDraw.Draw(flame)
    # outer flame: fill mid-gold, then vertical gradient clipped by polygon
    outer_scaled = [P(x, y) for x, y in outer_poly]
    flame_d.polygon(outer_scaled, fill=(*MID, 255))
    # simple vertical gradient overlay (top light -> bottom deep)
    grad = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    y0, y1 = R(398), R(628)
    # approximate: draw horizontal gradient stripes clipped by the flame
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).polygon(outer_scaled, fill=255)
    for yy in range(y0, y1 + 1):
        t = (yy - y0) / max(1, y1 - y0)
        gd.line([(0, yy), (n, yy)], fill=(*_lerp(LIGHT, DEEP, t), 255))
    flame = Image.composite(grad, flame, mask)
    # inner flame (hot white-gold core)
    inner_scaled = [P(x, y) for x, y in inner_poly]
    inner_layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(inner_layer).polygon(inner_scaled, fill=(*LIGHT, 230))
    flame = _composite(flame, inner_layer)
    im = _composite(im, flame)

    # --- layer 10: frame ring ---
    frame = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(frame).ellipse(
        [c - R(492), c - R(492), c + R(492), c + R(492)],
        outline=(*FRAME, 255), width=R(2))
    im = _composite(im, frame)

    return im


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    print("Rendering Khvarenah emblem (sacred flame + Faravahar wings) …")
    logo = make_emblem(1024).convert("RGB").convert("RGBA")
    logo.save(ASSETS / "golden.png")
    logo.save(DOCS / "golden.png")
    print("  golden.png (1024x1024)")

    fc = logo.resize((128, 128), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (128, 128), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, 127, 127], radius=30, fill=255)
    fc.putalpha(mask)
    fc.save(DOCS / "favicon.png")
    print("  favicon.png (128x128)")

    at = logo.resize((180, 180), Image.LANCZOS)
    at.save(DOCS / "apple-touch-icon.png")
    print("  apple-touch-icon.png (180x180)")

    print("Rendering og:image …")
    og = Image.new("RGBA", (1200, 630), (*BLACK, 255))
    og_d = ImageDraw.Draw(og)
    logo_sq = logo.resize((510, 510), Image.LANCZOS)
    og.paste(logo_sq, (60, 60), logo_sq)
    x = 60 + 510 + 70
    og_d.text((x, 170), "KHVARENAH", fill=(*LIGHT, 255))
    og_d.text((x, 290), "Cloudflare Worker VLESS", fill=(220, 205, 165, 255))
    og_d.text((x, 350), "· 0 → 100 · from your terminal", fill=(210, 200, 175, 255))
    og_d.text((x, 470), "Sacred flame — خوَرنه", fill=(180, 160, 120, 255))
    og.convert("RGB").save(DOCS / "og-image.png")
    print("  og-image.png (1200x630)")

    print("Done.")


if __name__ == "__main__":
    main()
