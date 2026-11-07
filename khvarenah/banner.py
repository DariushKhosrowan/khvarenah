"""Khvarenah logo banner — renders the golden Khosrowan logo as terminal art.

Produces a true-color half-block ANSI rendering of ``assets/golden.png`` so the
app can greet the user with its emblem in the terminal, whether in the TUI or
the headless CLI.
"""

from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover
    from PIL import Image
    HAVE_PIL = True
except Exception:  # pragma: no cover
    HAVE_PIL = False

_LOGO = Path(__file__).resolve().parent / "assets" / "golden.png"
_FALLBACK = Path.home() / "Projects" / "Khosrowan.ir" / "logo" / "golden.png"


def _composite(img) -> Image.Image:  # type: ignore[name-defined]
    """Flatten alpha onto a near-black canvas so the gold pops on any bg."""
    img = img.convert("RGBA")
    bg = Image.new("RGBA", img.size, (8, 7, 12, 255))
    bg.alpha_composite(img)
    return bg.convert("RGB")


def ansi_banner(width: int | None = None) -> str:
    """Return a true-color half-block ANSI banner of the golden logo.

    Returns an empty string when Pillow is missing or the logo can't be found
    (the app still runs — it just greets you in text instead).
    """
    if not HAVE_PIL:
        return ""
    path = _LOGO if _LOGO.exists() else _FALLBACK
    if not path.exists():
        return ""

    img = _composite(Image.open(path))
    W = width or 62
    W = max(20, min(W, 84))
    ar = img.height / img.width
    H = max(6, int(W * ar * 0.5))  # horizontal rows (each = 2px tall)

    img = img.resize((W, H * 2), Image.LANCZOS)
    px = img.load()

    lines = []
    for y in range(0, H * 2, 2):
        row = []
        for x in range(W):
            r1, g1, b1 = px[x, y][:3]
            r2, g2, b2 = px[x, y + 1][:3]
            row.append(
                f"\x1b[38;2;{r1};{g1};{b1}m"
                f"\x1b[48;2;{r2};{g2};{b2}m\u2580"
            )
        lines.append("".join(row) + "\x1b[0m")
    return "\n".join(lines)


def rich_banner(width: int | None = None):
    """Return the banner as a ``rich.text.Text`` object (for Textual/TUI)."""
    from rich.text import Text

    raw = ansi_banner(width)
    if not raw:
        return Text("")
    return Text.from_ansi(raw)
