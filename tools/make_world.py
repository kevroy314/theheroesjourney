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
import hashlib
import heapq
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


# --- geometry, shared by the water, the borders and the streets ----------------
#
# All five of these are pure functions of integers. They exist so that a river,
# a hedge and a street are the same kind of object -- a polyline with a width --
# and so that nothing in the town is expressed as a magic rectangle twice.


def _seg(a, b):
    """Bresenham. Cells from a to b inclusive."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    out = []
    x, y = x0, y0
    while True:
        out.append((x, y))
        if (x, y) == (x1, y1):
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return out


def _poly(points):
    """A run of segments, with the joins not counted twice."""
    out = []
    for a, b in zip(points, points[1:]):
        run = _seg(a, b)
        out.extend(run if not out else run[1:])
    return out


def _grow(cells, r):
    """Dilate by a disc of radius r. Round rather than square, because a square
    dilation puts a visible corner on every bend of a river."""
    out = set()
    for (x, y) in cells:
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r + r:
                    out.add((x + dx, y + dy))
    return {c for c in out if 0 <= c[0] < W and 0 <= c[1] < H}


def _blob(cx, cy, rx, ry):
    """A filled ellipse. The pond."""
    return {(x, y)
            for y in range(cy - ry, cy + ry + 1)
            for x in range(cx - rx, cx + rx + 1)
            if ((x - cx) / float(rx)) ** 2 + ((y - cy) / float(ry)) ** 2 <= 1.0
            and 0 <= x < W and 0 <= y < H}


def _rect(x, y, w, h):
    return {(i, j) for j in range(y, y + h) for i in range(x, x + w)}


def _ring(x, y, w, h):
    """The wall course of a building: its footprint's edge."""
    return {(i, j) for (i, j) in _rect(x, y, w, h)
            if i in (x, x + w - 1) or j in (y, y + h - 1)}


def _wobble(cells, amp, tag):
    """Push a boundary off its straight line by up to `amp` cells, from a hash
    of the cell rather than from the RNG.

    Two reasons it is a hash and not a draw. First, determinism does not depend
    on how many cells the caller happens to pass. Second -- and this is the one
    that matters -- a hedge has to look the same every run for the same reason
    the house does: it is a place, and a place the player half-remembers from
    the last run has to still be there.
    """
    out = set()
    for (x, y) in cells:
        d = int(hashlib.md5(("%s:%d:%d" % (tag, x, y)).encode()).hexdigest()[:8], 16)
        out.add((x + (d % (2 * amp + 1)) - amp, y + ((d >> 8) % (2 * amp + 1)) - amp))
    return {c for c in out if 0 <= c[0] < W and 0 <= c[1] < H}


def carve_road(world, rng, a, b, avoid=frozenset(), bridge=True):
    """A road from a to b that goes round what it cannot climb -- by search.

    The previous two versions were both greedy walks. The first ignored the
    elevation its docstring claimed to read; the second read it, but a greedy
    walk still cannot go *round* anything longer than it can see, and the town
    now has a river down one side of it and a hedge down the other. A greedy
    road meeting an eighty-cell barrier does not go round it: it grinds along
    the face of it laying dirt, or it bridges it, and a bridge over the boundary
    river is a hole in the only gate the early game has.

    So this is A*. Cost is one per step plus the climb, plus a small
    deterministic jitter so a road is not a ruled line, plus a stiff charge for
    walking through anything somebody built. `avoid` is the one hard rule:
    those cells are not passable at any price, and that is how the river, the
    hedge and the fifteen buildings stay whole. If the target cannot be reached
    without crossing one, this RAISES rather than quietly bridging it -- which
    is the whole point, because that failure is exactly the bug that a greedy
    carver hides.

    The jitter is a hash of the cell and the road's own endpoints, not a draw
    from `rng`: A* pops cells in an order that depends on the terrain, so
    drawing here would make the number of draws -- and therefore every later
    pass in the single RNG stream -- depend on the shape of a hill.
    """
    if a == b:
        return []
    tag = "road:%d,%d>%d,%d" % (a[0], a[1], b[0], b[1])

    def jitter(x, y):
        d = int(hashlib.md5(("%s:%d:%d" % (tag, x, y)).encode()).hexdigest()[:8], 16)
        return (d % 1000) / 1000.0 * 1.4

    def step_cost(fx, fy, tx, ty):
        climb = abs(world.elev[ty][tx] - world.elev[fy][fx]) * 260.0
        here = world.at(tx, ty)
        # Walls, roofs and water are expensive but not forbidden: a road must be
        # able to reach a door, and the door is in the wall. Dear enough never
        # to shortcut through a building; cheap enough to arrive at one.
        through = 0.0
        if here in (T["wall_plaster"], T["wall_stone"], T["wall_timber"],
                    T["wall_brick"], T["roof"], T["roof_thatch"],
                    T["roof_slate"], T["roof_pantile"]):
            through = 220.0
        elif here == T["water"]:
            through = 60.0 if bridge else 4000.0
        elif here in (T["forest"], T["rock"]):
            through = 30.0
        return 1.0 + climb + jitter(tx, ty) + through

    open_heap = [(0.0, 0, a)]
    came = {a: None}
    best = {a: 0.0}
    tick = 0
    found = False
    while open_heap:
        _f, _n, cur = heapq.heappop(open_heap)
        if cur == b:
            found = True
            break
        cx, cy = cur
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < W and 0 <= ny < H):
                continue
            if (nx, ny) in avoid and (nx, ny) != b:
                continue
            g = best[cur] + step_cost(cx, cy, nx, ny)
            if g < best.get((nx, ny), 1e18) - 1e-9:
                best[(nx, ny)] = g
                came[(nx, ny)] = cur
                tick += 1
                h = abs(b[0] - nx) + abs(b[1] - ny)
                heapq.heappush(open_heap, (g + h, tick, (nx, ny)))
    if not found:
        raise SystemExit(
            "no road from %s to %s: every route crosses something the plan "
            "forbids. A road that cannot be built is a story anchor the player "
            "cannot reach." % (a, b))

    laid = []
    cur = b
    while cur is not None:
        laid.append(cur)
        cur = came[cur]
    laid.reverse()
    laid = laid[1:]

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


# --- the vale ------------------------------------------------------------------
#
# PROPOSALS/BUILDINGS.md: the town is "bounded on two sides by a river, and the
# third side is fenced by the farmlands", and the fourth way out is through the
# children's fort, which you cannot pass until the town's anomalies are closed.
# That is not scenery. It is the shape of the whole early game -- everything
# reachable before the fort opens is one bowl of land -- and a bowl with a hole
# in it is not a gate, so the geography is built first and the town is put in it.
#
#   THE WEND         a river out of the northern hills, down the WEST side of
#                    the vale and along the SOUTH of it to the sea. Five cells
#                    wide, never bridged between the fence and the fort. Two of
#                    the four sides.
#   THE FIELD FENCE  the NORTH: the farmland, its hedgerow and its stock fence,
#                    running from the river bank to the thicket. The third side.
#   THE THORN AND    the EAST, where the Long Road leaves. A thicket the length
#   THE FORT         of the boundary, and across the road cut itself the
#                    children's barricade of leaves, pine needles and boxes.
#                    The fourth side, and the only door in any of them.
#   THE MILL BROOK   drawn off the hills in the north-east, west across the top
#                    of the town into the MILL POND, then south between the
#                    house and the town and out to the Wend. It is INSIDE, so it
#                    is crossed rather than obeyed: two bridges, and they are
#                    the cheapest landmarks the town has.
#
# The consequence that matters for the first thirty minutes: the player's house
# is on the WEST bank with three neighbours, and the town is on the EAST bank.
# Walking to town means crossing water at the Town Bridge, so the trip out of
# the front door is a route with a middle rather than a corridor.
#
# The boundary is not trusted, it is PROVEN. main() flood-fills the vale twice:
# once with the fort gate open, to show every anchor is reachable, and once with
# it shut, to show that nothing outside the vale is. See `sealed the vale` there.

## Every barrier polyline ends ON the water or ON another barrier, because a
## boundary that stops one cell short is a boundary the player walks round and
## the hole is invisible in a picture.
WEND = [(114, 58), (108, 72), (100, 86), (92, 100), (85, 114), (79, 128),
        (76, 143), (78, 157), (85, 168), (97, 175), (112, 180), (128, 184),
        (144, 189), (158, 196), (170, 205)]

## The leat: it leaves the hills north-east of the fence, crosses under it --
## water under a fence is still a fence -- and runs west and then south.
BROOK_N = [(158, 84), (152, 90), (145, 96), (138, 100), (130, 104), (122, 108), (115, 111)]
BROOK_S = [(118, 123), (117, 132), (117, 141), (118, 150), (117, 158),
           (113, 166), (105, 173), (96, 177)]
POND = (112, 116, 8, 6)                 # cx, cy, rx, ry -- the mill pond

FENCE = [(83, 101), (100, 98), (118, 96), (136, 96), (152, 99), (159, 104)]
THORN = [(159, 104), (162, 118), (162, 133), (159, 148), (153, 162),
         (145, 174), (134, 182), (127, 185)]

## The cut the Long Road takes through the thicket, and the barricade across it.
## The gate cell itself stays WALKABLE in the generated world: it is gated at
## runtime the way the front door is -- an interactable whose kind declares
## `blocks_until_tag` -- so every path query respects it with no special case,
## and so this file can prove the seal by treating that one cell as solid.
FORT_GATE = (161, 129)
FORT_CUT = ((158, 128), (164, 130))     # where the Long Road is cut through
## The barricade itself: two courses across the cut with the road's middle row
## left open between them, so every route through the thicket passes the gate
## cell and only the gate cell. Proven, not assumed -- see `sealed the vale`.
FORT_WALL = [(x, y) for y in (128, 130) for x in range(159, 164)]


## STREETS. A polyline and a half-width, not a grid. Every one bends, and every
## bend has a reason: High Street follows the dry ground above the brook, Bridge
## Street aims at the one crossing there is, the Back Lane dead-ends in the
## inn's stable yard rather than at a wall, and the Farm Track stops being
## metalled the moment it is out of the fields, because nobody pays to pave a
## field.
##
## (name, points, half width, material)
STREETS = [
    ("high_street", [(119, 130), (121, 129), (128, 128), (136, 128), (144, 129),
                     (152, 129), (161, 129)], 1, "floor_stone"),
    ("north_lane",  [(132, 127), (132, 117), (133, 107), (134, 99)], 1, "path_dirt"),
    ("mill_lane",   [(126, 127), (125, 124), (125, 123)], 1, "path_dirt"),
    ("farm_track",  [(134, 99), (127, 100), (120, 102)], 0, "path_dirt"),
    ("shop_row",    [(146, 130), (146, 141)], 1, "path_dirt"),
    ("alley",       [(128, 131), (128, 141)], 1, "path_dirt"),
    ("bridge_st",   [(120, 151), (126, 152), (130, 150), (132, 147),
                     (133, 144), (141, 144), (149, 144)], 1, "path_dirt"),
    ("home_lane",   [(82, 152), (92, 151), (102, 151), (112, 151), (120, 151)], 1, "path_dirt"),
    ("low_street",  [(122, 159), (132, 160), (142, 160), (151, 159)], 1, "path_dirt"),
    ("back_lane",   [(154, 127), (154, 123)], 0, "path_dirt"),
    ("empty_track", [(101, 153), (103, 156), (105, 157)], 0, "path_dirt"),
]

SQUARE = (132, 132, 13, 9)

BRIDGES = [("town_bridge", (114, 149, 7, 4)),
           ("north_bridge", (130, 100, 5, 6))]

BUILDINGS = [
    ("mill", 121, 112, 10, 10, (125, 121), "wall_stone", "roof_slate"),
    ("commonhouse", 135, 111, 13, 13, (141, 123), "wall_brick", "roof_pantile"),
    ("innkeeper", 150, 114, 9, 8, (154, 121), "wall_timber", "roof_thatch"),
    ("busybodies", 120, 132, 7, 8, (126, 135), "wall_plaster", "roof_pantile"),
    ("store", 148, 132, 11, 8, (148, 135), "wall_stone", "roof_slate"),
    ("tavern", 135, 146, 12, 9, (140, 146), "wall_timber", "roof_thatch"),
    ("tavernkeep", 148, 146, 7, 8, (151, 146), "wall_plaster", "roof_pantile"),
    ("tinkerer", 118, 163, 11, 9, (123, 163), "wall_stone", "roof"),
    ("mayor", 132, 164, 12, 10, (138, 164), "wall_brick", "roof_pantile"),
    ("empty_house", 101, 158, 9, 9, (105, 158), "wall_timber", "roof_thatch"),
    ("farmhouse", 108, 99, 11, 9, (118, 103), "wall_timber", "roof_thatch"),
    ("neighbour_w", 80, 142, 6, 7, (83, 148), "wall_timber", "roof_thatch"),
    ("neighbour_e", 107, 142, 7, 7, (110, 148), "wall_timber", "roof_thatch"),
    ("across", 92, 155, 8, 7, (95, 155), "wall_plaster", "roof_thatch"),
]

OUTBUILDINGS = [
    (100, 100, 5, 4, "roof_thatch"),      # the barn, in the fields
    (101, 105, 4, 3, "roof_thatch"),      # the byre
    (150, 124, 3, 3, "roof_pantile"),     # the inn's stable, off the back lane
    (156, 125, 3, 3, "roof_pantile"),
    (137, 156, 4, 3, "roof_thatch"),      # the tavern's brewhouse
    (148, 155, 3, 3, "roof_thatch"),
    (128, 123, 3, 3, "roof_slate"),       # the mill's cart shed
    (108, 138, 3, 3, "roof_thatch"),      # the woodshed behind the girl's
    (80, 137, 3, 3, "roof_thatch"),       # and behind the guy's
    (155, 142, 3, 3, "roof_slate"),       # the store's stock shed
]


def vale_plan():
    """Everything above, resolved into cells. One source, read by every pass.

    The same discipline `house_plan` established: no other function in this file
    may recompute where the river is or where a wall stands. The house's first
    version worked its internal wall out twice, differently, and put a chair
    inside it; a town has fifteen buildings, eleven streets and three waters and
    would do that eleven times over.
    """
    water = (_grow(_poly(WEND), 2) | _grow(_poly(BROOK_N), 1)
             | _grow(_poly(BROOK_S), 1) | _blob(*POND))
    # The banks wobble by a cell so a river does not read as a pipe. Wobbling the
    # WHOLE channel would pinch it shut somewhere; wobbling only the outermost
    # ring cannot, because the inner channel is still there underneath.
    water |= _wobble(_grow(water, 1) - water, 1, "bank") - _grow(_poly(WEND), 3)
    barrier = _grow(_poly(FENCE), 1) | _grow(_poly(THORN), 1)
    barrier |= _wobble(barrier, 1, "hedge")
    cut = _rect(FORT_CUT[0][0], FORT_CUT[0][1],
                FORT_CUT[1][0] - FORT_CUT[0][0] + 1,
                FORT_CUT[1][1] - FORT_CUT[0][1] + 1)
    barrier -= cut
    barrier -= water                       # water under a fence is still a fence

    bridges = set()
    for _name, r in BRIDGES:
        bridges |= _rect(*r)

    streets = {}
    for (name, pts, half, material) in STREETS:
        run = _grow(_poly(pts), half) if half else set(_poly(pts))
        for c in run:
            streets[c] = material
    for c in _rect(*SQUARE):
        streets[c] = "floor_stone"

    buildings = []
    for (bid, x, y, w, h, door, wall, roof) in BUILDINGS:
        buildings.append(dict(id=bid, x=x, y=y, w=w, h=h, door=door,
                              wall=wall, roof=roof,
                              foot=_rect(x, y, w, h), ring=_ring(x, y, w, h),
                              inside=_rect(x + 1, y + 1, w - 2, h - 2)))
    sheds = [dict(x=x, y=y, w=w, h=h, roof=m, foot=_rect(x, y, w, h))
             for (x, y, w, h, m) in OUTBUILDINGS]

    built = set()
    for b in buildings:
        built |= b["foot"]
    for s in sheds:
        built |= s["foot"]

    return dict(water=water, barrier=barrier, bridges=bridges, streets=streets,
                buildings=buildings, sheds=sheds, built=built,
                square=_rect(*SQUARE), fort_wall=set(FORT_WALL),
                gate=FORT_GATE, pond=_blob(*POND),
                brook=_grow(_poly(BROOK_N), 1) | _grow(_poly(BROOK_S), 1) | _blob(*POND))


def stamp_vale(world, plan):
    """Water, boundary and bridges. Called before the town and again after the
    roads, because the whole point of the boundary is that nothing may reopen
    it -- and a road carver is exactly the kind of later pass that would."""
    for (x, y) in plan["water"]:
        world.put(x, y, T["water"])
    for (x, y) in plan["barrier"]:
        # A thorn hedge and a field boundary, drawn as closed canopy: it is the
        # material the tileset already has for "you go round this, not through
        # it", and it costs no props, which matters when the boundary is 300
        # cells long and props can fail to place.
        world.put(x, y, T["forest"])
    for (x, y) in plan["bridges"]:
        if world.at(x, y) == T["water"]:
            world.put(x, y, T["bridge"])


def stamp_town(world, plan):
    """Streets, the square, and fifteen buildings that face them.

    What the old one did was lay two streets crossing in a circle of flagstone
    and drop rectangles beside them, and the note on it was "not just some grid
    of buildings". Three things are different here and each is the reason for
    one of the others.

    THE GROUND IS NOT PAVED. The old town was a 22-cell disc of floor_stone with
    dirt streets scribbled on it, which is why it read as a car park. A village
    is mostly green: paving is High Street and the market square and nothing
    else, every other street is dirt, and between the buildings is grass, yard
    and garden.

    STREETS ARE POLYLINES, NOT AXES. Every one bends, and the bends have reasons
    -- the brook, the pond, the ground. Two of them dead-end on purpose: the
    Back Lane in the inn's stable yard and the lane past the tinkerer's, because
    a street that stops at a yard is a place and a street that stops at nothing
    is an unfinished map.

    BUILDINGS ARE NAMED, DIFFERENT SHAPES, AND SET BACK BY DIFFERENT AMOUNTS.
    The commonhouse is 13x13 on the street; the busybodies' is 7x8 hard on the
    pavement with no setback at all, facing the square, because that is who they
    are; the mayor's is 12x10 behind a garden nobody else in town has. The
    material follows the building -- see the table in make_tiles.py.

    Construction is shared, which is what makes it one town: every building is a
    wall course with a roof laid inside it and one door tile in the wall. The
    sheds have no wall and no door, because a shed seen from above is a roof.
    """
    for (x, y), material in plan["streets"].items():
        if (x, y) in plan["water"]:
            continue
        world.put(x, y, T[material])

    for s in plan["sheds"]:
        for (x, y) in s["foot"]:
            world.put(x, y, T[s["roof"]])

    for b in plan["buildings"]:
        for (x, y) in b["foot"]:
            world.put(x, y, T[b["roof"]])
        for (x, y) in b["ring"]:
            world.put(x, y, T[b["wall"]])
        world.put(b["door"][0], b["door"][1], T["door"])

    for (x, y) in plan["bridges"]:
        if world.at(x, y) == T["water"]:
            world.put(x, y, T["bridge"])


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
# Four rooms, four floors and a rug, because §5: "each room inside a building has its
# own floor", and a change of material is what tells you that you have gone
# somewhere. Three wall runs with four doorways between them, so the space
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

    SCALE. One tile is about three feet. The bed is one cell by two and reads as
    a 3 x 6 ft single; the front door is one cell and reads as a 36 in door;
    36 in is also the code minimum for a circulation path, so ONE CLEAR TILE IS
    ONE WALKWAY and two clear tiles is a generous one. Every clearance below is
    quoted in tiles against that ruler.

    THE PLAN is the English three-cell cottage: a hall you come in to, a heated
    room where the cooking and the eating happen, a parlour that is the private
    chamber, and an unheated service room at the far end. The previous layout
    was three boxes with the furniture scattered where it happened to fit, and
    what was wrong with it was not the walls -- it was that a bed floated in the
    middle of a floor, a bookshelf stood in open space, the kitchen had no
    working relationship between stove, sink and counter, and a 17 x 5 hall held
    one of everything, which is the shape of a storage unit and not of a room.

    What changed, and the rule each change is serving:

    * A FOURTH ROOM. The 17 x 5 south range is now a 12 x 6 hall and a 4 x 6
      pantry. A room reads as having a purpose or it reads as storage; the fix
      for "one of everything" is not to spread the everything out, it is to give
      the barrels and crates a room that is *supposed* to be full of them. The
      service end of a real cottage -- buttery and pantry, unheated, at the low
      end past the entrance -- is exactly that room.
    * ONE ANCHOR PER ROOM, and everything else in the room serves it. Parlour:
      the bed. Kitchen: the range and the table. Hall: the door you come in by
      and the reading corner under the window. Pantry: the shelves.
    * CASE GOODS AGAINST WALLS. Every bookshelf, dresser, chest, shelf and
      counter below has its back on a wall cell. Only the tables, the chairs and
      the rugs float, which is the one rule that separates a furnished room from
      a warehouse floor.
    * A SINGLE-WALL KITCHEN. The work triangle collapses to a line when the
      kitchen is one run, so the order is cold store, then sink, then range.
      Ours is dresser (10,0), sink (12,0), range (14,0) -- two tiles between
      each, so two 6 ft legs and 12 ft in total. NKBA Guideline 5 wants each leg
      between 4 and 9 ft and the total under 26, which this clears with room to
      spare. A tile of landing counter sits on each side of both the sink and
      the range -- 36 in against the 24 in / 18 in the guidelines ask for -- and
      there is 15 ft of worktop against a 13 ft minimum (Guideline 25). No
      traffic crosses it: both doorways are at the south of the room and the
      table sits three tiles clear of the run.

      An earlier draft of this comment cited "the NKBA rule for a single wall:
      within 12 ft". There is no such rule. The layout happened to be compliant
      anyway, which is exactly why the invention survived a reading -- a made-up
      citation that agrees with the right answer is the hardest kind to catch.
    * CLEARANCES, all measured below and all met: one clear tile in front of
      every doorway on both sides, two in front of the front door; one clear
      tile each side of the bed and at its foot; one clear tile of chair ring on
      every used side of a table; a two-tile aisle between the kitchen run and
      the table.
    * DOORS AND WINDOWS CONSTRAIN EVERYTHING. Nothing solid stands on a doorway
      landing cell and nothing solid stands in front of a window. The bed's
      headboard is on a solid wall, it is not under a window, and its column is
      not the column of either doorway into the room -- you do not lie with your
      feet pointing out of the door.
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
        # room -> (i0, j0, i1, j1) inclusive, and the material it is floored in.
        # The floor is what tells you which room you are in before you have seen
        # a stick of its furniture, so the service room gets cold stone and the
        # parlour gets the good boards.
        "rooms": {
            "parlour": ((0, 0, 7, 5), "floor_plank"),     # the bed chamber
            "kitchen": ((9, 0, 16, 5), "floor_tile"),     # the range and the table
            "hall":    ((0, 7, 11, 12), "floor_boards"),  # the door you come in by
            "pantry":  ((13, 7, 16, 12), "floor_stone"),  # unheated, and full of it
        },
        # Rugs are patches of a fourth floor material, and they are how a group
        # of furniture reads as one zone rather than as three objects: the rug
        # has to reach under the front of every piece in the group. One beside
        # the bed where the player's feet land, one under the reading corner.
        "rugs": [(3, 1, 4, 3), (1, 10, 3, 12)],
        # internal walls, as runs, and the doorways punched through them
        "walls": [(8, 0, 8, 5), (0, 6, 16, 6), (12, 7, 12, 12)],
        "doorways": [(8, 2), (2, 6), (10, 6), (12, 9)],
        # the front door sits in the south exterior wall; the road stops at the
        # cell outside it, never inside the building
        "door": (x0 + HOUSE_W // 2, y0 + HOUSE_H - 1),
        "door_outside": (x0 + HOUSE_W // 2, y0 + HOUSE_H),
        # Windows are props standing on wall cells, so they are (x, y) already.
        # North and east for the kitchen (the sink is under one of them, which is
        # where a sink goes), west for the parlour and for the hall's reading
        # corner, east for the pantry. Nothing solid stands on the floor cell in
        # front of any of them.
        "windows": [(x0 + 4, y0),                      # north, parlour
                    (x0 + 13, y0),                     # north, over the sink
                    (x0 + HOUSE_W - 1, y0 + 5),        # east, kitchen
                    (x0, y0 + 2),                      # west, parlour
                    (x0, y0 + 11),                     # west, hall
                    (x0 + HOUSE_W - 1, y0 + 12)],      # east, pantry
        # you wake beside the bed, on the rug, and the hole in reality is in the
        # hall — Beat 2: "the player does not spawn on the anomaly"
        "spawn": cell(4, 1),
        # The one hole in reality inside the house, in the hall, two rooms from
        # the bed. Beat 2: "the player does not spawn on the anomaly; it is
        # somewhere else in the house and they have to walk into it."
        "anomaly": cell(10, 10),
        # SPITE, on the doorstep. He is the first person the player meets and he
        # is met from INSIDE the threshold, so he stands on the ground outside
        # it -- adjacent to the cell the player lands on when the front door
        # finally opens, and outside the `indoors` rectangle, because Beat 5
        # fires on crossing out of it and he is the reason for crossing. Not on
        # the doorstep itself: that cell is the Beat 4 gate and has to stay
        # walkable. Preference first, then the eight cells round the doorstep in
        # a fixed order -- see main(), which resolves it against the finished
        # world and raises if none of them is standable.
        "spite": (x0 + HOUSE_W // 2 + 1, y0 + HOUSE_H + 1),
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
            # -- the parlour ---------------------------------------------------
            # Anchor: the bed, headboard on the north wall, a clear tile down
            # each side and at the foot, and not in the axis of either door. The
            # three chests are the three chests a bed chamber actually has: one
            # by the head for a candle, one against the wall for clothes, one at
            # the foot for blankets. Somebody got out of this bed and did not
            # make it.
            ("bed", 5, 1), ("chest", 6, 0), ("bookshelf", 0, 0),
            ("chest", 0, 2), ("shelf_open", 0, 4), ("plant_pot", 0, 5),
            ("shelf_open", 7, 0), ("chair", 7, 3), ("chest", 7, 4),
            ("floor_lamp", 7, 5),
            # the washstand run along the south wall, and the bench beside it
            ("bench", 3, 5), ("counter", 4, 5), ("counter", 5, 5),
            ("candle", 6, 1), ("book_open", 4, 2), ("boots", 4, 3),
            ("cat", 3, 3),
            # -- the kitchen ---------------------------------------------------
            # Anchor: the range, and the table that faces it. The north wall is
            # the whole work run -- dresser, landing, sink under the window,
            # prep, range, landing, worktop -- and the table sits two clear tiles
            # south of it so that nobody walking to a door crosses the cook.
            ("barrel", 9, 0), ("bookshelf", 10, 0), ("counter", 11, 0),
            ("counter", 12, 0), ("counter", 13, 0), ("stove", 14, 0),
            ("counter", 15, 0), ("counter", 16, 0), ("shelf_open", 16, 2),
            ("table", 12, 4), ("chair", 11, 3), ("chair", 11, 4),
            ("chair", 13, 3), ("chair_pulled", 14, 4),
            ("bench", 9, 3), ("crate", 9, 5), ("chest", 16, 3),
            ("plant_pot", 16, 5), ("cup", 13, 2), ("bottle", 16, 1),
            # Four at table and one pushed back and turned away, with the gap at
            # (13,4) it was pulled out of. §"evidence of use", and the cheapest
            # sentence of story in the house.
            # -- the hall ------------------------------------------------------
            # Anchor: the front door and, at the far end under the west window,
            # the reading corner -- table, chair, lamp, a book face down on the
            # boards. The library wall is on the north side where it has a wall
            # to stand against; the middle of the room is left open because it is
            # the route from the door to every other room in the house.
            ("plant_pot", 0, 7), ("bookshelf", 3, 7), ("bookshelf", 4, 7),
            ("bookshelf", 5, 7), ("chest", 6, 7), ("bench", 8, 7),
            ("bench", 9, 7), ("chest", 11, 7), ("crate", 11, 8),
            # the settle under the library, and the table it looks at
            ("table", 8, 9), ("chair", 7, 9), ("chair_pulled", 9, 9),
            ("table", 1, 11), ("chair", 2, 10), ("chair", 2, 11),
            ("floor_lamp", 3, 12), ("book_open", 2, 12),
            ("barrel", 11, 10), ("crate", 10, 12), ("bench", 6, 12),
            # and the boots by the front door, with the dog beside them
            ("boots", 7, 12), ("dog", 6, 11),
            # -- the pantry ----------------------------------------------------
            # The one room that is allowed to read as storage, because storage is
            # what it is for. Shelves across the top, casks and crates round the
            # walls, and a two-tile aisle down the middle that reaches every one
            # of them.
            ("shelf_open", 13, 7), ("shelf_open", 14, 7), ("shelf_open", 15, 7),
            ("barrel", 16, 7), ("crate", 16, 8), ("barrel", 13, 8),
            ("chest", 16, 10), ("crate", 13, 11), ("barrel", 13, 12),
            ("crate", 14, 12), ("chest", 15, 12), ("barrel", 16, 12),
            ("cup", 14, 9), ("bottle", 15, 9),
        ],
        # (type, i, j, label or None). `type` names an entry in
        # data/content/interactables.json; the world only says where.
        "interactables": [
            ("stove", 14, 0, None),
            ("counter", 13, 0, None),
            ("cat", 3, 3, None),
            ("dog", 6, 11, None),
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
    for (ri0, rj0, ri1, rj1) in plan["rugs"]:
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


def scatter_props(world, elev, rng, reach, plane):
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


def town_props(plan):
    """Every prop in the town, by hand, with a reason each.

    Placed rather than scattered for the reason the house's furniture is: a well
    two tiles from a wall is litter and a well in the middle of a square is a
    landmark, and no density can tell the difference. The list is long because a
    town is furniture -- §3 of docs/AESTHETIC-EDA.md, "a street that is lit is
    the single cheapest thing that makes a town read as a town" -- and because
    §"evidence of use" applies at this scale too: the crates outside the store,
    the washing between the cottages, the barrels in the tavern yard and the
    bin nobody has emptied are the town's version of the chair pulled out from
    the table.

    Returns (id, x, y) triples. Every one is checked on placement and a failure
    is a build error, exactly as in furnish_house -- a hand-made list that
    silently drops a third of itself is worse than no list.
    """
    out = []

    def add(name, *cells):
        for (x, y) in cells:
            out.append((name, x, y))

    # -- the market square: the one landmark everybody navigates by ------------
    add("well", (136, 137))
    add("standing_stone", (139, 134))              # the market cross
    add("market_stall", (133, 133), (135, 133), (141, 133), (143, 133))
    add("cart", (133, 139))
    add("barrel", (135, 140), (143, 136))
    add("crate", (136, 140), (143, 137))
    add("bench", (138, 140), (140, 140), (133, 136))
    add("trash_can", (143, 140))
    # Lit on all four corners. Two silhouettes alternating, because §6: anything
    # that appears more than ten times needs more than one outline.
    add("lamppost", (132, 132), (144, 140))
    add("street_lamp", (144, 132), (132, 140))

    # -- High Street: the lit spine of the parish ------------------------------
    add("street_lamp", (126, 131), (140, 126), (154, 131))
    add("lamppost", (133, 126), (147, 126), (122, 131))
    add("milestone", (159, 131))
    add("signpost", (130, 126))
    add("trash_can", (150, 131))
    add("bench", (137, 126))

    # -- shop fronts. The sign is how a building says what it sells ------------
    add("sign_shop", (147, 135),                   # the general store
        (139, 145),                                # the tavern
        (142, 124),                                # the commonhouse
        (124, 122),                                # the mill
        (124, 162))                                # the tinkerer
    # And the store's stock, on the pavement, which is where a shop keeps it.
    add("crate", (147, 133), (147, 134), (149, 141))
    add("barrel", (147, 137), (148, 141))
    add("cart", (150, 142))

    # -- the tavern yard: the reason the back of a pub smells ------------------
    add("barrel", (136, 155), (135, 155), (141, 155))
    add("crate", (142, 155))
    add("trash_can", (134, 155))
    add("bottle", (139, 155), (143, 156))
    add("bench", (137, 145), (142, 145))
    add("cart", (147, 155))

    # -- the mill and the pond -------------------------------------------------
    add("cart", (131, 123))
    add("crate", (132, 122), (133, 123))
    add("barrel", (120, 123), (121, 122))
    add("bench", (117, 124))                       # somebody sits and watches it
    add("reed_bed", (105, 118), (106, 121), (119, 110), (117, 122),
        (103, 114), (121, 118))

    # -- the fields: what a farm looks like from the road ----------------------
    add("haystack", (106, 108), (110, 109), (99, 106), (96, 101))
    add("cart", (107, 98))
    add("crate", (105, 99))
    add("field_gate", (119, 98))
    add("fence_rail", *[(x, 97) for x in range(120, 132)])
    add("fence_rail", *[(133, y) for y in range(98, 103)])
    add("washing_line", (105, 97))

    # -- the mayor's garden. Nobody else in town has a fence in front ----------
    add("fence_rail", *[(x, 162) for x in range(132, 144) if x != 138])
    add("plant_pot", (136, 163), (140, 163))
    add("bench", (134, 163))
    add("lamppost", (138, 163))

    # -- the hamlet: four cottages and the evidence that people live in them ---
    add("washing_line", (85, 150), (101, 147), (97, 153))
    add("boots", (83, 149))
    add("bench", (93, 153), (109, 149))
    add("crate", (86, 143), (106, 141))
    add("barrel", (86, 144))
    add("street_lamp", (91, 149))
    add("lamppost", (105, 149))
    add("plant_pot", (95, 154), (110, 141))
    add("cart", (99, 152))
    # The empty house gets NO lamp, no washing and a bramble across the path.
    # An absence is the cheapest characterisation there is.
    add("bramble", (104, 157), (108, 157), (101, 161))
    add("crate", (110, 160))

    # -- the children's defence -----------------------------------------------
    #
    # The barricade itself is load-bearing: it is the only thing between the
    # player and the rest of the world until the town's anomalies are closed.
    # Everything else here is the fort being LIVED IN, which is the difference
    # between a wall and a place children are holding.
    add("leaf_wall", *plan["fort_wall"])
    add("campfire", (157, 126))
    add("crate", (156, 125), (158, 124), (157, 132))
    add("barrel", (156, 133))
    add("signpost", (158, 133))
    add("bramble", (155, 135), (156, 122))
    add("washing_line", (154, 133))
    return out


def stock_town(world, plane, plan, rng):
    """Put the list down, and refuse to lose a piece of it.

    Same contract as furnish_house and for the same reason: `placed` props have
    no density, so the validator's "this prop never appears" warning cannot see
    them, and a silently dropped lamp is a dark street nobody can explain. The
    only prop allowed to be missing is none of them.
    """
    manifest = json.load(open(os.path.join(ROOT, "assets", "tiles", "tiles.json")))
    catalogue = {p["id"]: p for p in manifest["props"]["list"]}
    problems = []
    placed = 0
    for (name, x, y) in town_props(plan):
        prop = catalogue.get(name)
        if prop is None:
            problems.append("%s is not in the catalogue" % name)
            continue
        if not (0 <= x < W and 0 <= y < H):
            problems.append("%s at (%d,%d) is off the map" % (name, x, y))
            continue
        if plane[y][x]:
            here = next((p["id"] for p in catalogue.values()
                         if p["plane"] == plane[y][x]), "?")
            problems.append("%s at (%d,%d) lands on %s" % (name, x, y, here))
            continue
        if not world.walkable(x, y):
            problems.append("%s at (%d,%d) stands on %s, which is not ground"
                            % (name, x, y, ORDER[world.at(x, y)]))
            continue
        if world.at(x, y) == T["door"]:
            problems.append("%s at (%d,%d) is standing in a doorway" % (name, x, y))
            continue
        plane[y][x] = prop["plane"]
        placed += 1
    if problems:
        raise SystemExit("the town's furniture is wrong:\n  " + "\n  ".join(problems))
    return placed


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

    vale = vale_plan()
    stamp_vale(world, vale)
    stamp_town(world, vale)
    stamp_house(world, plan)
    stamp_observatory(world, cells)
    stamp_summit(world, cells)

    # WHAT A ROAD MAY NOT CROSS.
    #
    # The boundary is the whole early game -- two sides river, one side
    # farmland, one side the children's fort -- and a road carver that bridges
    # what is in its way would put a hole in it without anyone noticing, which
    # is exactly what happened to the house's east wall. So the barrier, the
    # river, the brook and every building are handed to carve_road as cells it
    # may not enter at any price. The two bridges and the doorsteps are the
    # deliberate exceptions, and they are the only ones.
    #
    # Roads OUTSIDE the vale may still cross the Wend -- there has to be a way
    # round or the western half of the world is unreachable -- so the forbidden
    # water is only the stretch that touches the vale. `_grow(inside, 4)` is how
    # that is said: the river is off limits where the vale can see it.
    door_step = {plan["door_outside"]}
    approx_inside = reachable(World(world.tiles, elev), CENTRE)
    near_town = _grow(approx_inside, 4)
    no_cross = ((vale["barrier"] | (vale["water"] & near_town) | vale["brook"]
                 | vale["built"]) - vale["bridges"] - door_step)

    # Roads last, so nothing is painted over them. This is why the old map had
    # roads that dead-ended in walls: the town, observatory and summit were all
    # stamped after the carve and simply overwrote it.
    #
    # Everything outside now starts at the GATE rather than at the town centre,
    # because the gate is the only way out and a road that begins inside the
    # boundary and ends outside it has crossed the boundary somewhere.
    gate = vale["gate"]
    for name in ("summit", "observatory", "foothills", "long_road", "tall_grass"):
        carve_road(world, rng, gate, cells[name], avoid=no_cross - {gate})
    for bearing in (0.0, 90.0, 270.0):
        target = coast_stop(world, bearing)
        if target is not None:
            carve_road(world, rng, gate, target, avoid=no_cross - {gate})
    # The road to the house stops at the DOORSTEP. Aimed at the anchor, which is
    # inside the building, carve_road walked in through the east wall and laid
    # seven columns of path_dirt across the bedroom -- which is most of why the
    # house has never had walls. Then re-stamp, so nothing any later pass does
    # can open the building up again.
    carve_road(world, rng, (96, 151), plan["door_outside"],
               avoid=no_cross - door_step)
    # And re-lay the boundary and the town over the top of all of it, because
    # the seal is a promise this file makes and a road is the thing most likely
    # to break it.
    stamp_vale(world, vale)
    stamp_town(world, vale)
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

    # The town's own furniture goes down FIRST and the scatter fills in round
    # it. The other order loses lamps: scatter_props refuses a cell that already
    # holds a prop, so whichever pass runs second is the one that gets dropped,
    # and a hand-made list is the wrong one to drop.
    props = [[0] * W for _ in range(H)]
    town_prop_count = stock_town(world, props, vale, rng)
    scatter_props(world, elev, rng, reach, props)
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

    # Nothing procedural within sight of the house.
    #
    # `forbid=house_cells` kept anomalies out of the rooms and let one land a
    # single tile past the north wall -- tier 1, four tiles from the bed, and
    # plainly visible through the bedroom window. That breaks the tutorial twice
    # over: Beat 2 is the player *finding* the first hole, and the one they
    # would find is both harder than the tier-0 the house contains and reachable
    # before it. The viewport is about seven tiles wide, so ten is far enough
    # that the first portal a player ever sees is the one meant for them.
    HOUSE_CLEARANCE = 10
    house_keep_out = {(x, y)
                      for y in range(plan["y0"] - HOUSE_CLEARANCE,
                                     plan["y0"] + plan["h"] + HOUSE_CLEARANCE)
                      for x in range(plan["x0"] - HOUSE_CLEARANCE,
                                     plan["x0"] + plan["w"] + HOUSE_CLEARANCE)}

    # Spite stands on the doorstep, and he has to actually be standable on: his
    # reach is `adjacent`, which is the eight cells around him plus his own, so
    # a Spite three cells into the long grass is a Spite you cannot talk to. The
    # preference from the plan first, then the rest of the ring round the door
    # in a fixed order so the answer is the same on every run.
    dx0, dy0 = plan["door_outside"]
    # Diagonals first. carve_road lays path_dirt in a plus around every cell it
    # walks, so all four orthogonal neighbours of the doorstep are road; the
    # diagonals are the only cells that are both adjacent to where the player
    # lands and off the path they land on.
    ring = [plan["spite"]] + [(dx0 + a, dy0 + b)
                              for (a, b) in ((1, 1), (-1, 1), (1, -1), (-1, -1),
                                             (1, 0), (-1, 0), (0, 1))]

    def standable(c):
        return (c in reach and c not in house_cells
                and c != plan["door_outside"])

    spite = (next((c for c in ring if standable(c)
                   and not props[c[1]][c[0]]
                   and ORDER[world.at(*c)] != "path_dirt"), None)
             or next((c for c in ring if standable(c)
                      and ORDER[world.at(*c)] != "path_dirt"), None)
             or next((c for c in ring if standable(c)), None))
    if spite is None:
        raise SystemExit(
            "there is nowhere for Spite to stand: every cell round the doorstep "
            "at %s is blocked, indoors, or unreachable" % (plan["door_outside"],))

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
        cells, place_anomalies(world, rng, reach, forbid=house_keep_out))

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
    stranded_inside = sorted(
        c for c in house_cells
        if c not in inside and c != plan["door"] and world.walkable(c[0], c[1]))
    if stranded_inside:
        raise SystemExit(
            "the furniture has boxed %d cell(s) of the house in: %s. Every "
            "walkable cell inside has to be reachable from the bed -- a pocket "
            "behind a barrel is a cell the player can see, walk at, and never "
            "stand on." % (len(stranded_inside), stranded_inside))
    leaked = sorted(c for c in inside if c not in house_cells)
    if leaked:
        raise SystemExit(
            "the house is not sealed: with the front door shut, %d cells "
            "outside it are still reachable from the bed, starting at %s"
            % (len(leaked), leaked[0]))

    stranded = [n for n, c in cells.items() if c not in reach]

    interactables = [{"x": plan["door"][0], "y": plan["door"][1],
                      "type": "front_door", "label": "Front door"},
                     {"x": spite[0], "y": spite[1], "type": "spite"}]
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
    print("  Spite waits at %s, %d cell(s) from the doorstep at %s, outdoors"
          % (spite, max(abs(spite[0] - dx0), abs(spite[1] - dy0)),
             plan["door_outside"]))
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
