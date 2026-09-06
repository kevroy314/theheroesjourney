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

## The vale's bounding box, inclusive: x0, y0, x1, y1. It is what main() proves
## the town is sealed inside, and it is also the shape the town CLAIMS as a
## place -- see REGION_RECTS.
VALE_BOX = (68, 86, 170, 192)

## A REGION MAY CLAIM A RECTANGLE AS WELL AS A POINT.
##
## `the_town` was one anchor at (128, 128) and HJWorld.place_id() gave up beyond
## 24 tiles of Manhattan distance, so most of the town -- the tavern, the mill,
## the mayor's, the whole hamlet on the west bank -- reported itself as
## "Outside" and every conversation held there was drawn against the wrong
## backdrop plate. Widening the radius would have been the wrong fix twice over:
## a circle is not the shape of a valley, and a bigger circle round the town
## swallows the house.
##
## So a region may carry a rect, and place_id() prefers the SMALLEST rect that
## contains the cell before falling back to the nearest anchor. Smallest, so
## rects can nest: the house's own plot sits inside the vale and keeps its own
## name, which is what stops a player standing on their own doorstep being told
## they are in town.
##
## Emitted as a nested `rect` on the region's own entry in the world file, so
## there is one list of regions and not two. The Tiled round trip carries it for
## free -- a region is already an {x, y, ...} record and object_from_cell turns
## a structured value into a JSON property it knows to decode on the way back.
##
## Anchors a rect is allowed to swallow, and the rect that swallows them.
##
## One entry, and it is the tutorial's: `waking_room` is the hole in reality in
## the hall, so it is INSIDE the house by construction and answering "the_house"
## for it is right rather than a mistake. Both areas call the place "Home", so
## nothing the player reads changes. An absorption that changed what the player
## was told would belong in neither this list nor the world.
ABSORBED = {"waking_room": "the_house"}

## (area id, x, y, w, h)
##
## The town's rect is deliberately NOT `VALE_BOX`, which is the deliberately generous box the seal
## is proved against and takes in the tall grass on the far bank. This is the
## built envelope: from the east bank of the Wend where the four cottages stand,
## up to the field fence, down past the mayor's garden, and out to the thorn the
## fort gate is cut through. A cell inside it is somewhere a townsperson would
## say you were in town.
REGION_RECTS = [
    ("the_town", 78, 94, 93, 87),
    # The house and the ground round it: the footprint, the doorstep, the cell
    # Spite stands on and the yard the second anomaly lands in. Deliberately
    # short of both neighbours' walls, because next door is next door.
    ("the_house", 81, 128, 31, 27),
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


def standing_planes():
    """Prop plane ids that DRAW ABOVE THEIR OWN CELL.

    A prop's art is 64x96 in a 32px cell and is painted north to south, so a
    prop on (x, y) covers (x, y-1) and (x, y-2) as well -- which is how a bench
    at (6,12) came to be painted over two thirds of the dog at (6,11). That is
    only true of props that stand up. A prop the catalogue marks `flat` -- grit,
    a rut, fallen leaves, a damp patch -- is drawn in the bottom few rows of the
    slot and covers nothing but the cell it is on.

    The distinction has to be made or the burial check is wrong in the direction
    that costs a build: it refused to let Spite stand on his own doorstep
    because a twig had blown into the road one cell south of him.
    """
    path = os.path.join(ROOT, "assets", "tiles", "tiles.json")
    catalogue = json.load(open(path))["props"]["list"]
    return {p["plane"] for p in catalogue if not p.get("flat")}


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
        step = 1.0 + climb + jitter(tx, ty) + through
        # THE ROAD-REUSE DISCOUNT. docs/PROCGEN-RESEARCH.md §2.1 calls this the
        # highest-value line in the document, and it is one line: a cell that
        # already carries road is a tenth of the price. Routes then converge
        # into shared trunks and branch late, which is what a road network
        # actually looks like and what no per-road search can produce on its
        # own -- the five roads out of the gate leave town as one road.
        if here in (T["path_dirt"], T["bridge"], T["floor_stone"]):
            step *= 0.1
        return step

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
                # 0.1 per step, because the reuse discount makes that the
                # cheapest a step can be. A heuristic of 1.0 per step would
                # overestimate along an existing road and A* would stop being
                # optimal exactly where we most want it to follow one.
                h = 0.1 * (abs(b[0] - nx) + abs(b[1] - ny))
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
    # Water Lane, up the west bank between the house and the leat to the mill
    # pond and the west field, and the Sheep Walk south between the tinkerer's
    # and the mayor's. Neither is here for elegance: without them the north-west
    # of the vale and the south meadow are LAND THE PLAYER CAN SEE AND NEVER
    # STAND ON, which the pocket check in main() reports as a build failure.
    ("water_lane",  [(106, 150), (106, 141), (105, 133), (103, 125),
                     (101, 117), (100, 109), (99, 103)], 1, "path_dirt"),
    ("sheep_walk",  [(130, 161), (130, 170), (132, 177)], 1, "path_dirt"),
]

## The market square, and it now REACHES HIGH STREET.
##
## It used to start at y = 132, two rows below the street's south kerb, and the
## two rows between them were left as whatever the terrain pass had put there --
## a full-width band of grass straight across the middle of the paving, visible
## in .scratch/town-141-130.png and the single most obvious thing wrong with the
## town square. The square is not a rectangle that happens to sit near the
## street; docs/PROCGEN-RESEARCH.md §2.1 has it exactly: "a market is not a
## special case: it is a cell where several lanes meet, widened by two". So it
## is widened from the street it is a widening OF, and the two rows come back.
SQUARE = (132, 130, 13, 11)

## Metalled beats unmetalled where two roads cross.
##
## `streets` is a dict and the old loop simply assigned into it, so at a
## junction the winner was whichever street came later in STREETS -- which put a
## three-cell notch of mud across the paving of High Street where the north lane
## and the alley met it, for no reason anybody chose. A village metals its
## through route and the lanes join it; the junction takes the better surface.
PAVING = {"path_dirt": 0, "floor_stone": 1}

## GRASS VERGES, stated rather than left over.
##
## Kevin's note on the old square was that it read as a car park, and the answer
## then was to pave almost nothing. That went too far and left accidental
## stripes instead. The answer here is the one a real square has: paving that is
## CONTINUOUS, with a kerb, and something green on the other side of the kerb
## that is there on purpose. These rectangles are subtracted from the paved set
## after it has been closed, so they are the only places inside the square's
## bounding box where the flagstones stop, and each is a strip TWO cells wide
## along the full run of the square rather than a patch: a verge that starts
## and stops is the accidental stripe again with a comment on it.
##
## Both sit between the square and a dirt lane -- the alley on the west, the
## shop row on the east -- which is exactly where a village puts its green:
## metalling is expensive and you stop laying it where the lane takes over.
##
## Cells that are already built, watered or hedged are dropped, so a verge can
## never punch a hole in a wall or the river.
VERGES = [
    (130, 130, 2, 11),        # the west shoulder, between the alley and the square
    (145, 130, 2, 11),        # the east shoulder, between the square and the shop row
]

BRIDGES = [("town_bridge", (114, 149, 7, 4)),
           ("north_bridge", (130, 100, 5, 6))]

## Who stands outside which door. The offset is from the doorstep, so a person
## is beside their threshold rather than in it -- standing IN a doorway blocks
## the building, and `adjacent` reach means beside is close enough to talk.
## Offsets are the side the street is on, which is not the same for every door
## -- the busybodies' faces east onto the square, the tavern and the empty house
## open north. Worked out by asking which neighbour is walkable rather than
## assumed, because the first guess put Bram inside his own front wall and the
## build refused it.
TOWNSFOLK = [
    ("kid_bird",  (161, 129), (-1,  0)),   # beside the barricade, counting
    ("busybody",  (126, 135), ( 1,  0)),   # hard on the pavement, facing the square
    ("tobin",     (140, 146), ( 0, -1)),   # outside the tavern he works behind
    ("cobb",      (148, 135), (-1,  0)),   # the store he sleeps in the back of
    ("bram",      (105, 158), ( 0, -1)),   # outside the empty house that is his
]

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
    ("neighbour_e", 108, 142, 7, 7, (111, 148), "wall_timber", "roof_thatch"),
    ("across", 92, 155, 8, 7, (95, 155), "wall_plaster", "roof_thatch"),
]

## Extensions: a second roof over part of a building, because a building that
## grew has a seam. The tavern is the case Kevin named -- "timber-framed with
## plaster infill because it was cheap and got extended twice" -- and one
## rectangle of pantile over the east third of a thatched roof says that in a
## way no amount of footprint variation can. It is the cheapest piece of history
## in the town and it costs four lines.
##
## BOTH OF THESE ARE CURRENTLY INERT, and saying so is cheaper than leaving
## somebody to find out. The tavern and the farmhouse are the two buildings the
## extension mechanism was written for and both are now enterable, so their roof
## is a cutaway floor and there is no second roof left to lay. The sentence the
## rectangle used to say is said by the interior instead: the tavern's snug is
## flagged where its common room is boarded and the old outside wall is still
## standing between them, and the farmhouse's dairy is cold stone under the same
## seam. The pass is kept because it is four lines and the next building that
## grew and stays shut will want it.
##
## (building id, x, y, w, h, roof)
EXTENSIONS = [
    ("tavern", 143, 146, 4, 9, "roof_pantile"),
    ("farmhouse", 108, 105, 11, 3, "roof_slate"),
]

OUTBUILDINGS = [
    (100, 100, 5, 4, "roof_thatch"),      # the barn, in the fields
    (101, 105, 4, 3, "roof_thatch"),      # the byre
    (150, 124, 3, 3, "roof_pantile"),     # the inn's stable, off the back lane
    (137, 156, 4, 3, "roof_thatch"),      # the tavern's brewhouse
    (148, 155, 3, 3, "roof_thatch"),
    (128, 123, 3, 3, "roof_slate"),       # the mill's cart shed
    (109, 137, 3, 3, "roof_thatch"),      # the woodshed behind the girl's
    (80, 137, 3, 3, "roof_thatch"),       # and behind the guy's
    (155, 142, 3, 3, "roof_slate"),       # the store's stock shed
]



# --- the insides of the town's buildings ---------------------------------------
#
# "The town only has 3 accessible buildings as far as I can tell" -- and the
# three that felt accessible were only the ones with somebody standing in the
# doorway. Every building in BUILDINGS was a solid block of roof with a painted
# `door` tile in the wall, which is a picture of a door rather than a door.
#
# An interior in this game is NOT a separate scene. It is a carved, furnished,
# walkable region of the same overworld grid, listed in the world file's
# `indoors` so the engine knows the roof is between you and the sky. `house_plan`
# is the worked example and everything below follows it:
#
#   * the geometry is stated ONCE, here, and every other pass reads it. Nothing
#     recomputes a wall position -- that is what put a chair inside a wall the
#     first time the house was built;
#   * a room reads as having a purpose or it reads as storage, so every room
#     below has an anchor and a floor of its own. A change of material is what
#     tells the player they have gone somewhere before they have seen a stick of
#     the furniture;
#   * case goods go against walls and only tables float;
#   * one clear tile -- 36 in, one walkway -- in front of every doorway on both
#     sides, and nothing solid on a landing cell;
#   * and none of it is trusted. `furnish_buildings` raises rather than dropping
#     a piece, and main() flood-fills every one of these rooms twice: once to
#     prove you can reach every cell of it from the bed, and once with its own
#     door treated as solid to prove the only way in is the door.
#
# THE ROOF COMES OFF. A building the player can walk into is drawn as a cutaway,
# exactly as the house is: floor and wall courses, no roof tile. So an enterable
# building loses its ridge and its chimney stacks, because there is no longer a
# roof for them to stand on -- see `facade_props`, which asks. The buildings that
# stay shut keep theirs, and so do all nine outbuildings, which is what stops the
# parish reading as fourteen open floor plans.
#
# THE TAVERN'S SEAM SURVIVES THE ROOF. EXTENSIONS said "this building grew" with
# a rectangle of a second roof material, and with the roof gone that sentence has
# nowhere to be written. It is written on the FLOOR instead: the tavern's snug is
# flagged where the common room is boarded and the old outside wall is still
# standing between them as an internal wall, which says the same thing louder.
#
# Interior coordinates (i, j) run from the cell inside the north-west corner, so
# a layout below reads as a floor plan rather than as a list of world cells:
# i is 0 .. w - 3 and j is 0 .. h - 3 for a building w x h. `interior_plan`
# resolves them and refuses anything that falls outside the walls.
#
#   floors     ((i0, j0, i1, j1), material) painted in order, later wins. The
#              first entry is the whole room; the ones after it are the rooms
#              inside it.
#   walls      (i0, j0, i1, j1) runs, painted in the building's OWN wall
#              material -- shared construction is what makes it one town.
#   doorways   cells punched back out of those runs. A doorway is a GAP, not a
#              `door` tile: the wall's overlay set draws its face into the
#              opening, which reads as a lintel. A `door` tile inside a building
#              would be a second front door.
#   furniture  (catalogue id, i, j), placed by hand and checked on placement.
#   place      what the run header calls the room. Emitted into `indoors` as
#              `place`, which HJWorld.place_name() returns instead of "Home".
#   door       the interactable kind for the front door, from
#              data/content/interactables.json.
#
# ONE TILE IS ABOUT THREE FEET, from the front door: one cell, and a real door is
# 36 in. Every clearance below is quoted against that ruler.
INTERIORS = {
    # THE MILL. 8 x 8 of stone floor -- 24 x 24 ft -- because a mill floor is a
    # working surface that gets wet. The north two rows are boarded: that is the
    # staging the sacks come down onto off the hoist, and the one gap in the
    # north run at (4, 0) is where they land. The toll office is walled off in
    # the south-east corner, which is where a miller sits to take his tenth
    # without leaving the floor.
    "mill": dict(
        place="The Wend Mill",
        door="door_mill",
        floors=[((0, 0, 7, 7), "floor_stone"), ((0, 0, 7, 1), "floor_plank")],
        walls=[(5, 5, 7, 5), (5, 6, 5, 7)],
        doorways=[(5, 6)],
        furniture=[
            # the meal bins and the sack staging along the north wall, with the
            # hoist's drop at (4, 0) deliberately left clear
            ("crate", 0, 0), ("crate", 1, 0), ("barrel", 2, 0), ("barrel", 3, 0),
            ("crate", 5, 0), ("barrel", 6, 0), ("crate", 7, 0),
            # case goods on the walls, both sides
            ("shelf_open", 0, 2), ("barrel", 0, 3), ("crate", 0, 4),
            ("bench", 0, 6),
            ("counter", 7, 1), ("counter", 7, 2), ("chest", 7, 3),
            ("shelf_open", 7, 4),
            # the weighing table, the only thing allowed to float, with a chair
            # each side and the cup somebody left on the floor beside it
            ("table", 3, 3), ("chair", 2, 3), ("chair", 4, 3), ("cup", 4, 2),
            ("floor_lamp", 1, 7), ("boots", 2, 7),
            # the toll office: a counter, the chest it goes in, one candle
            ("counter", 7, 6), ("chest", 7, 7), ("candle", 6, 7),
        ],
    ),
    # THE COMMONHOUSE. The parish hall, and the biggest room in the vale at
    # 11 x 8 -- 33 x 24 ft. It is entered through a SCREENS PASSAGE: a stone
    # vestibule the width of the building with the hall beyond it, so you come in
    # at the low end and turn, which is how every real hall of this shape works
    # and which stops the front door looking straight down the meeting table.
    # The committee room in the north-east corner is the one lockable room, and
    # the parish chest lives in it.
    "commonhouse": dict(
        place="The Commonhouse",
        door="door_commonhouse",
        floors=[((0, 0, 10, 10), "floor_boards"),
                ((7, 0, 10, 3), "floor_tile"),
                ((0, 9, 10, 10), "floor_stone")],
        walls=[(0, 8, 10, 8), (6, 0, 6, 4), (7, 4, 10, 4)],
        doorways=[(2, 8), (8, 8), (6, 3)],
        furniture=[
            # -- the hall ------------------------------------------------------
            ("bookshelf", 0, 0), ("chest", 1, 0), ("shelf_open", 2, 0),
            ("shelf_open", 3, 0), ("chest", 4, 0), ("plant_pot", 5, 0),
            ("bench", 0, 2), ("bench", 0, 3), ("chest", 0, 5),
            ("floor_lamp", 0, 7),
            # the meeting table, with the head of it against the north end and
            # one chair pushed back from the foot -- the cell it was pulled out
            # of, (3, 4), is left empty on purpose. A chair_pulled against a full
            # table says nothing; the gap is the whole trick.
            ("table", 3, 3), ("chair", 2, 2), ("chair", 2, 3),
            ("chair", 4, 2), ("chair", 4, 3), ("chair_pulled", 3, 5),
            ("cup", 4, 5), ("book_open", 1, 4),
            # the serving side, against the east wall
            ("counter", 10, 5), ("counter", 10, 6), ("barrel", 10, 7),
            ("bench", 5, 7), ("crate", 9, 7),
            # -- the committee room, and the parish chest ----------------------
            ("bookshelf", 7, 0), ("chest", 8, 0), ("shelf_open", 10, 0),
            ("table", 9, 1), ("chest", 10, 1), ("chair", 9, 2),
            ("candle", 10, 3), ("book_open", 8, 2),
            # -- the screens passage -------------------------------------------
            ("bench", 0, 9), ("bench", 10, 9), ("boots", 4, 10),
            ("plant_pot", 0, 10), ("crate", 10, 10),
        ],
    ),
    # THE WAYHOUSE. A taproom you can sit four in and one room to let, which is
    # what a village inn on a road this size actually is. The let room is two
    # cells wide -- 6 x 18 ft -- which is a bed, a chest and enough floor to
    # stand up in, and that is the truthful size of a rented room.
    "innkeeper": dict(
        place="The Wayhouse",
        door="door_innkeeper",
        floors=[((0, 0, 6, 5), "floor_boards"), ((5, 0, 6, 5), "floor_plank")],
        walls=[(4, 0, 4, 5)],
        doorways=[(4, 2)],
        furniture=[
            # -- the taproom ---------------------------------------------------
            # The bar and the cellar barrel are on the north wall and the table
            # sits in the middle of the floor, so column 3 stays clear from the
            # front door all the way to the doorway of the let room: one clear
            # tile on both sides of it, which is the 36 in walkway.
            ("counter", 0, 0), ("counter", 1, 0), ("barrel", 2, 0),
            ("floor_lamp", 3, 0), ("shelf_open", 0, 1),
            ("table", 2, 3), ("chair", 1, 3), ("chair", 3, 3),
            # and the chair somebody pushed back, with (2, 4) left empty
            ("chair_pulled", 2, 5), ("bench", 0, 5),
            ("cup", 1, 1), ("bottle", 3, 1), ("boots", 1, 4),
            # -- the room to let -----------------------------------------------
            ("bed", 6, 1), ("chest", 5, 0), ("chest", 6, 2),
            ("shelf_open", 6, 4), ("candle", 5, 1), ("boots", 5, 5),
        ],
    ),
    # THE OLLARDS'. Mrs Ollard "was at the window a moment ago and is now,
    # somehow, out here", and the room is the evidence: the front parlour faces
    # EAST onto the market square, her chair is in the north-east corner under
    # the window, and there is a clear line from it to the door she came out of.
    # The kitchen is two rows at the back and unheated but for the range.
    "busybodies": dict(
        place="The Ollards' Front Room",
        door="door_busybodies",
        floors=[((0, 0, 4, 5), "floor_plank"), ((0, 4, 4, 5), "floor_tile")],
        walls=[(0, 3, 4, 3)],
        doorways=[(1, 3)],
        furniture=[
            # -- the front room, and the chair at the window -------------------
            # Her chair is in the north-east corner with the square through the
            # window in front of it and a clear run to the door she comes out of
            # -- which is the whole of what the catalogue says about her.
            ("chair", 4, 0),
            ("bookshelf", 0, 0), ("chest", 0, 1), ("plant_pot", 0, 2),
            ("table", 2, 2), ("chair", 3, 2), ("floor_lamp", 3, 0),
            ("cup", 3, 1), ("book_open", 1, 1),
            # -- the kitchen ---------------------------------------------------
            # (1, 4) is the landing of the only doorway and stays clear, so the
            # range run starts one cell along.
            ("shelf_open", 0, 4), ("stove", 2, 4), ("counter", 3, 4),
            ("counter", 4, 4), ("bench", 0, 5), ("crate", 4, 5),
            ("bottle", 1, 5),
        ],
    ),
    # COBB'S. Shopfront and the back room he sleeps in, which is the shape the
    # catalogue already gives him: "He sleeps in the back and it shows". The
    # counter run is along the north where the light is, the middle of the shop
    # is left empty because that is where the customers stand, and the wares are
    # on the walls.
    "store": dict(
        place="Cobb's Stores",
        door="door_store",
        floors=[((0, 0, 8, 5), "floor_boards"), ((7, 0, 8, 5), "floor_plank")],
        walls=[(6, 0, 6, 5)],
        doorways=[(6, 4)],
        furniture=[
            # -- the shop ------------------------------------------------------
            ("shelf_open", 0, 0), ("shelf_open", 1, 0), ("counter", 2, 0),
            ("counter", 3, 0), ("counter", 4, 0), ("counter", 5, 0),
            ("crate", 0, 4), ("barrel", 0, 5),
            ("barrel", 1, 5), ("crate", 2, 5), ("crate", 3, 5), ("barrel", 4, 5),
            ("shelf_open", 5, 1), ("shelf_open", 5, 2), ("chest", 5, 3),
            ("table", 2, 3), ("floor_lamp", 5, 5),
            ("cup", 4, 2), ("bottle", 1, 1), ("book_open", 4, 4),
            # -- the back room he sleeps in ------------------------------------
            ("chest", 7, 0), ("bed", 8, 1), ("chest", 8, 2),
            ("shelf_open", 8, 3), ("barrel", 7, 5), ("crate", 8, 5),
            ("candle", 7, 1), ("boots", 7, 3), ("bottle", 8, 4),
        ],
    ),
    # THE BLIND EWE. Timber-framed, thatched, and extended east once -- and the
    # seam is the internal wall at i = 6, which is the pub's old outside wall
    # with a doorway knocked through it. Common room on boards, snug on flags,
    # because the snug was a yard before it was a room. The bar is the L in the
    # north-west corner, which is where Tobin stands when he is not out the front
    # wiping something that is already clean.
    "tavern": dict(
        place="The Blind Ewe",
        door="door_tavern",
        floors=[((0, 0, 9, 6), "floor_boards"), ((7, 0, 9, 6), "floor_stone")],
        walls=[(6, 0, 6, 6)],
        doorways=[(6, 4)],
        furniture=[
            # -- the bar, in the corner you see from the door ------------------
            ("counter", 0, 0), ("counter", 1, 0), ("counter", 2, 0),
            ("counter", 0, 1), ("counter", 0, 2),
            ("barrel", 0, 3), ("barrel", 0, 4),
            # the fire, and the only warm light in the room
            ("stove", 0, 5),
            # -- the tables ----------------------------------------------------
            ("table", 2, 3), ("chair", 1, 2), ("chair", 1, 3), ("chair", 3, 2),
            # pushed back from the foot of the table, with (2, 4) -- the cell it
            # was pulled out of -- left empty. Row 4 stays open right across the
            # room, which is the route from the door to the fire and the snug.
            ("chair_pulled", 2, 5),
            ("table", 4, 6), ("chair", 3, 6), ("chair", 5, 5),
            ("shelf_open", 5, 0), ("chest", 5, 1),
            ("bench", 0, 6), ("crate", 5, 6),
            ("bottle", 4, 1), ("cup", 1, 5), ("boots", 3, 0),
            # -- the snug ------------------------------------------------------
            ("shelf_open", 7, 0), ("shelf_open", 9, 0),
            ("table", 8, 1), ("chair", 7, 1), ("chair", 9, 1),
            ("chest", 7, 3), ("floor_lamp", 9, 3),
            ("barrel", 9, 5), ("crate", 9, 6), ("bench", 7, 6),
            ("candle", 8, 5),
        ],
    ),
    # TOBIN'S. The tavernkeep's own cottage, and it is small on purpose: a man
    # who works twenty feet away does not need a hall. Two rooms, 5 x 3 and
    # 5 x 2, and the bed is against the internal wall so it has a solid head and
    # is not in the column of the door.
    "tavernkeep": dict(
        place="Tobin's Cottage",
        door="door_tavernkeep",
        floors=[((0, 0, 4, 5), "floor_boards"), ((0, 4, 4, 5), "floor_plank")],
        walls=[(0, 3, 4, 3)],
        doorways=[(3, 3)],
        furniture=[
            # -- the room he lives in ------------------------------------------
            ("counter", 0, 0), ("stove", 0, 1), ("counter", 0, 2),
            ("shelf_open", 4, 0), ("chest", 4, 1),
            ("table", 1, 2), ("chair", 2, 2), ("bench", 4, 2),
            ("cup", 3, 1), ("bottle", 1, 0),
            # -- the room he sleeps in -----------------------------------------
            ("bed", 0, 5), ("chest", 4, 4), ("shelf_open", 4, 5),
            ("candle", 1, 4), ("boots", 2, 5),
        ],
    ),
    # THE TINKER'S. A workshop first: stone floor, two benches out in the middle
    # of it where the light is, a forge against the back wall, and the parts on
    # every wall there is. He lives in the two rows behind it, which is what the
    # back of a shop is for.
    "tinkerer": dict(
        place="The Tinker's Shop",
        door="door_tinkerer",
        floors=[((0, 0, 8, 6), "floor_stone"), ((0, 5, 8, 6), "floor_boards")],
        walls=[(0, 4, 8, 4)],
        doorways=[(4, 4)],
        furniture=[
            # -- the workshop --------------------------------------------------
            ("counter", 0, 0), ("counter", 1, 0), ("shelf_open", 2, 0),
            ("shelf_open", 6, 0), ("counter", 7, 0), ("counter", 8, 0),
            ("shelf_open", 0, 1), ("chest", 0, 2), ("barrel", 0, 3),
            ("bookshelf", 8, 1), ("chest", 8, 2), ("crate", 8, 3),
            # the two benches, with column 4 left clear between them: it is the
            # route from the shop door straight through to the room he lives in,
            # and the stool has been pushed back into the corner at (7, 3) with
            # the working side of the bench at (6, 2) left empty behind it
            ("table", 3, 2), ("table", 5, 2), ("chair_pulled", 7, 3),
            # the forge, with the back wall behind it
            ("stove", 1, 3),
            ("cup", 6, 2), ("bottle", 6, 1),
            # -- the room he lives in ------------------------------------------
            ("bed", 0, 6), ("chest", 1, 6), ("bench", 2, 6),
            ("bookshelf", 5, 6), ("chest", 6, 6), ("shelf_open", 7, 6),
            ("counter", 8, 5), ("counter", 8, 6),
            ("floor_lamp", 4, 6), ("candle", 1, 5), ("boots", 3, 6),
        ],
    ),
    # THE MAYOR'S. The only house in the parish with a fence in front of it, and
    # the only one with three rooms and a corridor's worth of manners: a parlour
    # you are received in, a study you are not, and the kitchen behind. The rug
    # in the parlour is what makes the table and its chairs read as one group
    # rather than four objects -- it has to reach under the front of every piece.
    "mayor": dict(
        place="The Mayor's Parlour",
        door="door_mayor",
        floors=[((0, 0, 9, 7), "floor_boards"),
                ((0, 0, 5, 3), "floor_plank"),
                ((0, 5, 5, 7), "floor_tile"),
                # The rug runs one row PAST the chairs, at j = 3, because a rug
                # entirely under the furniture is a rug nobody can see: it has
                # to reach under the front of every piece and then show.
                ((1, 1, 3, 3), "floor_rug")],
        walls=[(6, 0, 6, 7), (0, 4, 5, 4)],
        doorways=[(6, 3), (2, 4)],
        furniture=[
            # -- the parlour ---------------------------------------------------
            # The table and its four chairs sit on the rug, which is what makes
            # them read as one group rather than five objects, and columns 4 and
            # 5 are left entirely clear: that is the corridor from the front door
            # to the study doorway and to the kitchen, and no chair stands in it.
            ("bookshelf", 0, 0), ("chest", 1, 0), ("bookshelf", 2, 0),
            ("bookshelf", 3, 0), ("floor_lamp", 4, 0),
            ("chest", 0, 1), ("bench", 0, 2), ("chest", 0, 3),
            ("table", 2, 2), ("chair", 1, 1), ("chair", 3, 1),
            ("chair", 1, 2), ("chair", 3, 2),
            ("book_open", 4, 2), ("cup", 5, 3),
            # -- the kitchen ---------------------------------------------------
            # (2, 5) is the landing of the parlour doorway and stays clear, which
            # is why the range run has a gap in the middle of it.
            ("counter", 0, 5), ("stove", 1, 5), ("counter", 3, 5),
            ("counter", 4, 5), ("shelf_open", 5, 5),
            ("barrel", 0, 7), ("crate", 1, 7), ("bench", 3, 7),
            ("table", 5, 7), ("chair", 4, 7), ("chair", 4, 6),
            ("bottle", 0, 6), ("cup", 2, 7),
            # -- the study -----------------------------------------------------
            ("bookshelf", 7, 0), ("bookshelf", 8, 0), ("bookshelf", 9, 0),
            ("bookshelf", 7, 1), ("bookshelf", 7, 2),
            ("chair", 8, 1), ("counter", 9, 1), ("chest", 9, 2),
            ("bookshelf", 9, 4), ("chest", 9, 5),
            ("bench", 7, 5), ("chest", 7, 6),
            ("floor_lamp", 7, 7), ("candle", 9, 7), ("book_open", 8, 3),
        ],
    ),
    # THE EMPTY HOUSE. Bram's, and the whole point of it is that nobody lives
    # here: one chair in the middle of a floor facing nothing, one candle, no
    # lamp, and a cold store at the back full of what he has been carrying home.
    # An absence is the cheapest characterisation there is, and it is the same
    # device as the bramble across the path outside.
    "empty_house": dict(
        place="The Empty House",
        door="door_empty_house",
        floors=[((0, 0, 6, 6), "floor_boards"), ((0, 5, 6, 6), "floor_stone")],
        walls=[(0, 4, 6, 4)],
        doorways=[(5, 4)],
        furniture=[
            # -- the room somebody used to sit in ------------------------------
            ("chair", 1, 2),
            ("chest", 0, 0), ("crate", 6, 0), ("barrel", 0, 2), ("crate", 0, 3),
            ("bench", 6, 3), ("candle", 5, 1), ("book_open", 4, 2),
            ("boots", 2, 1),
            # -- the cold store, and what Bram has been bringing in ------------
            ("barrel", 0, 5), ("crate", 1, 5), ("crate", 0, 6),
            ("barrel", 6, 6), ("shelf_open", 6, 5), ("bottle", 3, 6),
        ],
    ),
    # WENDFIELD FARM. The one building in the parish that is a place of work and
    # a home in the same walls: a farm kitchen with the range and the long table,
    # and behind it the dairy -- the lean-to that EXTENSIONS used to say had been
    # added, floored in cold stone because that is what a dairy is for.
    "farmhouse": dict(
        place="Wendfield Farm",
        door="door_farmhouse",
        floors=[((0, 0, 8, 6), "floor_boards"),
                ((0, 0, 8, 3), "floor_tile"),
                ((0, 5, 8, 6), "floor_stone")],
        walls=[(0, 4, 8, 4)],
        doorways=[(2, 4), (6, 4)],
        furniture=[
            # -- the farm kitchen ----------------------------------------------
            ("shelf_open", 0, 0), ("stove", 1, 0), ("counter", 2, 0),
            ("counter", 3, 0), ("counter", 4, 0), ("bookshelf", 5, 0),
            ("chest", 6, 0), ("barrel", 7, 0),
            ("bench", 0, 2), ("chest", 0, 3),
            # the long table everybody eats at, with one seat pushed back and
            # (5, 2) left empty
            ("table", 4, 2), ("chair", 3, 1), ("chair", 5, 1), ("chair", 3, 2),
            ("chair_pulled", 5, 3),
            ("cup", 2, 1), ("bottle", 6, 1), ("boots", 1, 3),
            # -- the dairy -----------------------------------------------------
            ("counter", 0, 5), ("counter", 1, 5), ("barrel", 3, 5),
            ("crate", 4, 5), ("counter", 5, 5), ("shelf_open", 7, 5),
            ("chest", 8, 5),
            ("barrel", 0, 6), ("crate", 1, 6), ("crate", 8, 6),
            ("cup", 4, 6), ("candle", 7, 6),
        ],
    ),
    # NEXT DOOR, WEST. Four cells by five -- 12 x 15 ft -- which is one room with
    # a bed in it, and that is an honest cottage rather than a small house. The
    # range is on the north wall, the bed's head is against it, and the table is
    # the only thing floating.
    "neighbour_w": dict(
        place="Next Door, West",
        door="door_neighbour_w",
        floors=[((0, 0, 3, 4), "floor_boards"), ((0, 0, 1, 1), "floor_plank")],
        walls=[],
        doorways=[],
        furniture=[
            ("bed", 0, 1), ("counter", 1, 0), ("stove", 2, 0),
            ("shelf_open", 3, 0), ("chest", 3, 1),
            ("table", 2, 3), ("chair", 1, 3),
            ("candle", 1, 1), ("boots", 1, 4), ("cup", 3, 2),
        ],
    ),
    # NEXT DOOR, EAST. The same cottage one cell wider and with the bed on the
    # other side, because two houses built by the same parish should read as the
    # same building lived in by different people -- shared construction, and the
    # difference is the arrangement.
    "neighbour_e": dict(
        place="Next Door, East",
        door="door_neighbour_e",
        floors=[((0, 0, 4, 4), "floor_boards"), ((3, 0, 4, 2), "floor_plank")],
        walls=[],
        doorways=[],
        furniture=[
            ("bed", 4, 1), ("stove", 0, 0), ("counter", 1, 0), ("counter", 2, 0),
            ("shelf_open", 0, 1), ("chest", 0, 2),
            ("table", 2, 2), ("chair", 1, 2), ("chair", 1, 1),
            ("bench", 0, 4), ("crate", 4, 4),
            ("candle", 3, 1), ("book_open", 3, 3), ("boots", 1, 4),
        ],
    ),
}

## And the buildings that stay shut, with the sentence the door says when you
## try it. A shut door with a line of text is far better than a wall, because it
## tells the player the building IS a building -- the failure being fixed here is
## that fourteen of them read as scenery. Anything not furnished above belongs in
## this list rather than being left silent.
##
## `door_across` declares `blocks_until_tag` in the catalogue, so
## HJWorld.walkable() returns false on the cell and every path query respects it
## with no special case -- the same mechanism as the front door and the fort
## gate, one radius out.
SHUT_DOORS = {
    "across": "door_across",
}


def interior_plan(b):
    """One building's interior, resolved from the (i, j) floor plan into cells.

    Returns None for a building with no interior, which is how every other pass
    asks whether the roof comes off. Everything is checked against the wall
    rectangle here rather than where it is used, because a coordinate one cell
    out is a piece of furniture inside a wall and the whole reason `house_plan`
    exists is that the house computed one twice and got it wrong the second time.
    """
    spec = INTERIORS.get(b["id"])
    if spec is None:
        return None
    ix, iy = b["x"] + 1, b["y"] + 1
    iw, ih = b["w"] - 2, b["h"] - 2

    def cell(i, j):
        if not (0 <= i < iw and 0 <= j < ih):
            raise SystemExit(
                "%s: (%d,%d) is outside the interior, which is %dx%d"
                % (b["id"], i, j, iw, ih))
        return (ix + i, iy + j)

    floors = {}
    for (i0, j0, i1, j1), material in spec["floors"]:
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                floors[cell(i, j)] = material
    if len(floors) != iw * ih:
        raise SystemExit(
            "%s: %d of %d interior cells have no floor. The first entry of "
            "`floors` has to cover the whole room; the ones after it are the "
            "rooms inside it." % (b["id"], iw * ih - len(floors), iw * ih))

    walls = set()
    for (i0, j0, i1, j1) in spec["walls"]:
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                walls.add(cell(i, j))
    doorways = [cell(i, j) for (i, j) in spec["doorways"]]
    for c in doorways:
        if c not in walls:
            raise SystemExit(
                "%s: the doorway at %s is not in a wall, so it is a hole in a "
                "room rather than a door between two." % (b["id"], c))
    walls -= set(doorways)

    # The cell you land on when you come in through the front door, derived from
    # the door rather than declared beside it -- a hand-written landing is a
    # second statement of where the door is and the two drift.
    landing = [(b["door"][0] + dx, b["door"][1] + dy)
               for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))
               if ix <= b["door"][0] + dx < ix + iw
               and iy <= b["door"][1] + dy < iy + ih]
    if len(landing) != 1:
        raise SystemExit("%s: the door at %s has %d cells inside it"
                         % (b["id"], b["door"], len(landing)))

    return dict(id=b["id"], place=spec["place"], door=spec["door"],
                x=ix, y=iy, w=iw, h=ih, floors=floors, walls=walls,
                doorways=doorways, landing=landing[0],
                furniture=[(name, cell(i, j)) for (name, i, j) in spec["furniture"]],
                inside={cell(i, j) for j in range(ih) for i in range(iw)})

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
            if PAVING[material] >= PAVING.get(streets.get(c), -1):
                streets[c] = material
    for c in _rect(*SQUARE):
        streets[c] = "floor_stone"

    buildings = []
    extension_roof = {}
    for (bid, x, y, w, h, door, wall, roof) in BUILDINGS:
        foot = _rect(x, y, w, h)
        # The doorstep is derived, never declared: it is the neighbour of the
        # door that is not part of the building. A hand-written doorstep is a
        # second statement of where the door is, and the two drift.
        step = [(door[0] + dx, door[1] + dy)
                for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))
                if (door[0] + dx, door[1] + dy) not in foot]
        ext = set()
        for (eid, ex, ey, ew, eh, eroof) in EXTENSIONS:
            if eid != bid:
                continue
            patch = _rect(ex, ey, ew, eh) & foot
            ext |= patch
            for c in patch:
                extension_roof[c] = eroof
        buildings.append(dict(id=bid, x=x, y=y, w=w, h=h, door=door,
                              doorstep=step[0], wall=wall, roof=roof,
                              foot=foot, ring=_ring(x, y, w, h),
                              extensions=ext,
                              inside=_rect(x + 1, y + 1, w - 2, h - 2)))
    sheds = [dict(x=x, y=y, w=w, h=h, roof=m, foot=_rect(x, y, w, h))
             for (x, y, w, h, m) in OUTBUILDINGS]

    built = set()
    for b in buildings:
        built |= b["foot"]
    for s in sheds:
        built |= s["foot"]

    # THE PAVED AREA IS CLOSED, NOT ASSEMBLED.
    #
    # Two independent gaps, both visible on screen and neither in anybody's
    # plan. `_grow(polyline, 1)` is a plus-shaped dilation, so wherever High
    # Street turns a diagonal the plus of one cell and the plus of the next
    # touch only at a corner and leave a notch in the kerb; and a dirt lane laid
    # across the paving used to win the cell outright.
    #
    # A morphological closing at a gap of exactly ONE fixes both and can invent
    # paving nowhere else: a cell joins only if paving already lies on both
    # sides of it, so the set fills its own single-cell concavities and stops.
    #
    # Read from a SNAPSHOT and applied once. The first version let each new cell
    # seed the next and ran three passes at a gap of two, which is a dilation
    # wearing a closing's name -- it paved nine rows of the town centre
    # including the yards between the mill and the inn. A closing has to be a
    # fixed-point of the set it started from or it is just growth.
    paved = {c for c, m in streets.items() if m == "floor_stone"}
    off_limits = built | water | barrier | bridges
    for (x, y) in sorted(paved):
        for (ax, ay), (bx, by) in (((0, -1), (0, 1)), ((-1, 0), (1, 0))):
            gap = (x + ax, y + ay)
            if (gap in paved or gap in off_limits
                    or not (0 <= gap[0] < W and 0 <= gap[1] < H)):
                continue
            if (gap[0] + ax, gap[1] + ay) in paved:
                streets[gap] = "floor_stone"

    # ...and then the verges are taken back out, so that where the green
    # survives it is because somebody drew a kerb there.
    for r in VERGES:
        for c in _rect(*r):
            if c in off_limits:
                continue
            streets.pop(c, None)

    # AND THE PAVING IS PROVEN CONTINUOUS, not eyeballed.
    #
    # The defect this whole block exists to fix -- a full-width band of grass
    # straight across the market square -- is invisible in the tile histogram
    # and was found by a person walking the town on a phone. A flood fill over
    # the paved set is the cheap version of that walk: if High Street and the
    # square are one surface, every flagstone reaches every other flagstone,
    # and if a verge or a closing bug ever cuts the square in half again this
    # says so at generation time instead of six screenshots later.
    #
    # Deliberately ONE component and not "few": the vale has exactly one paved
    # surface in it, so a second component is a fragment somebody did not mean
    # -- which is what the two orphaned flagstones by the brook were.
    paved = {c for c, m in streets.items() if m == "floor_stone"}
    islands = []
    seen = set()
    for c in sorted(paved):
        if c in seen:
            continue
        lump, stack = set(), [c]
        while stack:
            here = stack.pop()
            if here in seen or here not in paved:
                continue
            seen.add(here)
            lump.add(here)
            stack += [(here[0] + dx, here[1] + dy) for dx, dy in ORTHOGONAL]
        islands.append(sorted(lump))
    islands.sort(key=len, reverse=True)
    if len(islands) > 1:
        raise SystemExit(
            "the paving is in %d pieces, not one: %s. High Street and the "
            "market square are one surface and the player walks from one onto "
            "the other; a stripe of grass across the middle of it is the fault "
            "this pass exists to prevent."
            % (len(islands), "; ".join("%d cells at %s" % (len(i), i[0])
                                       for i in islands)))

    return dict(water=water, barrier=barrier, bridges=bridges, streets=streets,
                extension_roof=extension_roof,
                buildings=buildings, sheds=sheds, built=built,
                square=_rect(*SQUARE), fort_wall=set(FORT_WALL),
                gate=FORT_GATE, pond=_blob(*POND),
                brook=_grow(_poly(BROOK_N), 1) | _grow(_poly(BROOK_S), 1) | _blob(*POND))


def stamp_vale(world, plan, only=None):
    """Water, boundary and bridges.

    Called twice. The second time is after the roads, because a road carver is
    exactly the kind of later pass that reopens a boundary -- it lays dirt in a
    plus around every cell it walks, so a road running ALONGSIDE the hedge
    paints over it without ever entering it.

    `only` scopes that second pass. It has to be scoped: outside the vale a road
    is allowed to bridge the Wend, and a blanket re-stamp would put the river
    back over its own bridge and cut the west of the world off. Ask for the
    unreachable-anchor failure that taught this; it is not visible in a picture.
    """
    for (x, y) in plan["water"]:
        if only is not None and (x, y) not in only:
            continue
        world.put(x, y, T["water"])
    for (x, y) in plan["barrier"]:
        if only is not None and (x, y) not in only:
            continue
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
        for (x, y) in b["extensions"]:
            world.put(x, y, T[plan["extension_roof"][(x, y)]])
        for (x, y) in b["ring"]:
            world.put(x, y, T[b["wall"]])
        world.put(b["door"][0], b["door"][1], T["door"])

        # AND THEN THE ROOF COMES OFF THE ONES YOU CAN WALK INTO.
        #
        # An interior in this game is a cutaway of the same grid, not a scene of
        # its own -- see INTERIORS -- so opening a building means replacing the
        # roof tiles inside its wall course with floors, standing the internal
        # walls up in the building's OWN material, and punching the doorways
        # back out of them as gaps. It is done here, inside the pass that is
        # called twice, so that a road, a scatter or anything else that runs
        # later cannot reopen a wall or repaint a floor: the second stamp puts
        # the whole building back exactly as the plan says it is.
        inside = interior_plan(b)
        if inside is None:
            continue
        for (x, y), material in inside["floors"].items():
            world.put(x, y, T[material])
        for (x, y) in inside["walls"]:
            world.put(x, y, T[b["wall"]])
        for (x, y) in inside["doorways"]:
            # A doorway is a GAP with the room's own floor under it. A `door`
            # tile in an internal wall would be a second front door.
            world.put(x, y, T[inside["floors"][(x, y)]])

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
            ("barrel", 11, 10), ("crate", 10, 12), ("bench", 5, 12),
            # and the boots by the front door, with the dog beside them.
            #
            # The bench used to be at (6,12), directly SOUTH of the dog, and on
            # the device that read as the dog standing on the furniture: a prop
            # is drawn 96 px tall in a 32 px cell and the cells are painted
            # north to south, so anything south of a prop is drawn over the
            # bottom two thirds of it. The dog is a live sprite, so he is the
            # one it shows on. It is checked now rather than remembered -- see
            # the interactables assertion in main().
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


ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
## Eight-way, INCLUDING corner-cutting. #84 has diagonal movement on the table
## and docs/PROCGEN-RESEARCH.md §2.5 names the hazard exactly: on a diagonal
## grid a one-tile river is crossable at any kitty-corner pinch, so a boundary
## proved with a four-way fill is not proved at all. Every seal in this file is
## checked with BOTH relations and the barrier is built wide enough to survive
## the harsher one; that way the answer does not change on the day the movement
## code does.
DIAGONAL = ORTHOGONAL + ((1, 1), (1, -1), (-1, 1), (-1, -1))


def reachable(world, start, moves=ORTHOGONAL):
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
        for dx, dy in moves:
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


def scatter_props(world, elev, rng, reach, plane, keep_clear=frozenset()):
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

    def free(x, y, foot, flat):
        for fy in range(foot[1]):
            for fx in range(foot[0]):
                cx, cy = x + fx, y - fy
                if (cx, cy) in blocked or plane[cy][cx] != 0:
                    return False
                if not world.walkable(cx, cy):
                    return False
                # Never in a doorway and never on a bridge: those are the two
                # places the player is guaranteed to be walking through, and a
                # bridge is planking that nothing grows on.
                if world.at(cx, cy) in (T["door"], T["bridge"]):
                    return False
                # A ROAD TAKES FLAT SCATTER AND NOTHING ELSE.
                #
                # This used to refuse a road outright, on the reasonable ground
                # that a boulder in the lane is a boulder in the lane. The
                # consequence nobody noticed is that the `path_dirt` scatter set
                # -- grit, ruts, dry leaves, the damp patch -- could never once
                # be placed on a road, because it is authored FOR roads and
                # roads were the one material it was forbidden. So the lanes
                # were 376 cells of bare tile with nothing on them at all, which
                # is half of why they read as a stain rather than as a street.
                #
                # The rule that was actually wanted is about what a prop IS, not
                # about where it is: a prop that is not solid, casts no shadow
                # and has no outline is texture lying ON the ground rather than
                # anything standing up off it, and texture belongs on a road.
                # `flat` is the catalogue's own word for it -- see the flat
                # contract in _p() -- and it is read rather than re-derived
                # here because the three declarations it comes from (`solid`,
                # `shadow`, `outline`) are not all in the manifest, and because
                # a second derivation of the same rule in a second tool is a
                # second chance to disagree with it. Absent means false, which
                # keeps everything off the road that was ever off the road.
                if world.at(cx, cy) == T["path_dirt"] and not flat:
                    return False
                # And never on a doorstep. The door cell is refused above, but
                # the cell you land on when you come out of it is ordinary grass
                # and a scattered tree took four of them -- which is a building
                # nobody can enter and, for the house, nowhere for Spite to
                # stand. Passed in rather than derived, because this function
                # knows about materials and nothing about doors.
                if (cx, cy) in keep_clear:
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

            # `keep_clear` is asked here, before a single draw is taken,
            # rather than only inside free(). It has to be: the town's thirteen
            # interiors are floor now, they are reachable, and every one of
            # their cells would otherwise offer the square's scatter set a
            # dice roll it can only ever lose -- seven hundred draws consumed to
            # place nothing, moving every anomaly downstream of them for no
            # reason anybody chose. free() still checks the whole FOOTPRINT
            # against the same set, because a prop two cells tall anchored
            # outside a room can still reach into one.
            if not options or (x, y) not in reach or (x, y) in keep_clear:
                continue
            for prop in options:
                if rng.random() >= prop["density"]:
                    continue
                foot = prop["foot"]
                flat = bool(prop.get("flat"))
                if not free(x, y, foot, flat):
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



def furnish_buildings(world, plane, plan):
    """Put the town's interiors in, and refuse to lose a stick of them.

    The same contract as `furnish_house`, `stock_town` and `dress_facades`, and
    the same reason: a `placed` prop has no density, so the validator's "this
    prop never appears" warning is blind to it and a bed that quietly failed to
    land would be an empty room nobody could explain. Every failure below is a
    build failure, not a `continue`.

    It reads its geometry out of `interior_plan` rather than working a wall
    position out for itself, which is the rule the house had to learn twice: the
    old `furnish_house` recomputed the internal wall, got it wrong, and dropped
    every piece that landed on one without saying so.
    """
    manifest = json.load(open(os.path.join(ROOT, "assets", "tiles", "tiles.json")))
    interior = {p["id"]: p for p in manifest["props"]["list"]
                if p["biome"] == "placed"}
    problems = []
    placed = 0
    rooms = 0
    for b in plan["buildings"]:
        spec = interior_plan(b)
        if spec is None:
            continue
        rooms += 1
        for (name, (x, y)) in spec["furniture"]:
            prop = interior.get(name)
            if prop is None:
                problems.append("%s: %s is not in the catalogue" % (b["id"], name))
                continue
            if plane[y][x]:
                problems.append("%s: %s at (%d,%d) lands on another prop"
                                % (b["id"], name, x, y))
                continue
            # Furniture stands on a floor. Anything else -- a chair on a wall, a
            # dresser on the doorstep -- is the plan and the stamp having drifted
            # apart, which is precisely the class of error that once put an NPC
            # inside his own front wall.
            material = ORDER[world.at(x, y)]
            if not world.walkable(x, y):
                problems.append("%s: %s at (%d,%d) lands on %s, which is not floor"
                                % (b["id"], name, x, y, material))
                continue
            if (x, y) == spec["landing"]:
                # One clear tile -- 36 in, one walkway -- on the inside of the
                # front door, so you arrive somewhere rather than into a barrel.
                problems.append("%s: %s at (%d,%d) is standing on the cell you "
                                "land on when you come in" % (b["id"], name, x, y))
                continue
            plane[y][x] = prop["plane"]
            placed += 1

        # ONE CLEAR TILE ON BOTH SIDES OF EVERY INTERNAL DOORWAY -- 36 in, one
        # walkway, the ruler house_plan sets. Checked rather than promised,
        # because the failure it catches is not a stranded cell (the flood fill
        # would find that) but a room you can only enter by squeezing past a
        # dresser standing in the opening. Both neighbours along the doorway's
        # own axis, and which axis that is comes from the wall it is cut into.
        solid_here = set()
        for (name, (x, y)) in spec["furniture"]:
            prop = interior.get(name)
            if prop is None or not prop["solid"]:
                continue
            for fy in range(prop["foot"][1]):
                for fx in range(prop["foot"][0]):
                    solid_here.add((x + fx, y - fy))
        for (dx, dy) in spec["doorways"]:
            axes = [[(dx - 1, dy), (dx + 1, dy)], [(dx, dy - 1), (dx, dy + 1)]]
            if not any(all(c not in spec["walls"] and c not in solid_here
                           for c in pair) for pair in axes):
                problems.append(
                    "%s: the doorway at (%d,%d) has no clear tile on both "
                    "sides of it" % (b["id"], dx, dy))

    if problems:
        raise SystemExit("the town's interiors are wrong:\n  "
                         + "\n  ".join(problems))
    return placed, rooms


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
    add("milestone", (158, 131))
    add("signpost", (130, 126))
    add("trash_can", (150, 131))
    add("bench", (137, 126))

    # -- shop fronts. The sign is how a building says what it sells ------------
    add("sign_shop", (147, 138),                   # the general store
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
    add("bench", (112, 123))                       # somebody sits and watches it
    add("reed_bed", (104, 115), (105, 119), (108, 122), (113, 110),
        (118, 112), (119, 119))

    # -- the fields: what a farm looks like from the road ----------------------
    add("haystack", (106, 108), (108, 109), (99, 106), (96, 101))
    add("cart", (107, 103))
    add("crate", (105, 104))
    # A paddock corner rather than a fence line: two short runs and a gate, so
    # it reads as an enclosure without being a second boundary. A long solid run
    # of props inside the vale can strand land behind it, which the flood fill
    # would catch -- but the honest fix is not to build one.
    add("fence_rail", *[(97, y) for y in range(103, 109)])
    add("fence_rail", *[(x, 109) for x in range(98, 104)])
    add("field_gate", (97, 109))
    add("washing_line", (106, 102))

    # -- the mayor's garden. Nobody else in town has a fence in front ----------
    add("fence_rail", *[(x, 162) for x in range(132, 144) if x != 138])
    add("plant_pot", (135, 163), (141, 163))
    add("bench", (134, 163))
    add("lamppost", (140, 163))

    # -- the hamlet: four cottages and the evidence that people live in them ---
    add("washing_line", (86, 149), (107, 146), (97, 153))
    add("boots", (83, 149))
    add("bench", (93, 153), (110, 149))
    add("crate", (86, 145), (107, 138))
    add("barrel", (86, 144))
    add("street_lamp", (91, 149))
    add("lamppost", (104, 149))
    add("plant_pot", (93, 154), (111, 141))
    add("cart", (99, 152))
    # The empty house gets NO lamp, no washing and a bramble across the path.
    # An absence is the cheapest characterisation there is.
    add("bramble", (102, 157), (104, 157), (110, 161))
    add("crate", (110, 163))

    # -- the children's defence -----------------------------------------------
    #
    # The barricade itself is load-bearing: it is the only thing between the
    # player and the rest of the world until the town's anomalies are closed.
    # Everything else here is the fort being LIVED IN, which is the difference
    # between a wall and a place children are holding.
    add("leaf_wall", *plan["fort_wall"])
    add("campfire", (157, 126))
    add("crate", (156, 125), (158, 126), (159, 132))
    add("barrel", (156, 127))
    add("signpost", (159, 131))
    add("bramble", (160, 134), (159, 124))
    add("washing_line", (159, 133))
    return out


## WHAT DRESSES A FACADE.
##
## The complaint that produced this: "every building presents a ten-plus-tile
## expanse of one wall material with a single door and nothing else". It is
## exactly right, and it is the single biggest reason the town does not read as
## a town -- fourteen buildings had between them fourteen features, one door
## each.
##
## The answer is NOT fifteen bespoke elevations. What makes it one town is that
## every facade is dressed by the same rule -- windows on one rhythm, a lintel
## and a sill on every one of them, a stack on every roof, damp at every foot --
## and what makes them fourteen different buildings is that the rule reads the
## material off the building it is dressing. That is the same division the roofs
## already make (see the table in make_tiles.py): shared construction, different
## material.
##
##   wall material   window          because
##   wall_stone      window_stone    rubble walls take dressed stone surrounds
##   wall_brick      window_stone    the two BUILT buildings, same dressings
##   wall_plaster    window_stone    plaster over a stone plinth
##   wall_timber     window_timber   a frame takes a shuttered frame, and warm
##                                   timber dressings rather than cold stone
##                                   ones -- the aperture, the mullion and the
##                                   transom are identical either way, so what
##                                   differs is the dressing and the shutters
##
## The chimney is deliberately NOT in the table. Every stack in the parish is
## brick, over thatch and slate alike, because it is the one part of a house
## whose job is to survive a chimney fire -- see the note in make_tiles.py. It
## is also the piece of shared silhouette the four roofs cannot be.
FACADE_KIT = {
    "wall_stone":   "window_stone",
    "wall_brick":   "window_stone",
    "wall_plaster": "window_stone",
    "wall_timber":  "window_timber",
}
CHIMNEY = "chimney_brick"

## The ridge cap. Neutral lead on every roof in the parish, so four roof
## materials share one line -- see the note on the sprite in make_tiles.py.
RIDGE = "roof_ridge"

## Who trades, and therefore hangs a board over the door. `sign_shop` already
## stands on the pavement outside five of these; the bracket is the other half
## of the same sentence and it goes ON the building, which is where a sign goes
## when the shop is hard on the street.
SHOPFRONTS = ("mill", "commonhouse", "innkeeper", "store", "tavern",
              "tinkerer", "tavernkeep")

## Every third cell. Two is a curtain wall of glass and four reads as a barn
## with a hole in it; three at 32 px is one window per metre and a bit, which is
## about right for a house whose windows are shuttered.
WINDOW_PITCH = 3

## And every fourth cell of the ground under a south wall gets its damp. Sparser
## than the windows on purpose -- weather is not periodic and a stain under
## every window would read as a second rhythm arguing with the first.
STAIN_PITCH = 4


def _facade_runs(b):
    """The wall courses of one building that a player actually looks at, as
    lists of cells in order along the run.

    Two of the four sides, never all four, and the reason is in the renderer.
    A wall cell is the CAP of the wall seen from above; the vertical face that
    makes it read as a wall at all is painted by the overlay set on the cell
    BELOW it -- and the cell below a north, east or west wall cell is another
    wall or the roof, neither of which has a rank in the precedence stack and
    so neither of which takes an overlay. Only the SOUTH course throws a face
    onto open ground, so only the south course reads as an elevation. That plus
    the side the door is on, which is the frontage by definition, is the whole
    of what is worth dressing; windows on the other two would be windows lying
    flat on a roofline.
    """
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    sides = {
        "S": [(i, y + h - 1) for i in range(x, x + w)],
        "N": [(i, y) for i in range(x, x + w)],
        "W": [(x, j) for j in range(y, y + h)],
        "E": [(x + w - 1, j) for j in range(y, y + h)],
    }
    dx, dy = b["door"]
    front = ("S" if dy == y + h - 1 else "N" if dy == y
             else "E" if dx == x + w - 1 else "W")
    return [sides[k] for k in dict.fromkeys((front, "S"))]


def facade_props(plan):
    """Every window, sign, chimney and stain in the town, derived.

    Fourteen buildings times two faces is twenty-eight runs, and a hand-written
    list of twenty-eight runs is twenty-eight chances to put a window one cell
    inside a wall. So
    what is hand-written here is the RULE and the geometry comes out of
    vale_plan's rectangles, which is the same discipline furnish_house imposed
    on the house after it built its internal wall twice and put a chair in it.

    No RNG. Every choice below is index arithmetic on the run, so this pass
    consumes no draws and cannot reshuffle anything downstream of it -- which
    matters, because there is one stream for the whole world and a new pass that
    draws from it moves every anomaly in the map (see the world-generator
    skill, "One RNG stream").

    Returns (prop id, x, y, what the cell must be) quadruples. The last field is
    the contract dress_facades checks: `wall` means a wall course, `roof` a
    roof, `ground` a walkable cell outside the building.

    THE FIRST TWO ARE MANDATORY AND THE THIRD IS NOT, and the difference is not
    laziness. A window and a stack are structure: the rectangle says where the
    wall is, so a window that misses it means the plan and the stamp disagree
    and that is a build failure. A stain is WEATHER, and the cell south of a
    south wall is ordinary generated world -- it is the river behind the
    tinkerer's, the thicket behind the mayor's, or the bench somebody already
    put there. Weather does not fall on the river. So `ground` may be refused
    per cell, and dress_facades reports how many were refused so that losing
    all of them would still show up in the build report.
    """
    out = []
    doorsteps = {b["doorstep"] for b in plan["buildings"]}
    # Nobody's standing room is dressed over. A townsperson is placed beside a
    # door by main(), and while none of these props is solid, a stain under
    # somebody's feet is still a stain nobody chose.
    reserved = doorsteps | {(d[0] + o[0], d[1] + o[1]) for (_k, d, o) in TOWNSFOLK}

    for b in plan["buildings"]:
        window = FACADE_KIT[b["wall"]]
        door = b["door"]

        for run in _facade_runs(b):
            # The corners are structure, not wall: a window in the quoin of a
            # building is a window in the corner of two walls at once.
            body = run[1:-1]
            if not body:
                continue
            # Centre the rhythm on the run rather than starting at one end, so a
            # facade is symmetrical about itself and two buildings of different
            # widths still look like they were built by the same mason.
            span = ((len(body) - 1) // WINDOW_PITCH) * WINDOW_PITCH
            start = (len(body) - 1 - span) // 2
            for k in range(start, len(body), WINDOW_PITCH):
                c = body[k]
                # A window does not go in the door, nor immediately beside it:
                # the jamb of the door and the jamb of the window would be the
                # same two pixels and the pair reads as one wide hole.
                if max(abs(c[0] - door[0]), abs(c[1] - door[1])) <= 1:
                    continue
                out.append((window, c[0], c[1], "wall"))

            # The sign hangs on the wall next to the door, on the frontage, on
            # whichever side of it has room. Only the run containing the door.
            if b["id"] in SHOPFRONTS and door in run:
                i = run.index(door)
                for j in (i - 1, i + 1):
                    if 0 < j < len(run) - 1 and not any(
                            q[1:3] == run[j] for q in out):
                        out.append(("sign_bracket", run[j][0], run[j][1], "wall"))
                        break

        # THE RIDGE AND THE CHIMNEYS SHARE A ROW, because they do on a building:
        # a stack comes up through the ridge, not through the middle of a slope.
        # One row, worked out once, and the stacks are punched out of the ridge
        # run rather than laid on top of it -- one prop per cell means the two
        # cannot both have the cell and the chimney is the one that wins.
        #
        # ...ON A BUILDING THAT STILL HAS A ROOF. A building the player can walk
        # into is drawn as a cutaway, so its roof tiles are floors now and a
        # ridge laid on one would be a lead cap running across somebody's
        # kitchen. Asked of the plan rather than listed here, so opening a
        # building is one entry in INTERIORS and not two.
        if interior_plan(b) is None:
            ry = b["y"] + max(2, b["h"] // 2)
            stacks = [b["x"] + max(1, b["w"] // 3)]
            if b["w"] >= 10:
                # Anything ten cells or more across gets two, one over each end.
                # A hall with one hearth in the middle of it is a hall with one
                # room.
                stacks = [b["x"] + 2, b["x"] + b["w"] - 3]
            for sx in stacks:
                out.append((CHIMNEY, sx, ry, "roof"))
            for rx in range(b["x"] + 1, b["x"] + b["w"] - 1):
                if rx in stacks:
                    continue
                out.append((RIDGE, rx, ry, "roof"))

        # AND THE DAMP AT THE FOOT OF IT. On the ground cell south of the south
        # wall, which is the cell the wall's vertical face is painted on -- see
        # `wall_base` in make_tiles.py, which draws in the top half of its own
        # cell for exactly that reason.
        south = [(i, b["y"] + b["h"]) for i in range(b["x"] + 1, b["x"] + b["w"] - 1)]
        for k in range(1, len(south), STAIN_PITCH):
            c = south[k]
            if c in reserved:
                continue
            out.append(("wall_base", c[0], c[1], "ground"))

    # THE OUTBUILDINGS GET A RIDGE AND NOTHING ELSE. A shed seen from above is
    # a roof -- it has no wall course and no door, which is why stamp_town does
    # not give it one -- but it still has a top, and nine sheds with no ridge
    # beside fifteen buildings with one is the two-idioms problem in miniature.
    for shed in plan["sheds"]:
        ry = shed["y"] + shed["h"] // 2
        for rx in range(shed["x"], shed["x"] + shed["w"]):
            out.append((RIDGE, rx, ry, "roof"))
    return out


def dress_facades(world, plane, plan):
    """Put the facade down, and refuse to lose a piece of it.

    The same contract as furnish_house and stock_town, and the same reason: a
    `placed` prop has no density, so the validator's "this prop never appears"
    warning is blind to it and a window that silently failed to land would be a
    blank wall nobody could explain.

    It adds one check those two do not have, and it is the one that would have
    caught the previous pass's mistake in a different costume: **every prop here
    declares what the cell under it must be, and the cell is read out of the
    world to see.** A window that is not on this building's own wall material,
    a chimney that is not on its own roof, a stain that is not on walkable
    ground -- each is a placement worked out from a rectangle that has drifted
    from what was actually stamped, which is precisely the class of error that
    put an NPC inside his own front wall.
    """
    manifest = json.load(open(os.path.join(ROOT, "assets", "tiles", "tiles.json")))
    catalogue = {p["id"]: p for p in manifest["props"]["list"]}
    problems = []
    placed = 0
    weathered = 0
    wanted_ground = 0
    for (name, x, y, wants) in facade_props(plan):
        # Weather may be refused; structure may not. Everything that goes wrong
        # below produces a sentence either way -- what `optional` decides is
        # whether the sentence is a build failure or a stain that did not fall.
        optional = wants == "ground"
        wanted_ground += 1 if optional else 0
        material = ORDER[world.at(x, y)]
        why = None
        prop = catalogue.get(name)
        if prop is None:
            why = "%s is not in the catalogue" % name
        elif prop["solid"]:
            # A facade prop is a picture on a surface that is already solid, or
            # a stain on a pavement the player walks over. Either way it must
            # not be the thing that decides collision: the wall already does
            # that, and a solid prop on a walkable cell would put an invisible
            # post in the street.
            why = "%s is solid and cannot dress a facade" % name
        elif wants == "wall" and not material.startswith("wall_"):
            why = "%s at (%d,%d) wants a wall and found %s" % (name, x, y, material)
        elif wants == "roof" and not material.startswith("roof"):
            why = "%s at (%d,%d) wants a roof and found %s" % (name, x, y, material)
        elif wants == "ground" and not world.walkable(x, y):
            why = "%s at (%d,%d) wants ground and found %s" % (name, x, y, material)
        elif world.at(x, y) == T["door"]:
            why = "%s at (%d,%d) is standing in a doorway" % (name, x, y)
        elif plane[y][x]:
            here = next((p["id"] for p in catalogue.values()
                         if p["plane"] == plane[y][x]), "?")
            why = "%s at (%d,%d) lands on %s" % (name, x, y, here)
        if why is not None:
            if not optional:
                problems.append(why)
            continue
        plane[y][x] = prop["plane"]
        placed += 1
        weathered += 1 if optional else 0
    if problems:
        raise SystemExit("the town's facades are wrong:\n  " + "\n  ".join(problems))
    # ...and losing ALL the weather is a bug even though losing some of it is
    # not. If the geometry ever drifts so that the cell south of every south
    # wall is a wall, this is what says so instead of a town that quietly stops
    # being damp.
    if wanted_ground and weathered * 2 < wanted_ground:
        raise SystemExit(
            "only %d of %d wall stains found open ground under a wall. The "
            "cell south of a south wall is where the wall's face is painted, "
            "so this many refusals means the building rectangles and what was "
            "actually stamped have drifted apart."
            % (weathered, wanted_ground))
    return placed


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


def cliff_plane(steps, elev, graded=frozenset()):
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

    `graded` BREAKS A RUN. A road is a cutting: the terrace is derived from
    elevation and knows nothing about what has been built on it, so a contour
    ran an unclimbable face straight across three cells of the Sheep Walk and
    put 216 cells of the south meadow behind it. Handled here rather than by
    clearing cells afterwards, because the run codes are positional -- zeroing
    a middle cell leaves a run with no left end, the Tiled importer normalises
    it back, and the byte-identical round trip fails on cliffs_b64_deflate.
    Breaking the run here means each half gets its own ends and its own length
    test, which is also the correct answer: half a bluff is still a bluff and a
    two-cell remnant is a crate.
    """
    plane = [[0] * W for _ in range(H)]

    def face(x, y):
        return (steps[y - 1][x] > steps[y][x]
                and elev[y - 1][x] - elev[y][x] > MIN_CLIFF_DROP
                and (x, y) not in graded)

    for y in range(1, H):
        x = 0
        while x < W:
            if not face(x, y):
                x += 1
                continue
            start = x
            while x < W and face(x, y):
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
    # to break it. Scoped to `no_cross`, which is precisely the set no road was
    # allowed into: outside it the roads' own bridges over the Wend are how the
    # western half of the world is reachable at all.
    stamp_vale(world, vale, only=no_cross | vale["bridges"])
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
    # A ROAD IS A CUTTING: wherever somebody has made a road, they have graded
    # what was in the way. Everything the roads and the streets laid down is
    # handed to cliff_plane as cells a terrace face may not run through.
    made = {(x, y) for y in range(H) for x in range(W)
            if world.at(x, y) in (T["path_dirt"], T["floor_stone"],
                                  T["bridge"], T["door"])}
    # AND SO IS A BUILDING. The terrace is derived from the elevation field and
    # knows nothing about what has been built on it, so a contour that happened
    # to cross the town ran an unclimbable rock face straight over three roofs:
    # (132-136, 165) and (141-144, 167) inside the mayor's, (120-123, 166)
    # inside the tinkerer's, with one piece hanging off the east wall over open
    # ground. _draw_cliff paints after the terrain and before the props, so it
    # lands squarely on the roof and there is no z-order that could save it.
    #
    # It is the same fault the road cutting fixed and it takes the same fix:
    # somebody who builds a house on a slope digs the slope out first. The
    # footprints go into `graded` alongside the roads, which BREAKS the run
    # rather than blanking cells out of it -- see cliff_plane's docstring for
    # why blanking would fail the byte-identical round trip.
    made |= vale["built"] | {(x, y)
                             for y in range(plan["y0"], plan["y0"] + plan["h"])
                             for x in range(plan["x0"], plan["x0"] + plan["w"])}
    cliffs = cliff_plane(steps, elev, graded=made)
    faces = {(x, y) for y in range(H) for x in range(W) if cliffs[y][x]}

    # The town's own furniture goes down FIRST and the scatter fills in round
    # it. The other order loses lamps: scatter_props refuses a cell that already
    # holds a prop, so whichever pass runs second is the one that gets dropped,
    # and a hand-made list is the wrong one to drop.
    props = [[0] * W for _ in range(H)]
    town_prop_count = stock_town(world, props, vale, rng)
    dressed = dress_facades(world, props, vale)
    doorsteps = {b["doorstep"] for b in vale["buildings"]}
    doorsteps |= {plan["door_outside"], plan["spite"]}
    # THE INSIDE OF THE HOUSE IS NOT SCATTERED, IT IS FURNISHED.
    #
    # `floor_stone` is the market square AND the house's hall floor, and the
    # scatter set written for the square -- grit in the joints, leaves against
    # the kerb -- was therefore offered to the hall as well, where it landed on
    # the cell a crate belongs on and failed the build. Which is the right
    # failure and the wrong fix: furnish_house owns every cell inside the
    # building and nothing else may put anything there, whatever the floor is
    # made of. Stated once here rather than by keeping the two material
    # vocabularies apart, because they should not have to be kept apart.
    house_cells = {(x, y)
                   for y in range(plan["y0"], plan["y0"] + plan["h"])
                   for x in range(plan["x0"], plan["x0"] + plan["w"])}
    # ...AND SO IS THE INSIDE OF EVERY BUILDING IN TOWN, for exactly the same
    # reason one radius out. Thirteen of the fourteen have had their roofs taken
    # off and their floors laid, so they are walkable, reachable, and made of the
    # same `floor_stone` as the market square -- which means the square's scatter
    # set (grit in the joints, leaves against the kerb) would happily blow into
    # the mayor's study. `vale["built"]` is every footprint including the four
    # walls, so it also keeps the scatter off the buildings that stay shut, which
    # were only ever safe because their roofs were solid.
    scatter_props(world, elev, rng, reach, props,
                  keep_clear=doorsteps | house_cells | vale["built"])
    furnish_house(world, props, plan)
    interior_count, interior_rooms = furnish_buildings(world, props, vale)

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

    # STORY ANCHORS ARE SNAPPED TO GROUND THEY CAN BE STOOD ON.
    #
    # region_cells() places them by bearing and radius, which is the right way
    # to say where a chapter *is* and no way at all to say what is there -- and
    # the answer, once the world has a river in it, is sometimes water. The
    # tall grass landed on one stray cell of the Wend's wobbled bank and was
    # reported as an UNREACHABLE story anchor, which is a build failure and was
    # the correct one: a chapter you cannot walk to is a run you cannot finish.
    # Snapping is what HJWorld.nearest_walkable already does at runtime; doing
    # it here means the data agrees with the engine rather than relying on it.
    for name in list(cells):
        if name in ("waking_room", "the_house") or cells[name] in reach:
            continue
        cells[name] = nearest_open(cells[name], reach, frozenset())

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

    # Only a prop that STANDS UP can bury him -- see standing_planes().
    standing = standing_planes()

    def clear_south(c):
        x, y = c[0], c[1] + 1
        return not (0 <= x < W and 0 <= y < H and props[y][x] in standing)

    spite = (next((c for c in ring if standable(c)
                   and not props[c[1]][c[0]] and clear_south(c)
                   and ORDER[world.at(*c)] != "path_dirt"), None)
             or next((c for c in ring if standable(c)
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
    # And nothing procedural inside anybody else's house either. A hole in
    # reality in the middle of the tavern would be a tier-2 anomaly the player
    # walks into while looking for the barman, and the town's buildings are
    # walkable now, so the footprints have to be said out loud rather than being
    # protected by the accident of a solid roof.
    anomalies = name_anomalies(
        cells, place_anomalies(world, rng, reach,
                               forbid=house_keep_out | vale["built"]))

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

    # AND EVERY OTHER INTERIOR IN THE VALE, TWICE, FOR THE SAME TWO REASONS.
    #
    # The complaint this whole pass answers is "the town only has 3 accessible
    # buildings", and the honest way to know a building is accessible is not to
    # look at it -- a picture cannot tell you that a barrel closed the only route
    # to the back room. So each opened building gets the pair of fills the house
    # gets:
    #
    #   REACHABLE  every walkable cell of it is in the fill from the bed. Not
    #              "the door is walkable": a pocket behind a dresser is a cell
    #              the player can see, walk at and never stand on, and a
    #              hand-placed layout is exactly where that happens because you
    #              are reasoning about a picture and the collision plane is
    #              reasoning about bytes.
    #   SEALED     with that building's own front door treated as solid, nothing
    #              outside its walls is reachable from inside it. The hole would
    #              never be in the plan; it would be something a later pass did,
    #              which is precisely what happened when the road carver drove
    #              seven columns of dirt through the house's east wall.
    interiors = [spec for spec in (interior_plan(b) for b in vale["buildings"])
                 if spec is not None]
    unreachable, unsealed = [], []
    for spec in interiors:
        walls = {(x, y)
                 for y in range(spec["y"] - 1, spec["y"] + spec["h"] + 1)
                 for x in range(spec["x"] - 1, spec["x"] + spec["w"] + 1)}
        missed = sorted(c for c in spec["inside"]
                        if world.walkable(c[0], c[1]) and c not in reach)
        if missed:
            unreachable.append("%s: %d cell(s) starting at %s"
                               % (spec["id"], len(missed), missed[0]))
        door = next(b["door"] for b in vale["buildings"] if b["id"] == spec["id"])
        barred_house = World(world.tiles, elev)
        barred_house.blocked = blocked | {door}
        within = reachable(barred_house, spec["landing"])
        escaped = sorted(c for c in within if c not in walls)
        if escaped:
            unsealed.append("%s: %d cell(s) starting at %s"
                            % (spec["id"], len(escaped), escaped[0]))
    if unreachable:
        raise SystemExit(
            "%d building(s) have interior cells nobody can walk to: %s. Every "
            "walkable cell inside has to be reachable from the bed -- a pocket "
            "behind a dresser is a cell the player can see, walk at, and never "
            "stand on." % (len(unreachable), "; ".join(unreachable)))
    if unsealed:
        raise SystemExit(
            "%d building(s) leak: %s. With its own front door shut, nothing "
            "outside a building's walls may be reachable from inside it, or the "
            "wall has a hole in it that no picture would show."
            % (len(unsealed), "; ".join(unsealed)))

    stranded = [n for n, c in cells.items() if c not in reach]

    # THE VALE MUST BE SEALED BUT FOR THE FORT.
    #
    # This is the standing goal, in flood fills. PROPOSALS/BUILDINGS.md says the
    # town is bounded by the river on two sides and the farmland on the third,
    # "and you must pass through [the children's fort] to get out of town" -- so
    # the boundary IS the gate, and a boundary the player can walk round is not
    # one. The hole would not be visible in a picture and it would not be
    # visible in the tile histogram: it would be one cell, put there by some
    # later pass, exactly as the road once drove seven columns of dirt through
    # the house's east wall.
    #
    # Three fills, because two of them describe a prison rather than a gate.
    # docs/PROCGEN-RESEARCH.md §2.5 names the third and it is the one everybody
    # forgets:
    #
    #   SHUT, cannot leave   with the gate solid, no cell outside the vale is
    #                        reachable from the bed.
    #   OPEN, can leave      with the gate walkable, the world outside IS
    #                        reachable. A provably enclosed town that stays
    #                        enclosed when the gate opens is a bug, not a gate.
    #   SHUT, town usable    with the gate solid, every doorstep in town is
    #                        still reachable -- the whole first act happens
    #                        while it is shut.
    #
    # And the first is run with BOTH movement relations. #84 has diagonal
    # movement on the table, and on a diagonal grid a one-cell river is
    # crossable at any kitty-corner pinch, so a seal proved four-way is not
    # proved. The Wend is five cells wide and the thorn three for that reason.
    gate = vale["gate"]
    OUTSIDE_ANCHORS = ("tall_grass", "long_road", "foothills",
                       "observatory", "summit")

    def outside(fill):
        return sorted(c for c in fill
                      if not (VALE_BOX[0] <= c[0] <= VALE_BOX[2]
                              and VALE_BOX[1] <= c[1] <= VALE_BOX[3]))

    barred = World(world.tiles, elev)
    barred.blocked = blocked | {gate}
    for relation, label in ((ORTHOGONAL, "four-way"), (DIAGONAL, "eight-way")):
        penned = reachable(barred, spawn, relation)
        escaped = outside(penned)
        reached = [n for n in OUTSIDE_ANCHORS if cells[n] in penned]
        if escaped or reached:
            raise SystemExit(
                "the vale is not sealed under %s movement: with the fort gate "
                "shut, %d cell(s) outside it are reachable from the bed, "
                "starting at %s%s. The gate is the whole of the early game's "
                "progression, and a hole anywhere in the Wend, the field fence "
                "or the thorn bypasses it."
                % (label, len(escaped), escaped[0] if escaped else "-",
                   "; anchors reached: " + ", ".join(reached) if reached else ""))
    penned = reachable(barred, spawn)

    # ...and it has to OPEN. `reach` is the same fill with the gate walkable.
    if not outside(reach):
        raise SystemExit(
            "the fort gate at %s leads nowhere: with it open, nothing outside "
            "the vale is reachable. A town that stays sealed when the gate "
            "opens is a prison, not a gate." % (gate,))

    # ...and there must be no POCKETS. This is the house's `stranded` check at
    # town scale and it is the one that found real bugs: a single crate in the
    # one-cell gap between the house and the girl next door's cut 737 cells of
    # the vale -- the whole north-west, the west field and the pond's west
    # shore -- off from everywhere, and 217 more sat behind the mayor's house
    # with no lane past it. Land the player can see and never stand on.
    everywhere = {(x, y) for y in range(H) for x in range(W)
                  if world.walkable(x, y)}
    beyond = reachable(barred, (gate[0] + 4, gate[1]))
    orphaned = everywhere - penned - beyond
    lumps = []
    unseen = set()
    for cell in sorted(orphaned):
        if cell in unseen:
            continue
        lump = set()
        stack = [cell]
        while stack:
            here = stack.pop()
            if here in unseen or here not in orphaned:
                continue
            unseen.add(here)
            lump.add(here)
            stack += [(here[0] + dx, here[1] + dy) for dx, dy in ORTHOGONAL]
        if len(lump) >= 20 and any(VALE_BOX[0] <= c[0] <= VALE_BOX[2]
                                   and VALE_BOX[1] <= c[1] <= VALE_BOX[3]
                                   for c in lump):
            lumps.append(sorted(lump))
    if lumps:
        raise SystemExit(
            "%d pocket(s) of the vale are cut off from both the town and the "
            "world: %s. A pocket is land the player can see, walk at and never "
            "stand on."
            % (len(lumps), "; ".join("%d cells at %s" % (len(l), l[0])
                                     for l in lumps)))

    # ...and the town has to work while it is shut, because the whole first act
    # happens before the gate opens.
    unreached = [b["id"] for b in vale["buildings"]
                 if b["doorstep"] not in penned]
    if unreached:
        raise SystemExit(
            "%d building(s) have a doorstep nobody can reach with the fort "
            "shut: %s. A door that opens onto somewhere you cannot walk is a "
            "building that is not in the town."
            % (len(unreached), ", ".join(unreached)))

    interactables = [{"x": plan["door"][0], "y": plan["door"][1],
                      "type": "front_door", "label": "Front door"},
                     {"x": spite[0], "y": spite[1], "type": "spite"},
                     # The fort gate. The physical barricade is stamped by
                     # stamp_vale; this is what makes the cell in it actually
                     # shut. Same mechanism as the front door one radius out --
                     # HJWorld._shut() reads `blocks_until_tag` off the
                     # catalogue and walkable() returns false, so the town's
                     # boundary is respected by every path query without the
                     # movement code knowing a boundary exists. The tag comes
                     # from the town objective completing, and because run tags
                     # die with the loop, the children have to be convinced
                     # again next time -- which is right, the holes are back.
                     {"x": FORT_GATE[0], "y": FORT_GATE[1],
                      "type": "leaf_gate", "label": "The barricade"}]

    # EVERY BUILDING GETS A DOOR YOU CAN ACT ON, and that is true of the ones
    # you cannot go into as well.
    #
    # A painted `door` tile in a wall is a picture of a door; what made three
    # buildings feel accessible and eleven feel like scenery was that three
    # happened to have somebody standing in front of them. An interactable on
    # every door cell is the fix, and it does two jobs. On a building that is
    # open it is the sentence you get on the way in -- what the room smells of
    # before you have seen it. On a building that is shut it is the whole of the
    # building's presence: "bolted from the inside" tells the player this is a
    # house somebody lives in, where a wall tells them nothing at all. Both are
    # one entry in data/content/interactables.json, and a shut one declares
    # `blocks_until_tag` there, which is what makes HJWorld.walkable() refuse the
    # cell -- the same mechanism as the front door and the fort gate.
    for b in vale["buildings"]:
        spec = interior_plan(b)
        kind = spec["door"] if spec is not None else SHUT_DOORS.get(b["id"])
        if kind is None:
            raise SystemExit(
                "%s has no door interactable and no interior. A building the "
                "player can neither enter nor be told about is the defect this "
                "pass exists to remove." % b["id"])
        interactables.append({"x": b["door"][0], "y": b["door"][1], "type": kind})

    # The townsfolk, each outside the door of the building they belong to, or in
    # the case of Bird, beside the barricade her sister is standing in. Placed
    # here rather than in the plan because who lives where is a fact about the
    # cast and the plan is a fact about the ground -- and the assertion below
    # checks every one of them can be stood beside and is not buried.
    for kind, door, offset in TOWNSFOLK:
        interactables.append({"x": door[0] + offset[0],
                              "y": door[1] + offset[1], "type": kind})
    for (kind, i, j, label) in plan["interactables"]:
        x, y = plan["cell"](i, j)
        entry = {"x": x, "y": y, "type": kind}
        if label:
            entry["label"] = label
        interactables.append(entry)

    # EVERY INTERACTABLE HAS TO BE SOMEWHERE YOU CAN STAND, AND NOTHING MAY BE
    # DRAWN OVER IT.
    #
    # The dog was reported standing on a table. He was not: he was at (6,11) of
    # the hall with a bench at (6,12), and a prop is a 96 px sprite in a 32 px
    # cell drawn north to south, so the bench was painted over two thirds of
    # him. The class of bug is the one that matters -- an interactable's cell
    # and the furniture pass did not know about each other, and any of the
    # placements could have landed under a prop. The animals are simply where it
    # shows, because they are live sprites on top of whatever is there.
    #
    # So it is a build failure now, the way a chair that cannot be placed is.
    # Three conditions, and the third is the one nobody would think of:
    #   * the cell is walkable, so you can reach the thing;
    #   * nothing solid stands on it;
    #   * for anything DRAWN -- an animal, a person -- nothing stands on the
    #     cell directly south of it, because a 96px prop in a 32px cell is
    #     painted north-to-south and buries whatever is above it. That is the
    #     rule that caught the dog under a bench, and it applies to figures
    #     rather than to every interactable: the fort gate is a cell in a
    #     barricade with barricade necessarily south of it, and it has no
    #     sprite of its own to bury. Over-applying it forbids the one placement
    #     the town's whole boundary depends on.
    #
    #     It applies only to props that STAND UP, too, and that is the second
    #     way over-applying it costs a build. The rule comes from the 96px slot
    #     a prop is drawn in; a prop the catalogue marks `flat` is drawn in the
    #     bottom few rows of that slot and paints nothing above its own cell.
    #     Once lanes started taking grit, the first thing this check did was
    #     refuse to let Spite stand on his own doorstep because a twig had blown
    #     into the road one cell south of him.
    drawn_over = []
    animals = {"dog", "cat", "spite"}
    for entry in interactables:
        ix, iy = entry["x"], entry["y"]
        # Reach is `adjacent`, so the test is not "can you stand ON it" -- the
        # stove is a solid prop and always will be -- but "can you stand BESIDE
        # it".
        if not any((ix + dx, iy + dy) in reach for dx, dy in ORTHOGONAL):
            drawn_over.append("%s at (%d,%d) has no walkable cell beside it"
                              % (entry["type"], ix, iy))
            continue
        # Anything drawn as a live sprite has to stand on floor of its own.
        if entry["type"] in animals and (ix, iy) in blocked:
            drawn_over.append("%s at (%d,%d) is standing on something solid"
                              % (entry["type"], ix, iy))
        if (entry["type"] in animals and iy + 1 < H
                and props[iy + 1][ix] in standing):
            # props_by_plane() is {plane: {solid, foot}} -- no id, no plane
            # key. Written against a shape that does not exist, so the report
            # crashed with a KeyError at the exact moment it had something to
            # say. PROPS is the list this plane indexes into.
            plane = props[iy + 1][ix]
            over = next((c["id"] for c in json.load(open(os.path.join(
                ROOT, "assets", "tiles", "tiles.json")))["props"]["list"]
                if int(c.get("plane", -1)) == plane), "something")
            drawn_over.append("%s at (%d,%d) is drawn over by the %s at (%d,%d) "
                              "south of it" % (entry["type"], ix, iy, over,
                                               ix, iy + 1))
    if drawn_over:
        raise SystemExit("interactables are in the wrong place:\n  "
                         + "\n  ".join(drawn_over))

    region_rects = {}
    for (name, rx, ry, rw, rh) in REGION_RECTS:
        if name not in cells:
            raise SystemExit("REGION_RECTS names %s, which is not a region" % name)
        if not (rx <= cells[name][0] < rx + rw and ry <= cells[name][1] < ry + rh):
            # An anchor outside its own rect means the two disagree about where
            # the place is, and place_id() would answer one thing while
            # place_nodes() put the chapter's nodes somewhere else entirely.
            raise SystemExit(
                "the %s anchor at %s is outside its own rect (%d,%d %dx%d)"
                % (name, cells[name], rx, ry, rw, rh))
        region_rects[name] = {"x": rx, "y": ry, "w": rw, "h": rh}

    # A RECT MAY NOT QUIETLY SWALLOW ANOTHER PLACE.
    #
    # Nesting is the point -- the house's plot sits inside the town's and the
    # smaller claim wins, which is what keeps a player on their own doorstep at
    # home. What is not the point is a rect eating a region nobody meant it to:
    # the first draft of the town's rect was VALE_BOX, the deliberately generous
    # box the SEAL is proved against, and it took in the tall grass on the far
    # bank of the Wend. That anchor would have gone on existing and gone on
    # placing its chapter's nodes while nobody standing on it was ever told its
    # name again -- a silent loss, and the only kind worth a check.
    #
    # So the rule is the engine's own rule, asked here: resolve every anchor the
    # way HJWorld.place_id() will, and require the answer to be the region itself
    # or an absorption somebody wrote down on purpose.
    swallowed = {}
    for other, cell in cells.items():
        best, best_area = other, 1 << 30
        for (name, rx, ry, rw, rh) in REGION_RECTS:
            if (rx <= cell[0] < rx + rw and ry <= cell[1] < ry + rh
                    and rw * rh < best_area):
                best, best_area = name, rw * rh
        if best != other and ABSORBED.get(other) != best:
            swallowed[other] = (best, cell)
    if swallowed:
        raise SystemExit(
            "%d region anchor(s) fall inside somebody else's rect: %s. Add the "
            "pair to ABSORBED if that is what you meant, or move the rect."
            % (len(swallowed), "; ".join(
                "%s at %s answers %s" % (k, v[1], v[0])
                for k, v in sorted(swallowed.items()))))

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
        # A region is an anchor, and some of them are also a rectangle -- see
        # REGION_RECTS. The rect rides on the same record so there is one list
        # of regions and not two, and so the round trip needs no new shape.
        "regions": {n: ({"x": c[0], "y": c[1], "rect": region_rects[n]}
                        if n in region_rects else {"x": c[0], "y": c[1]})
                    for n, c in cells.items()},
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
        # rectangle per building, the whole footprint including its walls and its
        # door cell, so the boon breaks on the first cell of ground OUTSIDE a
        # building rather than in the doorway. Deriving it from the floor
        # material would break the first time somebody floors a porch.
        #
        # A LIST, AND EVERY ENTRY BUT THE FIRST IS NAMED. HJWorld.place_name()
        # returns an entry's `place` instead of "Home", and until it did there
        # was no way to add the tavern here at all: the run header would have
        # introduced it as the player's own house, which is exactly why thirteen
        # buildings were left as solid blocks. The house itself carries no name
        # on purpose -- an unnamed rect still means home, and home is where it
        # is.
        "indoors": [{"x": plan["x0"], "y": plan["y0"],
                     "w": plan["w"], "h": plan["h"]}]
                   + [{"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"],
                       "place": interior_plan(b)["place"]}
                      for b in vale["buildings"] if interior_plan(b) is not None],
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
    print("cliff cells: %d (%d cells of made road the terrace may not cross)"
          % (len(faces), len(made)))
    in_vale = [a for a in anomalies
               if (a["x"], a["y"]) in penned]
    print("the vale: %d walkable cells behind the Wend, the field fence and the "
          "thorn" % len(penned))
    print("  %d buildings + %d outbuildings, %d street cells, %d water cells, "
          "%d cells of boundary"
          % (len(vale["buildings"]), len(vale["sheds"]), len(vale["streets"]),
             len(vale["water"]), len(vale["barrier"])))
    print("  %d town props placed by hand, %d facade pieces on the buildings "
          "(windows, signs, ridges, stacks and stains)"
          % (town_prop_count, dressed))
    print("  %d of %d buildings open onto a furnished interior (%d pieces of "
          "furniture, %d shut with a door that says why)"
          % (interior_rooms, len(vale["buildings"]), interior_count,
             len(vale["buildings"]) - interior_rooms))
    print("  the fort gate is at %s and %d anomalies are inside the vale"
          % (vale["gate"], len(in_vale)))
    print("  %d cells of paving in one connected surface"
          % sum(1 for m in vale["streets"].values() if m == "floor_stone"))
    print("  sealed under four-way AND eight-way movement with the gate shut; "
          "opens to %d outside cells when it is not" % len(outside(reach)))
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
