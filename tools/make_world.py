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
    ("waking_room", 200.0, 6.0),
    ("the_house", 205.0, 12.0),
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


def biome(e, m):
    """A tile id from the two fields, and from nothing else.

    Deliberately blind to which sector it is in. The first version tested the
    sector weights here — `if desert > 0.45: sand` — and that test is a boundary
    however smoothly the weights were blended: the map came out cut into
    triangular wedges with seams on the diagonals.

    The sectors belong in the *fields*, where they bend elevation and moisture
    continuously. By the time we are choosing a tile there is nothing left but
    two numbers, so a desert is simply somewhere dry and a shore is simply where
    the ground crosses sea level.
    """
    if e < SEA:
        return T["water"]
    if e < SHORE:
        return T["sand"]
    if e < GRASS:
        if m < 0.30:
            return T["sand"]
        if m > 0.68:
            return T["forest"]
        return T["grass_short"]
    if e < HILL:
        if m < 0.27:
            return T["sand"]
        if m > 0.70:
            return T["forest"]
        return T["grass_tall"] if m > 0.50 else T["grass_short"]
    if e < SCREE:
        return T["scree"] if m < 0.55 else T["grass_short"]
    if e < SNOW:
        return T["scree"]
    return T["snow"]


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

    def walkable(self, x, y):
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
            score = closer + climb + jitter
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
    tiles = [[biome(elev[y][x], moist[y][x]) for x in range(W)] for y in range(H)]
    world = World(tiles, elev)
    cells = region_cells()

    stamp_town(world, rng, CENTRE)

    # Roads last, so nothing is painted over them. This is why the old map had
    # roads that dead-ended in walls: the town, observatory and summit were all
    # stamped after the carve and simply overwrote it.
    # Out of town every way, not only toward the northern story beats. The
    # player may leave in any direction and should find a road doing the same.
    for name in ("summit", "observatory", "foothills", "long_road", "tall_grass"):
        carve_road(world, rng, CENTRE, cells[name])
    for bearing in (0.0, 90.0, 180.0, 270.0):
        target = coast_stop(world, bearing)
        if target is not None:
            carve_road(world, rng, CENTRE, target)

    spawn = cells["the_town"]
    reach = reachable(world, spawn)
    anomalies = place_anomalies(world, rng, reach)

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
    print("anomalies: %d" % len(anomalies))
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
