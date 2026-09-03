#!/usr/bin/env python3
"""Build the world: rings of an onion, dug outward from one town.

The journey used to be a linear climb — eight chapters south to north, and the
only direction that meant anything was up. It is now **radial**. The town sits
at the middle and you may walk any way out of it. North the ground rises to the
mountain; the other quarters are their own countries, and the mountain cannot be
finished without what is in them.

Two structures do all the work:

  RINGS      Distance from town is difficulty. Ring 0 is the town itself, and
             each ring out is a tier: anomalies there are drawn from a harder
             and *swingier* distribution. Rings are concentric because the
             player should be able to choose difficulty by walking, in any
             direction, without being told which way is allowed.

  SECTORS    Direction is character. Mountain north, desert east, ocean south,
             jungle west — blended by *angle* rather than cut at a boundary, so
             the desert becomes scrub becomes jungle over thirty tiles and
             nobody can point at where one ends.

Both fields are continuous, which is the whole trick: difficulty and biome are
functions of position, so there are no zone walls to draw and none to maintain.

Two outputs, and the important thing about them is that **the drawn map is a
rendering of the tile grid, not a separate picture of it**:

    data/world/overworld.json      the grid the game walks on
    assets/world/worldmap.png      the drawn map, rendered from that same grid

Generated together from one source, so they cannot drift. A hand-painted map
beside a hand-built tilemap is two descriptions of one place that will disagree
within a week, and the player is who finds out.

The JSON now also carries the **elevation field** and the **anomaly spawns**.
The elevation was previously computed, used to hillshade the drawn map, and then
thrown away — which is exactly why the map has depth and the tilemap has none.
Same data, one consumer.

    python3 tools/make_world.py
"""
import base64
import json
import math
import os
import random
import sys
import zlib

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(ROOT, "data", "themes", "firstlight.json")
DATA_OUT = os.path.join(ROOT, "data", "world")
ART_OUT = os.path.join(ROOT, "assets", "world")


def tile_order():
    """The tile list, read out of the tool that draws them rather than copied.

    Sheet index IS the id stored in the world grid, so a second copy of this
    list would be a second chance to disagree with it.
    """
    src = open(os.path.join(ROOT, "tools", "make_tiles.py")).read()
    body = src.split("ORDER = [", 1)[1].split("]", 1)[0]
    return [p.strip().strip('"') for p in body.replace("\n", "").split(",") if p.strip()]


ORDER = tile_order()
T = {name: i for i, name in enumerate(ORDER)}

W = H = 256
CENTRE = (W // 2, H // 2)

RING_WIDTH = 24.0          # tiles per difficulty tier
MAX_TIER = 4               # ring 0 is the town; 4 is the far edge

SEA = 0.30
SHORE = 0.35
GRASS = 0.52
HILL = 0.66
SCREE = 0.79
SNOW = 0.89

## The dry and wet ends of the moisture axis, which is where the five materials
## the tileset drew and the generator never made now live. All of them are
## thresholds on the same two fields (plus, for ice, the field's own gradient),
## because a test on anything else is a boundary — see biome().
HARDPAN = 0.10           # the driest ground there is: cracked flat
DUNE = 0.22              # dry, and above the shore band, so deep desert
MARSH = 0.75             # wet enough to be standing water
MARSH_TOP = 0.45         # ...and low enough for it to sit there
UNDERGROWTH = 0.66       # damp: the walkable floor between grass and wood
CANOPY = 0.82            # wet: closed forest
ICE_SLOPE = 0.0015       # elevation change per cell; flat ground, high up

## Each quarter of the world, as a compass bearing and what it does to the two
## fields. Weights fall off with angular distance, so a sector is a *bias*, not
## a border — the desert thins into scrub and the scrub thickens into jungle
## with no line anywhere.
##
## (bearing degrees, elevation push, moisture push, name)
SECTORS = [
    (90.0, 0.52, -0.14, "mountain"),   # north: the climb, and the endgame
    (0.0, -0.04, -0.42, "desert"),     # east: dry, open, low
    (270.0, -0.40, 0.12, "ocean"),     # south: falls away into water
    (180.0, -0.02, 0.42, "jungle"),    # west: wet, dense, close
]

## The story beats keep their names and their prose; what changes is that they
## are now *places in a radial world* rather than rungs of a ladder. Bearing in
## degrees, radius in tiles from the town.
REGIONS = [
    ("waking_room", 202.0, 34.0),
    ("the_house", 202.0, 34.0),
    ("the_town", 0.0, 0.0),
    ("tall_grass", 175.0, 52.0),
    ("long_road", 20.0, 58.0),
    ("foothills", 80.0, 62.0),
    ("observatory", 105.0, 88.0),
    ("summit", 90.0, 112.0),
]


def theme_colors():
    data = json.load(open(THEME))
    return {k: tuple(int(v.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            for k, v in data["colors"].items()}


C = theme_colors()


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


class Noise:
    """Value noise on a wrapping lattice.

    Hand-rolled rather than imported: these tools run anywhere with nothing but
    PIL, and one lattice of seeded randoms with smoothstep interpolation is
    twenty lines.
    """

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
        # Smoothstep, not linear: linear interpolation leaves diamond creases
        # along the lattice, and on a coastline those read as geometry.
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


def polar(x, y):
    """Distance from town in tiles, and bearing in degrees (0 east, 90 north)."""
    dx = x - CENTRE[0]
    dy = CENTRE[1] - y          # screen y grows downward; bearings do not
    return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx)) % 360.0


def sector_weights(bearing):
    """How much each sector claims this bearing.

    A raised cosine over the angular distance, normalised. Every point is a
    blend of at least two sectors, which is what makes the quarters bleed into
    one another instead of meeting at a seam.
    """
    weights = []
    for deg, _, _, _ in SECTORS:
        delta = abs((bearing - deg + 180.0) % 360.0 - 180.0)
        # cos^2, reaching zero at 90 degrees. Smooth everywhere including the
        # diagonals, where two neighbouring quarters meet at half each.
        #
        # The first attempt clamped at 135 degrees and squared, which put a
        # discontinuity on the diagonals and cut the map into visible triangular
        # wedges. The second halved the angle to soften it, and softened it so
        # far that a sector held only 46% weight *at its own bearing* — the
        # opposite failure, where no quarter ever commits to being anything and
        # half the world comes out the same grass.
        w = max(0.0, math.cos(math.radians(delta)))
        weights.append(w * w)
    total = sum(weights) or 1.0
    return [w / total for w in weights]


def tier_at(radius):
    """Difficulty ring. 0 is the town, MAX_TIER the far edge."""
    return max(0, min(MAX_TIER, int(radius / RING_WIDTH)))


def build_fields():
    """Elevation and moisture over the whole grid."""
    en = Noise(20260901, 64)
    mn = Noise(4241, 64)
    elev = [[0.0] * W for _ in range(H)]
    moist = [[0.0] * W for _ in range(H)]

    for y in range(H):
        for x in range(W):
            radius, bearing = polar(x, y)
            weights = sector_weights(bearing)

            # Sector character, scaled by how far out we are: the town is
            # temperate whichever way you look, and the world only commits to
            # being a desert or an ocean once you have walked into one.
            reach = min(1.0, radius / (RING_WIDTH * MAX_TIER))
            push_e = sum(w * s[1] for w, s in zip(weights, SECTORS))
            push_m = sum(w * s[2] for w, s in zip(weights, SECTORS))

            # Elevation ramps with the square of reach so the mountain climbs
            # steeply rather than sloping the whole quarter; moisture is linear
            # because a desert gets dry gradually.
            e = 0.50 + push_e * reach * reach + (en.fbm(x, y, 44.0, 5) - 0.5) * 0.26
            m = 0.50 + push_m * reach + (mn.fbm(x, y, 36.0, 3) - 0.5) * 0.36

            # A coast at the very rim, so the world ends in water rather than at
            # the bounds of an array. Only the outermost few tiles: pulling from
            # 18 tiles in dropped a whole ring of the map into the beach band and
            # turned a third of the world to sand.
            edge = min(x, W - 1 - x, y, H - 1 - y) / 7.0
            e *= min(1.0, edge) * 0.72 + 0.28

            elev[y][x] = max(0.0, min(1.0, e))
            moist[y][x] = max(0.0, min(1.0, m))
    return elev, moist


def slope_field(elev):
    """How fast the ground is changing height, per cell.

    A third *derived* quantity, not a third input: it is the gradient of the
    elevation we already have. It buys the one distinction the two raw fields
    cannot make, which is between a peak and a plateau — both are simply "high".
    Ice needs that, because a frozen tarn is flat ground high up and a snowfield
    is the steep ground around it. Central differences, halved, so the number is
    an elevation change per cell rather than per two.
    """
    out = [[0.0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            dx = elev[y][min(W - 1, x + 1)] - elev[y][max(0, x - 1)]
            dy = elev[min(H - 1, y + 1)][x] - elev[max(0, y - 1)][x]
            out[y][x] = math.hypot(dx, dy) * 0.5
    return out


def biome(e, m, s):
    """A tile id from the two fields, and from nothing else.

    Deliberately blind to which sector it is in. The first version tested the
    sector weights here — `if desert > 0.45: sand` — and that test is a boundary
    however smoothly the weights were blended: the map came out cut into
    triangular wedges with seams on the diagonals.

    The sectors belong in the *fields*, where they bend elevation and moisture
    continuously. By the time we are choosing a tile there is nothing left but
    two numbers, so a desert is simply somewhere dry and a shore is simply where
    the ground crosses sea level.

    `s` is the third argument and it is not a third field: it is the *gradient*
    of the elevation already passed in, which is the only thing that separates a
    plateau from a peak. Nothing else may be added here.

    The tileset drew twenty-five materials and this function used to emit seven,
    so dune, hardpan, undergrowth, mud and ice existed as art with props authored
    for them and not one cell anywhere. They are bands on the same two numbers:

      hardpan       the driest ground of all — cracked flat, nothing grows
      dune          dry, and above the shore band, so it is desert not beach
      mud           wet *and* low: water with nowhere to drain, which is where
                    the jungle runs into the sea
      undergrowth   damp: the walkable floor of a wood, between open grass and
                    closed canopy, so a forest now has an edge you walk through
      ice           above the snow line where the ground has stopped climbing
    """
    if e < SEA:
        return T["water"]
    # Marsh before the shore band, because a wet shore is a marsh and not a
    # beach: the test that matters is where the water cannot drain, not how
    # close the coast is.
    if m >= MARSH and e < MARSH_TOP:
        return T["mud"]
    if e < SHORE:
        return T["sand"]
    if e < GRASS:
        if m < HARDPAN:
            return T["hardpan"]
        if m < DUNE:
            return T["dune"]
        if m < 0.30:
            return T["sand"]
        if m > CANOPY:
            return T["forest"]
        if m > UNDERGROWTH:
            return T["undergrowth"]
        return T["grass_short"]
    if e < HILL:
        if m < HARDPAN:
            return T["hardpan"]
        if m < DUNE:
            return T["dune"]
        if m < 0.27:
            return T["sand"]
        # Higher ground sheds water, so every wet band asks for a little more of
        # it up here — the same two-point offset the old thresholds used.
        if m > CANOPY + 0.02:
            return T["forest"]
        if m > UNDERGROWTH + 0.02:
            return T["undergrowth"]
        return T["grass_tall"] if m > 0.50 else T["grass_short"]
    if e < SCREE:
        return T["scree"] if m < 0.55 else T["grass_short"]
    if e < SNOW:
        return T["scree"]
    # Above the snow line the question is no longer how high but how steep: the
    # summit plateau is flat and freezes over, the flanks it sits on do not.
    return T["ice"] if s < ICE_SLOPE else T["snow"]


def region_cells():
    """Story anchors placed by bearing and radius."""
    out = {}
    for name, bearing, radius in REGIONS:
        rad = math.radians(bearing)
        x = int(round(CENTRE[0] + math.cos(rad) * radius))
        y = int(round(CENTRE[1] - math.sin(rad) * radius))
        out[name] = (max(2, min(W - 3, x)), max(2, min(H - 3, y)))
    return out


class World:
    def __init__(self, tiles, elev):
        self.tiles = tiles
        self.elev = elev

    def at(self, x, y):
        if 0 <= x < W and 0 <= y < H:
            return self.tiles[y][x]
        return T["void"]

    def put(self, x, y, tile):
        if 0 <= x < W and 0 <= y < H:
            self.tiles[y][x] = tile

    blocked = frozenset()

    def walkable(self, x, y):
        if (x, y) in self.blocked:
            return False
        return self.at(x, y) not in SOLID


SOLID = None      # filled in main(), once ORDER is known


def solid_ids():
    """Which ids cannot be stood on, from the tileset's own manifest.

    make_tiles.py publishes this. A hand-kept copy here would be a third place
    the same list lives, and the last one already went stale the moment the
    tileset grew — three new materials were solid and nothing knew.
    """
    path = os.path.join(ROOT, "assets", "tiles", "tiles.json")
    if os.path.exists(path):
        return set(json.load(open(path)).get("solid_ids", []))
    names = ["wall_plaster", "wall_stone", "water", "rock", "void", "forest", "roof"]
    return {T[n] for n in names if n in T}


def carve_road(world, rng, a, b):
    """A road from a to b that goes round what it cannot climb.

    The previous version's docstring claimed exactly this and then ignored the
    elevation it was handed — it was a greedy walk toward the target that
    happened to look plausible. This one actually reads the field: at each step
    it prefers the neighbour that is closest to the target *and* flattest, so a
    road bends round a hill instead of climbing it, and reaches a coast at a
    beach rather than a cliff.
    """
    x, y = a
    guard = 0
    laid = []
    while (x, y) != b and guard < W * H:
        guard += 1
        best, best_score = None, None
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < W and 0 <= ny < H):
                continue
            closer = math.hypot(b[0] - nx, b[1] - ny)
            climb = abs(world.elev[ny][nx] - world.elev[y][x]) * 260.0
            jitter = rng.random() * 1.4
            # Walls and roofs are expensive but not forbidden: a road must be
            # able to reach a door, and the door is in the wall. Cheap enough to
            # arrive, dear enough never to shortcut through a building.
            through = 0.0
            here = world.at(nx, ny)
            if here in (T["wall_plaster"], T["wall_stone"], T["roof"]):
                through = 220.0
            score = closer + climb + jitter + through
            if best_score is None or score < best_score:
                best, best_score = (nx, ny), score
        if best is None:
            break
        x, y = best
        laid.append((x, y))

    for (rx, ry) in laid:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if abs(dx) + abs(dy) > 1:
                    continue
                if world.at(rx + dx, ry + dy) == T["water"]:
                    world.put(rx + dx, ry + dy, T["bridge"])
                elif world.at(rx + dx, ry + dy) != T["bridge"]:
                    world.put(rx + dx, ry + dy, T["path_dirt"])
    return laid


def stamp_town(world, rng, centre):
    """A town with streets, and buildings that face them.

    The old one was a jittered lattice of rectangles with random skips: no
    streets, no lots, doors on the south face whether or not anything was there,
    and roads carved *before* it so the buildings were painted over them. This
    lays two crossing streets first, then puts buildings in the lots between,
    each with its door on the side that actually touches a street.
    """
    cx, cy = centre
    half = 22

    for y in range(cy - half, cy + half + 1):
        for x in range(cx - half, cx + half + 1):
            if math.hypot(x - cx, y - cy) <= half:
                world.put(x, y, T["floor_stone"])

    streets = []
    for offset in (-9, 9):
        for i in range(-half, half + 1):
            streets.append((cx + i, cy + offset))
            streets.append((cx + offset, cy + i))
    for (sx, sy) in streets:
        if math.hypot(sx - cx, sy - cy) <= half:
            world.put(sx, sy, T["path_dirt"])

    # Lots between the streets. A building is placed only if its whole footprint
    # is free and one of its edges touches a street, so every door opens onto
    # somewhere you can actually walk.
    for ly in (-19, -4, 12):
        for lx in (-19, -4, 12):
            if rng.random() < 0.2:
                continue
            bw, bh = rng.randint(5, 7), rng.randint(4, 6)
            ox, oy = cx + lx + rng.randint(0, 1), cy + ly + rng.randint(0, 1)
            if math.hypot(ox - cx, oy - cy) > half - 6:
                continue
            touches = any(
                world.at(ox + i, oy + bh) == T["path_dirt"] for i in range(bw))
            if not touches:
                continue
            for y in range(oy, oy + bh):
                for x in range(ox, ox + bw):
                    world.put(x, y, T["roof"])
            world.put(ox + bw // 2, oy + bh - 1, T["door"])


def coast_stop(world, bearing):
    """How far a road out of town should go on this bearing.

    Walk outward until the land runs out, then back up to the last dry tile. A
    road that simply aimed at a fixed distance built a bridge straight out into
    open ocean — the south road ran off the beach and kept going, which is the
    dead-end-in-a-wall problem wearing different clothes.
    """
    rad = math.radians(bearing)
    last = None
    for step in range(8, int(RING_WIDTH * MAX_TIER) + 24):
        x = int(round(CENTRE[0] + math.cos(rad) * step))
        y = int(round(CENTRE[1] - math.sin(rad) * step))
        if not (4 <= x < W - 4 and 4 <= y < H - 4):
            break
        if world.at(x, y) in (T["water"], T["void"]):
            break
        last = (x, y)
    return last


def stamp_house(world, cells):
    """The house you wake in.

    Restored: the radial rewrite dropped this along with the observatory and the
    summit, so the first room of the game was an unmarked patch of town square
    with a bed standing in it. The waking room and the house are the same
    building — upstairs and down — which is why they share an anchor.
    """
    cx, cy = cells["waking_room"]
    x0, y0, w, h = cx - 8, cy - 7, 17, 14
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            edge = x in (x0, x0 + w - 1) or y in (y0, y0 + h - 1)
            world.put(x, y, T["wall_plaster"] if edge else T["floor_boards"])
    # An internal wall with a doorway: the room you wake in, and the one with
    # the kettle in it.
    for x in range(x0 + 1, x0 + w - 1):
        if abs(x - cx) > 1:
            world.put(x, cy, T["wall_plaster"])
    world.put(cx, y0 + h - 1, T["door"])


def stamp_observatory(world, cells):
    """A stone drum on a ridge, one door facing back down the hill."""
    cx, cy = cells["observatory"]
    r = 8
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            d = math.hypot(x - cx, y - cy)
            if d > r:
                continue
            world.put(x, y, T["wall_stone"] if d > r - 1.6 else T["floor_stone"])
    world.put(cx, cy + r - 1, T["door"])


def stamp_summit(world, cells):
    """The door in the rock, and bare stone all round it so it is the only thing
    to look at when you finally get up here."""
    cx, cy = cells["summit"]
    for y in range(cy - 6, cy + 7):
        for x in range(cx - 7, cx + 8):
            world.put(x, y, T["floor_stone"])
    for x in range(cx - 7, cx + 8):
        world.put(x, cy - 6, T["rock"])
    world.put(cx, cy - 6, T["door"])


def reachable(world, start):
    """Every cell you can actually walk to from the spawn.

    Generated worlds are full of places that look connected and are not, and a
    story beat behind a wall is a run the player cannot finish. This is the
    check that turns that from a bug report into a build failure.
    """
    seen = set()
    stack = [start]
    while stack:
        cell = stack.pop()
        if cell in seen:
            continue
        x, y = cell
        if not world.walkable(x, y):
            continue
        seen.add(cell)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if nxt not in seen:
                stack.append(nxt)
    return seen


def name_anomalies(cells, anomalies):
    """The eight written chapters, as fixed anomalies at their own anchors.

    Chapters used to be a sequence you were handed one at a time. They are now
    *places*: the Waking Room is still the Waking Room and still opens with the
    ceiling you cannot place, but you reach it by walking to it, and its
    difficulty is the ring it sits in rather than its number.

    Procedural anomalies fill the rest of the world. These eight are the spine.
    """
    named = []
    for area_id, (cx, cy) in cells.items():
        radius = math.hypot(cx - CENTRE[0], cy - CENTRE[1])
        named.append({
            "x": cx, "y": cy,
            "tier": tier_at(radius),
            "sector": SECTORS[max(range(4), key=lambda i: sector_weights(polar(cx, cy)[1])[i])][3],
            "area": area_id,
        })
    # A procedural spawn sitting on a story anchor would hide it, so the named
    # ones win their cell.
    taken = {(a["x"], a["y"]) for a in named}
    return named + [a for a in anomalies
                    if (a["x"], a["y"]) not in taken
                    and all(math.hypot(a["x"] - n["x"], a["y"] - n["y"]) > 8 for n in named)]


def place_anomalies(world, rng, reach):
    """Where the roguelite content lives.

    Difficulty is position: the tier of an anomaly is its ring, so the player
    chooses how hard the game is by choosing how far to walk. Spread by a
    minimum separation rather than at random, because two anomalies in sight of
    each other is one decision, not two.
    """
    out = []
    per_tier = {0: 2, 1: 5, 2: 6, 3: 6, 4: 4}
    for tier, count in per_tier.items():
        placed = 0
        attempts = 0
        while placed < count and attempts < 4000:
            attempts += 1
            angle = rng.random() * math.tau
            radius = (tier + rng.random()) * RING_WIDTH
            x = int(round(CENTRE[0] + math.cos(angle) * radius))
            y = int(round(CENTRE[1] - math.sin(angle) * radius))
            if (x, y) not in reach:
                continue
            if any(math.hypot(x - a["x"], y - a["y"]) < 14 for a in out):
                continue
            _, bearing = polar(x, y)
            weights = sector_weights(bearing)
            sector = SECTORS[max(range(4), key=lambda i: weights[i])][3]
            out.append({"x": x, "y": y, "tier": tier, "sector": sector})
            placed += 1
    return out


def encode(tiles):
    """One byte per cell, deflated, base64.

    Plain zlib.compress, header and all: Godot's COMPRESSION_DEFLATE is
    zlib-wrapped despite the name, and raw deflate (wbits=-15) decompresses to
    zero bytes without erroring. Verified by round-tripping every pairing. If
    you change this, re-test it.
    """
    raw = bytes(bytearray(t for row in tiles for t in row))
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def scatter_props(world, elev, rng, reach):
    """Put things in the world.

    The measured failure was that half of all possible screens showed exactly
    one material and the room you wake in had no bed. Terrain alone cannot fix
    that: a field of perfect grass is still a field of nothing. Props are what
    turn ground into somewhere.

    Density is per walkable cell of the material the prop belongs to, declared
    by the tileset rather than guessed here. A prop occupies its foot cells and
    those become impassable when it says so, which is what stops a boulder being
    scenery you can stand inside.
    """
    manifest = json.load(open(os.path.join(ROOT, "assets", "tiles", "tiles.json")))
    catalogue = manifest["props"]["list"]
    by_biome = {}
    for prop in catalogue:
        by_biome.setdefault(prop["biome"], []).append(prop)

    plane = [[0] * W for _ in range(H)]
    blocked = set()

    def free(x, y, foot):
        for fy in range(foot[1]):
            for fx in range(foot[0]):
                cx, cy = x + fx, y - fy
                if (cx, cy) in blocked or plane[cy][cx] != 0:
                    return False
                if not world.walkable(cx, cy):
                    return False
                # Never on a road or in a doorway: those are the two places the
                # player is guaranteed to be walking through.
                if world.at(cx, cy) in (T["path_dirt"], T["door"], T["bridge"]):
                    return False
        return True

    def beside_road(x, y):
        return any(world.at(x + dx, y + dy) == T["path_dirt"]
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))

    for y in range(1, H - 1):
        for x in range(1, W - 1):
            material = ORDER[world.at(x, y)]
            options = list(by_biome.get(material, []))

            # Road furniture is authored for roads and the placement rule refuses
            # roads — a signpost cannot stand in the lane the player walks down.
            # A milestone was never *on* the road anyway; it was beside it. So
            # props declared for path_dirt are offered to the walkable cells that
            # touch a road, which is where they actually belong.
            if beside_road(x, y) and world.at(x, y) != T["path_dirt"]:
                options = options + by_biome.get("path_dirt", [])

            if not options or (x, y) not in reach:
                continue
            for prop in options:
                if rng.random() >= prop["density"]:
                    continue
                foot = prop["foot"]
                if not free(x, y, foot):
                    break
                plane[y][x] = prop["plane"]
                if prop["solid"]:
                    for fy in range(foot[1]):
                        for fx in range(foot[0]):
                            blocked.add((x + fx, y - fy))
                break
    return plane, blocked


def furnish_house(world, plane, cells):
    """The bedroom you wake in, which had nothing in it at all.

    Placed by hand rather than scattered, because this is the first thing anyone
    sees and a randomly positioned bed is worse than none.
    """
    manifest = json.load(open(os.path.join(ROOT, "assets", "tiles", "tiles.json")))
    interior = {p["id"]: p["plane"] for p in manifest["props"]["list"]
                if p["biome"] == "placed"}
    cx, cy = cells["waking_room"]
    # dy == 0 is the internal wall stamp_house lays down for every x more than
    # one cell from centre, so a chair at (cx+2, cy) was being placed into a
    # wall and silently dropped — a piece of furniture that has never existed.
    # Nothing checks `placed` props, so the only way to find this was to look.
    layout = [("bed", -2, -1), ("chair", 2, -1), ("table", 3, -2),
              ("bookshelf", -3, 1), ("chest", 2, 2), ("floor_lamp", -3, -2),
              ("plant_pot", 3, 2), ("rug", 0, 1)]
    for name, dx, dy in layout:
        if dy == 0 and abs(dx) > 1:
            continue        # would be the internal wall; skip rather than lose it silently
        if name not in interior:
            continue
        x, y = cx + dx, cy + dy
        if 0 <= x < W and 0 <= y < H and world.walkable(x, y):
            plane[y][x] = interior[name]


def terrace(elev, levels=5):
    """Quantise elevation into steps, then smooth the steps into contours.

    Quantising alone is not enough. Noise crossing a threshold produces a
    speckle of one-cell drops, and a one-cell drop rendered as a cliff is a
    block sitting on the grass rather than an escarpment — which is exactly how
    the first version looked. A majority filter pulls the boundaries into long
    contours, so a terrace edge runs along the land the way a real one does.
    """
    steps = [[min(levels - 1, int(e * levels)) for e in row] for row in elev]
    for _ in range(3):
        out = [row[:] for row in steps]
        for y in range(1, H - 1):
            for x in range(1, W - 1):
                tally = {}
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        v = steps[y + dy][x + dx]
                        tally[v] = tally.get(v, 0) + 1
                out[y][x] = max(tally, key=lambda k: (tally[k], -abs(k - steps[y][x])))
        steps = out
    return steps


def stock_town(world, plane, centre, rng):
    """The town, which had streets and buildings and nothing in them.

    Placed rather than scattered: town props belong beside a building or along a
    street, and scattering them across flagstone would read as debris. A well in
    the middle of a square is a landmark; a well two tiles from a wall is
    litter.
    """
    manifest = json.load(open(os.path.join(ROOT, "assets", "tiles", "tiles.json")))
    placed = {p["id"]: p for p in manifest["props"]["list"] if p["biome"] == "placed"}
    cx, cy = centre

    def put(name, x, y):
        prop = placed.get(name)
        if prop is None or not (0 <= x < W and 0 <= y < H):
            return
        if not world.walkable(x, y) or plane[y][x] != 0:
            return
        if world.at(x, y) == T["door"]:
            return
        plane[y][x] = prop["plane"]

    put("well", cx + 1, cy - 2)
    for i, name in enumerate(["market_stall", "cart", "barrel", "crate"]):
        put(name, cx - 6 + i * 3, cy + 4)
    for offset in (-13, -5, 5, 13):
        put("lamppost", cx + offset, cy - 9)
        put("lamppost", cx + offset, cy + 9)
    put("bench", cx - 3, cy - 2)
    put("bench", cx + 4, cy + 2)
    put("standing_stone", cx - 15, cy - 14)

    # Barrels and crates against the walls of whatever buildings are here.
    for _ in range(40):
        x = cx + rng.randint(-20, 20)
        y = cy + rng.randint(-20, 20)
        if world.at(x, y) == T["roof"] or not world.walkable(x, y):
            continue
        touching = any(world.at(x + dx, y + dy) == T["roof"]
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if touching:
            put(rng.choice(["barrel", "crate"]), x, y)


MIN_CLIFF_RUN = 4         # cells; shorter than this reads as a block, not a bluff
MIN_CLIFF_DROP = 0.004    # elevation, so a cliff only forms on genuinely steep ground


def cliff_plane(steps, elev):
    """Where the ground steps down hard enough and far enough to be a cliff.

    Returns a plane the renderer draws directly rather than a rule it has to
    re-derive, because the rule is not local: whether a cell is a cliff depends
    on how far the drop runs either side of it, and asking the renderer to
    measure that per frame would be both slow and a second implementation to
    disagree with.

    Two conditions, and the first version had neither, which is why cliffs came
    out as isolated blocks scattered over gentle grass:

      the drop must be steep     — a terrace boundary drawn across a shallow
                                   slope is a wall where the eye expects a hill
      the drop must be long      — a bluff three cells wide is a crate

    1 left end, 2 middle, 3 right end.
    """
    plane = [[0] * W for _ in range(H)]
    for y in range(1, H):
        x = 0
        while x < W:
            if not (steps[y - 1][x] > steps[y][x]
                    and elev[y - 1][x] - elev[y][x] > MIN_CLIFF_DROP):
                x += 1
                continue
            start = x
            while (x < W and steps[y - 1][x] > steps[y][x]
                   and elev[y - 1][x] - elev[y][x] > MIN_CLIFF_DROP):
                x += 1
            if x - start < MIN_CLIFF_RUN:
                continue
            for i in range(start, x):
                plane[y][i] = 1 if i == start else (3 if i == x - 1 else 2)
    return plane


def encode_plane(plane):
    raw = bytes(bytearray(v for row in plane for v in row))
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def encode_elevation(elev):
    """The elevation field, quantised to a byte a cell.

    Exported because the renderer needs it. It was computed, used to hillshade
    the drawn map, and thrown away — which is precisely why the map has depth
    and the tilemap does not. A byte is plenty: this drives shading, not
    collision.
    """
    raw = bytes(bytearray(
        max(0, min(255, int(round(e * 255.0)))) for row in elev for e in row))
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def draw_map(world, cells, anomalies, px=3):
    """The drawn map: the same grid, rendered as something you would pin up."""
    colour = {
        T["water"]: mix(C["accent_2"], C["bg"], 0.62),
        T["sand"]: mix(mix(C["bg"], C["accent"], 0.30), C["muted"], 0.26),
        T["grass_short"]: mix(C["good"], C["bg"], 0.72),
        T["grass_tall"]: mix(C["good"], C["bg"], 0.64),
        T["forest"]: mix(C["good"], C["bg"], 0.86),
        T["scree"]: mix(mix(C["line"], C["muted"], 0.45), C["bg"], 0.30),
        T["snow"]: mix(C["muted"], C["bg"], 0.26),
        # The five the generator never used to make. Kept in the same family as
        # the material they sit beside — dune is sand with the sun on it, mud is
        # sand with the light gone out of it — so the map still reads as four
        # countries rather than twelve.
        T["dune"]: mix(mix(C["bg"], C["accent"], 0.46), C["muted"], 0.18),
        T["hardpan"]: mix(mix(C["bg"], C["accent"], 0.34), C["danger"], 0.15),
        T["mud"]: mix(mix(C["bg"], C["accent"], 0.20), C["line"], 0.42),
        T["undergrowth"]: mix(mix(C["good"], C["warn"], 0.24), C["bg"], 0.74),
        T["ice"]: mix(C["accent_2"], C["text"], 0.42),
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
            base = colour.get(world.at(x, y), C["bg"])
            # Hillshade from the elevation field's own gradient, light from the
            # north-west — the convention every relief map uses, because the eye
            # reads the other direction as pits.
            dzdx = world.elev[y][min(W - 1, x + 1)] - world.elev[y][max(0, x - 1)]
            dzdy = world.elev[min(H - 1, y + 1)][x] - world.elev[max(0, y - 1)][x]
            shade = max(-1.0, min(1.0, (dzdy - dzdx) * 7.0))
            c = mix(base, C["text"], shade * 0.30) if shade > 0 \
                else mix(base, C["bg"], -shade * 0.42)
            for j in range(px):
                for i in range(px):
                    out[x * px + i, y * px + j] = c

    for a in anomalies:
        for ring in (3, 4):
            for step in range(0, 360, 6):
                ax = int(a["x"] * px + px // 2 + math.cos(math.radians(step)) * ring)
                ay = int(a["y"] * px + px // 2 + math.sin(math.radians(step)) * ring)
                if 0 <= ax < W * px and 0 <= ay < H * px:
                    out[ax, ay] = C["danger"]
    for name, (cx, cy) in cells.items():
        r = 9 if name in ("summit", "the_town") else 6
        for step in range(0, 360, 4):
            ax = int(cx * px + px // 2 + math.cos(math.radians(step)) * r)
            ay = int(cy * px + px // 2 + math.sin(math.radians(step)) * r)
            if 0 <= ax < W * px and 0 <= ay < H * px:
                out[ax, ay] = C["accent"]
    return img


def main():
    global SOLID
    SOLID = solid_ids()

    os.makedirs(DATA_OUT, exist_ok=True)
    os.makedirs(ART_OUT, exist_ok=True)

    # One generator, threaded through everything. The previous version created a
    # seeded RNG and then called the bare global random.random() inside the road
    # carver, so the world was not reproducible at all despite the docstring
    # promising it was. Two runs produced two different worlds.
    rng = random.Random(20260901)

    elev, moist = build_fields()
    grade = slope_field(elev)
    tiles = [[biome(elev[y][x], moist[y][x], grade[y][x]) for x in range(W)]
             for y in range(H)]
    world = World(tiles, elev)
    cells = region_cells()

    stamp_town(world, rng, CENTRE)
    stamp_house(world, cells)
    stamp_observatory(world, cells)
    stamp_summit(world, cells)

    # Roads last, so nothing is painted over them. This is why the old map had
    # roads that dead-ended in walls: the town, observatory and summit were all
    # stamped after the carve and simply overwrote it.
    # Out of town every way, not only toward the northern story beats. The
    # player may leave in any direction and should find a road doing the same.
    for name in ("summit", "observatory", "foothills", "long_road", "tall_grass",
                 "waking_room"):
        carve_road(world, rng, CENTRE, cells[name])
    for bearing in (0.0, 90.0, 180.0, 270.0):
        target = coast_stop(world, bearing)
        if target is not None:
            carve_road(world, rng, CENTRE, target)

    spawn = cells["the_town"]
    reach = reachable(world, spawn)

    # A cliff face is the wall of a terrace, and you cannot walk up a wall. The
    # renderer derives the same faces from the same quantisation, so the picture
    # and the collision cannot disagree.
    steps = terrace(elev)
    cliffs = cliff_plane(steps, elev)
    faces = {(x, y) for y in range(H) for x in range(W) if cliffs[y][x]}

    props, _scattered = scatter_props(world, elev, rng, reach)
    stock_town(world, props, CENTRE, rng)
    furnish_house(world, props, cells)

    # The collision plane is *derived* from the finished prop plane rather than
    # accumulated while scattering, and it is derived by the same function the
    # Tiled importer uses (tools/world_to_tiled.py, imported rather than copied —
    # a second implementation of this rule is a second chance to disagree with
    # it). It has to be: a prop you place by hand in Tiled has to block, and the
    # importer can only see the plane, so the generated file and the imported one
    # can only agree if one rule produces both.
    #
    # It also fixes what the accumulate-as-you-go version got wrong. stock_town
    # and furnish_house run *after* scatter_props and only wrote to the plane, so
    # the well, the benches, the lampposts and the whole bedroom were solid in the
    # catalogue and walk-through in the game. Deriving from the finished plane
    # picks them up — 31 cells, none of which cuts anything off.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from world_to_tiled import derive_blocked, props_by_plane
    blocked_plane = derive_blocked([v for row in props for v in row],
                                   [v for row in cliffs for v in row],
                                   W, H, props_by_plane())
    blocked = {(i % W, i // W) for i, v in enumerate(blocked_plane) if v}

    # Props that block have to be part of walkability, so reachability is
    # measured on the world the player will actually meet rather than on the
    # bare terrain underneath it.
    world.blocked = blocked
    reach = reachable(world, spawn)
    anomalies = name_anomalies(cells, place_anomalies(world, rng, reach))

    stranded = [n for n, c in cells.items() if c not in reach]

    payload = {
        "_comment": "Generated by tools/make_world.py. Do not hand-edit; edit in "
                    "Tiled and import, or regenerate. Tile ids index ORDER in "
                    "tools/make_tiles.py.",
        "w": W, "h": H,
        "ring_width": RING_WIDTH,
        "max_tier": MAX_TIER,
        "centre": {"x": CENTRE[0], "y": CENTRE[1]},
        "tiles_b64_deflate": encode(tiles),
        "elevation_b64_deflate": encode_elevation(elev),
        "props_b64_deflate": encode_plane(props),
        # A prop's art is 64x96 and its collision is one or two cells at its
        # foot, so solidity cannot be derived from the prop plane alone — the
        # anchor cell is not the whole footprint. Exported as its own plane
        # rather than recomputed in the engine from the same manifest twice.
        "blocked_b64_deflate": encode_plane(
            [blocked_plane[y * W:(y + 1) * W] for y in range(H)]),
        "cliffs_b64_deflate": encode_plane(cliffs),
        "terrace_levels": 5,
        "regions": {n: {"x": c[0], "y": c[1]} for n, c in cells.items()},
        "anomalies": anomalies,
        "spawn": {"x": spawn[0], "y": spawn[1]},
    }
    path = os.path.join(DATA_OUT, "overworld.json")
    json.dump(payload, open(path, "w"), indent=1)
    open(path, "a").write("\n")

    draw_map(world, cells, anomalies).save(os.path.join(ART_OUT, "worldmap.png"))

    counts = {}
    for row in tiles:
        for t in row:
            counts[t] = counts.get(t, 0) + 1
    total = W * H
    print("world %dx%d = %d cells, %d KB tiles + %d KB elevation"
          % (W, H, total, len(payload["tiles_b64_deflate"]) // 1024,
             len(payload["elevation_b64_deflate"]) // 1024))
    print("reachable from spawn: %d cells (%.1f%% of walkable)"
          % (len(reach), 100.0 * len(reach) / max(1, sum(
              1 for y in range(H) for x in range(W) if world.walkable(x, y)))))
    filled = sum(1 for row in props for v in row if v)
    print("props: %d placed (%.1f%% of cells), %d of them solid"
          % (filled, 100.0 * filled / (W * H), len(blocked)))
    print("cliff cells: %d" % len(faces))
    named = sum(1 for a in anomalies if a.get("area"))
    print("anomalies: %d  (%d named story beats, %d procedural)"
          % (len(anomalies), named, len(anomalies) - named))
    for tier in range(MAX_TIER + 1):
        band = [a for a in anomalies if a["tier"] == tier]
        secs = {}
        for a in band:
            secs[a["sector"]] = secs.get(a["sector"], 0) + 1
        print("  tier %d: %d  %s" % (tier, len(band), secs))
    for t, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print("  %-14s %6d  %5.1f%%" % (ORDER[t], n, 100.0 * n / total))

    if stranded:
        raise SystemExit("UNREACHABLE story anchors: %s" % ", ".join(stranded))
    print("every story anchor is reachable on foot")


if __name__ == "__main__":
    main()
