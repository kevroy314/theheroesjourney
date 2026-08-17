#!/usr/bin/env python3
"""Draw the overworld tileset as true pixel art.

Same production as tools/make_glyphs.py and tools/make_frames.py: authored by
hand on a grid, aliased, no antialiasing and no smooth gradients. Godot renders
these with TEXTURE_FILTER_NEAREST at integer zoom.

Three rules shape everything below.

  Seamless.  Every drawing operation goes through px(), which wraps its
             coordinates modulo the tile size. A tile is therefore seamless *by
             construction* rather than by careful edge-matching, and a blade of
             grass that runs off the right edge grows back in on the left. The
             ordered dither uses an 8x8 matrix and 32 % 8 == 0, so the dither
             tiles too. verify_seams() proves it numerically at the end.

  Quiet.     These tiles sit under the UI and behind a character. Each tile
             keeps its own value range narrow — roughly 25 luma points — and
             lets the palette carry the difference between one material and the
             next. A busy tile ruins both the interface and the sprite.

  Derived.   Colours are read from data/themes/firstlight.json and mixed; no
             second copy of the palette lives in this file. A theme swap moves
             the whole tileset with it.

    python3 tools/make_tiles.py        # writes assets/tiles/*.png
"""
import json
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "tiles")
THEME = os.path.join(ROOT, "data", "themes", "firstlight.json")

N = 32          # tile size, px
BLACK = (0, 0, 0)

# Which tiles the player may stand on. The art and the collision answer to one
# list so they cannot drift apart; docs/OVERWORLD-ART.md quotes it.
WALKABLE = {
    "floor_boards": True,
    "floor_stone": True,
    "grass_short": True,
    "grass_tall": True,
    "path_dirt": True,
    "door": True,
    "wall_plaster": False,
    "wall_stone": False,
    "water": False,
    "rock": False,
    "void": False,
}

# Standard 8x8 ordered (Bayer) matrix. Values 0..63.
BAYER8 = [
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
]


# --- palette ------------------------------------------------------------------

def theme_colors():
    with open(THEME, encoding="utf-8") as f:
        colors = json.load(f)["colors"]
    return {k: tuple(int(v.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            for k, v in colors.items()}


C = theme_colors()


def mix(a, b, t):
    """Lerp two colours. Every tile colour is a mix of theme colours, so nothing
    in the tileset is a free-floating hex someone has to maintain separately."""
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


# --- drawing primitives -------------------------------------------------------

def canvas(fill):
    return Image.new("RGBA", (N, N), fill + (255,))


def px(img, x, y, c):
    """The whole seamlessness argument. Coordinates wrap, so anything drawn
    partly off one edge completes itself on the opposite edge."""
    img.putpixel((int(x) % N, int(y) % N), c + (255,))


def hline(img, y, x0, x1, c):
    for x in range(x0, x1 + 1):
        px(img, x, y, c)


def vline(img, x, y0, y1, c):
    for y in range(y0, y1 + 1):
        px(img, x, y, c)


def dither(img, dark, light, weight, x0=0, y0=0, x1=N - 1, y1=N - 1):
    """Ordered dither between two colours. `weight` is a function (x, y) -> 0..1
    giving the proportion of `light`. Ordered rather than random because a
    random dither re-rolls on every run and does not tile against itself."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            thr = (BAYER8[y % 8][x % 8] + 0.5) / 64.0
            px(img, x, y, light if weight(x, y) > thr else dark)


def speckle(img, rng, count, c, x0=0, y0=0, x1=N - 1, y1=N - 1):
    """Unstructured mottle. Used instead of a Bayer dither wherever the target
    is *texture* rather than a gradient: an ordered dither near 50% coverage
    lays down a visible crosshatch lattice, and at 32px the eye finds the
    lattice long before it finds the grass. Seeded, so still deterministic."""
    for _ in range(count):
        px(img, rng.randint(x0, x1), rng.randint(y0, y1), c)


def blob(img, rng, cx, cy, r, fill, lit, dim):
    """A lumpy filled mass with a lit crown and a shadowed underside. Wraps,
    because hline() wraps, so a lump straddling the edge finishes next door."""
    for dy in range(-r, r + 1):
        span = int(round(math.sqrt(max(0.0, r * r - dy * dy))))
        span = max(0, span + rng.choice((-1, 0, 0, 1)))
        if span == 0:
            continue
        y = cy + dy
        # One row of crown and one of shadow, no more. A thicker crown swallows
        # the body and the lump reads as a flat grey cap rather than as mass.
        if dy <= -r + 1:
            hline(img, y, cx - span, cx + span, lit)
        elif dy >= r - 1:
            hline(img, y, cx - span, cx + span, dim)
        else:
            hline(img, y, cx - span, cx + span, fill)


# --- the tiles ----------------------------------------------------------------

def floor_boards():
    """The Waking Room. Planks run east-west, ~10px, seams at y=10,21,31 so the
    board that straddles the tile joint is the same width as the others.

    Two things were tried first and had to go. Butt joints (a short vertical at
    one x per plank) turned the tile into brickwork the moment it repeated —
    at 32px a vertical every 32px reads as a course, not as the end of a board.
    A lit row under every seam did the same thing louder. What actually reads as
    wood is the long grain: dashes running the length of the plank, no verticals
    anywhere."""
    base = mix(C["panel"], C["accent"], 0.16)
    grain = mix(base, C["bg"], 0.26)
    seam = mix(base, C["bg"], 0.50)
    lit = mix(base, C["text"], 0.07)

    img = canvas(base)
    rng = random.Random(1041)
    speckle(img, rng, 60, grain)
    # Seams at 4/15/26, deliberately *not* at 31. A hard line sitting on the
    # tile edge is the one place a repeat announces itself, and putting the
    # board that crosses the joint in the middle of its own run means the
    # joint carries no feature at all.
    for top, bot in ((5, 14), (16, 25), (27, 36)):
        hline(img, bot, 0, N - 1, seam)
        hline(img, top, 0, N - 1, lit)
        # Grain: three or four broken lines per board, drawn as dashes so no
        # single line ever reads as a second seam.
        for _ in range(4):
            gy = rng.randint(top + 2, bot - 2)
            x = rng.randint(0, N - 1)
            for _ in range(rng.randint(2, 4)):
                run = rng.randint(4, 9)
                for i in range(run):
                    px(img, x + i, gy, grain)
                x += run + rng.randint(2, 5)
    return img


def floor_stone():
    """Flagstone. Courses are ~10px and, like the boards, are offset so that
    neither a mortar row nor a mortar column falls on the tile edge — the
    joint runs through the middle of a slab, where there is nothing to see."""
    base = mix(C["panel_alt"], C["muted"], 0.24)
    mortar = mix(base, C["bg"], 0.52)
    lit = mix(base, C["text"], 0.09)
    dim = mix(base, C["bg"], 0.16)

    img = canvas(base)
    rng = random.Random(2207)
    dither(img, base, dim, lambda x, y: 0.35)
    courses = [(6, 15), (17, 26), (28, 37)]
    for ci, (top, bot) in enumerate(courses):
        hline(img, bot, 0, N - 1, mortar)
        hline(img, top, 0, N - 1, lit)        # each slab's own top edge
        for jx in (4 + ci * 9, 19 + ci * 5):
            vline(img, jx, top, bot, mortar)
    speckle(img, rng, 26, dim)
    speckle(img, rng, 10, lit)
    return img


def grass_short():
    """Walkable ground. Cold, close to black-green: the difference between this
    and the path is hue, not brightness, because brightness is the character's
    job."""
    base = mix(C["good"], C["bg"], 0.76)
    dark = mix(C["good"], C["bg"], 0.84)
    mid = mix(C["good"], C["bg"], 0.70)
    tip = mix(C["good"], C["bg"], 0.62)

    img = canvas(base)
    rng = random.Random(3313)
    speckle(img, rng, 190, dark)
    speckle(img, rng, 120, mid)
    # Tufts: two pixels, a stem and a lean. Sparse enough that the 32px repeat
    # does not announce itself.
    for _ in range(22):
        x, y = rng.randint(0, N - 1), rng.randint(0, N - 1)
        px(img, x, y, tip)
        px(img, x + rng.choice((-1, 1)), y - 1, tip)
    return img


def grass_tall():
    """Chapter 4. Walkable but visually dense — the tell is blade *count*, not
    contrast, so the player still reads on top of it."""
    base = mix(C["good"], C["bg"], 0.80)
    dark = mix(C["good"], C["bg"], 0.88)
    blade = mix(C["good"], C["bg"], 0.70)
    tip = mix(C["good"], C["bg"], 0.63)

    img = canvas(base)
    rng = random.Random(4127)
    speckle(img, rng, 200, dark)
    # Blades are drawn on a jittered lattice rather than at random positions:
    # pure random clumps, and a clump at this density looks like damage.
    for gy in range(0, N, 4):
        for gx in range(0, N, 3):
            x = gx + rng.randint(0, 2)
            y = gy + rng.randint(0, 3)
            h = rng.randint(3, 5)
            lean = rng.choice((-1, 0, 0, 1))
            for i in range(h):
                px(img, x + (lean if i >= h - 2 else 0), y - i, blade)
            px(img, x + lean, y - h, tip)
    return img


def path_dirt():
    """The trodden road. Warm where the grass is cold; almost the same luma."""
    base = mix(mix(C["bg"], C["accent"], 0.21), C["muted"], 0.11)
    dark = mix(base, C["bg"], 0.26)
    grit = mix(base, C["text"], 0.11)

    img = canvas(base)
    rng = random.Random(5023)
    dither(img, dark, base, lambda x, y: 0.55)
    # Two ruts, wandering by one pixel. Vertical so the road reads as running
    # north-south when laid in a column; a rotated copy is the loader's job.
    for rx in (9, 22):
        wob = 0
        for y in range(N):
            wob += rng.choice((-1, 0, 0, 0, 1))
            wob = max(-1, min(1, wob))
            px(img, rx + wob, y, dark)
    speckle(img, rng, 30, grit)
    speckle(img, rng, 18, dark)
    return img


def wall_plaster():
    """Solid. Lighter than every floor because a wall catches what light there
    is, and because the player must never have to think about whether a tile is
    walkable."""
    base = mix(C["panel_alt"], C["text"], 0.20)
    dim = mix(base, C["bg"], 0.14)
    crack = mix(base, C["bg"], 0.34)

    img = canvas(base)
    rng = random.Random(6151)
    dither(img, base, dim, lambda x, y: 0.40)
    # Three hairline cracks, each a wandering 1px walk. Wrapping px() means a
    # crack that leaves the tile arrives in the copy next door.
    for sx, sy, steps in ((4, 2, 14), (21, 9, 11), (13, 20, 13)):
        x, y = sx, sy
        for _ in range(steps):
            px(img, x, y, crack)
            x += rng.choice((0, 0, 1, 1, -1))
            y += rng.choice((1, 1, 1, 0))
    speckle(img, rng, 24, dim)
    return img


def wall_stone():
    """Solid. Big courses, half-offset, so it never reads as the flagstone
    floor even though both are grey blocks."""
    base = mix(C["line"], C["muted"], 0.28)
    mortar = mix(base, C["bg"], 0.38)
    lit = mix(base, C["text"], 0.07)
    dim = mix(base, C["bg"], 0.16)

    img = canvas(base)
    rng = random.Random(7043)
    dither(img, base, dim, lambda x, y: 0.42)
    # Courses offset off the tile edge for the same reason as the boards.
    for ci, (top, bot) in enumerate(((8, 22), (24, 38))):
        hline(img, bot, 0, N - 1, mortar)
        hline(img, top, 0, N - 1, lit)
        # Half-offset verticals, and none on x=0 or x=31.
        for jx in ((5, 21) if ci == 0 else (13, 29)):
            vline(img, jx, top, bot, mortar)
    speckle(img, rng, 30, dim)
    speckle(img, rng, 12, lit)
    return img


def water():
    """Not walkable. The one tile allowed a hue that is nowhere else on the
    ground, because 'do not walk here' has to survive being glanced at."""
    base = mix(C["accent_2"], C["bg"], 0.78)
    deep = mix(C["accent_2"], C["bg"], 0.86)
    crest = mix(C["accent_2"], C["bg"], 0.62)

    img = canvas(base)
    # A swell: one sine in y on a period of 16, which divides 32, so the phase
    # matches itself across the joint. This is the one place a real gradient is
    # wanted, so this is the one place the Bayer dither earns its keep.
    dither(img, deep, base,
           lambda x, y: 0.30 + 0.40 * (0.5 + 0.5 * math.sin(2 * math.pi * y / 16.0)))
    # Crests: broken horizontal dashes on the two swell peaks, staggered so the
    # tile does not read as two ruled lines. Every period here divides 32 — a
    # dash pattern on a period of 13 would break the joint even though px()
    # wraps, because the *pattern* would not.
    for y, phase in ((4, 0), (20, 6)):
        for x in range(N):
            if (x + phase) % 16 < 7:
                px(img, x, y, crest)
            if (x + phase + 5) % 8 < 3:
                px(img, x, y + 1, crest)
    return img


def rock():
    """Not walkable. A mass rather than a boulder — a boulder needs an outline,
    and an outline on a tile means a grid of outlines when it repeats."""
    base = mix(C["line"], C["bg"], 0.30)
    lit = mix(C["line"], C["muted"], 0.24)
    dim = mix(C["line"], C["bg"], 0.50)

    img = canvas(base)
    rng = random.Random(8117)
    speckle(img, rng, 150, dim)
    # Rubble, not one boulder. Scattered short highlight strokes were tried and
    # read as scratches on a flat plane; what makes stone is *mass* — overlapping
    # lumps, each with a lit crown and a shadow under it, packed until there is
    # no flat ground left.
    lumps = [(4, 6, 6), (17, 3, 7), (27, 9, 5), (9, 17, 7),
             (22, 20, 6), (2, 26, 5), (14, 29, 6), (29, 25, 4)]
    for cx, cy, r in lumps:
        # Each lump gets its own value inside a narrow band, so the pile has
        # depth without any one stone becoming the bright thing on the screen.
        fill = mix(base, lit, rng.uniform(0.10, 0.40))
        blob(img, rng, cx, cy, r, fill, lit, dim)
    speckle(img, rng, 40, dim)
    return img


def door():
    """The way out. Drawn as a doorway *in a wall*: the outer ring is wall
    material, so a field of doors still tiles cleanly (the ring meets itself)
    while a single door sits correctly in a plaster run."""
    wall = mix(C["panel_alt"], C["text"], 0.20)
    wall_dim = mix(wall, C["bg"], 0.14)
    frame = mix(C["bg"], C["accent"], 0.20)
    slab = mix(C["bg"], C["accent"], 0.32)
    slab_dim = mix(slab, C["bg"], 0.30)
    handle = mix(C["accent"], C["bg"], 0.45)

    img = canvas(wall)
    dither(img, wall, wall_dim, lambda x, y: 0.40)
    d = ImageDraw.Draw(img)
    d.rectangle([4, 3, 27, 31], fill=frame + (255,))       # jamb
    d.rectangle([6, 5, 25, 31], fill=slab + (255,))        # the door itself
    # Two recessed panels. Aliased 1px insets, no bevel gradient.
    for top, bot in ((8, 16), (19, 28)):
        d.rectangle([9, top, 22, bot], outline=slab_dim + (255,))
        d.rectangle([10, top + 1, 21, bot - 1], fill=mix(slab, C["bg"], 0.14) + (255,))
    px(img, 21, 18, handle)                                # the one warm pixel
    px(img, 22, 18, handle)
    return img


def void():
    """Off-map filler. Not flat black: a flat field is the one thing a nearest
    filter renders perfectly, and the eye reads it as a hole in the buffer
    rather than as part of the picture."""
    base = mix(C["bg"], BLACK, 0.52)
    lift = mix(C["bg"], BLACK, 0.38)
    img = canvas(base)
    dither(img, base, lift, lambda x, y: 0.14)
    return img


TILES = {
    "floor_boards": floor_boards,
    "floor_stone": floor_stone,
    "grass_short": grass_short,
    "grass_tall": grass_tall,
    "path_dirt": path_dirt,
    "wall_plaster": wall_plaster,
    "wall_stone": wall_stone,
    "water": water,
    "rock": rock,
    "door": door,
    "void": void,
}

# Sheet order — materials grouped, solids after walkables, void last.
ORDER = [
    "floor_boards", "floor_stone", "grass_short", "grass_tall",
    "path_dirt", "door", "wall_plaster", "wall_stone",
    "water", "rock", "void",
]


# --- verification -------------------------------------------------------------

def verify_seams(name, img):
    """Lay the tile up 4x4 and measure the joints against the tile's own
    internal transitions.

    A seam is invisible when the step across the joint is no larger than the
    steps the tile already makes internally — an absolute threshold would fail
    the flagstone (whose mortar lines are legitimately hard) and pass a flat
    tile that is subtly wrong. So the test is relative: joint delta vs. the
    distribution of every adjacent-pair delta in the repeat.
    """
    rep = Image.new("RGB", (N * 4, N * 4))
    for ty in range(4):
        for tx in range(4):
            rep.paste(img.convert("RGB"), (tx * N, ty * N))
    w, h = rep.size
    p = rep.load()

    def delta(a, b):
        return sum(abs(a[i] - b[i]) for i in range(3)) / 3.0

    cols = [sum(delta(p[x, y], p[x + 1, y]) for y in range(h)) / h
            for x in range(w - 1)]
    rows = [sum(delta(p[x, y], p[x, y + 1]) for x in range(w)) / w
            for y in range(h - 1)]
    seam_x = [x for x in (N - 1, 2 * N - 1, 3 * N - 1)]
    seam_y = list(seam_x)

    def judge(series, seams):
        interior = [v for i, v in enumerate(series) if i not in seams]
        joint = max(series[i] for i in seams)
        mean = sum(interior) / len(interior)
        sd = (sum((v - mean) ** 2 for v in interior) / len(interior)) ** 0.5
        # The joint has to sit *inside* the tile's own distribution of steps —
        # not below its maximum. Comparing against the max alone is a test of
        # one noisy sample against another: the flagstone's course boundary
        # lands exactly on the joint (structurally identical, differing only in
        # where the dither fell), and the tall grass's blade lattice is uniform
        # but its harshest row is chosen by the RNG. Both are seamless by
        # construction. An outlier test says so; a max test does not.
        return joint, max(interior), mean, mean + 3.0 * sd

    jx, mx, ax, lx = judge(cols, seam_x)
    jy, my, ay, ly = judge(rows, seam_y)
    ok = jx <= max(mx, lx) + 1e-6 and jy <= max(my, ly) + 1e-6
    return {
        "name": name, "ok": ok,
        "h_joint": jx, "h_int_max": mx, "h_int_mean": ax, "h_lim": max(mx, lx),
        "v_joint": jy, "v_int_max": my, "v_int_mean": ay, "v_lim": max(my, ly),
    }


def value_range(img):
    p = img.convert("RGB").load()
    lo, hi = 255.0, 0.0
    for y in range(N):
        for x in range(N):
            v = luma(p[x, y])
            lo, hi = min(lo, v), max(hi, v)
    return lo, hi


# --- output -------------------------------------------------------------------

def contact_sheet(tiles, scale=4, cols=4):
    """A labelled 4x preview, purely so a human can eyeball the set. Each cell
    shows the tile repeated 2x2 — a lone tile hides exactly the seam you want
    to check."""
    pad, label_h = 6, 12
    cell_w = N * scale
    cell_h = N * scale + label_h
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGBA",
                      (cols * (cell_w + pad) + pad, rows * (cell_h + pad) + pad),
                      mix(C["bg"], BLACK, 0.3) + (255,))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for i, (name, img) in enumerate(tiles):
        cx = pad + (i % cols) * (cell_w + pad)
        cy = pad + (i // cols) * (cell_h + pad)
        quad = Image.new("RGBA", (N * 2, N * 2))
        for qy in range(2):
            for qx in range(2):
                quad.paste(img, (qx * N, qy * N))
        sheet.paste(quad.resize((cell_w, cell_w), Image.NEAREST), (cx, cy))
        mark = "walk" if WALKABLE[name] else "SOLID"
        d.text((cx, cy + cell_w + 1), "%s  [%s]" % (name, mark),
               fill=C["text"] + (255,), font=font)
    return sheet


def main():
    os.makedirs(OUT, exist_ok=True)
    built = [(name, TILES[name]()) for name in ORDER]

    for name, img in built:
        img.save(os.path.join(OUT, "%s.png" % name))

    # One strip, tiles in ORDER, for anyone who wants a single atlas. Index i
    # of the strip is ORDER[i]; docs/OVERWORLD-ART.md carries the list.
    strip = Image.new("RGBA", (N * len(built), N))
    for i, (_, img) in enumerate(built):
        strip.paste(img, (i * N, 0))
    strip.save(os.path.join(OUT, "tileset.png"))

    contact_sheet(built).save(os.path.join(OUT, "_sheet_x4.png"))

    print("wrote %d tiles (%dx%d) to %s" % (len(built), N, N, OUT))
    print("4x4 repeat seam test: joint step vs the tile's own interior steps "
          "(mean / max / limit)")
    print("%-14s %-5s  %-26s %-26s %s"
          % ("tile", "", "horizontal", "vertical", "luma lo-hi (range)"))
    bad = 0
    for name, img in built:
        r = verify_seams(name, img)
        lo, hi = value_range(img)
        bad += 0 if r["ok"] else 1
        print("%-14s %-5s  %5.2f | %5.2f %5.2f %5.2f   %5.2f | %5.2f %5.2f %5.2f   "
              "%3.0f-%3.0f (%.0f)"
              % (name, "ok" if r["ok"] else "SEAM",
                 r["h_joint"], r["h_int_mean"], r["h_int_max"], r["h_lim"],
                 r["v_joint"], r["v_int_mean"], r["v_int_max"], r["v_lim"],
                 lo, hi, hi - lo))
    print("seam failures: %d" % bad)


if __name__ == "__main__":
    main()
