#!/usr/bin/env python3
"""Generate the PWA / home-screen icons, and the Android launcher icons.

One motif, drawn from the game's own fiction: a dark room, a mountain, and the
one light on it that never goes out. Colours come from data/themes/firstlight.json
so the installed icon and the running app agree.

    python3 tools/make_icons.py        # writes web/icons/*.png and
                                       #        assets/icons/android/*.png

Android wants the same picture in four cuts, and they are not interchangeable:

    main_192x192              the legacy square icon, opaque, still used by
                              launchers and by the "app info" screens
    adaptive_background       full bleed; the launcher masks it to whatever
                              shape the device uses and may parallax it
    adaptive_foreground       transparent, and only the middle ~66% is
                              guaranteed visible after masking
    adaptive_monochrome       alpha-only silhouette for Android 13 themed icons;
                              the system throws the colours away and tints it

Splitting the motif across the adaptive pair is free: the flat sky-and-floor
bands are the background layer and the mountains and the light are the
foreground, which is exactly the decomposition the parallax effect wants
anyway. Composited, the two layers are pixel-for-pixel the PWA icon.
"""
import json
import os
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "icons")
# Referenced by export_presets.cfg [preset.2] launcher_icons/*, read straight
# off disk at export time rather than out of the pck.
ANDROID_OUT = os.path.join(ROOT, "assets", "icons", "android")
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

# Adaptive icons are 108dp of which only the middle 72dp survives every mask
# shape. Godot asks for 432x432, so the safe zone is the middle 288 — 2/3.
ADAPTIVE = 432
SAFE = 72.0 / 108.0

# The scene, as fractions of the drawing box. Shared by every cut so the PWA
# icon and the Android launcher icon are literally the same picture.
SKY = [
    (0.00, 0.30, (18, 21, 34)),
    (0.30, 0.46, (26, 32, 50)),
    (0.46, 0.58, (38, 45, 66)),
    (0.58, 0.66, (60, 60, 78)),
]
FAR_RIDGE = ([(0.00, 0.72), (0.26, 0.50), (0.52, 0.72)], (30, 35, 52))
NEAR_PEAK = ([(0.40, 0.72), (0.72, 0.42), (1.00, 0.72)], (22, 26, 40))
HORIZON = 0.72
FLOOR = (13, 15, 22)
FLOOR_EDGE = (44, 50, 70)
LIGHT = (0.72, 0.445)      # sitting on the ridge, not floating over it
LIGHT_CORE = (255, 244, 224)

# The adaptive layers are drawn full-bleed, so the mask is allowed to eat the
# ridge skirts — but not the one thing the icon is about. Fail here rather than
# discovering it on a device with a circular mask.
assert all((1.0 - SAFE) / 2.0 < v < 1.0 - (1.0 - SAFE) / 2.0 for v in LIGHT), \
    "the light at %s falls outside the adaptive-icon safe zone" % (LIGHT,)


def theme_colors():
    with open(THEME, encoding="utf-8") as f:
        colors = json.load(f)["colors"]
    return {k: tuple(int(v.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) for k, v in colors.items()}


def _box(n, pad_frac):
    """Return a fraction -> pixel mapper for a padded n x n canvas."""
    pad = int(n * pad_frac)
    inner = n - pad * 2

    def px(fx, fy):
        return (pad + fx * inner, pad + fy * inner)

    return px, inner


def _bloom(img, px, inner, accent):
    """The light: a soft bloom under a hard core, so it survives downsampling.

    Composited through a blurred luminance mask rather than drawn, because a
    plain circle at 64px turns into four grey pixels.
    """
    n = img.size[0]
    peak = px(*LIGHT)
    glow = Image.new("RGB", (n, n), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = inner * 0.052
    gd.ellipse([peak[0] - r, peak[1] - r, peak[0] + r, peak[1] + r], fill=accent)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=inner * 0.030))
    mask = glow.convert("L")
    flat = Image.new(img.mode, (n, n), accent if img.mode == "RGB" else accent + (255,))
    img = Image.composite(flat, img, mask)

    d = ImageDraw.Draw(img)
    core = inner * 0.015
    fill = LIGHT_CORE if img.mode == "RGB" else LIGHT_CORE + (255,)
    d.ellipse([peak[0] - core, peak[1] - core, peak[0] + core, peak[1] + core], fill=fill)
    return img


def draw_icon(size, pad_frac, c):
    """The whole scene, opaque. Draw at SUPER x scale, then downsample."""
    n = size * SUPER
    px, inner = _box(n, pad_frac)

    img = Image.new("RGB", (n, n), c["bg"])
    d = ImageDraw.Draw(img)

    # Sky: a few flat bands, darkest at the top. Banding is deliberate — it
    # reads as dusk without needing a gradient that will dither at 64px.
    for y0, y1, col in SKY:
        d.rectangle([px(0.0, y0), px(1.0, y1)], fill=col)

    # Far ridge, then the near mountain in front of it.
    for points, col in (FAR_RIDGE, NEAR_PEAK):
        d.polygon([px(*p) for p in points], fill=col)

    img = _bloom(img, px, inner, c["accent"])

    # Floor: the dark room the player wakes up in.
    d = ImageDraw.Draw(img)
    d.rectangle([px(0.0, HORIZON), px(1.0, 1.0)], fill=FLOOR)
    d.line([px(0.0, HORIZON), px(1.0, HORIZON)], fill=FLOOR_EDGE, width=max(1, int(inner * 0.006)))

    return img.resize((size, size), Image.LANCZOS)


def draw_adaptive_background(c):
    """The flat layers: sky above the horizon, the dark room below it.

    Full bleed and opaque. The launcher can shift this layer by up to 1/6 of
    its width for parallax, so there must be no dead area to slide into view —
    which is why the sky is drawn edge to edge rather than stopping where the
    mountains would cover it.
    """
    n = ADAPTIVE * SUPER
    px, inner = _box(n, 0.0)
    img = Image.new("RGB", (n, n), SKY[0][2])
    d = ImageDraw.Draw(img)
    for y0, y1, col in SKY:
        d.rectangle([px(0.0, y0), px(1.0, y1)], fill=col)
    d.rectangle([px(0.0, HORIZON), px(1.0, 1.0)], fill=FLOOR)
    d.line([px(0.0, HORIZON), px(1.0, HORIZON)], fill=FLOOR_EDGE,
           width=max(1, int(inner * 0.006)))
    return img.resize((ADAPTIVE, ADAPTIVE), Image.LANCZOS)


def draw_adaptive_foreground(c):
    """The mountains and the light, on transparency, at full scale.

    Deliberately *not* shrunk into the safe zone: the ridges are supposed to run
    off the sides, and letting the mask trim their skirts is what makes the two
    layers compose back into exactly the PWA icon. What the safe zone actually
    protects is the peak and the light at LIGHT = (0.72, 0.445), and both sit
    well inside the middle two thirds.
    """
    n = ADAPTIVE * SUPER
    px, inner = _box(n, 0.0)
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for points, col in (FAR_RIDGE, NEAR_PEAK):
        d.polygon([px(*p) for p in points], fill=col + (255,))
    return _bloom(img, px, inner, c["accent"]).resize((ADAPTIVE, ADAPTIVE), Image.LANCZOS)


def draw_adaptive_monochrome(c):
    """A flat silhouette — Android 13 keeps only the alpha and tints the rest.

    So the bloom is useless here (it would tint to a solid blob) and the light
    has to be punched *through* the mountain as a ring of empty alpha to read
    at all.
    """
    n = ADAPTIVE * SUPER
    px, inner = _box(n, 0.0)
    img = Image.new("RGBA", (n, n), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    solid = (255, 255, 255, 255)
    for points, _ in (FAR_RIDGE, NEAR_PEAK):
        d.polygon([px(*p) for p in points], fill=solid)
    d.rectangle([px(0.0, HORIZON), px(1.0, 1.0)], fill=solid)

    peak = px(*LIGHT)
    for r_frac, fill in ((0.060, (255, 255, 255, 0)), (0.030, solid)):
        r = inner * r_frac
        d.ellipse([peak[0] - r, peak[1] - r, peak[0] + r, peak[1] + r], fill=fill)
    return img.resize((ADAPTIVE, ADAPTIVE), Image.LANCZOS)


def save(img, path, label):
    img.save(path, optimize=True)
    print("wrote %s (%dx%d, %d bytes)%s"
          % (path, img.size[0], img.size[1], os.path.getsize(path), label))


def main():
    c = theme_colors()

    os.makedirs(OUT, exist_ok=True)
    for name, size, pad in SIZES:
        save(draw_icon(size, pad, c), os.path.join(OUT, name), "")

    os.makedirs(ANDROID_OUT, exist_ok=True)
    android = [
        # Same picture, same size as the PWA 192 — an Android launcher and a
        # home-screen PWA sitting side by side should be the same icon.
        ("icon-192.png", draw_icon(192, 0.00, c), " [main_192x192]"),
        ("adaptive-background.png", draw_adaptive_background(c), " [adaptive_background_432x432]"),
        ("adaptive-foreground.png", draw_adaptive_foreground(c), " [adaptive_foreground_432x432]"),
        ("adaptive-monochrome.png", draw_adaptive_monochrome(c), " [adaptive_monochrome_432x432]"),
    ]
    for name, img, label in android:
        save(img, os.path.join(ANDROID_OUT, name), label)


if __name__ == "__main__":
    main()
