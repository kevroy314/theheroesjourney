#!/usr/bin/env python3
"""Generate the PWA / home-screen icons.

One motif, drawn from the game's own fiction: a dark room, a mountain, and the
one light on it that never goes out. Colours come from data/themes/firstlight.json
so the installed icon and the running app agree.

    python3 tools/make_icons.py        # writes web/icons/*.png
"""
import json
import os
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "icons")
THEME = os.path.join(ROOT, "data", "themes", "firstlight.json")

# Rendered large and downsampled, so the diagonals come out clean.
SUPER = 4
SIZES = [
    ("icon-192.png", 192, 0.00),
    ("icon-512.png", 512, 0.00),
    # Maskable icons get cropped to a circle by the launcher, so the artwork
    # has to sit inside the middle ~80%.
    ("icon-maskable-512.png", 512, 0.18),
    ("apple-touch-icon.png", 180, 0.06),
    ("favicon-64.png", 64, 0.00),
]


def theme_colors():
    with open(THEME, encoding="utf-8") as f:
        colors = json.load(f)["colors"]
    return {k: tuple(int(v.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) for k, v in colors.items()}


def draw_icon(size, pad_frac, c):
    """Draw at SUPER x scale, then downsample."""
    n = size * SUPER
    pad = int(n * pad_frac)
    inner = n - pad * 2

    img = Image.new("RGB", (n, n), c["bg"])
    d = ImageDraw.Draw(img)

    def px(fx, fy):
        return (pad + fx * inner, pad + fy * inner)

    # Sky: a few flat bands, darkest at the top. Banding is deliberate — it
    # reads as dusk without needing a gradient that will dither at 64px.
    sky = [
        (0.00, 0.30, (18, 21, 34)),
        (0.30, 0.46, (26, 32, 50)),
        (0.46, 0.58, (38, 45, 66)),
        (0.58, 0.66, (60, 60, 78)),
    ]
    for y0, y1, col in sky:
        d.rectangle([px(0.0, y0), px(1.0, y1)], fill=col)

    # Far ridge, then the near mountain in front of it.
    d.polygon([px(0.00, 0.72), px(0.26, 0.50), px(0.52, 0.72)], fill=(30, 35, 52))
    d.polygon([px(0.40, 0.72), px(0.72, 0.42), px(1.00, 0.72)], fill=(22, 26, 40))

    peak = px(0.72, 0.445)   # sitting on the ridge, not floating over it

    # The light: a soft bloom under a hard core, so it survives downsampling.
    glow = Image.new("RGB", (n, n), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = inner * 0.052
    gd.ellipse([peak[0] - r, peak[1] - r, peak[0] + r, peak[1] + r], fill=c["accent"])
    glow = glow.filter(ImageFilter.GaussianBlur(radius=inner * 0.030))
    img = Image.blend(img, Image.new("RGB", (n, n), c["accent"]), 0.0)
    img = Image.composite(Image.new("RGB", (n, n), c["accent"]), img, glow.convert("L"))

    d = ImageDraw.Draw(img)
    core = inner * 0.015
    d.ellipse([peak[0] - core, peak[1] - core, peak[0] + core, peak[1] + core],
              fill=(255, 244, 224))

    # Floor: the dark room the player wakes up in.
    d.rectangle([px(0.0, 0.72), px(1.0, 1.0)], fill=(13, 15, 22))
    d.line([px(0.0, 0.72), px(1.0, 0.72)], fill=(44, 50, 70), width=max(1, int(inner * 0.006)))

    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    c = theme_colors()
    for name, size, pad in SIZES:
        icon = draw_icon(size, pad, c)
        path = os.path.join(OUT, name)
        icon.save(path, optimize=True)
        print("wrote %s (%dx%d, %d bytes)" % (path, size, size, os.path.getsize(path)))


if __name__ == "__main__":
    main()
