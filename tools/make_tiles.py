#!/usr/bin/env python3
"""Draw the overworld tileset as true pixel art.

Same production as tools/make_glyphs.py and tools/make_frames.py: authored by
hand on a grid, aliased, no antialiasing and no smooth gradients. Godot renders
these with TEXTURE_FILTER_NEAREST at integer zoom.

This file used to emit seventeen flat material squares. It now emits five sets,
all from the same palette and the same handful of generators:

  bases      25 materials, one 32x32 seamless fill each      -> tileset.png
  variants   2 alternates per material, chosen by hash(x,y)  -> tileset_var.png
  overlays   16 materials x (16 edge + 16 corner) x 3 seeds  -> overlays.png
  cliffs     16 elevation faces, lips and corners            -> cliffs.png
  props      50 objects that stand on the ground             -> props.png

Read docs/ART-DIRECTION-OVERWORLD.md before changing anything here; it is the
measured brief this file answers. The five rules that shape the code:

  Seamless.  Every *fill* operation goes through px(), which wraps its
             coordinates modulo the tile size. A fill is therefore seamless by
             construction rather than by careful edge-matching. verify_seams()
             proves it numerically at the end. Overlays, cliffs and props are
             not tiled against themselves and use pxa(), which clips.

  Organic.   A transition whose silhouette is a straight line moved half a tile
             is still a straight line. Every intrusion depth in this file comes
             from a seeded 1-D midpoint displacement pinned to the same depth at
             both ends of the run -- so lobes are irregular *and* continuous
             across cell boundaries -- plus detached scatter ahead of the front
             and bites taken out behind it. Inner corners are rounded, never
             mitred. There is no right angle anywhere in the overlay set.

  Quiet.     Each material keeps its own value range narrow -- 20 to 30 luma
             points -- and lets hue carry the difference between one material
             and the next. A busy tile ruins both the interface and the sprite.

  Ranged.    The *scene* is not quiet. Ground means are pulled down so the world
             sits dark like the backdrops do, and the recovered headroom is
             spent on three things only: prop crowns, cliff lips, and the
             character. SOLID materials sit a hard 12+ luma below the walkable
             ground they border -- that is a rule, not a preference, and it is
             checked and printed by verify_contrast().

  Derived.   Colours are read from data/themes/firstlight.json. No second copy
             of the palette lives in this file, and no material carries a hex.
             A material declares a hue source and a target luma; at_luma() does
             the rest. A theme swap moves the whole set with it.

    python3 tools/make_tiles.py        # writes assets/tiles/*
"""
import hashlib
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

VARIANTS = 3    # seeded alternates per overlay case
BASE_VARIANTS = 2   # alternate fills per material, beyond the base

# Standard 8x8 ordered (Bayer) matrix. Values 0..63. 32 % 8 == 0, so it tiles.
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
    """Lerp two colours. Every colour in the tileset is a mix of theme colours,
    so nothing here is a free-floating hex someone has to maintain separately."""
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


# The two ends of the value axis. Everything is graded between them, so the
# darks stay tinted with the app's background rather than going to dead black
# and the lights stay tinted with its text colour rather than going to paper.
DARK = mix(C["bg"], BLACK, 0.62)
LIGHT = C["text"]


def at_luma(hue, target):
    """Grade a hue to a target luma by mixing it toward DARK or LIGHT.

    This is the whole of the §2.6 re-grade. A material declares *what colour it
    is* and *how bright it is* separately, so the value structure of the scene
    is a table of numbers you can read in one place instead of forty hand-tuned
    mix() calls scattered through the file."""
    lh = luma(hue)
    if target <= lh:
        span = lh - luma(DARK)
        return hue if span <= 0.01 else mix(hue, DARK, (lh - target) / span)
    span = luma(LIGHT) - lh
    return hue if span <= 0.01 else mix(hue, LIGHT, (target - lh) / span)


def rng_for(*keys):
    """Deterministic RNG from a key. Python hashes strings with a per-process
    salt, so seeding from hash() would break byte-identical re-runs."""
    h = hashlib.md5("|".join(str(k) for k in keys).encode("utf-8")).hexdigest()
    return random.Random(int(h[:12], 16))


def hashv(*keys):
    h = hashlib.md5("|".join(str(k) for k in keys).encode("utf-8")).hexdigest()
    return int(h[:8], 16)


# --- the material table -------------------------------------------------------
#
# One row per material. `hue` says what colour it is, `mean` how bright, and
# `spread` how much internal contrast it is allowed. Everything downstream --
# fills, overlays, cliffs, props -- reads its colours from here, so the whole
# value structure of the world is this one table.
#
# The `mean` column is the §2.6 re-grade in full. Compare with what shipped:
# grass 54 -> 42, forest 50 -> 24, sand 73 -> 62, snow 80 -> 74. Ground medians
# fall; solids fall much further; the recovered headroom above 90 belongs to
# prop crowns, cliff lips and the character, and nothing else may spend it.
#
# SOLID materials must sit >= 12 luma below every walkable material they can
# border. verify_contrast() checks it against ADJACENCY and prints the margins.

def _hue(*pairs):
    """Blend theme colours by weight. Written this way so a material's hue is a
    readable sentence -- 'good, a fifth of the way to accent_2' -- rather than
    an opaque nested mix()."""
    out = pairs[0][0]
    acc = pairs[0][1]
    for col, w in pairs[1:]:
        acc += w
        out = mix(out, col, w / acc)
    return out


MATERIALS = {
    # name              hue                                       mean spread walk family
    "floor_boards":  dict(hue=_hue((C["accent"], 1.0), (C["panel"], 0.9)), mean=42, spread=20, walk=True,  family="boards"),
    "floor_stone":   dict(hue=_hue((C["panel_alt"], 1.0), (C["muted"], 0.55)), mean=46, spread=22, walk=True,  family="paving"),
    "grass_short":   dict(hue=_hue((C["good"], 1.0), (C["warn"], 0.22)), mean=42, spread=18, walk=True,  family="turf"),
    "grass_tall":    dict(hue=_hue((C["good"], 1.0), (C["accent_2"], 0.16)), mean=34, spread=20, walk=True,  family="blades"),
    "path_dirt":     dict(hue=_hue((C["accent"], 1.0), (C["muted"], 0.85)), mean=46, spread=18, walk=True,  family="trodden"),
    "door":          dict(hue=_hue((C["accent"], 1.0), (C["warn"], 0.4)), mean=58, spread=52, walk=True,  family="doorway"),
    "wall_plaster":  dict(hue=_hue((C["panel_alt"], 1.0), (C["accent"], 0.30)), mean=26, spread=18, walk=False, family="plaster"),
    "wall_stone":    dict(hue=_hue((C["line"], 1.0), (C["accent_2"], 0.12)), mean=22, spread=20, walk=False, family="blocks"),
    "water":         dict(hue=_hue((C["accent_2"], 1.0),), mean=26, spread=22, walk=False, family="swell"),
    "rock":          dict(hue=_hue((C["line"], 1.0), (C["muted"], 0.30)), mean=26, spread=24, walk=False, family="rubble"),
    "void":          dict(hue=_hue((C["bg"], 1.0),), mean=8,  spread=6,  walk=False, family="void"),
    "sand":          dict(hue=_hue((C["accent"], 1.0), (C["muted"], 0.55)), mean=62, spread=20, walk=True,  family="grain"),
    "scree":         dict(hue=_hue((C["line"], 1.0), (C["muted"], 0.50)), mean=38, spread=22, walk=True,  family="chips"),
    "snow":          dict(hue=_hue((C["muted"], 1.0), (C["accent_2"], 0.55)), mean=74, spread=22, walk=True,  family="drift"),
    "bridge":        dict(hue=_hue((C["accent"], 1.0), (C["panel"], 0.7)), mean=44, spread=22, walk=True,  family="planks"),
    "forest":        dict(hue=_hue((C["good"], 1.0), (C["accent_2"], 0.22)), mean=24, spread=22, walk=False, family="canopy"),
    "roof":          dict(hue=_hue((C["accent"], 1.0), (C["danger"], 0.45)), mean=30, spread=22, walk=False, family="shingle"),
    # --- appended for the concentric-biome world. Ids 17..24, nothing renumbered.
    "ocean":         dict(hue=_hue((C["accent_2"], 1.0), (C["line"], 0.9)), mean=15, spread=16, walk=False, family="swell"),
    "dune":          dict(hue=_hue((C["accent"], 1.0), (C["warn"], 0.8), (C["muted"], 0.25)), mean=68, spread=20, walk=True,  family="grain"),
    "hardpan":       dict(hue=_hue((C["accent"], 1.0), (C["danger"], 0.55)), mean=50, spread=20, walk=True,  family="cracked"),
    "jungle":        dict(hue=_hue((C["good"], 1.0), (C["warn"], 0.55)), mean=20, spread=24, walk=False, family="canopy"),
    "undergrowth":   dict(hue=_hue((C["good"], 1.0), (C["warn"], 0.75)), mean=36, spread=22, walk=True,  family="blades"),
    "mud":           dict(hue=_hue((C["accent"], 1.0), (C["line"], 1.3)), mean=30, spread=16, walk=True,  family="silt"),
    "cliff":         dict(hue=_hue((C["line"], 1.0), (C["accent_2"], 0.18)), mean=22, spread=26, walk=False, family="strata"),
    "ice":           dict(hue=_hue((C["accent_2"], 1.0), (C["muted"], 0.45)), mean=66, spread=24, walk=True,  family="sheet"),
}

# Sheet index IS the id stored in the world grid, so this order is load-bearing:
# appending is safe, reordering silently rewrites every map ever generated.
# tools/make_world.py parses this list out of this file; keep it a flat literal.
ORDER = [
    "floor_boards", "floor_stone", "grass_short", "grass_tall",
    "path_dirt", "door", "wall_plaster", "wall_stone",
    "water", "rock", "void",
    "sand", "scree", "snow", "bridge", "forest", "roof",
    "ocean", "dune", "hardpan", "jungle", "undergrowth", "mud", "cliff", "ice",
]

# Which tiles the player may stand on. Derived from MATERIALS so the art and the
# collision answer to one source and cannot drift apart; the contact sheet
# labels each cell from it and docs/OVERWORLD-ART.md quotes it.
WALKABLE = {name: MATERIALS[name]["walk"] for name in ORDER}

# The precedence stack of §2.1. A cell draws its own fill, then every
# HIGHER-ranked material among its eight neighbours overlays it, lowest first.
# Because the overlays compose in a fixed total order, three- and four-way
# junctions resolve for free with no per-triple art. This is a *look* ordering,
# not an elevation ordering: it says which material's edge wins when two meet.
# Rank 0 never needs an edge set, so the overlay atlas holds ranks 1..16.
# make_world.py may parse this the same way it parses ORDER; keep it flat.
PRECEDENCE = [
    "ocean", "water", "ice", "mud", "sand", "dune", "hardpan", "snow",
    "scree", "grass_short", "grass_tall", "undergrowth", "forest", "jungle",
    "rock", "cliff", "path_dirt",
]
RANK = {name: i for i, name in enumerate(PRECEDENCE)}
OVERLAY_MATS = PRECEDENCE[1:]           # everything that owns an edge set

# Which pairs actually meet in the world. Used only by verify_contrast() to
# check the solid-vs-walkable rule where it matters rather than everywhere.
ADJACENCY = [
    ("grass_short", "forest"), ("grass_tall", "forest"), ("path_dirt", "forest"),
    ("sand", "forest"), ("grass_short", "scree"), ("scree", "rock"),
    ("snow", "rock"), ("scree", "cliff"), ("snow", "cliff"), ("grass_short", "cliff"),
    ("sand", "water"), ("water", "ocean"), ("mud", "water"), ("dune", "water"),
    ("undergrowth", "jungle"), ("mud", "jungle"), ("path_dirt", "jungle"),
    ("floor_boards", "wall_plaster"), ("floor_stone", "wall_stone"),
    ("floor_stone", "roof"), ("path_dirt", "roof"), ("grass_short", "roof"),
    ("dune", "hardpan"), ("hardpan", "cliff"), ("ice", "cliff"),
]


def ramp(name):
    """The six values a material is drawn with. Extremes are used sparsely, so
    the *effective* internal range is about 1.4x spread -- 25 to 32 points --
    which is the 'quiet' rule of §2.6 point 1, unchanged."""
    m = MATERIALS[name]
    h, u, s = m["hue"], m["mean"], m["spread"]
    return {
        "deep": at_luma(h, max(4.0, u - s * 0.95)),
        "dark": at_luma(h, u - s * 0.50),
        "base": at_luma(h, u),
        "mid": at_luma(h, u + s * 0.22),
        "lit": at_luma(h, u + s * 0.52),
        "tip": at_luma(h, u + s * 0.88),
    }


R = {name: ramp(name) for name in MATERIALS}

# One shadow colour for the whole game, at one alpha. Everything that stands on
# the ground -- props, cliff faces, canopy overhangs -- casts this and nothing
# else, so shadows read as one light source rather than as decoration. Two
# alpha values exist in the whole output, 255 and this; there is no soft edge
# anywhere and nearest filtering stays lossless.
SHADOW = mix(C["bg"], BLACK, 0.45)
SHADOW_A = 118


# --- drawing primitives -------------------------------------------------------

def canvas(fill):
    return Image.new("RGBA", (N, N), tuple(fill) + (255,))


def px(img, x, y, c):
    """The whole seamlessness argument. Coordinates wrap, so anything drawn
    partly off one edge completes itself on the opposite edge. Fills only."""
    img.putpixel((int(x) % N, int(y) % N), tuple(c) + (255,))


def pxa(img, x, y, c, a=255):
    """Clipping put, for anything that is not tiled against itself: overlays,
    cliff pieces and props."""
    x, y = int(x), int(y)
    if 0 <= x < img.size[0] and 0 <= y < img.size[1]:
        img.putpixel((x, y), tuple(c) + (a,))


def hline(img, y, x0, x1, c):
    for x in range(int(x0), int(x1) + 1):
        px(img, x, y, c)


def vline(img, x, y0, y1, c):
    for y in range(int(y0), int(y1) + 1):
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


def voronoi(rng, k, jitter=0.55):
    """Toroidal Voronoi labels over the tile. Toroidal, so the cells wrap and
    the tile stays seamless; irregular, because §1.4 measured that continuous
    straight mortar lines are a *wall* convention and are why the town and the
    summit currently read as brickwork you are standing on."""
    step = N / math.sqrt(k)
    seeds = []
    gy = 0.0
    while gy < N:
        gx = 0.0
        while gx < N:
            seeds.append((gx + rng.uniform(0, step) * jitter + step * 0.25,
                          gy + rng.uniform(0, step) * jitter + step * 0.25))
            gx += step
        gy += step
    lab = [[0] * N for _ in range(N)]
    for y in range(N):
        for x in range(N):
            best, bi = 1e9, 0
            for i, (sx, sy) in enumerate(seeds):
                dx = abs(x + 0.5 - sx)
                dy = abs(y + 0.5 - sy)
                dx = min(dx, N - dx)
                dy = min(dy, N - dy)
                d = dx * dx + dy * dy
                if d < best:
                    best, bi = d, i
            lab[y][x] = bi
    return lab, len(seeds)


def edges_of(lab):
    """Cells of a label map that touch a different label, toroidally."""
    out = set()
    for y in range(N):
        for x in range(N):
            a = lab[y][x]
            if (lab[y][(x + 1) % N] != a or lab[(y + 1) % N][x] != a
                    or lab[y][(x - 1) % N] != a or lab[(y - 1) % N][x] != a):
                out.add((x, y))
    return out


# --- material fills -----------------------------------------------------------
#
# One function per *family*, not per tile. `sand` and `dune` are the same grain
# generator at different grades; `forest` and `jungle` are the same canopy;
# `water` and `ocean` the same swell. That is what makes twenty-five materials
# cost eighteen functions, and it is the same argument that makes 1,536
# overlays cost one mask generator.

def f_boards(name, v, r, rng):
    """The Waking Room. Planks run east-west, ~10px, seams offset off the tile
    edge so the joint carries no feature at all.

    Butt joints and lit rows under every seam were both tried and both turned
    the tile into brickwork the moment it repeated. What reads as wood is the
    long grain: dashes running the length of the plank, no verticals anywhere."""
    img = canvas(r["base"])
    speckle(img, rng, 60, r["dark"])
    off = (0, 3, 6)[v]
    for top, bot in ((5 + off, 14 + off), (16 + off, 25 + off), (27 + off, 36 + off)):
        hline(img, bot, 0, N - 1, r["deep"])
        hline(img, top, 0, N - 1, r["mid"])
        for _ in range(4):
            gy = rng.randint(top + 2, bot - 2)
            x = rng.randint(0, N - 1)
            for _ in range(rng.randint(2, 4)):
                run = rng.randint(4, 9)
                for i in range(run):
                    px(img, x + i, gy, r["dark"])
                x += run + rng.randint(2, 5)
    return img


def f_paving(name, v, r, rng):
    """Flagstone, redrawn. §1.4: horizontal courses with unbroken mortar lines
    are a *wall* convention, and drawn that way the summit read as a brick wall
    the player was standing on. Top-down paving is irregular polygonal slabs
    with broken joints and no continuous straight line anywhere, so this is a
    toroidal Voronoi with a per-slab value jitter."""
    img = canvas(r["base"])
    lab, k = voronoi(rng, 11 + v)
    tone = [rng.uniform(-0.5, 0.6) for _ in range(k)]
    joint = edges_of(lab)
    for y in range(N):
        for x in range(N):
            t = tone[lab[y][x]]
            c = mix(r["base"], r["lit"] if t > 0 else r["dark"], abs(t))
            px(img, x, y, c)
    for (x, y) in joint:
        px(img, x, y, r["deep"])
    # A single lit pixel on the north-west shoulder of each slab. One light
    # source, stated once, is what stops paving reading as a flat grey field.
    for (x, y) in joint:
        if lab[y][(x - 1) % N] != lab[y][x] and lab[(y - 1) % N][x] != lab[y][x]:
            px(img, x + 1, y + 1, r["mid"])
    speckle(img, rng, 22, r["dark"])
    return img


def f_turf(name, v, r, rng):
    """Walkable ground. Cold, close to black-green: the difference between this
    and the path is hue, not brightness, because brightness belongs to the
    character and to the things standing on the ground."""
    img = canvas(r["base"])
    speckle(img, rng, 190, r["dark"])
    speckle(img, rng, 120, r["mid"])
    speckle(img, rng, 40, r["deep"])
    for _ in range(20 + v * 4):
        x, y = rng.randint(0, N - 1), rng.randint(0, N - 1)
        px(img, x, y, r["lit"])
        px(img, x + rng.choice((-1, 1)), y - 1, r["lit"])
    return img


def f_blades(name, v, r, rng):
    """Tall grass and jungle undergrowth. Walkable but visually dense -- the
    tell is blade *count*, not contrast, so the player still reads on top of
    it. Blades sit on a jittered lattice rather than at random positions: pure
    random clumps, and a clump at this density looks like damage."""
    img = canvas(r["base"])
    speckle(img, rng, 200, r["dark"])
    for gy in range(0, N, 4):
        for gx in range(0, N, 3):
            x = gx + rng.randint(0, 2)
            y = gy + rng.randint(0, 3)
            h = rng.randint(3, 5)
            lean = rng.choice((-1, 0, 0, 1))
            for i in range(h):
                px(img, x + (lean if i >= h - 2 else 0), y - i, r["mid"])
            px(img, x + lean, y - h, r["lit"])
    return img


def f_trodden(name, v, r, rng):
    """The trodden road. Warm where the grass is cold, and a step lighter --
    §2.6 point 5, the road and the roof used to differ by 0.7 luma."""
    img = canvas(r["base"])
    dither(img, r["dark"], r["base"], lambda x, y: 0.55)
    for rx in (9 + v * 2, 22 - v):
        wob = 0
        for y in range(N):
            wob += rng.choice((-1, 0, 0, 0, 1))
            wob = max(-1, min(1, wob))
            px(img, rx + wob, y, r["deep"])
            px(img, rx + wob + 1, y, r["dark"])
    speckle(img, rng, 34, r["lit"])
    speckle(img, rng, 22, r["dark"])
    return img


def f_plaster(name, v, r, rng):
    """Interior wall. SOLID, and now *darker* than the floor it abuts rather
    than lighter. §2.6 point 6 wins over the old 'a wall catches the light'
    rule: the player must never have to think about whether a tile is walkable,
    and dark-means-you-cannot-go-there is the convention the rest of the world
    now uses for water, forest and rock."""
    img = canvas(r["base"])
    dither(img, r["base"], r["dark"], lambda x, y: 0.40)
    for sx, sy, steps in ((4, 2, 14), (21, 9, 11), (13, 20, 13)):
        x, y = sx + v, sy
        for _ in range(steps):
            px(img, x, y, r["deep"])
            x += rng.choice((0, 0, 1, 1, -1))
            y += rng.choice((1, 1, 1, 0))
    speckle(img, rng, 24, r["dark"])
    speckle(img, rng, 10, r["mid"])
    return img


def f_blocks(name, v, r, rng):
    """Stone wall. SOLID. Big courses, half-offset, so it never reads as the
    flagstone floor even though both are grey blocks -- and the flagstone is no
    longer coursed at all, which does most of that work now."""
    img = canvas(r["base"])
    dither(img, r["base"], r["dark"], lambda x, y: 0.42)
    for ci, (top, bot) in enumerate(((8, 22), (24, 38))):
        hline(img, bot, 0, N - 1, r["deep"])
        hline(img, top, 0, N - 1, r["mid"])
        for jx in ((5 + v, 21 + v) if ci == 0 else (13 - v, 29 - v)):
            vline(img, jx, top, bot, r["deep"])
    speckle(img, rng, 30, r["dark"])
    speckle(img, rng, 12, r["mid"])
    return img


def f_swell(name, v, r, rng):
    """Water. SOLID. The one family allowed a hue that is nowhere else on the
    ground, because 'do not walk here' has to survive being glanced at.

    A sine in y on a period of 16, which divides 32, so the phase matches
    itself across the joint. This is the one place a real gradient is wanted,
    so this is the one place the Bayer dither earns its keep."""
    img = canvas(r["base"])
    ph = v * 5
    dither(img, r["deep"], r["base"],
           lambda x, y: 0.30 + 0.40 * (0.5 + 0.5 * math.sin(2 * math.pi * (y + ph) / 16.0)))
    for y, phase in ((4 + ph, 0), (20 + ph, 6)):
        for x in range(N):
            # Every period here divides 32. A dash pattern on a period of 13
            # would break the joint even though px() wraps, because the
            # *pattern* would not.
            if (x + phase) % 16 < 7:
                px(img, x, y, r["lit"])
            if (x + phase + 5) % 8 < 3:
                px(img, x, y + 1, r["mid"])
    return img


def f_rubble(name, v, r, rng):
    """Rock. SOLID. A mass rather than a boulder -- a boulder needs an outline,
    and an outline on a tile means a grid of outlines when it repeats."""
    img = canvas(r["base"])
    speckle(img, rng, 150, r["deep"])
    lumps = [(4, 6, 6), (17, 3, 7), (27, 9, 5), (9, 17, 7),
             (22, 20, 6), (2, 26, 5), (14, 29, 6), (29, 25, 4)]
    for cx, cy, rr in lumps:
        fill = mix(r["base"], r["mid"], rng.uniform(0.10, 0.50))
        blob(img, rng, cx + v, cy - v, rr, fill, r["lit"], r["deep"])
    speckle(img, rng, 40, r["deep"])
    return img


def f_chips(name, v, r, rng):
    """Scree. Walkable, and the ground the foothills are made of. Rock's cousin:
    same hue, less mass, more ground showing, and 12 luma points lighter so the
    boundary between what you may climb and what you may not is legible."""
    img = canvas(r["base"])
    dither(img, r["dark"], r["base"], lambda x, y: 0.4)
    for _ in range(46):
        x, y = rng.randrange(N), rng.randrange(N)
        n = rng.randint(2, 3)
        for i in range(n):
            px(img, x + i, y + (i >> 1), r["mid"] if rng.random() < 0.6 else r["deep"])
    speckle(img, rng, 40, r["dark"])
    speckle(img, rng, 12, r["lit"])
    return img


def f_drift(name, v, r, rng):
    """Snow. The brightest ground in the game and still narrow-range -- a white
    tile is a hole in a dark game, and the character has to stay 20 points
    above whatever he is standing on."""
    img = canvas(r["base"])
    dither(img, r["dark"], r["base"], lambda x, y: 0.30)
    for _ in range(14):
        y, x = rng.randrange(N), rng.randrange(N)
        run = rng.randint(5, 11)
        for i in range(run):
            px(img, x + i, y + (1 if i > run // 2 else 0), r["lit"])
    speckle(img, rng, 26, r["dark"])
    return img


def f_grain(name, v, r, rng):
    """Sand and dune. Warm like the road but paler and finer, so a beach never
    reads as a path you are meant to follow."""
    img = canvas(r["base"])
    dither(img, r["dark"], r["base"], lambda x, y: 0.35)
    for y in range(2 + v, N, 5):
        wob = 0
        for x in range(N):
            wob += rng.choice((-1, 0, 0, 0, 1))
            wob = max(-1, min(1, wob))
            px(img, x, y + wob, r["dark"])
            if rng.random() < 0.25:
                px(img, x, y + wob - 1, r["lit"])
    speckle(img, rng, 70, r["mid"])
    return img


def f_cracked(name, v, r, rng):
    """Desert hardpan. Baked clay in polygons -- the same Voronoi as the paving,
    but the joints are the cracks rather than the mortar and the plates are
    flat, which is the whole difference between a made surface and a dried one."""
    img = canvas(r["base"])
    lab, k = voronoi(rng, 7 + v, jitter=0.9)
    tone = [rng.uniform(-0.35, 0.35) for _ in range(k)]
    for y in range(N):
        for x in range(N):
            px(img, x, y, mix(r["base"], r["lit"] if tone[lab[y][x]] > 0 else r["dark"],
                              abs(tone[lab[y][x]])))
    for (x, y) in edges_of(lab):
        px(img, x, y, r["deep"])
    speckle(img, rng, 50, r["dark"])
    speckle(img, rng, 20, r["mid"])
    return img


def f_silt(name, v, r, rng):
    """Swamp mud. Walkable, dark, and wet: the sheen is two or three short
    horizontal highlights, not a gradient."""
    img = canvas(r["base"])
    speckle(img, rng, 220, r["dark"])
    speckle(img, rng, 60, r["deep"])
    for _ in range(9):
        x, y = rng.randrange(N), rng.randrange(N)
        for i in range(rng.randint(3, 6)):
            px(img, x + i, y, r["mid"])
    for _ in range(5):
        x, y = rng.randrange(N), rng.randrange(N)
        rr = rng.randint(2, 3)
        for dy in range(-rr, rr + 1):
            sp = int(math.sqrt(max(0, rr * rr - dy * dy)))
            hline(img, y + dy, x - sp, x + sp, r["deep"])
        hline(img, y - rr, x - 1, x + 1, r["lit"])
    return img


def f_sheet(name, v, r, rng):
    """Ice. Walkable and bright. Fractured plates with a lit rim on the
    north-west side of each -- the same one light source as everything else."""
    img = canvas(r["base"])
    lab, k = voronoi(rng, 5 + v, jitter=0.8)
    tone = [rng.uniform(-0.4, 0.5) for _ in range(k)]
    for y in range(N):
        for x in range(N):
            px(img, x, y, mix(r["base"], r["lit"] if tone[lab[y][x]] > 0 else r["dark"],
                              abs(tone[lab[y][x]])))
    for (x, y) in edges_of(lab):
        px(img, x, y, r["dark"])
        if lab[y][(x - 1) % N] != lab[y][x] or lab[(y - 1) % N][x] != lab[y][x]:
            px(img, x, y, r["tip"])
    speckle(img, rng, 18, r["mid"])
    return img


def f_strata(name, v, r, rng):
    """Bare mountain rock. SOLID. Banded rather than lumpy, because a mountain
    is bedding planes and scree is loose stone, and the two have to be
    distinguishable at a glance from the top of a phone."""
    img = canvas(r["base"])
    speckle(img, rng, 120, r["deep"])
    y = -3 + v
    while y < N:
        h = rng.randint(4, 7)
        wob = 0
        for x in range(N):
            wob += rng.choice((-1, 0, 0, 0, 1))
            wob = max(-2, min(2, wob))
            for i in range(h):
                px(img, x, y + wob + i, r["dark"] if i < h - 1 else r["deep"])
            px(img, x, y + wob, r["mid"])
        y += h
    speckle(img, rng, 50, r["deep"])
    speckle(img, rng, 16, r["lit"])
    return img


def f_canopy(name, v, r, rng):
    """Forest and jungle canopy seen from above. SOLID -- you walk round a wood,
    not through it, and after the re-grade you can see that you do: forest sits
    18 luma below the grass it borders, against 5.1 before.

    Drawn as crowns rather than as trees: at 32px a trunk is one pixel and reads
    as dirt. What says 'wood' from above is overlapping rounded masses with the
    light on the same side of every one, packed until no floor shows -- a gap
    between crowns reads as a clearing you ought to be able to walk into."""
    img = canvas(r["deep"])
    speckle(img, rng, 90, r["dark"])
    crowns = [(5, 5, 6), (18, 4, 7), (28, 8, 6), (10, 15, 7),
              (23, 18, 6), (3, 24, 6), (15, 27, 7), (29, 27, 5)]
    for cx, cy, rr in crowns:
        fill = mix(r["base"], r["mid"], rng.uniform(0.0, 0.35))
        blob(img, rng, cx + v * 2, cy - v, rr, fill, r["lit"], r["deep"])
    speckle(img, rng, 40, r["deep"])
    speckle(img, rng, 14, r["tip"])
    return img


def f_shingle(name, v, r, rng):
    """A building seen from above. SOLID, and now warm-saturated where the road
    is warm-desaturated: the two used to differ by 0.7 luma and were the same
    colour, so the town read as one continuous brown surface."""
    img = canvas(r["base"])
    speckle(img, rng, 60, r["dark"])
    for y in range(3 + v, N + v, 6):
        hline(img, y, 0, N - 1, r["deep"])
        hline(img, y - 1, 0, N - 1, r["lit"])
        offset = 0 if (y // 6) % 2 == 0 else 5
        for x in range(offset, N + offset, 10):
            for i in range(5):
                px(img, x, y - i, r["deep"])
    return img


def f_planks(name, v, r, rng):
    """Bridge. Walkable -- the one way across, so it has to read as deliberate
    construction rather than as debris."""
    img = canvas(r["base"])
    speckle(img, rng, 40, r["dark"])
    for y in range(v, N + v, 5):
        hline(img, y, 0, N - 1, r["deep"])
        hline(img, y + 1, 0, N - 1, r["lit"])
    for x in (0, 1, N - 2, N - 1):
        vline(img, x, 0, N - 1, r["deep"])
    return img


def f_void(name, v, r, rng):
    """Off-map filler. Not flat black: a flat field is the one thing a nearest
    filter renders perfectly, and the eye reads it as a hole in the buffer
    rather than as part of the picture."""
    img = canvas(r["base"])
    dither(img, r["base"], r["mid"], lambda x, y: 0.14)
    return img


def f_doorway(name, v, r, rng):
    """The way out, and deliberately the brightest thing in any interior. Drawn
    as a doorway *in a wall*: the outer ring is wall material, so a field of
    doors still tiles cleanly while a single door sits correctly in a run of
    plaster."""
    w = R["wall_plaster"]
    img = canvas(w["base"])
    dither(img, w["base"], w["dark"], lambda x, y: 0.40)
    d = ImageDraw.Draw(img)
    d.rectangle([4, 3, 27, 31], fill=tuple(r["dark"]) + (255,))
    d.rectangle([6, 5, 25, 31], fill=tuple(r["base"]) + (255,))
    for top, bot in ((8, 16), (19, 28)):
        d.rectangle([9, top, 22, bot], outline=tuple(r["deep"]) + (255,))
        d.rectangle([10, top + 1, 21, bot - 1], fill=tuple(r["mid"]) + (255,))
    hline(img, 4, 5, 26, r["tip"])          # the lintel catches the light
    px(img, 21, 18, r["tip"])
    px(img, 22, 18, r["tip"])
    return img


FAMILIES = {
    "boards": f_boards, "paving": f_paving, "turf": f_turf, "blades": f_blades,
    "trodden": f_trodden, "plaster": f_plaster, "blocks": f_blocks,
    "swell": f_swell, "rubble": f_rubble, "chips": f_chips, "drift": f_drift,
    "grain": f_grain, "cracked": f_cracked, "silt": f_silt, "sheet": f_sheet,
    "strata": f_strata, "canopy": f_canopy, "shingle": f_shingle,
    "planks": f_planks, "void": f_void, "doorway": f_doorway,
}

_FILL_CACHE = {}


def fill(name, v=0):
    """The 32x32 seamless texture for a material. Cached, and the *same* image
    is what the overlay set composites through its masks -- which is what makes
    the texture continue across a transition instead of restarting at the cell
    boundary."""
    key = (name, v)
    if key not in _FILL_CACHE:
        m = MATERIALS[name]
        _FILL_CACHE[key] = FAMILIES[m["family"]](name, v, R[name], rng_for("fill", name, v))
    return _FILL_CACHE[key]


# --- the overlay set ----------------------------------------------------------
#
# §2.1: 16 edge transitions plus 16 corner transitions cover all 256 eight-
# neighbour cases with 32 shapes, because they are drawn in two passes instead
# of one. Times 16 materials that own an edge set, times 3 seeded variants
# chosen by hash(x,y) so a shoreline does not repeat every 32 pixels.
#
#   1536 tiles. Nobody draws 1536 of anything -- there is one mask generator
#   here and one short 'how this material finishes' table, and that is the
#   entire authored surface.
#
# SIDES  bit 0 N, 1 E, 2 S, 3 W       -- the neighbours holding the overlay
# CORNRS bit 0 NE, 1 SE, 2 SW, 3 NW   -- diagonals whose two sides are unset
#
# THE ORGANIC RULE, which is the whole point of the file.
#
# An intrusion whose front is a straight line is a straight line whether it sits
# on the cell boundary or six pixels inside it. So no front here is a line and
# none is an arc. Every one is a 1-D midpoint displacement -- fractal, lobed,
# self-similar at two scales -- *pinned to the same depth d0 at both ends of its
# run*. The pinning is what makes it legal: two adjacent cells along the same
# shoreline may hold different variants and the silhouette still joins, because
# every variant leaves and arrives at d0. Between the pins it is free to push a
# lobe eighteen pixels into the neighbouring cell or pull back to two.
#
# Three further devices, and the compositions in _comp_*.png are the evidence
# that they are what actually kills the right angle:
#
#   scatter  detached pixels of the material ahead of its own front, thinning
#            with distance. This is the single biggest silhouette-breaker at
#            3x -- it turns an outline into a gradient of belonging.
#   bites    pixels removed just behind the front, so the front is not a clean
#            fill boundary either.
#   corner   where two sides of the overlay meet, a rounded lobe is added over
#   rounding the re-entrant right angle the union would otherwise leave. Inner
#            corners are the place a Wang set announces itself; this is the fix.

SIDE_BITS = ("N", "E", "S", "W")
CORNER_BITS = ("NE", "SE", "SW", "NW")

# Where a corner sits, and which way it opens. (corner x, corner y, ux, uy)
# in continuous tile coordinates.
CORNER_GEOM = {
    "NE": (N, 0, -1, 1),
    "SE": (N, N, -1, -1),
    "SW": (0, N, 1, -1),
    "NW": (0, 0, 1, 1),
}

# How each material finishes. d0 is the pinned depth at every run end; amp the
# first displacement, which sets lobe size; dmax the deepest a tongue may reach.
# `lip` is the two- or three-pixel treatment that makes sand read as *beach* and
# grass as *turf* instead of as a coloured region, and `tall` says whether the
# material stands high enough to throw a shadow onto the ground south and east
# of it. Seventeen lines. This is the per-material half of §2.1's "one generator
# plus seven short functions", and it turned out to want a table, not functions.
OVERLAY_STYLE = {
    "water":       dict(d0=5, amp=6.0, dmax=15, scatter=0.30, bite=0.20, lip="foam",  tall=False),
    "ice":         dict(d0=4, amp=5.0, dmax=13, scatter=0.14, bite=0.10, lip="rim",   tall=False),
    "mud":         dict(d0=5, amp=6.5, dmax=16, scatter=0.34, bite=0.24, lip="wet",   tall=False),
    "sand":        dict(d0=6, amp=7.0, dmax=18, scatter=0.42, bite=0.22, lip="foam",  tall=False),
    "dune":        dict(d0=6, amp=7.5, dmax=18, scatter=0.46, bite=0.24, lip="grain", tall=False),
    "hardpan":     dict(d0=5, amp=6.0, dmax=15, scatter=0.24, bite=0.18, lip="crack", tall=False),
    "snow":        dict(d0=5, amp=6.0, dmax=16, scatter=0.34, bite=0.20, lip="drift", tall=False),
    "scree":       dict(d0=4, amp=6.5, dmax=17, scatter=0.55, bite=0.30, lip="chip",  tall=True),
    "grass_short": dict(d0=5, amp=6.5, dmax=17, scatter=0.44, bite=0.22, lip="blade", tall=False),
    "grass_tall":  dict(d0=5, amp=7.0, dmax=18, scatter=0.50, bite=0.24, lip="blade", tall=True),
    "undergrowth": dict(d0=5, amp=7.0, dmax=18, scatter=0.50, bite=0.24, lip="blade", tall=True),
    "forest":      dict(d0=6, amp=8.0, dmax=19, scatter=0.30, bite=0.16, lip="crown", tall=True),
    "jungle":      dict(d0=6, amp=8.5, dmax=20, scatter=0.34, bite=0.16, lip="crown", tall=True),
    "rock":        dict(d0=5, amp=7.5, dmax=18, scatter=0.48, bite=0.28, lip="rag",   tall=True),
    "cliff":       dict(d0=5, amp=7.0, dmax=18, scatter=0.40, bite=0.26, lip="rag",   tall=True),
    "path_dirt":   dict(d0=5, amp=6.0, dmax=15, scatter=0.38, bite=0.26, lip="verge", tall=False),
}


def displaced(key, ends, amp, n, lo, hi, persistence=0.58):
    """1-D midpoint displacement, pinned at both ends. The fractal is what makes
    the front read as a coastline rather than as a wave: big lobes carrying
    smaller lobes carrying single-pixel roughness, all from one recursion."""
    rng = rng_for(key)
    f = [0.0] * (n + 1)
    f[0] = f[n] = float(ends)
    step, a = n, float(amp)
    while step > 1:
        half = step // 2
        for i in range(half, n, step):
            f[i] = 0.5 * (f[i - half] + f[i + half]) + rng.uniform(-a, a)
        step, a = half, a * persistence
    return [max(lo, min(hi, int(round(t)))) for t in f]


def side_profile(mat, side, variant):
    s = OVERLAY_STYLE[mat]
    return displaced(("side", mat, side, variant), s["d0"], s["amp"], N, 1, s["dmax"])


def corner_profile(mat, corner, variant, scale=1.0):
    """Radial depth around a corner, pinned to d0 on both axes so it meets the
    edge overlays the neighbouring cells draw along the same boundary."""
    s = OVERLAY_STYLE[mat]
    return displaced(("corner", mat, corner, variant, scale),
                     s["d0"] * scale, s["amp"] * 0.7, 16, 1, s["dmax"])


def _side_cells(side, prof):
    out = set()
    for t in range(N):
        d = prof[t]
        for k in range(d):
            if side == "N":
                out.add((t, k))
            elif side == "S":
                out.add((t, N - 1 - k))
            elif side == "W":
                out.add((k, t))
            else:
                out.add((N - 1 - k, t))
    return out


def _side_front(side, prof, t):
    """The pixel at the front of the run at position t, and the outward step."""
    d = prof[t]
    if side == "N":
        return (t, d - 1), (0, 1)
    if side == "S":
        return (t, N - d), (0, -1)
    if side == "W":
        return (d - 1, t), (1, 0)
    return (N - d, t), (-1, 0)


def _corner_cells(corner, prof):
    cx, cy, ux, uy = CORNER_GEOM[corner]
    out = set()
    for y in range(N):
        for x in range(N):
            u = (x + 0.5 - cx) * ux
            v = (y + 0.5 - cy) * uy
            if u < 0 or v < 0:
                continue
            d = math.hypot(u, v)
            if d > max(prof) + 1:
                continue
            th = math.atan2(v, u) / (math.pi / 2) * 16.0
            i = max(0, min(15, int(th)))
            fr = th - i
            rr = prof[i] * (1 - fr) + prof[i + 1] * fr
            if d <= rr:
                out.add((x, y))
    return out


def mask_region(mat, kind, mask, variant):
    """The set of pixels this overlay covers. `kind` is 'edge' or 'corner'."""
    s = OVERLAY_STYLE[mat]
    rng = rng_for("region", mat, kind, mask, variant)
    parts = {}
    if kind == "edge":
        for b, side in enumerate(SIDE_BITS):
            if mask & (1 << b):
                parts[side] = _side_cells(side, side_profile(mat, side, variant))
        # Round every re-entrant corner where two runs meet. Without this the
        # union of two bands leaves a 90-degree notch, and a notch is exactly
        # the artefact the owner is describing when he says the walking view is
        # a bunch of disjoint right angles.
        for corner in CORNER_BITS:
            a, b = corner[0], corner[1]
            side_a = {"N": "N", "S": "S"}[a]
            side_b = {"E": "E", "W": "W"}[b]
            if (mask & (1 << SIDE_BITS.index(side_a))) and (mask & (1 << SIDE_BITS.index(side_b))):
                parts["c" + corner] = _corner_cells(
                    corner, corner_profile(mat, corner, variant, scale=1.9))
    else:
        for b, corner in enumerate(CORNER_BITS):
            if mask & (1 << b):
                parts["c" + corner] = _corner_cells(
                    corner, corner_profile(mat, corner, variant))
    core = set()
    for p in parts.values():
        core |= p

    # Scatter ahead of the front and bites out of it. Applied per run, so the
    # roughness follows the silhouette instead of dusting the whole tile.
    add, sub = set(), set()
    if kind == "edge":
        for b, side in enumerate(SIDE_BITS):
            if not (mask & (1 << b)):
                continue
            prof = side_profile(mat, side, variant)
            for t in range(N):
                (fx, fy), (dx, dy) = _side_front(side, prof, t)
                p = s["scatter"]
                for k in range(1, 5):
                    p *= 0.62
                    if rng.random() < p:
                        add.add((fx + dx * k, fy + dy * k))
                if rng.random() < s["bite"]:
                    sub.add((fx, fy))
                    if rng.random() < 0.35:
                        sub.add((fx - dx, fy - dy))
    else:
        for b, corner in enumerate(CORNER_BITS):
            if not (mask & (1 << b)):
                continue
            cx, cy, ux, uy = CORNER_GEOM[corner]
            prof = corner_profile(mat, corner, variant)
            for i in range(24):
                th = (i + 0.5) / 24.0 * (math.pi / 2)
                a = th / (math.pi / 2) * 16.0
                j = max(0, min(15, int(a)))
                fr = a - j
                rr = prof[j] * (1 - fr) + prof[j + 1] * fr
                p = s["scatter"]
                for k in range(1, 5):
                    p *= 0.62
                    if rng.random() < p:
                        x = int(cx + ux * (rr + k) * math.cos(th))
                        y = int(cy + uy * (rr + k) * math.sin(th))
                        add.add((x, y))
                if rng.random() < s["bite"]:
                    sub.add((int(cx + ux * (rr - 1) * math.cos(th)),
                             int(cy + uy * (rr - 1) * math.sin(th))))

    region = set()
    for (x, y) in core:
        if (x, y) in sub:
            # A bite only bites where a single run owns the pixel. Chewing a
            # hole out of the middle of a junction would leave a floating
            # island of the material underneath.
            owners = sum(1 for p in parts.values() if (x, y) in p)
            if owners < 2:
                continue
        region.add((x, y))
    for (x, y) in add:
        if 0 <= x < N and 0 <= y < N:
            region.add((x, y))
    return region


def _outside_is_material(mat, kind, mask, x, y):
    """Whether the cell beyond the tile edge at (x, y) holds this material.
    Used so the overlay does not draw a bright lip along the boundary it shares
    with its own kind -- that boundary is interior, and a lip there would ring
    every transition with a 32px highlight."""
    d0 = OVERLAY_STYLE[mat]["d0"]
    if kind == "edge":
        if y < 0:
            return bool(mask & 1)
        if x >= N:
            return bool(mask & 2)
        if y >= N:
            return bool(mask & 4)
        if x < 0:
            return bool(mask & 8)
        return False
    ne, se, sw, nw = (mask & 1), (mask & 2), (mask & 4), (mask & 8)
    if y < 0:
        return bool((ne and x >= N - d0) or (nw and x < d0))
    if y >= N:
        return bool((se and x >= N - d0) or (sw and x < d0))
    if x < 0:
        return bool((nw and y < d0) or (sw and y >= N - d0))
    if x >= N:
        return bool((ne and y < d0) or (se and y >= N - d0))
    return False


def overlay_tile(mat, kind, mask, variant):
    """One overlay sprite: the material's own seamless texture, cut to an
    organic mask, finished with a lip and -- if it stands tall enough -- a hard
    contact shadow thrown south and east onto whatever is underneath.

    The texture is the *same* 32x32 fill the full tile uses, at the same phase,
    so grass spilling into sand is continuous with the grass next door instead
    of restarting at the cell boundary. That is Factorio's shared-mask trick
    (FFF #214) and it is why 1,536 sprites cost one function."""
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    if mask == 0:
        return img
    s = OVERLAY_STYLE[mat]
    r = R[mat]
    region = mask_region(mat, kind, mask, variant)
    src = fill(mat, 0).load()
    for (x, y) in region:
        c = src[x, y]
        img.putpixel((x, y), (c[0], c[1], c[2], 255))

    def inside(x, y):
        if 0 <= x < N and 0 <= y < N:
            return (x, y) in region
        return _outside_is_material(mat, kind, mask, x, y)

    rng = rng_for("finish", mat, kind, mask, variant)
    lip = s["lip"]
    shadow_depth = 3 if lip in ("crown", "rag") else 2
    steps = ((0, -1, "N"), (1, 0, "E"), (0, 1, "S"), (-1, 0, "W"))
    for (x, y) in sorted(region):
        outs = [t for t in steps if not inside(x + t[0], y + t[1])]
        if not outs:
            continue
        dark_side = any(t[2] in ("S", "E") for t in outs)
        lit_side = not dark_side

        if lip == "blade":
            pxa(img, x, y, r["lit"] if lit_side else r["dark"])
            # Blades break the outline on every side. Grass does not end; it
            # thins out, and the thinning is what stops the boundary reading as
            # a cut.
            for dx, dy, _d in outs:
                if rng.random() < 0.42:
                    for k in range(1, rng.randint(2, 4)):
                        pxa(img, x + dx * k, y + dy * k, r["tip"] if k == 1 else r["mid"])
        elif lip == "crown":
            pxa(img, x, y, r["mid"] if lit_side else r["deep"])
        elif lip == "foam":
            # The most-looked-at edge in the game. A bright broken line at the
            # water's edge, a second line of spray beyond it, and a band of wet
            # material behind -- which is three cheap pixels and the whole
            # difference between 'a beach' and 'where the sand region stops'.
            pxa(img, x, y, r["tip"])
            for dx, dy, _d in outs:
                if rng.random() < 0.34:
                    pxa(img, x + dx * 2, y + dy * 2, r["tip"])
            if rng.random() < 0.5:
                dx, dy, _d = outs[0]
                pxa(img, x - dx * 2, y - dy * 2, r["dark"])
        elif lip == "grain":
            pxa(img, x, y, r["lit"] if lit_side else r["dark"])
        elif lip == "drift":
            pxa(img, x, y, r["tip"] if lit_side else r["lit"])
        elif lip == "chip":
            pxa(img, x, y, r["mid"] if rng.random() < 0.55 else r["deep"])
        elif lip == "rag":
            pxa(img, x, y, r["mid"] if lit_side else r["deep"])
        elif lip == "rim":
            pxa(img, x, y, r["tip"] if lit_side else r["dark"])
        elif lip == "wet":
            pxa(img, x, y, r["mid"] if lit_side else r["deep"])
        elif lip == "verge":
            if rng.random() < 0.45:
                pxa(img, x, y, r["mid"] if lit_side else r["dark"])
        elif lip == "crack":
            pxa(img, x, y, r["deep"])

        if s["tall"] and dark_side:
            for dx, dy, d in outs:
                if d not in ("S", "E"):
                    continue
                for k in range(1, shadow_depth + 1):
                    nx, ny = x + dx * k, y + dy * k
                    if 0 <= nx < N and 0 <= ny < N and (nx, ny) not in region:
                        if img.getpixel((nx, ny))[3] == 0:
                            img.putpixel((nx, ny), tuple(SHADOW) + (SHADOW_A,))
    return img


# The overlay atlas. 16 columns; row = slot*6 + variant*2 + kind, where slot is
# the material's rank minus one (rank 0 is the bottom of the stack and never
# needs an edge set), kind is 0 for edge and 1 for corner.
OVERLAY_COLS = 16
OVERLAY_ROWS_PER_MAT = VARIANTS * 2


def overlay_row(mat, variant, kind):
    return (RANK[mat] - 1) * OVERLAY_ROWS_PER_MAT + variant * 2 + kind


def build_overlays():
    rows = len(OVERLAY_MATS) * OVERLAY_ROWS_PER_MAT
    atlas = Image.new("RGBA", (OVERLAY_COLS * N, rows * N), (0, 0, 0, 0))
    tiles = {}
    for mat in OVERLAY_MATS:
        for variant in range(VARIANTS):
            for ki, kind in enumerate(("edge", "corner")):
                row = overlay_row(mat, variant, ki)
                for mask in range(16):
                    t = overlay_tile(mat, kind, mask, variant)
                    tiles[(mat, kind, mask, variant)] = t
                    atlas.paste(t, (mask * N, row * N))
    return atlas, tiles, rows


# --- the reference renderer ---------------------------------------------------
#
# This is what a consumer has to do, written once here so the previews are
# produced by the *same* algorithm the game will run rather than by a
# hand-arranged mock-up. If a composition in _comp_*.png looks right, the rule
# below is what made it look right, and porting it to GDScript is a
# transliteration.

def overlay_plan(grid, x, y, seed=0):
    """The draw list for one cell: its own fill, then every higher-precedence
    material among its eight neighbours, lowest first.

    Returns [] for a cell that needs no overlay -- which the shipped map
    measured at 91.1% of them, mean 1.18 draws per cell."""
    h, w = len(grid), len(grid[0])

    def at(cx, cy):
        return grid[max(0, min(h - 1, cy))][max(0, min(w - 1, cx))]

    me = grid[y][x]
    if me not in RANK:
        return []
    mine = RANK[me]
    sides = {"N": at(x, y - 1), "E": at(x + 1, y), "S": at(x, y + 1), "W": at(x - 1, y)}
    diags = {"NE": at(x + 1, y - 1), "SE": at(x + 1, y + 1),
             "SW": at(x - 1, y + 1), "NW": at(x - 1, y - 1)}
    higher = sorted({m for m in list(sides.values()) + list(diags.values())
                     if m in RANK and RANK[m] > mine}, key=lambda m: RANK[m])
    plan = []
    for mat in higher:
        side = 0
        for b, d in enumerate(SIDE_BITS):
            if sides[d] == mat:
                side |= 1 << b
        corner = 0
        for b, d in enumerate(CORNER_BITS):
            # A corner bit only counts when neither of its two adjacent sides
            # already carries the material; otherwise the edge pass has covered
            # it and a second draw would double the lip.
            if diags[d] == mat and sides[d[0]] != mat and sides[d[1]] != mat:
                corner |= 1 << b
        v = hashv("ov", x, y, mat, seed) % VARIANTS
        if side:
            plan.append((mat, "edge", side, v))
        if corner:
            plan.append((mat, "corner", corner, v))
    return plan


def render_patch(grid, tiles, seed=0, props=None, zoom=1):
    """Draw a rectangle of the world exactly as the game must."""
    h, w = len(grid), len(grid[0])
    img = Image.new("RGBA", (w * N, h * N), (0, 0, 0, 255))
    for y in range(h):
        for x in range(w):
            v = hashv("base", x, y, seed) % (1 + BASE_VARIANTS)
            img.paste(fill(grid[y][x], v), (x * N, y * N))
    for y in range(h):
        for x in range(w):
            for (mat, kind, mask, v) in overlay_plan(grid, x, y, seed):
                img.alpha_composite(tiles[(mat, kind, mask, v)], (x * N, y * N))
    if props:
        for (px_, py_, sprite) in sorted(props, key=lambda p: (p[1], p[0])):
            img.alpha_composite(sprite, (px_ * N + N // 2 - PROP_W // 2,
                                         py_ * N + N - PROP_H))
    if zoom > 1:
        img = img.resize((img.size[0] * zoom, img.size[1] * zoom), Image.NEAREST)
    return img


# --- deterministic value noise, for the preview compositions only -------------

def _lat(seed, ix, iy):
    return (hashv("lat", seed, ix, iy) % 100000) / 100000.0


def vnoise(seed, x, y, freq):
    fx, fy = x * freq, y * freq
    ix, iy = int(math.floor(fx)), int(math.floor(fy))
    tx, ty = fx - ix, fy - iy
    tx = tx * tx * (3 - 2 * tx)
    ty = ty * ty * (3 - 2 * ty)
    a = _lat(seed, ix, iy) * (1 - tx) + _lat(seed, ix + 1, iy) * tx
    b = _lat(seed, ix, iy + 1) * (1 - tx) + _lat(seed, ix + 1, iy + 1) * tx
    return a * (1 - ty) + b * ty


def fbm(seed, x, y, freq, octaves=3):
    tot, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        tot += vnoise(seed + o * 977, x, y, freq * (2 ** o)) * amp
        norm += amp
        amp *= 0.5
    return tot / norm


# --- props --------------------------------------------------------------------
#
# §1.1 measured that half of all screens in this game show one texture repeated
# fifty-seven times and that the room the player wakes up in has no bed. That is
# the biggest fault in the document and it is not a tile problem. This is the
# fix.
#
# ANCHORING, which is the contract the world generator and the renderer share:
#
#   Every prop lives in a fixed 64 x 96 slot -- two tiles wide, three tall.
#   Its ANCHOR is the bottom-centre of that slot, (32, 96), and the anchor is
#   placed at the bottom-centre of the prop's BASE CELL. So to draw prop p
#   standing in cell (cx, cy):
#
#       dst_x = cx * 32 + 16 - 32          (= cx * 32 - 16)
#       dst_y = cy * 32 + 32 - 96          (= cy * 32 - 64)
#
#   Art therefore extends upward and outward from the base cell freely and
#   never affects collision. COLLISION IS THE FOOTPRINT ONLY -- `foot` cells
#   anchored at the base cell, 1x1 unless the table says otherwise. A tree is
#   solid where its trunk is; you walk behind its crown. Y-sort on the base
#   cell's bottom edge.
#
#   The contact shadow is baked into the sprite, centred under the base, at the
#   one shadow colour and the one alpha the rest of the file uses. Centred, not
#   offset: a scattered prop lands anywhere, including one cell from a cliff,
#   and an offset shadow will sooner or later fall across something it should
#   not (Slynyrd, Pixelblog 44). Anything authored in position -- buildings,
#   cliffs -- offsets south-east instead.

PROP_W, PROP_H = 64, 96
PROP_AX, PROP_AY = PROP_W // 2, PROP_H          # the anchor, in slot coords
OUTLINE = mix(C["bg"], BLACK, 0.55)


def mkramp(hue, mean, spread):
    return {
        "deep": at_luma(hue, max(4.0, mean - spread * 0.95)),
        "dark": at_luma(hue, mean - spread * 0.50),
        "base": at_luma(hue, mean),
        "mid": at_luma(hue, mean + spread * 0.22),
        "lit": at_luma(hue, mean + spread * 0.52),
        "tip": at_luma(hue, mean + spread * 0.88),
    }


# Prop palettes. Props are where the value headroom recovered in §2.6 gets
# spent: a lit crown reaches 110-135 against a ground plane whose mean is 24-46,
# so an object reads as an object at a glance and at arm's length.
PP = {
    "wood":    mkramp(_hue((C["accent"], 1.0), (C["line"], 1.2)), 40, 30),
    "bark":    mkramp(_hue((C["accent"], 1.0), (C["line"], 2.0)), 30, 26),
    "leaf":    mkramp(_hue((C["good"], 1.0), (C["accent_2"], 0.25)), 46, 44),
    "leaf_dry": mkramp(_hue((C["good"], 1.0), (C["warn"], 1.1)), 46, 42),
    "palm":    mkramp(_hue((C["good"], 1.0), (C["warn"], 0.5)), 44, 42),
    "pine":    mkramp(_hue((C["good"], 1.0), (C["accent_2"], 0.5)), 38, 40),
    "stone":   mkramp(_hue((C["line"], 1.0), (C["muted"], 0.6)), 42, 40),
    "pale":    mkramp(_hue((C["muted"], 1.0), (C["accent_2"], 0.3)), 62, 40),
    "cloth":   mkramp(_hue((C["danger"], 1.0), (C["accent"], 0.4)), 48, 40),
    "metal":   mkramp(_hue((C["muted"], 1.0), (C["accent_2"], 0.6)), 52, 44),
    "gold":    mkramp(C["accent"], 72, 52),
    "ice":     mkramp(_hue((C["accent_2"], 1.0), (C["text"], 0.4)), 74, 42),
    "flower":  mkramp(C["warn"], 78, 46),
    "bloom":   mkramp(C["danger"], 66, 44),
    "fungus":  mkramp(_hue((C["danger"], 1.0), (C["muted"], 0.5)), 58, 44),
    "reed":    mkramp(_hue((C["good"], 1.0), (C["warn"], 1.6)), 42, 40),
}


def prop_canvas():
    return Image.new("RGBA", (PROP_W, PROP_H), (0, 0, 0, 0))


def pp_(img, dx, dy, c, a=255):
    """Put a pixel in prop space: dx right of the anchor, dy *up* from it."""
    pxa(img, PROP_AX + int(dx), PROP_AY - 1 - int(dy), c, a)


def pdisc(img, dx, dy, r, c, squash=1.0, rng=None):
    for j in range(-int(r * squash) - 1, int(r * squash) + 2):
        span = r * math.sqrt(max(0.0, 1.0 - (j / (r * squash)) ** 2)) if r * squash > 0 else 0
        span = int(round(span))
        if rng is not None:
            span += rng.choice((-1, 0, 0, 1))
        for i in range(-span, span + 1):
            pp_(img, dx + i, dy + j, c)


def pbox(img, x0, y0, x1, y1, c):
    for y in range(int(y0), int(y1) + 1):
        for x in range(int(x0), int(x1) + 1):
            pp_(img, x, y, c)


def pshadow(img, rw, rh=None):
    """The one contact shadow: flat, hard-edged, aliased, one colour, centred
    under the base. Not a soft blur -- that is not this game's language and it
    would not survive nearest filtering."""
    rh = rh if rh is not None else max(2, int(rw * 0.38))
    for j in range(-rh, rh + 1):
        span = int(round(rw * math.sqrt(max(0.0, 1.0 - (j / float(rh)) ** 2))))
        for i in range(-span, span + 1):
            # Under, never over: the shadow only fills pixels the object and its
            # outline have not already claimed.
            sx, sy = PROP_AX + i, PROP_AY - 1 - (j + rh - 1)
            if 0 <= sx < PROP_W and 0 <= sy < PROP_H and img.getpixel((sx, sy))[3] == 0:
                img.putpixel((sx, sy), tuple(SHADOW) + (SHADOW_A,))


def poutline(img):
    """A hard rim in near-black around every opaque pixel. The character has one
    and it is what keeps him legible over any tile; props need it for the same
    reason, and it is what lets a prop sit on grass and on snow without being
    redrawn for each."""
    w, h = img.size
    src = img.load()
    edge = []
    for y in range(h):
        for x in range(w):
            if src[x, y][3] == 255:
                continue
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and src[nx, ny][3] == 255 \
                        and src[nx, ny][:3] != tuple(OUTLINE):
                    edge.append((x, y))
                    break
    for (x, y) in edge:
        img.putpixel((x, y), tuple(OUTLINE) + (255,))
    return img


# --- prop builders ------------------------------------------------------------
#
# Sixteen builders, fifty props. Same argument as the overlay set: parameterise
# the thing that repeats (a mass with a lit crown and a dark underside) and
# spend the words on the handful of objects that are actually different.
# Light is from the north-west in every one of them, without exception -- one
# stated light source is most of what "depth" means in a 2-D scene.

def b_tree(img, rng, p):
    """Broadleaf: a trunk you can see the bottom of, and a crown of overlapping
    masses. The trunk matters -- it is what says the prop is standing on the
    ground rather than floating over it."""
    bark, leaf = PP[p.get("bark", "bark")], PP[p["pal"]]
    th, cr = p["trunk"], p["crown"]
    hw = p.get("tw", 2)
    for dy in range(th + 2):
        for dx in range(-hw, hw + 1):
            c = bark["lit"] if dx <= -hw + 1 else (bark["deep"] if dx >= hw else bark["base"])
            pp_(img, dx, dy, c)
    cy = th + cr - 1
    lumps = [(0, 0, cr), (-cr * 0.6, cr * 0.35, cr * 0.72), (cr * 0.62, cr * 0.2, cr * 0.7),
             (-cr * 0.25, cr * 0.85, cr * 0.6), (cr * 0.3, -cr * 0.5, cr * 0.62)]
    for (ox, oy, rr) in lumps[:p.get("lumps", 5)]:
        pdisc(img, ox, cy + oy, rr, leaf["base"], rng=rng)
    for (ox, oy, rr) in lumps[:p.get("lumps", 5)]:
        pdisc(img, ox - rr * 0.28, cy + oy + rr * 0.30, rr * 0.55, leaf["lit"], rng=rng)
        pdisc(img, ox + rr * 0.45, cy + oy - rr * 0.45, rr * 0.34, leaf["deep"], rng=rng)
    for _ in range(p.get("tips", 10)):
        a = rng.uniform(0, math.tau)
        pp_(img, math.cos(a) * cr * 0.8, cy + math.sin(a) * cr * 0.8 + cr * 0.2, leaf["tip"])
    return int(cr * 0.9)


def b_pine(img, rng, p):
    """Conifer: stacked tiers, each one pixel proud of the one above on the
    lit side. Reads as a cone at 32px where a disc does not."""
    bark, leaf = PP["bark"], PP[p["pal"]]
    th, tiers, w0 = p["trunk"], p["tiers"], p["w"]
    for dy in range(th + 3):
        for dx in range(-1, 2):
            pp_(img, dx, dy, bark["lit"] if dx < 0 else bark["dark"])
    y = th
    for t in range(tiers):
        w = int(w0 * (1.0 - t / float(tiers)) + 2)
        hgt = p.get("th", 7)
        for j in range(hgt):
            span = int(w * (1.0 - j / float(hgt)))
            for i in range(-span, span + 1):
                c = leaf["base"]
                if i < -span + 2:
                    c = leaf["lit"]
                elif i > span - 2:
                    c = leaf["deep"]
                pp_(img, i, y + j, c)
        for i in range(-w, w + 1, 3):
            pp_(img, i + rng.choice((-1, 0, 1)), y - 1, leaf["deep"])
        pp_(img, -w + 1, y + 1, leaf["tip"])
        y += hgt - 2
    return w0


def b_palm(img, rng, p):
    """Desert and shore. A leaning trunk and six drooping fronds; the lean is
    the whole silhouette, so it is deliberate rather than random."""
    bark, leaf = PP["wood"], PP[p["pal"]]
    th = p["trunk"]
    lean = p.get("lean", 5)
    for dy in range(th):
        dx = lean * (dy / float(th)) ** 2
        for k in (-1, 0, 1):
            pp_(img, dx + k, dy, bark["lit"] if k < 0 else (bark["deep"] if k > 0 else bark["base"]))
        if dy % 3 == 0:
            pp_(img, dx - 1, dy, bark["deep"])
    tx, ty = lean, th
    for i in range(p.get("fronds", 6)):
        a = math.pi * (0.12 + 0.76 * i / float(p.get("fronds", 6) - 1))
        for s in range(p.get("flen", 13)):
            fx = tx + math.cos(a) * s
            fy = ty + math.sin(a) * s * 0.55 - (s * s) * 0.035
            pp_(img, fx, fy, leaf["base"])
            pp_(img, fx, fy + 1, leaf["lit"] if math.cos(a) < 0 else leaf["deep"])
            if s % 2 == 0:
                pp_(img, fx, fy - 1, leaf["deep"])
    for k in range(3):
        pp_(img, tx - 1 + k, ty + 1, PP["gold"]["base"])
    return 7


def b_bush(img, rng, p):
    pal = PP[p["pal"]]
    r = p["r"]
    pdisc(img, 0, r - 1, r, pal["base"], squash=0.85, rng=rng)
    pdisc(img, -r * 0.35, r * 0.55, r * 0.5, pal["lit"], rng=rng)
    pdisc(img, r * 0.4, r * 0.6, r * 0.38, pal["deep"], rng=rng)
    for _ in range(p.get("tips", 8)):
        a = rng.uniform(0, math.tau)
        pp_(img, math.cos(a) * r * 0.85, (r - 1) + math.sin(a) * r * 0.7, pal["tip"])
    for _ in range(p.get("berries", 0)):
        a = rng.uniform(0, math.tau)
        pp_(img, math.cos(a) * r * 0.6, (r - 1) + math.sin(a) * r * 0.5, PP["bloom"]["lit"])
    return int(r * 0.95)


def b_boulder(img, rng, p):
    """A stone with a face. Three tones and a hard top edge; the flat lit plane
    on top is what makes it a solid rather than a stain on the ground."""
    pal = PP[p["pal"]]
    w, h = p["w"], p["h"]
    for dy in range(h):
        t = dy / float(h)
        span = int(w * math.sqrt(max(0.0, 1.0 - (t * 0.85) ** 2))) + rng.choice((-1, 0, 0))
        for dx in range(-span, span + 1):
            u = (dx + span) / float(2 * span + 1)
            c = pal["base"]
            if u < 0.30:
                c = pal["mid"]
            elif u > 0.72:
                c = pal["deep"]
            if t > 0.80:
                c = pal["lit"] if u < 0.55 else pal["mid"]
            pp_(img, dx, dy, c)
    for _ in range(p.get("cracks", 3)):
        x, y = rng.randint(-w // 2, w // 2), rng.randint(1, h - 2)
        for _ in range(rng.randint(2, 5)):
            pp_(img, x, y, pal["deep"])
            x += rng.choice((-1, 0, 1))
            y -= 1
    return int(w * 0.95)


def b_tuft(img, rng, p):
    """Scatter filler. Half of the props in the world are these, and they are
    what turns fifty-seven identical squares into ground."""
    pal = PP[p["pal"]]
    for i in range(p["n"]):
        x = rng.randint(-p["spread"], p["spread"])
        h = rng.randint(p["h"] - 2, p["h"] + 2)
        lean = rng.choice((-1, 0, 0, 1))
        for j in range(h):
            pp_(img, x + (lean if j > h - 3 else 0), j, pal["base"] if j < h - 2 else pal["lit"])
        pp_(img, x + lean, h, pal["tip"])
    return p["spread"] + 1


def b_flowers(img, rng, p):
    pal, bl = PP["leaf"], PP[p["pal"]]
    for i in range(p["n"]):
        x = rng.randint(-p["spread"], p["spread"])
        h = rng.randint(4, 7)
        for j in range(h):
            pp_(img, x, j, pal["base"])
        pp_(img, x, h, bl["base"])
        pp_(img, x - 1, h, bl["lit"])
        pp_(img, x + 1, h, bl["dark"])
        pp_(img, x, h + 1, bl["tip"])
    return p["spread"] + 1


def b_log(img, rng, p):
    """Fallen. Lies along the ground, so it is wide and low and its shadow is
    the widest thing about it."""
    pal = PP[p["pal"]]
    w, r = p["w"], p["r"]
    for dx in range(-w, w + 1):
        for dy in range(r * 2):
            c = pal["base"]
            if dy > r + 1:
                c = pal["lit"]
            elif dy < r - 1:
                c = pal["deep"]
            pp_(img, dx, dy + 1, c)
    for dy in range(r * 2):
        pp_(img, -w, dy + 1, pal["mid"])
        pp_(img, -w + 1, dy + 1, pal["dark"] if dy % 3 else pal["deep"])
    for _ in range(p.get("moss", 0)):
        x = rng.randint(-w + 2, w - 1)
        pp_(img, x, r * 2, PP["leaf"]["dark"])
        pp_(img, x + 1, r * 2, PP["leaf"]["base"])
    return w + 1


def b_stump(img, rng, p):
    pal = PP["bark"]
    r = p["r"]
    for dy in range(p["h"]):
        for dx in range(-r, r + 1):
            pp_(img, dx, dy, pal["lit"] if dx < -r + 2 else (pal["deep"] if dx > r - 2 else pal["base"]))
    for dx in range(-r, r + 1):
        span = int(math.sqrt(max(0.0, 1.0 - (dx / float(r)) ** 2)) * 3)
        for dy in range(-span, span + 1):
            pp_(img, dx, p["h"] + dy, PP["wood"]["lit"] if abs(dy) < 2 else PP["wood"]["mid"])
    for k in range(-1, 2):
        pp_(img, k, p["h"], PP["wood"]["dark"])
    return r + 1


def b_post(img, rng, p):
    """Fencepost, waymarker, signpost. Vertical, thin, and tall enough to break
    the horizon of the tile it stands in."""
    pal = PP[p.get("pal", "wood")]
    h = p["h"]
    for dy in range(h):
        pp_(img, -1, dy, pal["lit"])
        pp_(img, 0, dy, pal["base"])
        pp_(img, 1, dy, pal["deep"])
    if p.get("board"):
        bw, bh = p["board"]
        for dy in range(bh):
            for dx in range(-bw, bw + 1):
                c = pal["mid"] if dy > bh - 3 else pal["base"]
                if dx < -bw + 1:
                    c = pal["lit"]
                elif dx > bw - 1:
                    c = pal["dark"]
                pp_(img, dx, h - bh + dy, c)
        for dx in range(-bw + 2, bw - 1, 2):
            pp_(img, dx, h - bh + bh // 2, pal["deep"])
    if p.get("rail"):
        for dx in range(-9, 10):
            pp_(img, dx, h - 4, pal["dark"])
            pp_(img, dx, h - 3, pal["mid"])
    if p.get("flag"):
        for dy in range(4):
            for dx in range(1, 6 - dy):
                pp_(img, dx, h - 1 - dy, PP["cloth"]["base"] if dx > 2 else PP["cloth"]["lit"])
    return 4


def b_cactus(img, rng, p):
    pal = PP["palm"]
    h, w = p["h"], p.get("w", 3)
    for dy in range(h):
        for dx in range(-w, w + 1):
            c = pal["base"]
            if dx < -w + 1:
                c = pal["lit"]
            elif dx > w - 1:
                c = pal["deep"]
            pp_(img, dx, dy, c)
    for dy in range(2, h - 1, 3):
        pp_(img, -w, dy, pal["tip"])
        pp_(img, w, dy, pal["tip"])
    for dx in range(-w, w + 1):
        pp_(img, dx, h, pal["mid"] if dx < 0 else pal["base"])
    for (side, ay, ah) in p.get("arms", []):
        for dy in range(ah):
            for k in range(-1, 2):
                pp_(img, side * (w + 2) + k, ay + dy, pal["base"] if k else pal["lit"])
        for dx in range(0, w + 3):
            pp_(img, side * dx, ay, pal["dark"])
    if p.get("bloom"):
        pp_(img, 0, h + 1, PP["bloom"]["tip"])
        pp_(img, -1, h + 1, PP["bloom"]["base"])
    return w + 2


def b_reeds(img, rng, p):
    pal = PP["reed"]
    for i in range(p["n"]):
        x = rng.randint(-p["spread"], p["spread"])
        h = rng.randint(p["h"] - 3, p["h"] + 3)
        bend = rng.choice((-2, -1, 1, 2))
        for j in range(h):
            pp_(img, x + int(bend * (j / float(h)) ** 2), j, pal["base"] if j % 3 else pal["lit"])
        if p.get("head"):
            for j in range(3):
                pp_(img, x + bend, h + j, PP["bark"]["mid"])
    return p["spread"] + 1


def b_flat(img, rng, p):
    """Things that lie on the ground: shells, bones, driftwood, a rug, a pool.
    No height, so no cast shadow -- only a rim, or the illusion is wrong."""
    pal = PP[p["pal"]]
    w, h = p["w"], p["h"]
    for dy in range(h):
        span = int(w * math.sqrt(max(0.0, 1.0 - ((dy - h / 2.0) / (h / 2.0)) ** 2)))
        for dx in range(-span, span + 1):
            c = pal["base"] if (dx + dy) % 5 else pal["mid"]
            if dy < 2:
                c = pal["dark"]
            pp_(img, dx, dy + 1, c)
    if p.get("ribs"):
        for dx in range(-w + 1, w, 2):
            for dy in range(h):
                pp_(img, dx, dy + 1, pal["deep"])
    if p.get("rim"):
        for dy in range(h):
            span = int(w * math.sqrt(max(0.0, 1.0 - ((dy - h / 2.0) / (h / 2.0)) ** 2)))
            pp_(img, -span, dy + 1, pal["lit"])
            pp_(img, span, dy + 1, pal["deep"])
    return 0


def b_box(img, rng, p):
    """Barrel, crate, chest. A lit top plane, two side planes at different
    values, and a hard vertical corner -- the cheapest thing in the file that
    reads as three-dimensional."""
    pal = PP[p.get("pal", "wood")]
    w, h, d = p["w"], p["h"], p.get("d", 4)
    for dy in range(h):
        for dx in range(-w, w + 1):
            pp_(img, dx, dy, pal["dark"] if dx > 0 else pal["base"])
    for dy in range(d):
        span = int(w * math.sqrt(max(0.0, 1.0 - ((dy - d / 2.0) / (d / 2.0 + 0.5)) ** 2)))
        for dx in range(-span, span + 1):
            pp_(img, dx, h + dy - 1, pal["lit"] if dx < 0 else pal["mid"])
    if p.get("bands"):
        for dy in (2, h - 3):
            for dx in range(-w, w + 1):
                pp_(img, dx, dy, PP["metal"]["mid"] if dx < 0 else PP["metal"]["dark"])
    if p.get("slats"):
        for dx in range(-w + 2, w, 3):
            for dy in range(h):
                pp_(img, dx, dy, pal["deep"])
    if p.get("lid"):
        for dx in range(-w, w + 1):
            pp_(img, dx, h - 1, PP["metal"]["dark"])
        pp_(img, 0, h - 3, PP["gold"]["tip"])
    return w


def b_furniture(img, rng, p):
    """The waking room. §1.1: the story is 'you wake and cross a bedroom floor',
    and there is nothing in the bedroom. There is now."""
    kind = p["kind"]
    wood, cloth = PP["wood"], PP["cloth"]
    if kind == "bed":
        for dy in range(4):
            for dx in range(-11, 12):
                pp_(img, dx, dy, wood["dark"] if dy < 2 else wood["base"])
        for dy in range(4, 22):
            for dx in range(-10, 11):
                c = cloth["base"]
                if dx < -8:
                    c = cloth["lit"]
                elif dx > 8:
                    c = cloth["deep"]
                if dy > 17:
                    c = PP["pale"]["lit"] if dx < 8 else PP["pale"]["base"]
                pp_(img, dx, dy, c)
        for dx in range(-10, 11):
            pp_(img, dx, 12, cloth["dark"])
            pp_(img, dx, 13, cloth["mid"])
        for dy in range(22, 30):
            for dx in range(-11, 12):
                pp_(img, dx, dy, wood["mid"] if dy > 27 else (wood["base"] if dx < 0 else wood["dark"]))
        return 12
    if kind == "table":
        for dy in range(9):
            for dx in ((-9, -8, 8, 9) if dy < 9 else ()):
                pp_(img, dx, dy, wood["dark"])
        for dy in range(9, 14):
            for dx in range(-12, 13):
                pp_(img, dx, dy, wood["lit"] if dy > 11 else (wood["base"] if dx < 0 else wood["dark"]))
        return 12
    if kind == "chair":
        for dy in range(9):
            for dx in (-5, 5):
                pp_(img, dx, dy, wood["dark"])
        for dy in range(9, 12):
            for dx in range(-6, 7):
                pp_(img, dx, dy, wood["lit"] if dy > 10 else wood["base"])
        for dy in range(12, 22):
            for dx in range(-6, 7):
                pp_(img, dx, dy, wood["base"] if dx < 0 else wood["dark"])
        return 6
    if kind == "shelf":
        for dy in range(26):
            for dx in range(-9, 10):
                pp_(img, dx, dy, wood["base"] if dx < 0 else wood["dark"])
        for dy in (6, 13, 20):
            for dx in range(-9, 10):
                pp_(img, dx, dy, wood["mid"])
            for dx in range(-8, 9, 2):
                hh = rng.randint(3, 5)
                col = (PP["cloth"], PP["leaf"], PP["gold"], PP["metal"])[rng.randint(0, 3)]
                for j in range(1, hh):
                    pp_(img, dx, dy + j, col["base"])
                    pp_(img, dx + 1, dy + j, col["dark"])
        return 9
    if kind == "lamp":
        for dy in range(16):
            pp_(img, 0, dy, PP["metal"]["dark"])
            pp_(img, -1, dy, PP["metal"]["base"])
        for dy in range(16, 23):
            span = 4 - abs(dy - 19)
            for dx in range(-span, span + 1):
                pp_(img, dx, dy, PP["gold"]["tip"] if abs(dx) < 2 else PP["gold"]["base"])
        return 4
    if kind == "pot":
        pal = PP["stone"]
        for dy in range(11):
            span = int(6 * math.sin(math.pi * (0.25 + 0.6 * dy / 11.0)))
            for dx in range(-span, span + 1):
                pp_(img, dx, dy, pal["mid"] if dx < -span + 2 else (pal["deep"] if dx > span - 2 else pal["base"]))
        for dy in range(11, 16):
            for dx in range(-3, 4):
                pp_(img, dx + rng.choice((-1, 0, 1)), dy, PP["leaf"]["base"])
        return 6
    if kind == "rug":
        for dy in range(11):
            for dx in range(-14, 15):
                c = cloth["base"]
                if abs(dx) > 11 or dy < 2 or dy > 8:
                    c = cloth["dark"]
                elif (dx // 3 + dy // 3) % 2 == 0:
                    c = cloth["mid"]
                pp_(img, dx, dy, c)
        return 0
    return 6


def b_structure(img, rng, p):
    """Town furniture. Placed by hand, not scattered, and the one place an
    offset shadow is allowed -- these do not move."""
    kind = p["kind"]
    stone, wood, metal = PP["stone"], PP["wood"], PP["metal"]
    if kind == "well":
        for dy in range(11):
            span = 11 - abs(dy - 5) // 3
            for dx in range(-span, span + 1):
                c = stone["base"]
                if dx < -span + 3:
                    c = stone["mid"]
                elif dx > span - 3:
                    c = stone["deep"]
                if (dx + dy * 2) % 7 == 0:
                    c = stone["dark"]
                pp_(img, dx, dy, c)
        for dy in range(11, 14):
            span = int(10 * math.sqrt(max(0.0, 1 - ((dy - 12.5) / 2.5) ** 2)))
            for dx in range(-span, span + 1):
                pp_(img, dx, dy, stone["lit"] if dy > 12 else stone["mid"])
        for dx in range(-6, 7):
            for dy in range(11, 14):
                pp_(img, dx, dy, mix(C["bg"], BLACK, 0.5))
        for side in (-1, 1):
            for dy in range(14, 30):
                pp_(img, side * 9, dy, wood["base"])
                pp_(img, side * 9 - 1, dy, wood["lit"] if side < 0 else wood["dark"])
        for dx in range(-11, 12):
            for dy in range(30, 34):
                pp_(img, dx, dy, wood["mid"] if dy > 32 else (wood["base"] if dx < 0 else wood["dark"]))
        return 11
    if kind == "cart":
        for dy in range(6, 16):
            for dx in range(-13, 10):
                pp_(img, dx, dy, wood["base"] if dx < -2 else wood["dark"])
        for dx in range(-13, 10, 3):
            for dy in range(6, 16):
                pp_(img, dx, dy, wood["deep"])
        for dx in range(-13, 10):
            pp_(img, dx, 16, wood["lit"])
        for cx in (-9, 5):
            for a in range(24):
                th = a / 24.0 * math.tau
                pp_(img, cx + math.cos(th) * 6, 6 + math.sin(th) * 6, metal["mid"])
                pp_(img, cx + math.cos(th) * 5, 6 + math.sin(th) * 5, metal["deep"])
        for dx in range(9, 20):
            pp_(img, dx, 10, wood["mid"])
        return 13
    if kind == "stall":
        for side in (-1, 1):
            for dy in range(20):
                pp_(img, side * 13, dy, wood["dark"])
                pp_(img, side * 13 - 1, dy, wood["base"])
        for dy in range(9, 14):
            for dx in range(-13, 14):
                pp_(img, dx, dy, wood["mid"] if dy > 12 else wood["base"])
        for dx in range(-16, 17):
            for dy in range(20, 26):
                band = ((dx + 48) // 4) % 2
                c = PP["cloth"]["base"] if band else PP["pale"]["base"]
                if dy > 23:
                    c = PP["cloth"]["dark"] if band else PP["pale"]["dark"]
                pp_(img, dx, dy + (abs(dx) // 8), c)
        for dx in range(-9, 10, 4):
            pp_(img, dx, 14, PP["gold"]["base"])
            pp_(img, dx + 1, 14, PP["bloom"]["base"])
        return 15
    if kind == "lamppost":
        for dy in range(26):
            pp_(img, -1, dy, metal["base"])
            pp_(img, 0, dy, metal["deep"])
        for dy in range(26, 33):
            span = 3 - abs(dy - 29) // 2
            for dx in range(-span - 1, span + 1):
                pp_(img, dx, dy, PP["gold"]["tip"] if abs(dy - 29) < 2 else PP["gold"]["base"])
        for dx in range(-4, 4):
            pp_(img, dx, 33, metal["dark"])
        return 4
    if kind == "bench":
        for side in (-1, 1):
            for dy in range(7):
                for dx in range(-1, 2):
                    pp_(img, side * 9 + dx, dy, wood["dark"])
        for dy in range(7, 10):
            for dx in range(-12, 13):
                pp_(img, dx, dy, wood["lit"] if dy > 8 else wood["base"])
        for dy in range(10, 17):
            for dx in range(-12, 13):
                pp_(img, dx, dy, wood["base"] if dy % 3 else wood["dark"])
        return 12
    return 8


def b_monument(img, rng, p):
    """Landmarks. 0.5% of props and most of the reason a place is somewhere
    rather than grass. Placed deliberately per region, not by density."""
    kind = p["kind"]
    stone = PP[p.get("pal", "stone")]
    if kind == "menhir":
        h, w = p["h"], p["w"]
        for dy in range(h):
            span = int(w * (1.0 - 0.25 * (dy / float(h)))) + rng.choice((-1, 0))
            for dx in range(-span, span + 1):
                c = stone["base"]
                if dx < -span + 2:
                    c = stone["lit"]
                elif dx > span - 2:
                    c = stone["deep"]
                pp_(img, dx, dy, c)
        for _ in range(p.get("runes", 5)):
            x, y = rng.randint(-w + 2, w - 2), rng.randint(3, h - 4)
            pp_(img, x, y, PP["gold"]["base"])
            pp_(img, x, y + 1, PP["gold"]["dark"])
        return w
    if kind == "cairn":
        y = 0
        for i, rr in enumerate(p["stack"]):
            for dy in range(rr):
                span = int(rr * 1.4 * math.sqrt(max(0.0, 1 - ((dy - rr / 2.0) / (rr / 2.0 + 0.5)) ** 2)))
                for dx in range(-span, span + 1):
                    c = stone["base"]
                    if dx < -span + 2:
                        c = stone["mid"]
                    elif dx > span - 2:
                        c = stone["deep"]
                    pp_(img, dx + p.get("jog", 1) * (i % 2 * 2 - 1), y + dy, c)
            y += rr - 1
        return int(p["stack"][0] * 1.4)
    if kind == "shrine":
        for dy in range(5):
            for dx in range(-10, 11):
                pp_(img, dx, dy, stone["base"] if dx < 0 else stone["dark"])
        for dy in range(5, 20):
            for dx in range(-8, 9):
                c = stone["mid"] if dx < -5 else (stone["deep"] if dx > 5 else stone["base"])
                pp_(img, dx, dy, c)
        for dy in range(9, 17):
            for dx in range(-4, 5):
                pp_(img, dx, dy, mix(C["bg"], BLACK, 0.4))
        pdisc(img, 0, 13, 3, PP["gold"]["tip"])
        for dy in range(20, 25):
            span = 10 - (dy - 20) * 2
            for dx in range(-span, span + 1):
                pp_(img, dx, dy, stone["lit"] if dx < 0 else stone["mid"])
        return 10
    return 6


def b_mushroom(img, rng, p):
    pal, cap = PP["pale"], PP[p.get("cap", "fungus")]
    for i in range(p["n"]):
        x = rng.randint(-p["spread"], p["spread"])
        h = rng.randint(3, 6)
        r = rng.randint(2, 4)
        for j in range(h):
            pp_(img, x, j, pal["base"])
            pp_(img, x - 1, j, pal["lit"])
        for dy in range(r):
            span = int(r * 1.5 * math.sqrt(max(0.0, 1 - (dy / float(r)) ** 2)))
            for dx in range(-span, span + 1):
                pp_(img, x + dx, h + dy, cap["lit"] if dx < 0 and dy > r // 2 else cap["base"])
        for dx in range(-r, r + 1, 2):
            pp_(img, x + dx, h + r - 1, cap["tip"])
    return p["spread"] + 2


def b_shard(img, rng, p):
    """Ice and crystal. Angular where everything else is lumpy, which is the
    only reason it reads as a different substance at this size."""
    pal = PP[p.get("pal", "ice")]
    for i in range(p["n"]):
        x = rng.randint(-p["spread"], p["spread"])
        h = rng.randint(p["h"] - 3, p["h"] + 3)
        w = max(1, h // 4)
        for dy in range(h):
            span = int(w * (1.0 - dy / float(h)))
            for dx in range(-span, span + 1):
                pp_(img, x + dx, dy, pal["lit"] if dx < 0 else (pal["deep"] if dx > 0 else pal["base"]))
        pp_(img, x, h, pal["tip"])
    return p["spread"] + 1


def b_mound(img, rng, p):
    """Snow drift and sand hummock. Almost flat, one lit crown, no outline --
    it is the ground, piled."""
    pal = PP[p["pal"]]
    w, h = p["w"], p["h"]
    for dy in range(h):
        span = int(w * math.sqrt(max(0.0, 1.0 - (dy / float(h)) ** 2)))
        for dx in range(-span, span + 1):
            c = pal["base"]
            if dy > h - 3:
                c = pal["tip"]
            elif dx < -span + 3:
                c = pal["lit"]
            elif dx > span - 3:
                c = pal["dark"]
            pp_(img, dx, dy, c)
    return 0


BUILDERS = {
    "tree": b_tree, "pine": b_pine, "palm": b_palm, "bush": b_bush,
    "boulder": b_boulder, "tuft": b_tuft, "flowers": b_flowers, "log": b_log,
    "stump": b_stump, "post": b_post, "cactus": b_cactus, "reeds": b_reeds,
    "flat": b_flat, "box": b_box, "furniture": b_furniture,
    "structure": b_structure, "monument": b_monument, "mushroom": b_mushroom,
    "shard": b_shard, "mound": b_mound,
}


# --- the prop table -----------------------------------------------------------
#
# `biome` is the material a scattered prop belongs on; `density` is instances
# per walkable cell of that biome, taken from §2.3's table and tuned to land in
# the 6-12 props per 57-cell screen the document asks for. `solid` and `foot`
# are the collision contract: `foot` cells anchored at the base cell, and
# NOTHING about the art participates.
#
# `biome: "placed"` means the generator must not scatter it -- interiors are
# furnished by hand and landmarks are put somewhere on purpose.
#
# Slot index in props.png IS the prop id minus one; id 0 in the props plane
# means nothing is there. Appending is safe, reordering rewrites every world.

def _p(pid, kind, biome, density, solid=False, foot=(1, 1), shadow=True,
       outline=True, **params):
    return dict(id=pid, kind=kind, biome=biome, density=density, solid=solid,
                foot=list(foot), shadow=shadow, outline=outline, params=params)


PROPS = [
    # --- grassland ------------------------------------------------------------
    _p("grass_tuft", "tuft", "grass_short", 0.055, shadow=False, outline=False, pal="leaf", n=7, spread=8, h=5),
    _p("grass_clump", "tuft", "grass_tall", 0.070, shadow=False, outline=False, pal="leaf", n=11, spread=10, h=9),
    _p("flowers_gold", "flowers", "grass_short", 0.022, shadow=False, outline=False, pal="flower", n=5, spread=7),
    _p("flowers_red", "flowers", "grass_short", 0.016, shadow=False, outline=False, pal="bloom", n=4, spread=6),
    _p("thistle", "tuft", "grass_tall", 0.020, shadow=False, outline=False, pal="pale", n=5, spread=5, h=11),
    _p("stone_small", "boulder", "grass_short", 0.024, pal="stone", w=5, h=5, cracks=2),
    _p("boulder", "boulder", "grass_short", 0.012, solid=True, pal="stone", w=11, h=13, cracks=4),
    _p("bush", "bush", "grass_short", 0.026, pal="leaf", r=8, tips=10),
    _p("bramble", "bush", "grass_tall", 0.020, solid=True, pal="leaf", r=10, tips=14, berries=6),
    _p("stump", "stump", "grass_short", 0.012, solid=True, r=5, h=7),
    _p("log_fallen", "log", "grass_short", 0.010, solid=True, foot=(2, 1), pal="bark", w=13, r=4, moss=6),
    _p("tree_lone", "tree", "grass_short", 0.014, solid=True, pal="leaf", trunk=13, crown=12, tw=2),
    _p("fencepost", "post", "grass_tall", 0.012, h=17, rail=True),
    _p("gate", "post", "grass_tall", 0.004, solid=True, h=22, rail=True, board=(7, 6)),

    # --- forest ---------------------------------------------------------------
    _p("tree_pine", "pine", "forest", 0.030, solid=True, pal="pine", trunk=8, tiers=4, w=12, th=8),
    _p("tree_broad", "tree", "forest", 0.028, solid=True, pal="leaf", trunk=15, crown=14, tw=3),
    _p("tree_dead", "pine", "scree", 0.014, solid=True, pal="bark", trunk=16, tiers=2, w=7, th=6),
    _p("log_mossy", "log", "forest", 0.014, solid=True, foot=(2, 1), pal="bark", w=15, r=5, moss=12),
    _p("mushroom_ring", "mushroom", "forest", 0.018, shadow=False, n=6, spread=10, cap="fungus"),
    _p("fern", "tuft", "forest", 0.030, shadow=False, outline=False, pal="pine", n=9, spread=9, h=7),

    # --- shore and sea --------------------------------------------------------
    _p("driftwood", "log", "sand", 0.016, pal="pale", w=11, r=3),
    _p("shell", "flat", "sand", 0.020, shadow=False, pal="pale", w=4, h=5, rim=True),
    _p("beach_weed", "tuft", "sand", 0.024, shadow=False, outline=False, pal="reed", n=6, spread=8, h=6),
    _p("tide_pool", "flat", "sand", 0.010, shadow=False, outline=False, pal="ice", w=9, h=7, rim=True),
    _p("palm_shore", "palm", "sand", 0.012, solid=True, pal="palm", trunk=26, lean=6, fronds=6, flen=14),
    _p("sea_rock", "boulder", "water", 0.014, solid=True, pal="stone", w=8, h=7, cracks=3),
    _p("reed_bed", "reeds", "mud", 0.055, shadow=False, outline=False, n=12, spread=11, h=13, head=True),

    # --- desert ---------------------------------------------------------------
    _p("cactus_tall", "cactus", "dune", 0.018, solid=True, h=24, w=3, arms=[(-1, 12, 8), (1, 16, 6)], bloom=True),
    _p("cactus_round", "cactus", "dune", 0.022, h=8, w=5, bloom=True),
    _p("dry_shrub", "bush", "dune", 0.028, pal="leaf_dry", r=7, tips=14),
    _p("dune_grass", "tuft", "dune", 0.045, shadow=False, outline=False, pal="leaf_dry", n=9, spread=10, h=8),
    _p("sand_mound", "mound", "dune", 0.030, shadow=False, outline=False, pal="pale", w=13, h=6),
    _p("skull", "flat", "hardpan", 0.010, pal="pale", w=5, h=6, rim=True),
    _p("bones", "flat", "hardpan", 0.012, pal="pale", w=8, h=5, ribs=True),
    _p("mesa_rock", "boulder", "hardpan", 0.018, solid=True, pal="stone", w=13, h=16, cracks=6),
    _p("palm_oasis", "palm", "hardpan", 0.006, solid=True, pal="palm", trunk=30, lean=-5, fronds=7, flen=15),

    # --- jungle ---------------------------------------------------------------
    _p("jungle_fern", "tuft", "undergrowth", 0.075, shadow=False, outline=False, pal="palm", n=13, spread=12, h=11),
    _p("banana_palm", "palm", "undergrowth", 0.020, solid=True, pal="palm", trunk=22, lean=4, fronds=5, flen=16),
    _p("vine_pillar", "post", "undergrowth", 0.016, solid=True, pal="bark", h=30, board=(4, 5)),
    _p("giant_mushroom", "mushroom", "undergrowth", 0.014, n=3, spread=7, cap="bloom"),
    _p("idol", "monument", "undergrowth", 0.004, solid=True, kind="menhir", pal="stone", h=26, w=6, runes=7),
    _p("marsh_reeds", "reeds", "undergrowth", 0.030, shadow=False, outline=False, n=9, spread=10, h=12),

    # --- highland -------------------------------------------------------------
    _p("scree_stone", "boulder", "scree", 0.045, pal="stone", w=6, h=5, cracks=2),
    _p("crag", "boulder", "scree", 0.020, solid=True, pal="stone", w=14, h=18, cracks=7),
    _p("cairn", "monument", "scree", 0.010, kind="cairn", stack=[6, 5, 4, 3], jog=1),
    _p("scrub", "bush", "scree", 0.026, pal="pine", r=6, tips=8),
    _p("snow_drift", "mound", "snow", 0.040, shadow=False, outline=False, pal="pale", w=14, h=7),
    _p("ice_shard", "shard", "snow", 0.018, pal="ice", n=3, spread=6, h=11),
    _p("marker_pole", "post", "snow", 0.010, h=24, flag=True),
    _p("crystal", "shard", "ice", 0.014, pal="ice", n=4, spread=7, h=14),

    # --- road -----------------------------------------------------------------
    _p("milestone", "monument", "path_dirt", 0.012, kind="menhir", pal="stone", h=10, w=4, runes=2),
    _p("signpost", "post", "path_dirt", 0.008, h=22, board=(8, 7)),
    _p("wayside_shrine", "monument", "path_dirt", 0.004, solid=True, kind="shrine"),
    _p("rut_stone", "boulder", "path_dirt", 0.014, pal="stone", w=4, h=3, cracks=1),

    # --- placed: the town -----------------------------------------------------
    _p("barrel", "box", "placed", 0.0, solid=True, w=6, h=13, d=5, bands=True),
    _p("crate", "box", "placed", 0.0, solid=True, w=7, h=12, d=4, slats=True),
    _p("well", "structure", "placed", 0.0, solid=True, foot=(2, 2), kind="well"),
    _p("cart", "structure", "placed", 0.0, solid=True, foot=(2, 1), kind="cart"),
    _p("market_stall", "structure", "placed", 0.0, solid=True, foot=(2, 1), kind="stall"),
    _p("lamppost", "structure", "placed", 0.0, solid=True, kind="lamppost"),
    _p("bench", "structure", "placed", 0.0, solid=True, foot=(2, 1), kind="bench"),
    _p("standing_stone", "monument", "placed", 0.0, solid=True, kind="menhir", pal="stone", h=30, w=7, runes=8),

    # --- placed: interiors ----------------------------------------------------
    _p("bed", "furniture", "placed", 0.0, solid=True, foot=(2, 2), kind="bed"),
    _p("table", "furniture", "placed", 0.0, solid=True, foot=(2, 1), kind="table"),
    _p("chair", "furniture", "placed", 0.0, solid=True, kind="chair"),
    _p("bookshelf", "furniture", "placed", 0.0, solid=True, kind="shelf"),
    _p("chest", "box", "placed", 0.0, solid=True, w=8, h=9, d=4, lid=True),
    _p("floor_lamp", "furniture", "placed", 0.0, kind="lamp"),
    _p("plant_pot", "furniture", "placed", 0.0, solid=True, kind="pot"),
    _p("rug", "furniture", "placed", 0.0, shadow=False, outline=False, kind="rug"),
]

# Flat literal, parsed the same way make_world.py parses ORDER. Index i is
# props-plane value i+1.
PROP_ORDER = [
    "grass_tuft", "grass_clump", "flowers_gold", "flowers_red", "thistle",
    "stone_small", "boulder", "bush", "bramble", "stump", "log_fallen",
    "tree_lone", "fencepost", "gate",
    "tree_pine", "tree_broad", "tree_dead", "log_mossy", "mushroom_ring", "fern",
    "driftwood", "shell", "beach_weed", "tide_pool", "palm_shore", "sea_rock",
    "reed_bed",
    "cactus_tall", "cactus_round", "dry_shrub", "dune_grass", "sand_mound",
    "skull", "bones", "mesa_rock", "palm_oasis",
    "jungle_fern", "banana_palm", "vine_pillar", "giant_mushroom", "idol",
    "marsh_reeds",
    "scree_stone", "crag", "cairn", "scrub", "snow_drift", "ice_shard",
    "marker_pole", "crystal",
    "milestone", "signpost", "wayside_shrine", "rut_stone",
    "barrel", "crate", "well", "cart", "market_stall", "lamppost", "bench",
    "standing_stone",
    "bed", "table", "chair", "bookshelf", "chest", "floor_lamp", "plant_pot",
    "rug",
]

PROP_BY_ID = {p["id"]: p for p in PROPS}
PROP_COLS = 8


def build_prop(pid):
    p = PROP_BY_ID[pid]
    img = prop_canvas()
    rng = rng_for("prop", pid)
    rw = BUILDERS[p["kind"]](img, rng, p["params"])
    if p["outline"]:
        poutline(img)
    if p["shadow"]:
        pshadow(img, max(4, int(rw)))
    return img


def build_props():
    rows = (len(PROP_ORDER) + PROP_COLS - 1) // PROP_COLS
    atlas = Image.new("RGBA", (PROP_COLS * PROP_W, rows * PROP_H), (0, 0, 0, 0))
    sprites = {}
    for i, pid in enumerate(PROP_ORDER):
        s = build_prop(pid)
        sprites[pid] = s
        atlas.paste(s, ((i % PROP_COLS) * PROP_W, (i // PROP_COLS) * PROP_H))
    return atlas, sprites, rows


# --- cliffs -------------------------------------------------------------------
#
# §2.2c. The elevation field already exists in make_world.py and is currently
# thrown away; this is the art it needs when it stops being thrown away. A drop
# reads as three things stacked, which is the only construction that works at
# this scale:
#
#   1. the LIP, drawn on the cell at the top of the drop: two or three rows of
#      lit rock along its southern edge. Material-agnostic, so it sits on grass,
#      scree or snow without a variant each.
#   2. the FACE, a full 32px vertical surface drawn on the cell BELOW the drop,
#      striated, lit from the north-west, and going genuinely dark -- luma 10 to
#      30, below anything on the ground plane. This is where the value range
#      recovered in §2.6 is actually spent.
#   3. the cast SHADOW, four to six rows on the ground below the face.
#
# A WALL IS A CLIFF WITH A ONE-BAND DROP and should use this same machinery:
# wall_plaster and wall_stone get a lip, a face on the cell below and a base
# shadow. That is what turns the grey stripe in the waking room into a wall.
#
# 16 pieces, laid out 4 x 4 in cliffs.png. Index = row * 4 + col.
CLIFF_ORDER = [
    "lip_mid", "lip_left", "lip_right", "lip_solo",
    "face_a", "face_b", "face_c", "face_mid",
    "face_left", "face_right", "corner_left", "corner_right",
    "shadow_mid", "shadow_left", "shadow_right", "shadow_solo",
]
CLIFF_COLS = 4


def _cliff_edge(key, ends, amp, lo, hi):
    return displaced(key, ends, amp, N, lo, hi)


def cliff_face(name, left_end=False, right_end=False, top_rim=True, base=True):
    r = R["cliff"]
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    rng = rng_for("cliff", name)
    rim = _cliff_edge(("cliffrim", name), 2, 1.6, 1, 4)
    for x in range(N):
        # Striations: a vertical column of banded rock, its bands offset by a
        # slow wander so the face never reads as a ruled grid.
        col_lit = 1.0 - min(1.0, max(0.0, (x - 3) / 24.0))
        y = rim[x] if top_rim else 0
        while y < N:
            h = rng.randint(3, 6)
            for j in range(h):
                if y + j >= N:
                    break
                t = col_lit
                c = mix(r["deep"], r["mid"], 0.25 + 0.55 * t)
                if j == 0:
                    c = mix(r["dark"], r["lit"], 0.30 + 0.60 * t)
                elif j == h - 1:
                    c = r["deep"]
                if base and y + j > N - 4:
                    c = mix(c, SHADOW, 0.55)
                pxa(img, x, y + j, c)
            y += h
        if top_rim:
            for k in range(rim[x]):
                pxa(img, x, k, r["tip"] if k == rim[x] - 1 else r["lit"])
    if left_end:
        for y in range(N):
            for k in range(3):
                pxa(img, k, y, mix(r["lit"], r["tip"], 0.4 - k * 0.15))
    if right_end:
        for y in range(N):
            for k in range(3):
                pxa(img, N - 1 - k, y, mix(r["deep"], SHADOW, 0.3 + k * 0.2))
    return img


def cliff_lip(name, left=False, right=False):
    """Drawn on the upper terrace's cell: the rock edge it stands on, catching
    the light. Organic top edge, so a terrace boundary is not a ruled line."""
    r = R["cliff"]
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    top = _cliff_edge(("lip", name), 4, 2.2, 2, 7)
    for x in range(N):
        if left and x < 2:
            continue
        if right and x >= N - 2:
            continue
        d = top[x]
        for k in range(d):
            y = N - 1 - k
            if k == d - 1:
                c = r["tip"]
            elif k >= d - 3:
                c = r["lit"]
            else:
                c = r["mid"]
            pxa(img, x, y, c)
    return img


def cliff_shadow(name, left=False, right=False):
    r = R["cliff"]
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    bot = _cliff_edge(("cshadow", name), 5, 2.4, 2, 9)
    for x in range(N):
        if left and x < 3:
            continue
        if right and x >= N - 3:
            continue
        for k in range(bot[x]):
            pxa(img, x, k, SHADOW, SHADOW_A)
        pxa(img, x, 0, r["deep"])
    return img


def build_cliffs():
    made = {
        "lip_mid": cliff_lip("mid"),
        "lip_left": cliff_lip("left", left=True),
        "lip_right": cliff_lip("right", right=True),
        "lip_solo": cliff_lip("solo", left=True, right=True),
        "face_a": cliff_face("a"),
        "face_b": cliff_face("b"),
        "face_c": cliff_face("c"),
        "face_mid": cliff_face("mid", top_rim=False, base=False),
        "face_left": cliff_face("l", left_end=True),
        "face_right": cliff_face("r", right_end=True),
        "corner_left": cliff_face("cl", left_end=True, top_rim=False),
        "corner_right": cliff_face("cr", right_end=True, top_rim=False),
        "shadow_mid": cliff_shadow("mid"),
        "shadow_left": cliff_shadow("left", left=True),
        "shadow_right": cliff_shadow("right", right=True),
        "shadow_solo": cliff_shadow("solo", left=True, right=True),
    }
    rows = (len(CLIFF_ORDER) + CLIFF_COLS - 1) // CLIFF_COLS
    atlas = Image.new("RGBA", (CLIFF_COLS * N, rows * N), (0, 0, 0, 0))
    for i, key in enumerate(CLIFF_ORDER):
        atlas.paste(made[key], ((i % CLIFF_COLS) * N, (i // CLIFF_COLS) * N))
    return atlas, made, rows


# --- previews -----------------------------------------------------------------
#
# §1.0's finding is that every decision in the old file was made looking at a
# 32x32 image or a 4x contact sheet, and none of them was made looking at 57
# cells at 96 screen pixels each -- which is the entire frame the player sees.
# So the tool now renders what the player sees, and you are expected to open it.

def comp_grid(bands, w, h, seed, tilt=(0.0, 0.0), freq=0.115, warp=0.0):
    """A patch of plausible terrain: one fbm field, thresholded into bands, with
    an optional linear tilt so a shoreline runs across the frame."""
    grid = []
    for y in range(h):
        row = []
        for x in range(w):
            v = fbm(seed, x, y, freq, 4)
            if warp:
                v += warp * (fbm(seed + 5501, x, y, freq * 2.3, 2) - 0.5)
            v += tilt[0] * (x / float(w) - 0.5) + tilt[1] * (y / float(h) - 0.5)
            mat = bands[-1][1]
            for thr, name in bands:
                if v < thr:
                    mat = name
                    break
            row.append(mat)
        grid.append(row)
    return grid


def scatter_props(grid, sprites, seed):
    out = []
    for y, row in enumerate(grid):
        for x, mat in enumerate(row):
            cands = [p for p in PROPS if p["biome"] == mat]
            if not cands:
                continue
            roll = (hashv("propscatter", x, y, seed) % 1000000) / 1000000.0
            acc = 0.0
            for p in cands:
                acc += p["density"]
                if roll < acc:
                    out.append((x, y, sprites[p["id"]]))
                    break
    return out


COMPOSITIONS = [
    ("shore", [(0.30, "ocean"), (0.44, "water"), (0.53, "sand"),
               (0.70, "grass_short"), (1.01, "grass_tall")],
     dict(seed=11, tilt=(0.42, 0.10))),
    ("forest_edge", [(0.40, "path_dirt"), (0.55, "grass_short"),
                     (0.66, "grass_tall"), (1.01, "forest")],
     dict(seed=27, tilt=(0.0, 0.30), warp=0.25)),
    ("scree_slope", [(0.34, "grass_short"), (0.48, "scree"), (0.60, "rock"),
                     (0.72, "cliff"), (1.01, "snow")],
     dict(seed=41, tilt=(0.15, -0.45))),
    ("desert", [(0.34, "water"), (0.42, "sand"), (0.60, "dune"),
                (0.78, "hardpan"), (1.01, "scree")],
     dict(seed=53, tilt=(0.30, 0.20), warp=0.30)),
    ("jungle", [(0.32, "water"), (0.44, "mud"), (0.62, "undergrowth"),
                (1.01, "jungle")],
     dict(seed=67, tilt=(-0.20, 0.28), warp=0.30)),
    ("crossroads", [(0.36, "grass_tall"), (0.52, "grass_short"),
                    (0.64, "sand"), (0.78, "scree"), (1.01, "path_dirt")],
     dict(seed=83, warp=0.40, freq=0.16)),
]


def build_compositions(tiles, sprites, w=12, h=12, zoom=3):
    out = {}
    for name, bands, kw in COMPOSITIONS:
        seed = kw.pop("seed")
        grid = comp_grid(bands, w, h, seed, **kw)
        kw["seed"] = seed
        props = scatter_props(grid, sprites, seed)
        out[name] = render_patch(grid, tiles, seed=seed, props=props, zoom=zoom)
    return out


def contact_sheet(built, scale=4, cols=5):
    """A labelled 4x preview of the base fills. Each cell shows the tile
    repeated 2x2 -- a lone tile hides exactly the seam you want to check --
    and carries its mean luma, because the value structure is the point now."""
    pad, label_h = 6, 12
    cell = N * scale
    rows = (len(built) + cols - 1) // cols
    sheet = Image.new("RGBA",
                      (cols * (cell + pad) + pad, rows * (cell + label_h + pad) + pad),
                      tuple(mix(C["bg"], BLACK, 0.3)) + (255,))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for i, (name, img) in enumerate(built):
        cx = pad + (i % cols) * (cell + pad)
        cy = pad + (i // cols) * (cell + label_h + pad)
        quad = Image.new("RGBA", (N * 2, N * 2))
        for qy in range(2):
            for qx in range(2):
                quad.paste(img, (qx * N, qy * N))
        sheet.paste(quad.resize((cell, cell), Image.NEAREST), (cx, cy))
        mark = "walk" if WALKABLE[name] else "SOLID"
        d.text((cx, cy + cell + 1), "%s [%s] %d" % (name, mark, round(mean_luma(img))),
               fill=tuple(C["text"]) + (255,), font=font)
    return sheet


def overlay_sheet(tiles, scale=3):
    """Every overlay case of every material, variant 0, composited over a
    checker of two contrasting grounds so the alpha is visible."""
    pad, label_h = 4, 12
    cell = N * scale
    rows = len(OVERLAY_MATS) * 2
    sheet = Image.new("RGBA", (16 * (cell + pad) + pad + 90,
                               rows * (cell + pad) + pad + label_h),
                      tuple(mix(C["bg"], BLACK, 0.3)) + (255,))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for mi, mat in enumerate(OVERLAY_MATS):
        under = "sand" if RANK[mat] > RANK["sand"] else "ocean"
        for ki, kind in enumerate(("edge", "corner")):
            row = mi * 2 + ki
            cy = pad + row * (cell + pad)
            d.text((4, cy + cell // 2), "%s %s" % (mat[:11], kind[0]),
                   fill=tuple(C["text"]) + (255,), font=font)
            for mask in range(16):
                base = fill(under, 0).copy()
                base.alpha_composite(tiles[(mat, kind, mask, 0)])
                sheet.paste(base.resize((cell, cell), Image.NEAREST),
                            (90 + pad + mask * (cell + pad), cy))
    return sheet


def prop_sheet(sprites, scale=2, cols=8):
    pad, label_h = 4, 11
    cw, ch = PROP_W * scale, PROP_H * scale
    rows = (len(PROP_ORDER) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * (cw + pad) + pad, rows * (ch + label_h + pad) + pad),
                      tuple(R["grass_short"]["base"]) + (255,))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for i, pid in enumerate(PROP_ORDER):
        p = PROP_BY_ID[pid]
        cx = pad + (i % cols) * (cw + pad)
        cy = pad + (i // cols) * (ch + label_h + pad)
        under = Image.new("RGBA", (PROP_W, PROP_H))
        for ty in range(3):
            for tx in range(2):
                under.paste(fill(p["biome"] if p["biome"] in MATERIALS else "floor_boards", 0),
                            (tx * N, ty * N))
        under.alpha_composite(sprites[pid])
        sheet.paste(under.resize((cw, ch), Image.NEAREST), (cx, cy))
        d.text((cx, cy + ch + 1), "%d %s%s" % (i + 1, pid, "*" if p["solid"] else ""),
               fill=tuple(C["text"]) + (255,), font=font)
    return sheet


# --- verification -------------------------------------------------------------

def verify_seams(name, img):
    """Lay the tile up 4x4 and measure the joints against the tile's own
    internal transitions.

    A seam is invisible when the step across the joint is no larger than the
    steps the tile already makes internally -- an absolute threshold would fail
    the flagstone (whose joints are legitimately hard) and pass a flat tile that
    is subtly wrong. So the test is relative: joint delta vs. the distribution
    of every adjacent-pair delta in the repeat."""
    rep = Image.new("RGB", (N * 4, N * 4))
    for ty in range(4):
        for tx in range(4):
            rep.paste(img.convert("RGB"), (tx * N, ty * N))
    w, h = rep.size
    p = rep.load()

    def delta(a, b):
        return sum(abs(a[i] - b[i]) for i in range(3)) / 3.0

    cols = [sum(delta(p[x, y], p[x + 1, y]) for y in range(h)) / h for x in range(w - 1)]
    rows = [sum(delta(p[x, y], p[x, y + 1]) for x in range(w)) / w for y in range(h - 1)]
    seams = [N - 1, 2 * N - 1, 3 * N - 1]

    def judge(series):
        interior = [v for i, v in enumerate(series) if i not in seams]
        joint = max(series[i] for i in seams)
        mean = sum(interior) / len(interior)
        sd = (sum((v - mean) ** 2 for v in interior) / len(interior)) ** 0.5
        return joint, max(interior), mean, max(max(interior), mean + 3.0 * sd)

    jx, mx, ax, lx = judge(cols)
    jy, my, ay, ly = judge(rows)
    return {"ok": jx <= lx + 1e-6 and jy <= ly + 1e-6,
            "h_joint": jx, "h_int_max": mx, "h_lim": lx,
            "v_joint": jy, "v_int_max": my, "v_lim": ly}


def lumas(img):
    out = []
    p = img.convert("RGBA").load()
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            c = p[x, y]
            if c[3] == 0:
                continue
            out.append(luma(c[:3]))
    return out


def mean_luma(img):
    v = lumas(img)
    return sum(v) / len(v) if v else 0.0


def stats(values):
    v = sorted(values)
    n = len(v)
    def q(f):
        return v[min(n - 1, max(0, int(f * n)))]
    return dict(min=v[0], p1=q(0.01), p50=q(0.50), p99=q(0.99), max=v[-1],
                mean=sum(v) / n)


def rgb_delta(a, b):
    pa, pb = a.convert("RGB"), b.convert("RGB")
    ma = [sum(pa.getdata(i)) / float(N * N) for i in range(3)]
    mb = [sum(pb.getdata(i)) / float(N * N) for i in range(3)]
    return sum(abs(ma[i] - mb[i]) for i in range(3)) / 3.0
