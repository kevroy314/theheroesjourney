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
    names = ["wall_plaster", "wall_stone", "wall_timber", "water", "rock",
             "void", "forest", "roof"]
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

    # Buildings, placed *along* the streets rather than in lots that hope to
    # touch one.
    #
    # The previous version put lots at ly in (-19, -4, 12) with heights 4..6 and
    # tested whether `oy + bh` landed on a street row. Streets are at cy +/- 9,
    # and those lots make oy+bh land in {cy-15..cy-12, cy..cy+3, cy+16..cy+19} —
    # never 9 either way. So `touches` was false every time, no building was
    # ever placed, and the town was a paved crossroads. It also only ever tested
    # the *south* edge, so even had the arithmetic worked, half the town could
    # not have faced a street.
    #
    # Walking the streets and setting buildings against them makes "the door
    # opens onto somewhere you can walk" true by construction rather than by a
    # test that can silently never pass.
    taken = set()

    def free(ox, oy, bw, bh):
        for y in range(oy - 1, oy + bh + 1):
            for x in range(ox - 1, ox + bw + 1):
                if (x, y) in taken:
                    return False
                if math.hypot(x - cx, y - cy) > half - 1:
                    return False
                if world.at(x, y) == T["path_dirt"]:
                    return False
        return True

    def place(ox, oy, bw, bh, door):
        for y in range(oy, oy + bh):
            for x in range(ox, ox + bw):
                world.put(x, y, T["roof"])
                taken.add((x, y))
        world.put(door[0], door[1], T["door"])

    # Along the two horizontal streets, on both sides.
    for sy in (cy - 9, cy + 9):
        x = cx - half + 3
        while x < cx + half - 8:
            bw, bh = rng.randint(5, 7), rng.randint(4, 6)
            for side in (-1, 1):
                if rng.random() < 0.25:
                    continue
                oy = sy - bh - 1 if side < 0 else sy + 2
                if free(x, oy, bw, bh):
                    # The door sits on the face looking at the street, one row
                    # inside the roof, so it reads as a doorway and not a gap.
                    dy = oy + bh - 1 if side < 0 else oy
                    place(x, oy, bw, bh, (x + bw // 2, dy))
            x += bw + rng.randint(2, 4)

    # And the two vertical ones, which is what makes the crossroads a place
    # rather than one long row of frontages.
    for sx in (cx - 9, cx + 9):
        y = cy - half + 4
        while y < cy + half - 8:
            bw, bh = rng.randint(5, 7), rng.randint(4, 6)
            for side in (-1, 1):
                if rng.random() < 0.3:
                    continue
                ox = sx - bw - 1 if side < 0 else sx + 2
                if free(ox, y, bw, bh):
                    dx = ox + bw - 1 if side < 0 else ox
                    place(ox, y, bw, bh, (dx, y + bh // 2))
            y += bh + rng.randint(3, 5)


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


# --- the house ----------------------------------------------------------------
#
# Beat 1 of docs/FIRST-THIRTY.md is "the player wakes in a house that has walls,
# an interior floor, furniture, a lit window and a front door that will not
# open", and the owner's note on the old one was "it doesn't even have walls yet
# lol". It had four, in the sense that a rectangle has four sides, and then the
# road carver drove straight through the east one — see the re-stamp in main().
#
# What it has now, and why each part is there rather than being one big room:
#
#   a BEDROOM   with the bed the player wakes in, on plank flooring with a rug
#               in front of the bed, so the first tile they stand on is not the
#               same tile as the last one
#   a KITCHEN   on tile, with the stove that is the only warm light in the house
#   a HALL      on boards, running the width of the building, with the front
#               door at the end of it and the hole in reality somewhere in it
#
# Three rooms, three floors, because §5: "each room inside a building has its
# own floor", and a change of material is what tells you that you have gone
# somewhere. Two internal walls with three doorways between them, so the space
# has to be walked rather than seen.
#
# All of the geometry is in one function that returns a description, and every
# other function here reads that description. Nothing computes a wall position
# twice: the old code worked out the internal wall in stamp_house and worked it
# out AGAIN, differently and wrongly, in furnish_house, which is how a chair
# came to be placed inside a wall and silently dropped.

HOUSE_W, HOUSE_H = 19, 15         # outside dimensions, walls included


def house_plan(cells):
    """Where every wall, floor, doorway and stick of furniture in the house is.

    Interior coordinates (i, j) run 0..16 across and 0..12 down from the cell
    inside the north-west corner, so the layout below reads as a floor plan and
    not as a list of magic world coordinates.
    """
    cx, cy = cells["waking_room"]
    x0, y0 = cx - HOUSE_W // 2, cy - HOUSE_H // 2
    ix, iy = x0 + 1, y0 + 1                       # origin of the interior grid

    def cell(i, j):
        return (ix + i, iy + j)

    plan = {
        "x0": x0, "y0": y0, "w": HOUSE_W, "h": HOUSE_H,
        "ix": ix, "iy": iy, "iw": HOUSE_W - 2, "ih": HOUSE_H - 2,
        "cell": cell,
        # room -> (i0, j0, i1, j1) inclusive, and the material it is floored in
        "rooms": {
            "bedroom": ((0, 0, 6, 6), "floor_plank"),
            "kitchen": ((8, 0, 16, 6), "floor_tile"),
            "hall":    ((0, 8, 16, 12), "floor_boards"),
        },
        # the rug is a patch of a fourth floor inside the bedroom, laid where
        # the player's feet land when they get out of bed
        "rug": (1, 4, 4, 6),
        # internal walls, as runs, and the doorways punched through them
        "walls": [(7, 0, 7, 6), (0, 7, 16, 7)],
        "doorways": [(7, 4), (2, 7), (12, 7)],
        # the front door sits in the south exterior wall; the road stops at the
        # cell outside it, never inside the building
        "door": (x0 + HOUSE_W // 2, y0 + HOUSE_H - 1),
        "door_outside": (x0 + HOUSE_W // 2, y0 + HOUSE_H),
        # windows are props standing on wall cells, so they are (x, y) already
        "windows": [(x0 + 4, y0), (x0 + 13, y0),
                    (x0 + HOUSE_W - 1, y0 + 4), (x0, y0 + 11)],
        # you wake beside the bed, on the rug, and the hole in reality is in the
        # hall — Beat 2: "the player does not spawn on the anomaly"
        "spawn": cell(2, 4),
        # The one hole in reality inside the house, in the hall, two rooms from
        # the bed. Beat 2: "the player does not spawn on the anomaly; it is
        # somewhere else in the house and they have to walk into it."
        "anomaly": cell(12, 10),
        # And where to start looking for the second one, out in the yard. It is
        # resolved against the walkable world in main() rather than fixed here,
        # because what is outside the south wall is generated terrain.
        "yard": (x0 + HOUSE_W + 4, y0 + HOUSE_H + 3),
        # (catalogue id, i, j). Placed by hand rather than scattered, because
        # this is the first room anyone sees and a randomly positioned bed is
        # worse than none. Every entry is checked on placement -- see
        # furnish_house, which now raises rather than dropping a piece.
        #
        # The second half of each room's list is §"evidence of use": "a level
        # should imply an event that already happened. A chair pulled out from a
        # table. A cup left on the counter. Boots by the door." They cost
        # nothing, they are the only narrative device in the room, and the old
        # house used none of them.
        "furniture": [
            # bedroom -- somebody got out of this bed and did not make it
            ("bed", 1, 3), ("chest", 4, 1), ("candle", 5, 1),
            ("floor_lamp", 6, 5), ("book_open", 0, 5), ("bottle", 0, 1),
            ("cat", 3, 6), ("chair", 0, 3), ("bookshelf", 6, 1),
            ("plant_pot", 6, 3), ("boots", 2, 2),
            # kitchen -- a stove lit, a run of counter, a cup left on the end
            ("stove", 9, 1), ("counter", 11, 1), ("counter", 12, 1),
            ("counter", 13, 1), ("cup", 14, 1), ("shelf_open", 16, 1),
            ("table", 12, 4), ("chair", 11, 4), ("chair_pulled", 13, 4),
            ("bottle", 14, 4), ("plant_pot", 16, 6), ("barrel", 8, 1),
            ("crate", 8, 6), ("book_open", 10, 4), ("shelf_open", 16, 5),
            ("chest", 9, 6),
            # hall -- and the boots by the front door
            ("bookshelf", 1, 8), ("chest", 15, 8), ("crate", 13, 9),
            ("boots", 7, 12), ("plant_pot", 0, 12), ("dog", 5, 11),
            ("table", 3, 10), ("chair", 2, 10), ("chair_pulled", 4, 10),
            ("cup", 3, 9), ("bench", 9, 8), ("barrel", 16, 12),
            ("floor_lamp", 11, 12), ("bottle", 12, 8), ("rug", 8, 11),
        ],
        # (type, i, j, label or None). `type` names an entry in
        # data/content/interactables.json; the world only says where.
        "interactables": [
            ("stove", 9, 1, None),
            ("counter", 12, 1, None),
            ("cat", 3, 6, None),
            ("dog", 5, 11, None),
        ],
    }
    return plan


def stamp_house(world, plan):
    """Paint the house. Idempotent, and called twice on purpose.

    The second call is after the roads are carved, and it is not belt and
    braces: the road to the house used to aim at the house's *centre*, and
    carve_road lays path_dirt in a plus around every cell it walks, so the
    generated world had seven columns of road driven through the east wall and
    out across the bedroom floor. A road may arrive at the doorstep and it may
    not come in. Aiming it at `door_outside` fixes the intent; re-stamping
    afterwards makes it true whatever any later pass does.
    """
    x0, y0, w, h = plan["x0"], plan["y0"], plan["w"], plan["h"]
    cell = plan["cell"]

    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            edge = x in (x0, x0 + w - 1) or y in (y0, y0 + h - 1)
            world.put(x, y, T["wall_timber"] if edge else T["floor_boards"])
    for (i0, j0, i1, j1), material in plan["rooms"].values():
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                world.put(*cell(i, j), tile=T[material])
    ri0, rj0, ri1, rj1 = plan["rug"]
    for j in range(rj0, rj1 + 1):
        for i in range(ri0, ri1 + 1):
            world.put(*cell(i, j), tile=T["floor_rug"])
    for (i0, j0, i1, j1) in plan["walls"]:
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                world.put(*cell(i, j), tile=T["wall_timber"])
    for (i, j) in plan["doorways"]:
        # A doorway is a GAP, not a door: the wall's overlay set draws its face
        # into the opening, which reads as a lintel over your head. A `door`
        # tile in an internal wall would be a second front door.
        world.put(*cell(i, j), tile=T["floor_boards"])
    world.put(plan["door"][0], plan["door"][1], T["door"])


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


## Story anchors whose difficulty is NOT their ring.
##
## Difficulty is position everywhere else in this file, and that is the design:
## the player chooses how hard the game is by choosing how far to walk. The
## tutorial is the one place it cannot be, because the first anomaly anyone ever
## steps into has to come out of the easiest pool and the house happens to stand
## 34 tiles from town, which is ring 1. So this is a short, explicit list of
## exceptions rather than a rule bent to fit one case.
FORCED_TIER = {"waking_room": 0}


def nearest_open(want, reach, forbid, *keep_clear):
    """The reachable cell closest to `want` that is not in `forbid` and not
    within four cells of anything in `keep_clear`."""
    best = None
    for radius in range(0, 40):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                cell = (want[0] + dx, want[1] + dy)
                if cell not in reach or cell in forbid:
                    continue
                if any(math.hypot(cell[0] - k[0], cell[1] - k[1]) < 4.0
                       for k in keep_clear):
                    continue
                return cell
        if best:
            break
    raise SystemExit("no reachable cell for a yard anomaly near %s" % (want,))


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
            "tier": FORCED_TIER.get(area_id, tier_at(radius)),
            "sector": SECTORS[max(range(4), key=lambda i: sector_weights(polar(cx, cy)[1])[i])][3],
            "area": area_id,
        })
    # A procedural spawn sitting on a story anchor would hide it, so the named
    # ones win their cell.
    taken = {(a["x"], a["y"]) for a in named}
    # HJWorld._anomaly_at is a Dictionary keyed by cell, so two anomalies on one
    # cell is not two anomalies -- the second overwrites the first and a written
    # chapter silently stops existing. `waking_room` and `the_house` shared an
    # anchor and therefore shared a cell, which is exactly how that happened.
    if len(taken) != len(named):
        seen, clashes = {}, []
        for a in named:
            key = (a["x"], a["y"])
            if key in seen:
                clashes.append("%s and %s both at %s" % (seen[key], a["area"], key))
            seen[key] = a["area"]
        raise SystemExit("two story anomalies on one cell: " + "; ".join(clashes))
    return named + [a for a in anomalies
                    if (a["x"], a["y"]) not in taken
                    and all(math.hypot(a["x"] - n["x"], a["y"] - n["y"]) > 8 for n in named)]


def place_anomalies(world, rng, reach, forbid=frozenset()):
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
            if (x, y) not in reach or (x, y) in forbid:
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


def furnish_house(world, plane, plan):
    """Put the furniture in, and refuse to lose a piece of it.

    The old version worked the internal wall out for itself, got it wrong, and
    then `continue`d past anything that landed on one -- so a chair was placed
    into a wall and silently dropped, and the only way to find out was to decode
    the plane and look. Nothing checks `placed` props: they have no density, so
    the validator's "this prop never appears" warning cannot see them.

    So this reads the geometry out of house_plan rather than recomputing it, and
    it raises on anything it cannot place. A missing chair is a build failure
    now, which is the only weight that keeps a hand-placed layout honest.
    """
    manifest = json.load(open(os.path.join(ROOT, "assets", "tiles", "tiles.json")))
    interior = {p["id"]: p for p in manifest["props"]["list"]
                if p["biome"] == "placed"}
    cell = plan["cell"]
    problems = []

    def put(name, x, y, on_wall=False):
        prop = interior.get(name)
        if prop is None:
            problems.append("%s is not in the catalogue" % name)
            return
        if not (0 <= x < W and 0 <= y < H):
            problems.append("%s at (%d,%d) is off the map" % (name, x, y))
            return
        if plane[y][x]:
            problems.append("%s at (%d,%d) lands on another prop" % (name, x, y))
            return
        # A window stands IN a wall; everything else stands on a floor. Anything
        # else -- furniture on a wall, a window in mid-air -- is the bug this
        # function exists to catch.
        material = ORDER[world.at(x, y)]
        if on_wall:
            if material != "wall_timber":
                problems.append("%s at (%d,%d) wants a wall and found %s"
                                % (name, x, y, material))
                return
        elif not world.walkable(x, y):
            problems.append("%s at (%d,%d) lands on %s, which is not floor"
                            % (name, x, y, material))
            return
        plane[y][x] = prop["plane"]

    for (name, i, j) in plan["furniture"]:
        put(name, *cell(i, j))
    for (x, y) in plan["windows"]:
        put("window_lit", x, y, on_wall=True)

    if problems:
        raise SystemExit("the house layout is wrong:\n  " + "\n  ".join(problems))

    # The furniture must not seal a room off, and it must not stand on the cell
    # the player wakes on or the one the anomaly is in. Checked here rather than
    # trusted, because the failure mode is a run nobody can finish.
    solid_here = set()
    for (name, i, j) in plan["furniture"]:
        prop = interior[name]
        if not prop["solid"]:
            continue
        x, y = cell(i, j)
        for fy in range(prop["foot"][1]):
            for fx in range(prop["foot"][0]):
                solid_here.add((x + fx, y - fy))
    for label in ("spawn", "anomaly"):
        if plan[label] in solid_here:
            raise SystemExit("the %s cell has furniture standing on it" % label)
    return solid_here


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
    # Alternating lamppost and street lamp, because §6: anything that appears
    # more than ten times needs more than one silhouette, and because a street
    # that is lit is the single cheapest thing that makes a town read as a town
    # (§3). Both declare a `light` in the catalogue; neither draws one.
    for i, offset in enumerate((-13, -5, 5, 13)):
        kind = "street_lamp" if i % 2 else "lamppost"
        put(kind, cx + offset, cy - 9)
        put("lamppost" if kind == "street_lamp" else "street_lamp",
            cx + offset, cy + 9)
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
    """The drawn map: the same grid, rendered as something you would pin up.

    `anomalies` is accepted and ignored -- see the note further down about why
    they are no longer painted in.
    """
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
        T["floor_plank"]: mix(mix(C["accent"], C["warn"], 0.30), C["bg"], 0.66),
        T["floor_tile"]: mix(mix(C["panel_alt"], C["accent_2"], 0.30), C["bg"], 0.46),
        T["floor_rug"]: mix(mix(C["danger"], C["accent"], 0.35), C["bg"], 0.62),
        T["wall_timber"]: mix(C["muted"], C["text"], 0.24),
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

    # Anomalies are deliberately NOT painted here.
    #
    # They used to be, and it put them on the map twice: baked into this image
    # at the positions this generation happened to choose, and drawn live by
    # WorldMapScreen from the discovery layer. Harmless while they never move,
    # and wrong the moment they do (#73) -- a region the player remembers from
    # last run would show this run's anomalies straight through the fog,
    # contradicting the memory it is supposed to be showing. The overlay owns
    # them; the painting owns the land.
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

    plan = house_plan(cells)
    # `waking_room` is the tutorial's one hole in reality and it is in the hall.
    # `the_house` used to share the same anchor and therefore the same cell, and
    # a Dictionary keyed by cell kept only one of them -- so it moves out into
    # the yard, where it is also the first thing the player can walk to after
    # Spite. Its exact cell is resolved once the world is walkable; see below.
    cells["waking_room"] = plan["anomaly"]

    stamp_town(world, rng, CENTRE)
    stamp_house(world, plan)
    stamp_observatory(world, cells)
    stamp_summit(world, cells)

    # Roads last, so nothing is painted over them. This is why the old map had
    # roads that dead-ended in walls: the town, observatory and summit were all
    # stamped after the carve and simply overwrote it.
    # Out of town every way, not only toward the northern story beats. The
    # player may leave in any direction and should find a road doing the same.
    for name in ("summit", "observatory", "foothills", "long_road", "tall_grass"):
        carve_road(world, rng, CENTRE, cells[name])
    # The road to the house stops at the DOORSTEP. Aimed at the anchor, which is
    # inside the building, carve_road walked in through the east wall and laid
    # seven columns of path_dirt across the bedroom -- which is most of why the
    # house has never had walls. Then re-stamp, so nothing any later pass does
    # can open the building up again.
    carve_road(world, rng, CENTRE, plan["door_outside"])
    for bearing in (0.0, 90.0, 180.0, 270.0):
        target = coast_stop(world, bearing)
        if target is not None:
            carve_road(world, rng, CENTRE, target)
    stamp_house(world, plan)

    # You wake in the bedroom, on the rug beside the bed, with the front door
    # two rooms away. Beat 1.
    spawn = plan["spawn"]
    reach = reachable(world, spawn)

    # A cliff face is the wall of a terrace, and you cannot walk up a wall. The
    # renderer derives the same faces from the same quantisation, so the picture
    # and the collision cannot disagree.
    steps = terrace(elev)
    cliffs = cliff_plane(steps, elev)
    faces = {(x, y) for y in range(H) for x in range(W) if cliffs[y][x]}

    props, _scattered = scatter_props(world, elev, rng, reach)
    stock_town(world, props, CENTRE, rng)
    furnish_house(world, props, plan)

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
    house_cells = {(x, y)
                   for y in range(plan["y0"], plan["y0"] + plan["h"])
                   for x in range(plan["x0"], plan["x0"] + plan["w"])}

    # The yard anomaly: the nearest reachable cell to the plan's suggestion that
    # is outside the building and not on the doorstep. Searched rather than
    # fixed, because what is south-east of the house is generated terrain and
    # may be a tree, a road or the sea.
    cells["the_house"] = nearest_open(plan["yard"], reach, house_cells,
                                      plan["door_outside"], plan["anomaly"])

    # A procedural hole in the kitchen would make Beat 2 unfindable and Beat 4
    # unreachable, so the house footprint is off limits to everything but its
    # own named anomaly.
    anomalies = name_anomalies(
        cells, place_anomalies(world, rng, reach, forbid=house_cells))

    # THE HOUSE MUST BE SEALED. HJWorld.walkable() returns false on the front
    # door cell until the player has paid the Grit to open it, so that one cell
    # is the entire Beat 4 gate: a gap anywhere else in the wall and the whole
    # tutorial economy is bypassed by walking round it. Flood-filling with the
    # door treated as solid is the only honest way to know, because the hole
    # would not be in the plan -- it would be something a later pass did, which
    # is precisely what happened when the road drove through the east wall.
    shut = World(world.tiles, elev)
    shut.blocked = blocked | {plan["door"]}
    inside = reachable(shut, spawn)
    leaked = sorted(c for c in inside if c not in house_cells)
    if leaked:
        raise SystemExit(
            "the house is not sealed: with the front door shut, %d cells "
            "outside it are still reachable from the bed, starting at %s"
            % (len(leaked), leaked[0]))

    stranded = [n for n, c in cells.items() if c not in reach]

    interactables = [{"x": plan["door"][0], "y": plan["door"][1],
                      "type": "front_door", "label": "Front door"}]
    for (kind, i, j, label) in plan["interactables"]:
        x, y = plan["cell"](i, j)
        entry = {"x": x, "y": y, "type": kind}
        if label:
            entry["label"] = label
        interactables.append(entry)

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
        # Things you can act on. `type` names an entry in
        # data/content/interactables.json; this file only says where they are.
        # The {x, y, ...} shape is the one tools/world_to_tiled.py classifies as
        # an object layer, so these arrive in Tiled as draggable, retypable
        # objects with no tooling change -- which is the point: the house agent
        # places them and the designer moves them.
        "interactables": interactables,
        # Where "inside" is, for the Boon of the White Room and for the three
        # things that fire when the player crosses the threshold (Beat 5). One
        # rectangle covers it because the house is one rectangle: the whole
        # footprint including its walls and the front door cell, so the boon
        # breaks on the first cell of ground OUTSIDE the building rather than in
        # the doorway. Deriving it from the floor material would break the first
        # time somebody floors a porch.
        "indoors": {"x": plan["x0"], "y": plan["y0"],
                    "w": plan["w"], "h": plan["h"]},
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
    # `blocked` is solid prop footprints UNION cliff cells, so reporting its
    # size as "of them solid" over-counted every prop report by the number of
    # cliffs printed on the very next line — 2,337 against 1,759 actually solid.
    solid_props = len(blocked - faces)
    print("props: %d placed (%.1f%% of cells), %d of them solid"
          % (filled, 100.0 * filled / (W * H), solid_props))
    print("cliff cells: %d" % len(faces))
    house_anom = [a for a in anomalies if a.get("area") == "waking_room"][0]
    print("house: %dx%d at (%d,%d), %d walkable cells inside, sealed but for the door"
          % (plan["w"], plan["h"], plan["x0"], plan["y0"], len(inside)))
    print("  wake at %s; the hole in reality is at (%d,%d), %.1f tiles away, tier %d"
          % (spawn, house_anom["x"], house_anom["y"],
             math.hypot(house_anom["x"] - spawn[0], house_anom["y"] - spawn[1]),
             house_anom["tier"]))
    near = [a for a in anomalies
            if max(abs(a["x"] - spawn[0]), abs(a["y"] - spawn[1])) <= 1]
    if near:
        raise SystemExit("an anomaly is on or beside the spawn cell: %s" % near)
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
