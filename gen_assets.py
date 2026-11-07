#!/usr/bin/env python3
"""Generate high-quality Khvarenah brand assets with Pillow only (no external
image API needed, always works offline).

Produces:
  * khvarenah/assets/golden.png   — 1024x1024 square app emblem
  * docs/golden.png                — copy for the site / og:image
  * docs/og-image.png              — 1200x630 social share card
  * docs/favicon.png               — 128x128 rounded favicon
  * docs/apple-touch-icon.png      — 180x180
"""
import math
import pathlib
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "khvarenah" / "assets"
DOCS = ROOT / "docs"

GOLD_LIGHT = (255, 224, 150)
GOLD = (230, 185, 64)
GOLD_DEEP = (166, 124, 26)
BLACK = (12, 11, 8)


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gold(t):
    """Gold gradient 0..1 from deep to light gold."""
    return _lerp(GOLD_DEEP, GOLD_LIGHT, t)


def _radial_gradient(size: int, inner, outer):
    """Circular gradient image (inner color at center → outer at edge)."""
    im = Image.new("RGB", (size, size))
    px = im.load()
    c = size / 2
    r = size / 2
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - c, y - c) / r
            px[x, y] = _lerp(inner, outer, min(1.0, d))
    return im


def _font(size: int, bold: bool = True):
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            p = pathlib.Path("/usr/share/fonts/truetype/dejavu") / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
        except Exception:
            pass
    return ImageFont.load_default()


def make_emblem(size: int = 1024) -> Image.Image:
    """A radiant winged Persian K emblem with a gold gradient on black."""
    im = Image.new("RGBA", (size, size), (*BLACK, 255))
    d = ImageDraw.Draw(im)

    # subtle radial halo behind the emblem
    halo = _radial_gradient(size, (60, 50, 25), BLACK)
    halo = halo.convert("RGBA")
    # faint overlay
    im = Image.alpha_composite(im, halo)

    cx, cy = size / 2, size / 2
    R = size * 0.34  # outer radius of the sun disc

    # --- solar disc (gold gradient ring) ---
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    steps = 60
    for i in range(steps):
        t0 = i / steps
        t1 = (i + 1) / steps
        r0 = R * (0.55 + 0.45 * t0)
        r1 = R * (0.55 + 0.45 * t1)
        color = _gold(t0)
        # draw an annulus segment
        dd.pieslice([cx - r1, cy - r1, cx + r1, cy + r1],
                    start=0, end=360, fill=color)
    # overlay a shading mask: center darker
    shade = Image.new("L", (size, size), 0)
    sd = ImageDraw.Draw(shade)
    for i in range(steps):
        r0 = R * (0.55 + 0.45 * (i / steps))
        r1 = R * (0.55 + 0.45 * ((i + 1) / steps))
        sd.ellipse([cx - r1, cy - r1, cx + r1, cy + r1],
                   fill=round(255 * (0.35 + 0.65 * (i / steps))))
    disc.putalpha(Image.composite(
        Image.new("L", (size, size), 255),
        shade, shade))
    im = Image.alpha_composite(im, disc)

    # --- wings (mirrored) ---
    wing = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wing)
    for side in (-1, 1):
        base_y = cy
        # three tapered feather blades
        for k, (span, lift) in enumerate(
                ((0.30, -0.02), (0.44, 0.04), (0.58, 0.12))):
            x0 = cx + side * R * 0.55
            x1 = cx + side * R * (0.55 + span)
            y_top = base_y - R * 0.30 + lift * R
            y_bot = base_y + R * 0.30 + lift * R
            wd.polygon([
                (x0, base_y - R * 0.06),
                (x1, y_top),
                (x1 + side * R * 0.10, (y_top + y_bot) / 2),
                (x1, y_bot),
                (x0, base_y + R * 0.06),
            ], fill=_gold(0.4 + 0.2 * k))
    im = Image.alpha_composite(im, wing)

    # --- central monogram: stylized "K" / flame ---
    # Draw a clean bold K as the royal monogram
    font = _font(int(size * 0.30))
    label = "K"
    bbox = d.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    mon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    md = ImageDraw.Draw(mon)
    md.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]),
            label, font=font, fill=(*GOLD, 255))
    im = Image.alpha_composite(im, mon)

    # --- small flame accents above the disc ---
    flame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fd = ImageDraw.Draw(flame)
    for i, dx in enumerate((-0.16, 0.0, 0.16)):
        fx = cx + dx * R
        fy = cy - R * 0.92
        fd.ellipse([fx - R * 0.05, fy - R * 0.10,
                     fx + R * 0.05, fy + R * 0.02], fill=_gold(0.7))
    im = Image.alpha_composite(im, flame)
    return im


def make_og(logo: Image.Image, width=1200, height=630) -> Image.Image:
    im = Image.new("RGBA", (width, height), (*BLACK, 255))
    d = ImageDraw.Draw(im)
    # gold gradient band on the left edge for depth
    band = _radial_gradient(max(width, height), (50, 42, 22), BLACK).convert("RGBA")
    band = band.resize((width, height), Image.LANCZOS)
    im = Image.alpha_composite(im, band)

    # logo on the left
    logo_sq = logo.resize((height - 120, height - 120), Image.LANCZOS)
    im.paste(logo_sq, (60, 60), logo_sq)

    # typography on the right
    x = 60 + (height - 120) + 70
    title = "KHVARENAH"
    f_title = _font(92)
    f_sub = _font(36)
    f_line = _font(28)
    d.text((x, 170), title, font=f_title, fill=(*GOLD, 255))
    d.text((x, 290), "Cloudflare Worker VLESS", font=f_sub,
           fill=(220, 205, 165, 255))
    d.text((x, 350), "· 0 → 100 · from your terminal", font=f_sub,
           fill=(210, 200, 175, 255))
    d.text((x, 470), "Ancient Persian Royal Glory — خوَرنه", font=f_line,
           fill=(180, 160, 120, 255))
    return im


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    print("Rendering square emblem …")
    logo = make_emblem(1024)
    logo = logo.convert("RGB").convert("RGBA")
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
    og = make_og(logo).convert("RGB")
    og.save(DOCS / "og-image.png")
    print("  og-image.png (1200x630)")

    print("Done.")


if __name__ == "__main__":
    main()
