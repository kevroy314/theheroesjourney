#!/usr/bin/env python3
"""Build the world: one continuous landscape, and the drawn map of it.

The journey used to be eight areas with eight maps. It is now **one place you
can walk from end to end** — the bed you wake in is a room in a house, the house
stands at the edge of a town, the town gives onto fields, the fields go to seed,
the road leaves, the ground tilts, and the mountain is at the top of the same
grid. No zone borders, no loading, no per-region maps. Chapters become *regions*
of one world: they say where the story is, not where you are allowed to be.

Two outputs, and the important thing about them is that **the drawn map is a
rendering of the tile grid, not a separate picture of it**:

    data/world/overworld.json      the grid the game walks on
    assets/world/worldmap.png      the drawn map, rendered from that same grid

Generated together from one source, so they cannot drift. A hand-painted map
beside a hand-built tilemap is two descriptions of a place that will disagree
within a week, and the player is the one who finds out.

Everything derives from two scalar fields — elevation and moisture — sampled
from value noise. Biomes are thresholds on those fields, which is what buys the
"no zone boundaries" requirement for free: a shore is wherever elevation crosses
sea level, not a line someone drew, so grass gives way to sand gives way to
water without anybody deciding where.

    python3 tools/make_world.py
"""
import base64
import json
import math
import os
import random
import struct
import zlib

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(ROOT, "data", "themes", "firstlight.json")
DATA_OUT = os.path.join(ROOT, "data", "world")
ART_OUT = os.path.join(ROOT, "assets", "world")

# Tile ids are indices into ORDER in tools/make_tiles.py. Kept in sync by
# reading that file rather than by copying the list, so appending a tile there
# cannot silently renumber the world.
def tile_order():
    src = open(os.path.join(ROOT, "tools", "make_tiles.py")).read()
    body = src.split("ORDER = [", 1)[1].split("]", 1)[0]
    return [p.strip().strip('"') for p in body.replace("\n", "").split(",") if p.strip()]


ORDER = tile_order()
T = {name: i for i, name in enumerate(ORDER)}

W, H = 150, 320          # tiles. Tall, because the journey is a climb.
SEA = 0.30               # elevation below this is water
SHORE = 0.34
GRASS = 0.52
HILL = 0.66
SCREE = 0.78             # above this, bare stone; above SNOW, snow
SNOW = 0.88

# Where each chapter's story sits in the world, as a fraction of the height,
# south (0.0, the house) to north (1.0, the summit). These are anchors for the
# node graph, not walls — you can walk to the summit on day one and find that
# the door is shut.
REGIONS = [
    ("waking_room", 0.945, 0.50),
    ("the_house", 0.912, 0.50),
    ("the_town", 0.830, 0.44),
    ("tall_grass", 0.690, 0.58),
    ("long_road", 0.540, 0.46),
    ("foothills", 0.375, 0.55),
    ("observatory", 0.225, 0.38),
    ("summit", 0.070, 0.50),
]

## A region's character, applied as a soft radial nudge to the two fields rather
## than as a painted rectangle. This is how the world gets to feel like eight
## named places while still having no borders: the Tall Grass is wetter than
## what surrounds it and the Long Road is drier, so the change happens over
## thirty tiles and nobody can point at where it starts.
##
## (radius in tiles, elevation nudge, moisture nudge)
CHARACTER = {
    "the_town": (26, 0.02, -0.10),
    "tall_grass": (34, -0.02, 0.26),
    "long_road": (34, -0.01, -0.28),
    "foothills": (34, 0.10, -0.14),
    "observatory": (26, 0.14, -0.20),
    "summit": (30, 0.22, -0.26),
}


def theme_colors():
    data = json.load(open(THEME))
    return {k: tuple(int(v.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            for k, v in data["colors"].items()}


C = theme_colors()


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


# --- value noise ---------------------------------------------------------------
#
# Hand-rolled rather than imported: the whole point of these tools is that they
# run anywhere with nothing but PIL, and one lattice of seeded randoms with
# smoothstep interpolation is twenty lines.

class Noise:
    def __init__(self, seed, period=64):
        self.period = period
        rng = random.Random(seed)
        self.grid = [[rng.random() for _ in range(period)] for _ in range(period)]

    def _at(self, ix, iy):
        return self.grid[iy % self.period][ix % self.period]

    def sample(self, x, y, scale):
        fx, fy = x / scale, y / scale
        ix, iy = int(math.floor(fx)), int(math.floor(fy))
        tx, ty = fx - ix, fy - iy
        # Smoothstep, not linear: linear interpolation leaves visible diamond
        # creases along the lattice, and on a coastline those read as geometry.
        tx = tx * tx * (3 - 2 * tx)
        ty = ty * ty * (3 - 2 * ty)
        a = self._at(ix, iy) + (self._at(ix + 1, iy) - self._at(ix, iy)) * tx
        b = self._at(ix, iy + 1) + (self._at(ix + 1, iy + 1) - self._at(ix, iy + 1)) * tx
        return a + (b - a) * ty

    def fbm(self, x, y, scale, octaves=4):
        total, amp, norm = 0.0, 1.0, 0.0
        for o in range(octaves):
            total += self.sample(x, y, scale / (2 ** o)) * amp
            norm += amp
            amp *= 0.5
        return total / norm


def build_fields(cells):
    """Elevation and moisture over the whole grid."""
    en = Noise(20260818, 64)
    mn = Noise(777, 64)
    nudges = [(cells[rid][0], cells[rid][1], r, de, dm)
              for rid, (r, de, dm) in CHARACTER.items()]
    elev = [[0.0] * W for _ in range(H)]
    moist = [[0.0] * W for _ in range(H)]
    for y in range(H):
        # The spine of the design: the land rises as you go north. Everything
        # else is detail on top of this one ramp, which is why the world reads
        # as a climb rather than as noise.
        climb = 1.0 - (y / (H - 1.0))
        ramp = 0.26 + 0.62 * (climb ** 1.35)
        for x in range(W):
            n = en.fbm(x, y, 46.0, 5)
            # Centred noise, so the ramp decides the altitude and the noise only
            # roughens it. Adding uncentred noise pushed the whole world up and
            # the summit never reached snow.
            e = ramp * 0.96 + (n - 0.5) * 0.34
            # Pull the map's edges down into water so the world has a coast and
            # ends somewhere, rather than being cut off by the array bounds.
            ex = min(x, W - 1 - x) / 15.0
            ey = min(y, H - 1 - y) / 14.0
            e *= min(1.0, ex) * 0.5 + 0.5
            e *= min(1.0, ey) * 0.5 + 0.5
            m = mn.fbm(x, y, 34.0, 3)
            # Region character, falling off smoothly to nothing.
            for nx, ny, r, de, dm in nudges:
                d2 = (x - nx) ** 2 + (y - ny) ** 2
                if d2 > (r * 2.2) ** 2:
                    continue
                w = math.exp(-d2 / (2.0 * r * r))
                e += de * w
                m += dm * w
            elev[y][x] = max(0.0, min(1.0, e))
            moist[y][x] = max(0.0, min(1.0, m))
    return elev, moist


def biome(e, m):
    if e < SEA:
        return T["water"]
    if e < SHORE:
        return T["sand"]
    if e < GRASS:
        return T["forest"] if m > 0.62 else T["grass_short"]
    if e < HILL:
        if m > 0.68:
            return T["forest"]
        return T["grass_tall"] if m > 0.48 else T["grass_short"]
    if e < SCREE:
        return T["scree"] if m < 0.55 else T["grass_short"]
    if e < SNOW:
        return T["scree"]
    return T["snow"]


def region_cells():
    return {rid: (int(fx * (W - 1)), int(fy * (H - 1))) for rid, fy, fx in REGIONS}


def carve_road(tiles, elev, points):
    """One road, south to north, through every region in order.

    Followed the terrain rather than ignoring it: the road prefers to stay level
    and goes round what it cannot climb, because a road that runs dead straight
    up a mountain is the clearest possible sign that nobody drew this place.
    """
    def put(x, y, tile):
        if 0 <= x < W and 0 <= y < H:
            # A road over water is a bridge, not a road. Anywhere else it is dirt.
            if tiles[y][x] == T["water"]:
                tiles[y][x] = T["bridge"]
            elif tiles[y][x] != T["bridge"]:
                tiles[y][x] = tile

    for i in range(len(points) - 1):
        ax, ay = points[i]
        bx, by = points[i + 1]
        x, y = ax, ay
        guard = 0
        while (x, y) != (bx, by) and guard < 4000:
            guard += 1
            for dx in (-1, 0, 1):
                put(x + dx, y, T["path_dirt"])
                put(x + dx, y + 1, T["path_dirt"])
            # Step toward the target, choosing the axis with further to go, and
            # letting the terrain nudge the sideways drift.
            if abs(by - y) >= abs(bx - x):
                y += 1 if by > y else -1
                if x != bx and random.random() < 0.34:
                    x += 1 if bx > x else -1
            else:
                x += 1 if bx > x else -1
    return tiles


def stamp_town(tiles, cx, cy, rng):
    """A cluster of buildings with streets between them, not a solid block."""
    for by in range(-9, 10, 6):
        for bx in range(-12, 13, 8):
            if rng.random() < 0.25:
                continue
            w, h = rng.randint(4, 6), rng.randint(3, 5)
            ox, oy = cx + bx + rng.randint(-1, 1), cy + by + rng.randint(-1, 1)
            for y in range(oy, oy + h):
                for x in range(ox, ox + w):
                    if 0 <= x < W and 0 <= y < H:
                        tiles[y][x] = T["roof"]
            # A door on the south face, so every building can be entered from
            # the street rather than being scenery.
            dx = ox + w // 2
            if 0 <= dx < W and 0 <= oy + h < H:
                tiles[oy + h - 1][dx] = T["door"]
    # Paved ground under the whole settlement.
    for y in range(cy - 13, cy + 14):
        for x in range(cx - 16, cx + 17):
            if 0 <= x < W and 0 <= y < H and tiles[y][x] in (
                    T["grass_short"], T["grass_tall"], T["forest"], T["scree"]):
                tiles[y][x] = T["floor_stone"]


def stamp_house(tiles, cx, cy):
    """The house you wake in. Walls, boards, and a door onto the road — the one
    interior that is part of the outdoor grid, because the first thing the game
    ever asks you to do is cross a bedroom floor."""
    x0, y0, w, h = cx - 7, cy - 9, 15, 12
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            if not (0 <= x < W and 0 <= y < H):
                continue
            edge = x in (x0, x0 + w - 1) or y in (y0, y0 + h - 1)
            tiles[y][x] = T["wall_plaster"] if edge else T["floor_boards"]
    # An internal wall with a gap: upstairs room, downstairs room, one doorway.
    for x in range(x0 + 1, x0 + w - 1):
        if abs(x - cx) > 1 and 0 <= y0 + 5 < H:
            tiles[y0 + 5][x] = T["wall_plaster"]
    if 0 <= y0 + h - 1 < H:
        tiles[y0 + h - 1][cx] = T["door"]


def stamp_observatory(tiles, cx, cy):
    """Stone drum on a ridge, one door facing back down the hill."""
    r = 7
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            if not (0 <= x < W and 0 <= y < H):
                continue
            d = math.hypot(x - cx, y - cy)
            if d > r:
                continue
            tiles[y][x] = T["wall_stone"] if d > r - 1.6 else T["floor_stone"]
    if 0 <= cy + r - 1 < H:
        tiles[cy + r - 1][cx] = T["door"]


def stamp_summit(tiles, cx, cy):
    """The door in the rock. Bare stone all round it so it is the only thing to
    look at when you finally get up here."""
    for y in range(cy - 5, cy + 6):
        for x in range(cx - 6, cx + 7):
            if 0 <= x < W and 0 <= y < H:
                tiles[y][x] = T["floor_stone"]
    for x in range(cx - 6, cx + 7):
        if 0 <= cy - 5 < H and 0 <= x < W:
            tiles[cy - 5][x] = T["rock"]
    if 0 <= cy - 5 < H:
        tiles[cy - 5][cx] = T["door"]


def build():
    cells = region_cells()
    elev, moist = build_fields(cells)
    tiles = [[biome(elev[y][x], moist[y][x]) for x in range(W)] for y in range(H)]

    rng = random.Random(4242)

    # Flatten a landing around every anchor first, so a story beat never lands
    # in the sea because the noise happened to dip there.
    for rid, (cx, cy) in cells.items():
        for y in range(cy - 6, cy + 7):
            for x in range(cx - 8, cx + 9):
                if 0 <= x < W and 0 <= y < H and tiles[y][x] in (T["water"], T["sand"]):
                    tiles[y][x] = T["grass_short"]

    ordered = [cells[rid] for rid, _, _ in REGIONS]
    carve_road(tiles, elev, list(reversed(ordered)))

    stamp_town(tiles, *cells["the_town"], rng=rng)
    stamp_observatory(tiles, *cells["observatory"])
    stamp_summit(tiles, *cells["summit"])
    stamp_house(tiles, *cells["waking_room"])

    return tiles, elev, cells


# --- output --------------------------------------------------------------------

def encode(tiles):
    """One byte per cell, deflated, base64. 48000 cells is 47KB raw and a couple
    of KB compressed — small enough to sit in the pck and load in one gulp."""
    raw = bytes(bytearray(t for row in tiles for t in row))
    # Plain zlib.compress, header and all. Godot's COMPRESSION_DEFLATE is
    # zlib-wrapped despite the name — verified by round-tripping every
    # python/godot pairing, and raw deflate (wbits=-15) silently decompresses to
    # zero bytes rather than erroring. If you change this, re-test it.
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def draw_map(tiles, elev, cells, px=4):
    """The drawn map: the same grid, rendered as something you would pin up.

    Not a zoomed-out screenshot. The tiles carry their own detail at 32px, which
    at 4px is just noise, so this renders flat biome colour and then does the
    work with *shading* — a hillshade taken from the elevation field's own
    gradient, exactly the way a paper relief map is made.
    """
    colour = {
        T["water"]: mix(C["accent_2"], C["bg"], 0.62),
        T["sand"]: mix(mix(C["bg"], C["accent"], 0.30), C["muted"], 0.26),
        T["grass_short"]: mix(C["good"], C["bg"], 0.72),
        T["grass_tall"]: mix(C["good"], C["bg"], 0.64),
        T["forest"]: mix(C["good"], C["bg"], 0.86),
        T["scree"]: mix(C["line"], C["bg"], 0.34),
        T["snow"]: mix(C["muted"], C["bg"], 0.26),
        T["rock"]: mix(C["line"], C["bg"], 0.50),
        T["path_dirt"]: mix(C["bg"], C["accent"], 0.30),
        T["bridge"]: mix(C["accent"], C["bg"], 0.55),
        T["floor_stone"]: mix(C["muted"], C["bg"], 0.52),
        T["floor_boards"]: mix(C["accent"], C["bg"], 0.70),
        T["wall_plaster"]: mix(C["muted"], C["bg"], 0.40),
        T["wall_stone"]: mix(C["muted"], C["bg"], 0.34),
        T["roof"]: mix(C["accent"], C["bg"], 0.60),
        T["door"]: C["accent"],
        T["void"]: C["bg"],
    }
    img = Image.new("RGB", (W * px, H * px))
    out = img.load()
    for y in range(H):
        for x in range(W):
            base = colour.get(tiles[y][x], C["bg"])
            # Hillshade with the light from the north-west, the convention every
            # relief map uses, because the eye reads the other direction as pits.
            dzdx = elev[y][min(W - 1, x + 1)] - elev[y][max(0, x - 1)]
            dzdy = elev[min(H - 1, y + 1)][x] - elev[max(0, y - 1)][x]
            shade = max(-1.0, min(1.0, (dzdy - dzdx) * 7.0))
            c = mix(base, C["text"], shade * 0.30) if shade > 0 \
                else mix(base, C["bg"], -shade * 0.42)
            for j in range(px):
                for i in range(px):
                    out[x * px + i, y * px + j] = c

    # A ring at each anchor, so the map is legible as a route and not only as
    # terrain. No text: the map is a thing in the world, and nothing in the real
    # world carries writing that survives the loop.
    for rid, (cx, cy) in cells.items():
        r = 10 if rid in ("summit", "the_town") else 7
        for a in range(0, 360, 4):
            ax = int(cx * px + px // 2 + math.cos(math.radians(a)) * r)
            ay = int(cy * px + px // 2 + math.sin(math.radians(a)) * r)
            if 0 <= ax < W * px and 0 <= ay < H * px:
                out[ax, ay] = C["accent"]
    return img


def main():
    os.makedirs(DATA_OUT, exist_ok=True)
    os.makedirs(ART_OUT, exist_ok=True)
    tiles, elev, cells = build()

    payload = {
        "_comment": "Generated by tools/make_world.py. Do not hand-edit; "
                    "regenerate. Tile ids index ORDER in tools/make_tiles.py.",
        "w": W, "h": H,
        "tiles_b64_deflate": encode(tiles),
        "regions": {rid: {"x": xy[0], "y": xy[1]} for rid, xy in cells.items()},
        "spawn": {"x": cells["waking_room"][0], "y": cells["waking_room"][1]},
    }
    path = os.path.join(DATA_OUT, "overworld.json")
    json.dump(payload, open(path, "w"), indent=1)
    open(path, "a").write("\n")

    draw_map(tiles, elev, cells).save(os.path.join(ART_OUT, "worldmap.png"))

    counts = {}
    for row in tiles:
        for t in row:
            counts[t] = counts.get(t, 0) + 1
    total = W * H
    print("world %dx%d = %d cells, %d KB encoded"
          % (W, H, total, len(payload["tiles_b64_deflate"]) // 1024))
    print("worldmap.png %dx%d" % (W * 4, H * 4))
    for t, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print("  %-14s %6d  %5.1f%%" % (ORDER[t], n, 100.0 * n / total))


if __name__ == "__main__":
    main()
