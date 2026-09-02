#!/usr/bin/env python3
"""Export the generated world into a Tiled map you can hand-edit.

    python3 tools/world_to_tiled.py          # data/world/overworld.json -> world/

This is one half of a round trip; tools/tiled_to_world.py is the other. The
whole design turns on one question: **what happens to Kevin's hand edits when
tools/make_world.py is re-run?** The answer here is a layered map.

    world/overworld.tmj
      layer "base"    generated. Overwritten in full on every export. Locked in
                      the editor, because the next export will discard anything
                      painted into it.
      layer "edits"   hand-authored. Never written by the generator. Empty cells
                      mean "no override"; a tile here wins over base.
      object layers   region anchors, spawn, anomalies, props. Generated objects
                      remember where the generator last put them, so an object
                      you drag is treated as pinned and stops following the
                      generator. Objects you add yourself are never touched.

So `overworld.tmj` — not `overworld.json` — is the durable artefact, and it is
the file that must be committed. Regeneration is:

    python3 tools/make_world.py        # new base terrain
    npm run world:export               # base layer refreshed, edits untouched
    npm run world:import               # base+edits composited back to the game

Region-scoped reseeding is not a separate mode because it falls out of this for
free: the generator may rewrite as much or as little of the terrain as it likes,
and the overrides sitting on top survive regardless of where they are.

The one destructive operation is --discard-edits, which needs the flag and
prints exactly what it is about to throw away.

Nothing here hardcodes the current schema. Tile ids, tile names, walkability and
the atlas geometry are read from tools/make_tiles.py and assets/tiles/ at run
time; every top-level key of overworld.json is classified (tile grid, object
collection, point marker, or opaque passthrough) rather than named. A tileset of
four hundred tiles, a square map, an elevation field and anomaly spawns all pass
through this without a code change — see docs/MAP-EDITING.md for the limits.

Stdlib only. The PNG header is parsed by hand rather than pulling in PIL, so the
map tooling runs on a checkout with nothing installed.
"""
import argparse
import ast
import base64
import json
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORLD_JSON = os.path.join(ROOT, "data", "world", "overworld.json")
WORLD_DIR = os.path.join(ROOT, "world")
TMJ = os.path.join(WORLD_DIR, "overworld.tmj")
TSJ = os.path.join(WORLD_DIR, "tileset.tsj")
PROJECT = os.path.join(WORLD_DIR, "heroes.tiled-project")


def plane_tsj(name):
    """world/props.tsj, world/cliffs.tsj — one per editable plane."""
    return os.path.join(WORLD_DIR, "%s.tsj" % name)


ATLAS = os.path.join(ROOT, "assets", "tiles", "tileset.png")
TILES_JSON = os.path.join(ROOT, "assets", "tiles", "tiles.json")
TILES_DIR = os.path.join(ROOT, "assets", "tiles")
MAKE_TILES = os.path.join(ROOT, "tools", "make_tiles.py")

TILED_VERSION = "1.12.2"
MAP_FORMAT_VERSION = "1.10"

BASE_LAYER = "base"
EDIT_LAYER = "edits"
MARKER_LAYER = "markers"

# Bookkeeping properties. Namespaced so they cannot collide with a field the
# world schema grows later, and so the docs can say "leave anything starting
# hj_ alone" as one rule instead of a list.
P_GEN_X = "hj_gen_x"
P_GEN_Y = "hj_gen_y"
P_MARKER = "hj_marker"
P_JSON = "hj_json"
P_KEYS = "hj_keys"
P_SCHEMA = "hj_schema"
P_PLANES = "hj_gen_planes"


# --- the editable byte planes ---------------------------------------------------
#
# props_b64_deflate and cliffs_b64_deflate are one byte per cell, and a byte is
# the one thing Tiled cannot show you. Both become object layers here and are
# folded back into their planes on import; the plane stays the runtime format
# because the renderer indexes it per cell every frame and 4,779 objects of JSON
# would be 280 KB to parse at every launch for a lookup the plane already does
# in O(1). See docs/MAP-EDITING.md.
#
# This table is the one place in the map tooling that knows a world-file key by
# name, and it has to be: every plane in the file is the same w*h bytes, so
# "which one is the props plane" is a fact about the *art*, not about the shape
# of the value. Matched on prefix rather than the exact key so a rename from
# props_b64_deflate to props_plane still lands. Nothing else is hardcoded — the
# atlas geometry, the tile size and the catalogue of what each value means are
# all read from assets/tiles/tiles.json at run time, so a prop the asset
# pipeline appends tomorrow is pickable today with no change here.
PLANE_KEYS = ("props", "cliffs")

# blocked_b64_deflate is not edited and not carried verbatim: it is *derived*
# from the props and cliffs planes on both sides of the trip, because a prop
# hand-placed in Tiled has to block and the importer can only see the plane.
DERIVED_KEY = "blocked"


# --- reading what the rest of the repo declares --------------------------------

def tile_meta():
    """Tile size, tile names and walkability, read out of tools/make_tiles.py.

    Parsed from the AST rather than imported, because importing it would import
    PIL and draw the entire tileset as a side effect. Parsed rather than copied,
    because a second copy of ORDER in this file is a renumbering bug waiting for
    the day someone inserts a tile in the middle.
    """
    meta = {"size": 32, "order": [], "walkable": {}}
    try:
        tree = ast.parse(open(MAKE_TILES, encoding="utf-8").read())
    except OSError:
        return meta
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            if target.id == "N" and isinstance(value, int):
                meta["size"] = value
            elif target.id == "ORDER" and isinstance(value, list):
                meta["order"] = [str(v) for v in value]
            elif target.id == "WALKABLE" and isinstance(value, dict):
                meta["walkable"] = {str(k): bool(v) for k, v in value.items()}
    return meta


def png_size(path):
    """Width and height from a PNG's IHDR chunk. Twelve lines instead of PIL."""
    with open(path, "rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise SystemExit("not a PNG: %s" % path)
    return struct.unpack(">II", header[16:24])


def tiles_manifest():
    """assets/tiles/tiles.json, read fresh every time.

    Never cached at module scope and never copied into this file: the asset
    pipeline appends to it, and a stale catalogue would silently drop the props
    it added.
    """
    try:
        with open(TILES_JSON, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError:
        raise SystemExit("%s missing — run python3 tools/make_tiles.py" % TILES_JSON)
    except ValueError as exc:
        raise SystemExit("%s is not valid JSON: %s" % (TILES_JSON, exc))


def normalise_cliffs(plane, w, h):
    """Left end / middle / right end, re-derived from the run each cell is in.

    The value in the cliff plane is 1, 2 or 3 depending on whether the drop
    continues either side, which is not something a human dragging one cell can
    keep consistent — nudge the end of a bluff and you have left a `middle`
    piece hanging in the air. So the editor only ever says *there is a cliff
    edge on this cell* and the ends are computed here, exactly the way
    make_world.py computes them: maximal horizontal runs, first cell 1, last 3,
    everything between 2. Verified to reproduce the generator's plane cell for
    cell, which is why an unedited round trip is still byte-identical.
    """
    out = [0] * (w * h)
    for y in range(h):
        x = 0
        while x < w:
            if not plane[y * w + x]:
                x += 1
                continue
            start = x
            while x < w and plane[y * w + x]:
                x += 1
            for i in range(start, x):
                out[y * w + i] = 1 if i == start else (3 if i == x - 1 else 2)
    return out


def plane_catalogue(name):
    """What a non-zero byte in one editable plane means, and how to draw it.

    Returns everything both halves of the round trip need: the image behind the
    Tiled tileset, its cell geometry, the value -> name mapping that makes a
    prop pickable by name instead of by a magic integer, and the per-tile
    properties worth seeing in the sidebar.
    """
    manifest = tiles_manifest()
    section = manifest.get(name)
    if not isinstance(section, dict):
        raise SystemExit("%s has no %r section; the map tooling cannot build the "
                         "%s tileset without it" % (TILES_JSON, name, name))
    image = os.path.join(TILES_DIR, str(section.get("file", "%s.png" % name)))
    if not os.path.exists(image):
        raise SystemExit("%s is missing — run python3 tools/make_tiles.py" % image)
    iw, ih = png_size(image)
    cols = max(1, int(section.get("cols") or 1))
    # The manifest states the cell size directly for props (`slot`) and by row
    # count for cliffs. Take whichever it offers rather than assuming, so an
    # atlas that grows a row needs nothing here.
    if isinstance(section.get("slot"), list) and len(section["slot"]) == 2:
        tw, th = int(section["slot"][0]), int(section["slot"][1])
    else:
        tw = iw // cols
        th = ih // max(1, int(section.get("rows") or 1))
    if tw <= 0 or th <= 0 or iw % tw or ih % th:
        raise SystemExit("%s is %dx%d, not a whole number of %dx%d cells"
                         % (image, iw, ih, tw, th))
    cols = iw // tw
    count = cols * (ih // th)

    cat = {"name": name, "layer": name, "image": image, "tw": tw, "th": th,
           "iw": iw, "ih": ih, "cols": cols, "count": count,
           # The world's own tile size, from the same manifest — a prop's
           # position is expressed in cells and has to land on the same grid the
           # terrain does.
           "size": int(manifest.get("tile") or 32),
           "tiles": {}, "by_value": {}, "by_name": {},
           "normalise": None, "default_slot": 0}

    if name == "props":
        # plane value = slot + 1, which is the manifest's own `layout` rule and
        # what scripts/ui/TileWorld.gd indexes the atlas by. Read `plane` rather
        # than `index` so there is one truth, not two that can disagree.
        for entry in section.get("list", []):
            value = int(entry["plane"])
            slot = value - 1
            ident = str(entry["id"])
            foot = entry.get("foot", [1, 1])
            cat["by_value"][value] = ident
            cat["by_name"][ident] = value
            cat["tiles"][slot] = {
                "name": ident,
                "biome": str(entry.get("biome", "")),
                "solid": bool(entry.get("solid", False)),
                "foot_w": int(foot[0]), "foot_h": int(foot[1]),
            }
    elif name == "cliffs":
        # The plane's three values are ends and middles of one thing, so the
        # catalogue is a single name: presence is the whole content, and the
        # value is recomputed by normalise_cliffs on the way back in.
        order = [str(v) for v in section.get("order", [])]
        for slot, piece in enumerate(order):
            cat["tiles"][slot] = {"name": piece}
        cat["default_slot"] = order.index("face_mid") if "face_mid" in order else 0
        cat["by_value"] = {1: "cliff", 2: "cliff", 3: "cliff"}
        cat["by_name"] = {"cliff": 1}
        cat["normalise"] = normalise_cliffs
    else:
        raise SystemExit("no catalogue reader for plane %r" % name)
    return cat


def props_by_plane():
    """plane value -> {solid, foot} for every prop in the catalogue.

    Imported by tools/make_world.py so the generator and the importer derive the
    collision plane from one rule rather than two.
    """
    out = {}
    for entry in tiles_manifest()["props"]["list"]:
        out[int(entry["plane"])] = {"solid": bool(entry.get("solid", False)),
                                    "foot": [int(v) for v in entry.get("foot", [1, 1])]}
    return out


def derive_blocked(props, cliffs, w, h, catalogue):
    """The collision plane, from the props standing on the world and its cliffs.

    A prop's art is 64x96 and its collision is the `foot` cells at its base, so
    solidity cannot be read off the prop plane one cell at a time — a fallen log
    is two cells wide and a well is four. A cliff face is a wall you cannot walk
    up, so it blocks too.

    Both halves of the round trip call this, and so does the generator: it is
    the only way a prop hand-placed in Tiled can block, and the only way the
    imported file can reproduce the generated one byte for byte.

    `props` and `cliffs` are flat lists of w*h ints; either may be None.
    """
    out = [0] * (w * h)
    for i, value in enumerate(props or []):
        if not value:
            continue
        entry = catalogue.get(value)
        if entry is None:
            raise SystemExit(
                "prop id %d at cell (%d, %d) is not in %s. Re-run the asset "
                "pipeline, or the game will draw a prop the collision plane knows "
                "nothing about." % (value, i % w, i // w, TILES_JSON))
        if not entry["solid"]:
            continue
        fw, fh = entry["foot"][0], entry["foot"][1]
        x, y = i % w, i // w
        for fy in range(fh):
            for fx in range(fw):
                cx, cy = x + fx, y - fy
                if 0 <= cx < w and 0 <= cy < h:
                    out[cy * w + cx] = 1
    for i, value in enumerate(cliffs or []):
        if value:
            out[i] = 1
    return out


# --- classifying the world file ------------------------------------------------
#
# The schema is being rewritten while this tool is being written, so nothing
# below asks "is this key called regions". It asks what shape the value is.

def _is_cell(value):
    return (isinstance(value, dict) and "x" in value and "y" in value
            and isinstance(value.get("x"), (int, float))
            and isinstance(value.get("y"), (int, float))
            and not isinstance(value.get("x"), bool))


def _looks_like_tile_blob(key, value):
    return (isinstance(value, str) and len(value) > 64
            and ("tiles" in key or "grid" in key)
            and ("b64" in key or "base64" in key or "deflate" in key or "zlib" in key))


def _plane_bytes(value, cells):
    """The raw bytes of a base64+deflate blob, if it is one byte per cell.

    Returns None for anything else, which is what keeps the classification a
    question about shape: elevation is the same encoding at the same size and
    would be claimed too if the caller did not also check the name against
    PLANE_KEYS.
    """
    if not isinstance(value, str) or len(value) < 8:
        return None
    try:
        raw = zlib.decompress(base64.b64decode(value))
    except Exception:
        return None
    return raw if len(raw) == cells else None


def measure_zlib(raw, original):
    """The compression level that reproduces this exact blob.

    Measured rather than assumed for the same reason the tile grid measures it:
    the promise in docs/MAP-EDITING.md is byte equality of the whole file, not
    equality after decompression.
    """
    for level in (9, 6, 1, 8, 7, 5, 4, 3, 2, -1, 0):
        if base64.b64encode(zlib.compress(raw, level)).decode("ascii") == original:
            return level
    return 9


def encode_plane(values, level=9):
    raw = bytes(bytearray(values))
    return base64.b64encode(zlib.compress(raw, level)).decode("ascii")


def sniff(world):
    """Work out what each top-level key of overworld.json is.

    Returns an envelope describing how to put the file back together byte for
    byte: which key held the tile grid, how it was encoded, which keys became
    object layers, and the verbatim value of everything this tool does not
    understand. The envelope rides along in the .tmj, so the map is a complete
    description of the world — you can delete overworld.json and rebuild it.
    """
    env = {
        "key_order": list(world.keys()),
        "tiles_key": None,
        "w_key": None, "h_key": None,
        "cell_bytes": 1,
        "zlib_level": 9,
        "collections": {},      # json key -> "dict" | "list"
        "markers": [],          # json keys holding a single {x, y}
        "planes": {},           # json key -> catalogue name (an object layer)
        "derived": {},          # json key -> rule name (recomputed, never stored)
        "plane_zlib": {},       # json key -> level that reproduces its blob
        "passthrough": {},
        "indent": 1,
        "trailing_newline": True,
    }
    # Width and height first: a byte plane is only recognisable as one if you
    # already know how many cells the world has.
    for key, value in world.items():
        if key == "w" or (env["w_key"] is None and key in ("width", "cols")):
            env["w_key"] = key
        elif key == "h" or (env["h_key"] is None and key in ("height", "rows")):
            env["h_key"] = key
    if env["w_key"] is None or env["h_key"] is None:
        raise SystemExit("overworld.json has no width/height keys I recognise")
    cells = int(world[env["w_key"]]) * int(world[env["h_key"]])

    for key, value in world.items():
        if key in (env["w_key"], env["h_key"]):
            continue
        if _looks_like_tile_blob(key, value):
            env["tiles_key"] = key
        elif _is_cell(value):
            env["markers"].append(key)
        elif isinstance(value, dict) and value and all(_is_cell(v) for v in value.values()):
            env["collections"][key] = "dict"
        elif isinstance(value, list) and value and all(_is_cell(v) for v in value):
            env["collections"][key] = "list"
        elif any(key.startswith(name) for name in PLANE_KEYS) \
                and _plane_bytes(value, cells) is not None:
            name = next(n for n in PLANE_KEYS if key.startswith(n))
            env["planes"][key] = name
            env["plane_zlib"][key] = measure_zlib(_plane_bytes(value, cells), value)
        elif key.startswith(DERIVED_KEY) and _plane_bytes(value, cells) is not None:
            env["derived"][key] = DERIVED_KEY
            env["plane_zlib"][key] = measure_zlib(_plane_bytes(value, cells), value)
        else:
            env["passthrough"][key] = value
    if env["tiles_key"] is None:
        raise SystemExit("overworld.json has no base64/deflate tile grid I recognise")
    if env["derived"] and not env["planes"]:
        # Nothing to derive it *from*. Carrying it verbatim is the only honest
        # answer; recomputing it from planes that are not there would empty it.
        for key in env["derived"]:
            env["passthrough"][key] = world[key]
            env["plane_zlib"].pop(key, None)
        env["derived"] = {}
    return env


def decode_tiles(world, env):
    """Tile ids out of the compressed blob.

    Byte width is measured, not assumed: 18 tiles fit in a byte and several
    hundred do not, so the day the generator switches to uint16 this keeps
    working. Little-endian, matching Godot's PackedByteArray.decode_u16.
    """
    w, h = world[env["w_key"]], world[env["h_key"]]
    raw = zlib.decompress(base64.b64decode(world[env["tiles_key"]]))
    cells = w * h
    if cells == 0 or len(raw) % cells:
        raise SystemExit("tile blob is %d bytes, not a whole number per cell (%d cells)"
                         % (len(raw), cells))
    env["cell_bytes"] = len(raw) // cells
    fmt = {1: "B", 2: "<%dH" % cells, 4: "<%dI" % cells}.get(env["cell_bytes"])
    if fmt is None:
        raise SystemExit("%d bytes per cell is not something I can read"
                         % env["cell_bytes"])
    ids = list(raw) if env["cell_bytes"] == 1 else list(struct.unpack(fmt, raw))

    # Find the compression level that reproduces the generator's blob exactly.
    # Without this the round trip is only equal after decompression, and the
    # promise made in docs/MAP-EDITING.md is byte equality of the whole file.
    original = world[env["tiles_key"]]
    for level in (9, 6, 1, 8, 7, 5, 4, 3, 2, -1, 0):
        if base64.b64encode(zlib.compress(raw, level)).decode("ascii") == original:
            env["zlib_level"] = level
            break
    else:
        env["zlib_level"] = 9
        print("  note: no zlib level reproduces the generator's blob byte for byte; "
              "using 9. Tile ids still round-trip exactly.", file=sys.stderr)
    return ids


# --- Tiled layer data ----------------------------------------------------------

def encode_layer(gids):
    raw = struct.pack("<%dI" % len(gids), *gids)
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def decode_layer(layer, cells):
    """Read a tile layer whatever format Tiled chose to save it in.

    Tiled honours the map's stored layer format, but that is a setting a human
    can change in Map Properties, and a map that will not load because someone
    picked CSV is a bad way to find that out.
    """
    data = layer.get("data")
    if isinstance(data, list):
        gids = [int(v) for v in data]
    else:
        raw = base64.b64decode(data)
        compression = layer.get("compression", "")
        if compression == "zlib":
            raw = zlib.decompress(raw)
        elif compression == "gzip":
            raw = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
        elif compression:
            raise SystemExit("layer %r uses %s compression; re-save the map with "
                             "Map > Properties > Tile Layer Format set to "
                             "'Base64 (zlib compressed)'"
                             % (layer.get("name"), compression))
        gids = list(struct.unpack("<%dI" % (len(raw) // 4), raw))
    if len(gids) != cells:
        raise SystemExit("layer %r has %d cells, map says %d"
                         % (layer.get("name"), len(gids), cells))
    # Strip Tiled's flip/rotate bits. The game reads a flat byte per cell and
    # has nowhere to put them, so a flipped tile would come back as a garbage id.
    return [g & 0x0FFFFFFF for g in gids]


# --- properties ----------------------------------------------------------------

def prop_list(mapping):
    out = []
    for name, value in mapping.items():
        if isinstance(value, bool):
            kind = "bool"
        elif isinstance(value, int):
            kind = "int"
        elif isinstance(value, float):
            kind = "float"
        else:
            kind, value = "string", str(value)
        out.append({"name": name, "type": kind, "value": value})
    return out


def prop_dict(obj):
    return {p["name"]: p["value"] for p in obj.get("properties", [])}


# --- the tileset ---------------------------------------------------------------

def build_tileset(meta, previous):
    """world/tileset.tsj, derived from the atlas and make_tiles.py.

    Regenerated on every export so that a tileset which grows from 17 tiles to
    400 needs no action here — but `wangsets` and any property whose name this
    tool did not write are carried over from the previous file, because terrain
    and Wang sets are hand-authored in Tiled and are exactly as precious as the
    edits layer.
    """
    size = meta["size"]
    width, height = png_size(ATLAS)
    if width % size or height % size:
        raise SystemExit("atlas %dx%d is not a whole number of %dpx tiles"
                         % (width, height, size))
    columns = width // size
    count = columns * (height // size)

    order = meta["order"]
    if order and len(order) > count:
        # The usual cause is a tileset that has grown in make_tiles.py without
        # the atlas being redrawn, and it matters: the ids the generator writes
        # would index past the end of the set and the map would not open.
        print("  note: tools/make_tiles.py declares %d tiles but the atlas holds "
              "only %d. Run python3 tools/make_tiles.py to redraw it."
              % (len(order), count), file=sys.stderr)
    elif order and len(order) < count:
        print("  note: the atlas holds %d tiles, make_tiles.py names %d. Ids %d and "
              "up are unnamed in the tileset."
              % (count, len(order), len(order)), file=sys.stderr)

    kept_wangsets = previous.get("wangsets", []) if previous else []
    kept_tile_props = {}
    for tile in (previous or {}).get("tiles", []):
        extra = {k: v for k, v in prop_dict(tile).items()
                 if k not in ("name", "walkable")}
        if extra:
            kept_tile_props[int(tile["id"])] = extra

    tiles = []
    for i in range(count):
        props = {}
        if i < len(order):
            props["name"] = order[i]
            if order[i] in meta["walkable"]:
                props["walkable"] = meta["walkable"][order[i]]
        props.update(kept_tile_props.get(i, {}))
        if props:
            tiles.append({"id": i, "properties": prop_list(props)})

    return {
        "columns": columns,
        "image": os.path.relpath(ATLAS, WORLD_DIR).replace(os.sep, "/"),
        "imageheight": height,
        "imagewidth": width,
        "margin": 0,
        "name": "heroes",
        "spacing": 0,
        "tilecount": count,
        "tiledversion": TILED_VERSION,
        "tileheight": size,
        "tilewidth": size,
        "tiles": tiles,
        "type": "tileset",
        "version": MAP_FORMAT_VERSION,
        "wangsets": kept_wangsets,
    }


# --- objects -------------------------------------------------------------------

def cell_to_px(cell, size):
    # Centre of the cell, so the marker sits in the square it names and a small
    # drag does not move it to the neighbour.
    return cell * size + size / 2.0


def px_to_cell(px, size):
    return int(px // size)


def object_from_cell(name, record, size, obj_class):
    """A Tiled point object for one {x, y, ...} record from the world file.

    Scalars become native Tiled properties so they are editable in the sidebar;
    anything structured is JSON in a string property, with its key listed in
    hj_json so the import knows to decode it. hj_keys preserves the record's
    original key order, which is what makes the round trip byte-identical rather
    than merely equivalent — and it is only written when the record is something
    other than a plain {x, y}, so today's anchors stay clean in the sidebar.
    """
    props = {}
    json_keys = []
    order = list(record.keys())
    for key, value in record.items():
        if key in ("x", "y"):
            continue
        if isinstance(value, (bool, int, float, str)):
            props[key] = value
        else:
            props[key] = json.dumps(value, separators=(",", ":"))
            json_keys.append(key)
    if order != ["x", "y"]:
        props[P_KEYS] = ",".join(order)
    if json_keys:
        props[P_JSON] = ",".join(json_keys)
    cell = (int(record["x"]), int(record["y"]))
    px, py = cell_to_px(cell[0], size), cell_to_px(cell[1], size)
    props[P_GEN_X], props[P_GEN_Y] = px, py
    return {
        "class": obj_class,
        "height": 0,
        "id": 0,
        "name": name,
        "point": True,
        "properties": prop_list(props),
        "rotation": 0,
        "visible": True,
        "width": 0,
        "x": px,
        "y": py,
    }


def merge_objects(generated, existing, discard):
    """Reconcile a freshly generated object layer with what is in the .tmj.

    Three cases, and the middle one is the whole point of the exercise:

      * an object the generator produces and nobody has moved -> take the new
        generated position;
      * an object the generator produces that sits somewhere other than where
        the generator last put it -> **it has been dragged by hand**, so keep
        the hand position and only update the remembered generated one. No flag
        to tick, no naming convention: moving it is the act of pinning it;
      * an object in the map that the generator no longer produces -> keep it.
        That covers both hand-added anchors and a region the world model has
        dropped, and both should survive an export they had nothing to do with.
    """
    by_name = {o.get("name"): o for o in existing}
    out, moved, added, orphans = [], 0, 0, 0
    for fresh in generated:
        old = by_name.pop(fresh["name"], None)
        if old is None or discard:
            out.append(fresh)
            added += old is None
            continue
        props = prop_dict(old)
        pinned = (old.get("x") != props.get(P_GEN_X)
                  or old.get("y") != props.get(P_GEN_Y))
        merged = dict(fresh)
        merged["id"] = old.get("id", 0)
        # Hand-added properties survive; the generator's own values are refreshed.
        keep = {k: v for k, v in props.items()
                if k not in prop_dict(fresh) and not k.startswith("hj_")}
        new_props = prop_dict(fresh)
        new_props.update(keep)
        if pinned:
            merged["x"], merged["y"] = old["x"], old["y"]
            moved += 1
        merged["properties"] = prop_list(new_props)
        out.append(merged)
    if not discard:
        for leftover in by_name.values():
            out.append(leftover)
            orphans += 1
    return out, moved, added, orphans


# --- planes as objects ----------------------------------------------------------
#
# A prop's art is 64x96 standing on a 32x32 cell, so it reaches up and out of
# the cell it belongs to. Written as a *tile* object rather than a point, the
# editor draws the actual tree at the actual place the game draws it, and you
# pick a new one out of the props tileset by its picture and its name. The
# object's Name is the catalogue id as well, so the Objects panel and `grep`
# both read like the catalogue.

def plane_cell_to_px(cx, cy, size, tw, th):
    """A cell to a Tiled tile-object origin, which is its *bottom-left*.

    The same arithmetic as the manifest's own draw rule
    (`dst = (cell.x*32 + 16 - 32, cell.y*32 + 32 - 96)`) expressed for a cell of
    any size: bottom-centred on the cell it stands on. Get this wrong and every
    prop in Tiled sits half a tile away from where the game puts it.
    """
    return (cx * size + size / 2.0 - tw / 2.0, (cy + 1) * size)


def plane_px_to_cell(x, y, size, tw, th):
    """Back to the cell, to the nearest one rather than the one containing the
    pixel: a tile object's origin is off-grid by design (a 64-wide prop starts
    16px left of its cell), so `floor` would drop everything a column."""
    return (int(round((x - size / 2.0 + tw / 2.0) / size)),
            int(round(y / size)) - 1)


def firstgid_for(tmj, source):
    """The first global tile id of the tileset loaded from `source`.

    By name, not by position: the map now carries three tilesets and the terrain
    one is no longer the only one, so "the last firstgid in the list" — which is
    what this used to be — would decode terrain against the props atlas.
    """
    for entry in (tmj or {}).get("tilesets", []):
        if os.path.basename(str(entry.get("source", ""))) == source:
            return int(entry.get("firstgid", 1))
    return None


def plane_objects(values, w, h, cat, firstgid):
    """One tile object per non-zero cell, in row-major order.

    Row-major so object ids stay stable across exports for an unchanged plane,
    which is what keeps the diff of a 4,779-object layer readable.
    """
    size = cat["size"]
    tw, th = cat["tw"], cat["th"]
    out = []
    for i, value in enumerate(values):
        if not value:
            continue
        name = cat["by_value"].get(value)
        if name is None:
            raise SystemExit(
                "the %s plane holds id %d at cell (%d, %d), which is not in %s. "
                "Re-run the asset pipeline before exporting — dropping it would "
                "lose a prop the game is already drawing."
                % (cat["name"], value, i % w, i // w, TILES_JSON))
        slot = cat["default_slot"] if cat["normalise"] else value - 1
        px, py = plane_cell_to_px(i % w, i // w, size, tw, th)
        out.append({
            "gid": firstgid + slot,
            "height": th,
            "id": 0,
            "name": name,
            "rotation": 0,
            "visible": True,
            "width": tw,
            "x": int(px) if float(px).is_integer() else px,
            "y": int(py) if float(py).is_integer() else py,
        })
    return out


def objects_to_plane(objects, w, h, cat, firstgid):
    """The object layer back to a byte plane.

    The tile decides the type, not the name: Tiled can swap an object's tile
    without touching its name, and the picture is what the person placing it was
    looking at. The name is the fallback, so a plain object typed `barrel` by
    hand still lands — and if neither resolves, this stops rather than quietly
    dropping the object, because a prop that vanishes on import is exactly the
    failure this whole exercise is about.
    """
    size = cat["size"]
    tw, th = cat["tw"], cat["th"]
    plane = [0] * (w * h)
    placed = {}
    for obj in objects:
        gid = int(obj.get("gid", 0)) & 0x0FFFFFFF
        label = str(obj.get("name") or obj.get("class") or obj.get("type") or "")
        value = None
        if gid and firstgid is not None and gid >= firstgid:
            slot = gid - firstgid
            if cat["normalise"]:
                value = 1            # presence is the content; the piece is derived
            elif slot + 1 in cat["by_value"]:
                value = slot + 1
        if value is None and label in cat["by_name"]:
            value = cat["by_name"][label]
        if value is None:
            raise SystemExit(
                "object %r (id %s, gid %s) in the %r layer is in no %s catalogue "
                "I can read. Give it a tile from %s.tsj or name it after an entry "
                "in %s — importing it as nothing would delete it silently."
                % (label, obj.get("id"), obj.get("gid"), cat["layer"],
                   cat["name"], cat["name"], TILES_JSON))
        cx, cy = plane_px_to_cell(obj.get("x", 0), obj.get("y", 0), size, tw, th)
        if not (0 <= cx < w and 0 <= cy < h):
            print("  note: %s object %r sits outside the map at (%d, %d) and was dropped"
                  % (cat["name"], label, cx, cy), file=sys.stderr)
            continue
        # One byte per cell is the runtime's constraint, so two objects on one
        # cell is a thing the game cannot draw. Say which two and where, and let
        # the topmost win — refusing the whole import over an overlapping drag
        # would be worse.
        if (cx, cy) in placed and placed[(cx, cy)] != label:
            print("  note: %s objects %r and %r are both on cell (%d, %d); keeping %r"
                  % (cat["name"], placed[(cx, cy)], label, cx, cy, label),
                  file=sys.stderr)
        placed[(cx, cy)] = label
        plane[cy * w + cx] = value
    if cat["normalise"]:
        plane = cat["normalise"](plane, w, h)
    return plane


def build_plane_tileset(cat, previous):
    """world/props.tsj and world/cliffs.tsj, derived from the atlas each export.

    Same contract as the terrain tileset: regenerated so a catalogue that grows
    needs no action, with hand-authored properties this tool did not write
    carried over.
    """
    kept = {}
    for tile in (previous or {}).get("tiles", []):
        extra = {k: v for k, v in prop_dict(tile).items()
                 if k not in ("name", "biome", "solid", "foot_w", "foot_h")}
        if extra:
            kept[int(tile["id"])] = extra
    if cat["tiles"] and max(cat["tiles"]) >= cat["count"]:
        print("  note: %s names slot %d but %s holds only %d. Re-run the asset "
              "pipeline to redraw it."
              % (TILES_JSON, max(cat["tiles"]), cat["image"], cat["count"]),
              file=sys.stderr)
    tiles = []
    for slot in range(cat["count"]):
        props = dict(cat["tiles"].get(slot, {}))
        props.update(kept.get(slot, {}))
        if props:
            tiles.append({"id": slot, "properties": prop_list(props)})
    return {
        "columns": cat["cols"],
        "image": os.path.relpath(cat["image"], WORLD_DIR).replace(os.sep, "/"),
        "imageheight": cat["ih"],
        "imagewidth": cat["iw"],
        "margin": 0,
        "name": cat["name"],
        "spacing": 0,
        "tilecount": cat["count"],
        "tiledversion": TILED_VERSION,
        "tileheight": cat["th"],
        "tilewidth": cat["tw"],
        "tiles": tiles,
        "type": "tileset",
        "version": MAP_FORMAT_VERSION,
    }


# --- assembling the map --------------------------------------------------------

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def layer_by_name(tmj, name):
    for layer in (tmj or {}).get("layers", []):
        if layer.get("name") == name:
            return layer
    return None


def translate_edits(gids, w, h, old_w, old_h, dx, dy):
    """Move the override layer when the world changes shape.

    Only reachable behind --resize. Cells that fall off the new map are dropped
    and counted; the caller says so out loud before writing anything.
    """
    out = [0] * (w * h)
    lost = 0
    for y in range(old_h):
        for x in range(old_w):
            gid = gids[y * old_w + x]
            if not gid:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                out[ny * w + nx] = gid
            else:
                lost += 1
    return out, lost


def shift_objects(previous, dx, dy, w, h, size):
    """Move the map's existing objects with the edits when the world is resized.

    Both the current position and the remembered generated position shift, or
    every object would suddenly look hand-dragged and pin itself. Objects that
    land outside the new map are dropped and counted — an anchor at a cell that
    no longer exists is worse than no anchor.
    """
    dropped = 0
    for layer in previous.get("layers", []):
        if layer.get("type") != "objectgroup":
            continue
        kept = []
        for obj in layer.get("objects", []):
            obj["x"] = obj.get("x", 0) + dx * size
            obj["y"] = obj.get("y", 0) + dy * size
            for prop in obj.get("properties", []):
                if prop["name"] == P_GEN_X:
                    prop["value"] += dx * size
                elif prop["name"] == P_GEN_Y:
                    prop["value"] += dy * size
            if 0 <= px_to_cell(obj["x"], size) < w and 0 <= px_to_cell(obj["y"], size) < h:
                kept.append(obj)
            else:
                dropped += 1
        layer["objects"] = kept
    return dropped


def build(args):
    world = load_json(WORLD_JSON)
    if world is None:
        raise SystemExit("%s missing — run python3 tools/make_world.py first" % WORLD_JSON)
    env = sniff(world)
    ids = decode_tiles(world, env)
    w, h = world[env["w_key"]], world[env["h_key"]]
    meta = tile_meta()
    size = meta["size"]

    previous = load_json(TMJ)
    prev_w = (previous or {}).get("width", w)
    prev_h = (previous or {}).get("height", h)

    # Is there anything new to seed?
    #
    # This is the trap in a two-file round trip: the import writes the *composite*
    # of base and edits back to overworld.json, so a naive re-export would read
    # that composite straight into the base layer. Every override would be
    # duplicated into the generated terrain, and erasing one would then do
    # nothing, because the tile it was overriding had become the edit itself.
    #
    # The test needs no stamp file and no extra state: compose the map we already
    # have and compare it to overworld.json. Equal means overworld.json is this
    # map's own output and the generator has not run since — so leave the base
    # layer and the objects exactly as they are. Different means the generator
    # (or a human) has produced new world data, and re-seeding is the point.
    reseed = True
    if previous is not None and not args.discard_edits:
        try:
            from tiled_to_world import compose, render
            with open(WORLD_JSON, "rb") as handle:
                reseed = render(compose(previous)).encode("utf-8") != handle.read()
        except Exception:
            reseed = True       # an unreadable map is not a reason to refuse

    # --- the edits layer, carried across ---
    edits = [0] * (w * h)
    # How far a resize moved the hand work, so the byte planes below can follow
    # the edits layer onto the new grid instead of being thrown away.
    shift = None
    if previous is not None and not args.discard_edits:
        old_layer = layer_by_name(previous, EDIT_LAYER)
        if old_layer is not None:
            old = decode_layer(old_layer, prev_w * prev_h)
            if (prev_w, prev_h) == (w, h):
                edits = old
            elif not args.resize:
                raise SystemExit(
                    "the world is now %dx%d but world/overworld.tmj is %dx%d.\n"
                    "Re-run with --resize to move the %d hand-edited cells onto the "
                    "new grid (add --anchor REGION to align them to a region anchor "
                    "that has moved), or --discard-edits to throw them away."
                    % (w, h, prev_w, prev_h, sum(1 for g in old if g)))
            else:
                dx = dy = 0
                if args.anchor:
                    old_obj = None
                    for layer in previous.get("layers", []):
                        if layer.get("type") != "objectgroup":
                            continue
                        for obj in layer.get("objects", []):
                            if obj.get("name") == args.anchor:
                                old_obj = obj
                    if old_obj is None:
                        raise SystemExit("no object named %r in the map to anchor to"
                                         % args.anchor)
                    new_cell = None
                    for key in env["collections"]:
                        source = world[key]
                        entries = source.items() if isinstance(source, dict) else \
                            [(str(v.get("id", i)), v) for i, v in enumerate(source)]
                        for name, rec in entries:
                            if name == args.anchor:
                                new_cell = (int(rec["x"]), int(rec["y"]))
                    if new_cell is None:
                        raise SystemExit("the world no longer has an anchor named %r"
                                         % args.anchor)
                    dx = new_cell[0] - px_to_cell(old_obj["x"], size)
                    dy = new_cell[1] - px_to_cell(old_obj["y"], size)
                edits, lost = translate_edits(old, w, h, prev_w, prev_h, dx, dy)
                shift = (dx, dy)
                dropped = shift_objects(previous, dx, dy, w, h, size)
                print("  resize: edits shifted by (%+d, %+d); %d cells and %d objects "
                      "fell off the map" % (dx, dy, lost, dropped))
    edit_count = sum(1 for g in edits if g)

    # --- the tilesets, and the global tile ids they claim ---
    #
    # Built before the layers because a prop object refers to its art by *global*
    # tile id, which is the props tileset's firstgid plus its slot — and the
    # firstgid depends on how many terrain tiles come before it. Terrain keeps
    # firstgid 1 so the tile layers' `id + 1` arithmetic is untouched.
    tileset = build_tileset(meta, load_json(TSJ))
    plane_catalogues = {name: plane_catalogue(name) for name in set(env["planes"].values())}
    plane_layer_names = {c["layer"] for c in plane_catalogues.values()}
    plane_tilesets, plane_firstgid = {}, {}
    tileset_refs = [{"firstgid": 1, "source": os.path.basename(TSJ)}]
    next_gid = 1 + tileset["tilecount"]
    for name in sorted(plane_catalogues):
        cat = plane_catalogues[name]
        plane_tilesets[name] = build_plane_tileset(cat, load_json(plane_tsj(name)))
        plane_firstgid[name] = next_gid
        tileset_refs.append({"firstgid": next_gid,
                             "source": os.path.basename(plane_tsj(name))})
        next_gid += cat["count"]

    # --- object layers ---
    layers = []
    next_id = 1
    prev_ids = {l.get("name"): l.get("id") for l in (previous or {}).get("layers", [])}

    def layer_id(name):
        nonlocal next_id
        if prev_ids.get(name):
            return prev_ids[name]
        while next_id in prev_ids.values():
            next_id += 1
        this, next_id = next_id, next_id + 1
        return this

    def view_state(name, default_locked=False):
        old = layer_by_name(previous, name) or {}
        return {"visible": old.get("visible", True),
                "opacity": old.get("opacity", 1),
                "locked": old.get("locked", default_locked)}

    if reseed:
        base_gids = [i + 1 for i in ids]
    else:
        base_gids = decode_layer(layer_by_name(previous, BASE_LAYER), prev_w * prev_h)

    base_layer = {
        "data": encode_layer(base_gids),
        "compression": "zlib", "encoding": "base64",
        "height": h, "width": w, "x": 0, "y": 0,
        "id": layer_id(BASE_LAYER), "name": BASE_LAYER, "type": "tilelayer",
    }
    base_layer.update(view_state(BASE_LAYER))
    # Always locked, never negotiable: the next export overwrites this layer in
    # full, so a lock is the only honest representation of what it is.
    base_layer["locked"] = True
    layers.append(base_layer)

    edit_layer = {
        "data": encode_layer(edits),
        "compression": "zlib", "encoding": "base64",
        "height": h, "width": w, "x": 0, "y": 0,
        "id": layer_id(EDIT_LAYER), "name": EDIT_LAYER, "type": "tilelayer",
    }
    edit_layer.update(view_state(EDIT_LAYER))
    edit_layer["locked"] = False
    layers.append(edit_layer)

    moved_total = added_total = orphan_total = 0
    for key, shape in env["collections"].items():
        source = world[key]
        generated = []
        entries = source.items() if shape == "dict" else \
            [(str(rec.get("id", i)), rec) for i, rec in enumerate(source)]
        for name, rec in entries:
            generated.append(object_from_cell(name, rec, size, key))
        old_layer = layer_by_name(previous, key) or {}
        if reseed:
            objects, moved, added, orphans = merge_objects(
                generated, old_layer.get("objects", []), args.discard_edits)
        else:
            # Nothing new to seed, so nothing to reconcile. Keeping the objects
            # untouched is what preserves a pin across an import: after an
            # import the hand position and the generated position are the same
            # value in overworld.json, and re-deriving hj_gen from it would
            # quietly unpin every marker Kevin has ever dragged.
            objects, moved, added, orphans = old_layer.get("objects", []), 0, 0, 0
        moved_total += moved
        added_total += added
        orphan_total += orphans
        layer = {"draworder": "topdown", "id": layer_id(key), "name": key,
                 "objects": objects, "type": "objectgroup", "x": 0, "y": 0}
        layer.update(view_state(key))
        layers.append(layer)

    # --- the editable byte planes ---
    #
    # Props and cliffs have no identity to reconcile by. A region anchor is
    # `the_town` wherever it moves to; prop number 3,140 is a coin toss in a
    # scatter, and a fresh seed produces a different 4,779 of them. So the
    # pinning here is by *cell* rather than by name, and it is the base/edits
    # split the tile layers already use, with the base stored compactly instead
    # of as a second object layer and the overrides derived instead of stored:
    #
    #   hj_gen_planes   the plane the generator last produced, remembered
    #   the object layer  what you see and edit — the composite
    #   overrides       every cell where the two disagree
    #
    # Which makes deletion representable, and that was the hard part. With a
    # plane, "absent" means nothing; here a cell the remembered plane fills and
    # the objects leave empty is a *positive* statement — "the generator wants a
    # tree here and I do not want one" — and it is re-applied over the next
    # generation exactly like an erased tile. Drag a prop and you get two
    # overrides, empty where it was and a prop where it now is, which is what
    # makes moving it the act of pinning it. No tombstone objects, no flags: the
    # tombstone is the absence, made meaningful by the map remembering what the
    # generator last said.
    plane_stats = {}
    gen_planes = {}
    prev_gen = {}
    if previous is not None:
        try:
            prev_gen = json.loads(prop_dict(previous).get(P_PLANES, "{}"))
        except ValueError:
            prev_gen = {}
    for key, cat_name in env["planes"].items():
        cat = plane_catalogues[cat_name]
        fresh = list(_plane_bytes(world[key], w * h) or [])
        old_layer = layer_by_name(previous, cat["layer"])
        if not reseed and old_layer is not None:
            # Same reason the object layers are left alone: overworld.json is
            # this map's own composite, so re-recording the generated plane from
            # it would swallow every override into the base and there would be
            # nothing left to re-apply.
            objects = old_layer.get("objects", [])
            gen_planes[key] = prev_gen.get(key, world[key])
            plane_stats[cat["layer"]] = None
        else:
            overrides = {}
            if old_layer is not None and not args.discard_edits and key in prev_gen:
                old_first = firstgid_for(previous, os.path.basename(plane_tsj(cat_name)))
                current = objects_to_plane(old_layer.get("objects", []),
                                           prev_w, prev_h, cat, old_first)
                recorded = list(_plane_bytes(prev_gen[key], prev_w * prev_h) or [])
                if (prev_w, prev_h) != (w, h) and shift is not None:
                    # A resize moved the objects already (shift_objects), so the
                    # plane they are compared against has to move with them or
                    # every prop in the world would read as hand-placed.
                    current, _ = translate_edits(current, w, h, prev_w, prev_h, *shift)
                    recorded, _ = translate_edits(recorded, w, h, prev_w, prev_h, *shift)
                if len(current) == len(recorded) == w * h:
                    overrides = {i: current[i] for i in range(w * h)
                                 if current[i] != recorded[i]}
                elif recorded:
                    print("  note: the world changed shape, so the hand-edited %s "
                          "were not carried across" % cat["layer"], file=sys.stderr)
            merged = list(fresh)
            for i, value in overrides.items():
                merged[i] = value
            objects = plane_objects(merged, w, h, cat, plane_firstgid[cat_name])
            gen_planes[key] = world[key]
            plane_stats[cat["layer"]] = {
                "total": sum(1 for v in merged if v),
                "placed": sum(1 for i, v in overrides.items() if v and not fresh[i]),
                "removed": sum(1 for i, v in overrides.items() if not v),
                "changed": sum(1 for i, v in overrides.items() if v and fresh[i]),
            }
        layer = {"draworder": "index", "id": layer_id(cat["layer"]),
                 "name": cat["layer"], "objects": objects,
                 "type": "objectgroup", "x": 0, "y": 0}
        layer.update(view_state(cat["layer"]))
        layers.append(layer)

    for layer in (previous or {}).get("layers", []):
        # Object layers Kevin made himself. The generator knows nothing about
        # them, so there is nothing to merge — carry them across untouched.
        if layer.get("type") != "objectgroup":
            continue
        if layer.get("name") in env["collections"] or layer.get("name") == MARKER_LAYER:
            continue
        if layer.get("name") in plane_layer_names:
            continue
        layers.append(layer)

    if env["markers"]:
        generated = []
        for key in env["markers"]:
            obj = object_from_cell(key, world[key], size, key)
            obj["properties"].append({"name": P_MARKER, "type": "bool", "value": True})
            generated.append(obj)
        old_layer = layer_by_name(previous, MARKER_LAYER) or {}
        if reseed:
            objects, moved, added, orphans = merge_objects(
                generated, old_layer.get("objects", []), args.discard_edits)
        else:
            objects, moved, added, orphans = old_layer.get("objects", []), 0, 0, 0
        moved_total += moved
        added_total += added
        layer = {"draworder": "topdown", "id": layer_id(MARKER_LAYER),
                 "name": MARKER_LAYER, "objects": objects,
                 "type": "objectgroup", "x": 0, "y": 0}
        layer.update(view_state(MARKER_LAYER))
        layers.append(layer)

    # Object ids must be unique across the map and stable across exports.
    used = {o["id"] for l in layers if l["type"] == "objectgroup"
            for o in l["objects"] if o.get("id")}
    counter = 1
    for layer in layers:
        if layer["type"] != "objectgroup":
            continue
        for obj in layer["objects"]:
            if obj.get("id"):
                continue
            while counter in used:
                counter += 1
            obj["id"] = counter
            used.add(counter)

    tmj = {
        "compressionlevel": -1,
        "height": h,
        "infinite": False,
        "layers": layers,
        "nextlayerid": max([l["id"] for l in layers] + [0]) + 1,
        "nextobjectid": max(used | {0}) + 1,
        "orientation": "orthogonal",
        # hj_gen_planes is the plane each editable object layer was seeded from.
        # It lives on the map rather than in hj_schema's passthrough because it
        # must survive an import: after one, overworld.json holds the composite,
        # and re-reading the base from there would swallow every override.
        "properties": prop_list({
            P_SCHEMA: json.dumps(env, separators=(",", ":"), sort_keys=True),
            P_PLANES: json.dumps(gen_planes, separators=(",", ":"), sort_keys=True),
        }),
        "renderorder": "right-down",
        "tiledversion": TILED_VERSION,
        "tileheight": size,
        "tilesets": tileset_refs,
        "tilewidth": size,
        "type": "map",
        "version": MAP_FORMAT_VERSION,
        "width": w,
    }
    stats = {"w": w, "h": h, "edits": edit_count, "moved": moved_total,
             "added": added_total, "orphans": orphan_total,
             "tiles": tileset["tilecount"], "reseed": reseed,
             "planes": plane_stats}
    return tmj, tileset, plane_tilesets, env, stats


PROJECT_JSON = {
    "automappingRulesFile": "",
    "commands": [],
    "compatibilityVersion": 1100,
    "extensionsPath": "extensions",
    "folders": ["."],
    "propertyTypes": [],
}


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def verify(tmj_path):
    """Prove the round trip, on a scratch copy of the map with the hand work
    stripped back out.

    The claim being tested is precise: *export then import, with no edits, is
    byte-identical*. So the copy has its override layer blanked, every generated
    object put back where the generator last put it, and every hand-added object
    removed — and what is left must reproduce data/world/overworld.json exactly,
    byte for byte, including key order, indentation and the trailing newline.
    Running it on every export means the guarantee is checked against the real
    map on the real schema, not asserted in a comment.

    Imported lazily: tiled_to_world imports this module for its schema helpers,
    and a top-level import here would close the loop.
    """
    from tiled_to_world import compose, render

    with open(tmj_path, encoding="utf-8") as handle:
        tmj = json.load(handle)
    clean = json.loads(json.dumps(tmj))
    env = json.loads(prop_dict(clean).get(P_SCHEMA, "{}"))
    known = set(env.get("collections", {})) | {MARKER_LAYER}
    # The plane layers are put back the same way: from the plane the generator
    # last produced, so a prop dragged, added or deleted by hand is stripped out
    # of the copy exactly as a dragged anchor is.
    gen_planes = json.loads(prop_dict(clean).get(P_PLANES, "{}"))
    by_layer = {}
    w, h = int(clean["width"]), int(clean["height"])
    for key, name in env.get("planes", {}).items():
        cat = plane_catalogue(name)
        first = firstgid_for(clean, os.path.basename(plane_tsj(name)))
        by_layer[cat["layer"]] = plane_objects(
            list(_plane_bytes(gen_planes.get(key, ""), w * h) or [0] * (w * h)),
            w, h, cat, first if first is not None else 1)
        known.add(cat["layer"])
    layers = []
    for layer in clean["layers"]:
        if layer.get("name") == EDIT_LAYER:
            layer["data"] = encode_layer([0] * (layer["width"] * layer["height"]))
        if layer.get("type") == "objectgroup":
            if layer.get("name") not in known:
                continue        # a whole object layer Kevin added
            if layer.get("name") in by_layer:
                layer["objects"] = by_layer[layer["name"]]
                layers.append(layer)
                continue
            kept = []
            for obj in layer["objects"]:
                props = prop_dict(obj)
                if P_GEN_X not in props:
                    continue    # hand-added object
                obj["x"], obj["y"] = props[P_GEN_X], props[P_GEN_Y]
                kept.append(obj)
            layer["objects"] = kept
        layers.append(layer)
    clean["layers"] = layers

    text = render(compose(clean))
    with open(WORLD_JSON, "rb") as original:
        want = original.read()
    if text.encode("utf-8") == want:
        return True, "byte-identical (%d bytes reproduced exactly)" % len(want)

    # A bare "not equal" on a file that is mostly one base64 blob is useless.
    # Say which key diverged, because that is the whole diagnosis.
    try:
        got, _ = compose(clean)
        original = json.loads(want)
        bad = [k for k in set(got) | set(original) if got.get(k) != original.get(k)]
        detail = "keys that differ: %s" % ", ".join(sorted(bad)) if bad else \
            "same values, different formatting (indent or key order)"
    except Exception as exc:      # a broken map should still report *something*
        detail = "could not diff: %s" % exc
    return False, detail


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--discard-edits", action="store_true",
                    help="throw away the hand-authored edits layer and reset every "
                         "moved object. Destructive; prints what it will destroy.")
    ap.add_argument("--resize", action="store_true",
                    help="allow the export when the world has changed size, moving "
                         "the edits layer onto the new grid")
    ap.add_argument("--anchor", metavar="NAME",
                    help="with --resize, align the edits to this named object "
                         "instead of to cell (0, 0)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the round-trip proof")
    args = ap.parse_args()

    if args.discard_edits and os.path.exists(TMJ):
        previous = load_json(TMJ)
        layer = layer_by_name(previous, EDIT_LAYER)
        cells = sum(1 for g in decode_layer(layer, previous["width"] * previous["height"])
                    if g) if layer else 0
        # Plane layers are excluded: their objects carry no hj_gen (the map
        # remembers the whole plane instead), so every prop in the world would
        # otherwise be counted as hand-placed. They are counted below.
        plane_names = {plane_catalogue(n)["layer"] for n in
                       json.loads(prop_dict(previous).get(P_SCHEMA, "{}"))
                       .get("planes", {}).values()}
        pinned = 0
        for l in previous.get("layers", []):
            if l.get("type") != "objectgroup" or l.get("name") in plane_names:
                continue
            for obj in l.get("objects", []):
                props = prop_dict(obj)
                if P_GEN_X not in props or obj["x"] != props[P_GEN_X] \
                        or obj["y"] != props[P_GEN_Y]:
                    pinned += 1
        # Prop and cliff edits are not objects with an hj_gen to compare against;
        # they are cells where the layer disagrees with the plane the generator
        # last produced. Counted the same way the export applies them.
        plane_cells = 0
        try:
            gen_planes = json.loads(prop_dict(previous).get(P_PLANES, "{}"))
            cells_n = previous["width"] * previous["height"]
            for key, name in json.loads(prop_dict(previous).get(P_SCHEMA, "{}")) \
                    .get("planes", {}).items():
                cat = plane_catalogue(name)
                layer = layer_by_name(previous, cat["layer"]) or {}
                first = firstgid_for(previous, os.path.basename(plane_tsj(name)))
                current = objects_to_plane(layer.get("objects", []),
                                           previous["width"], previous["height"],
                                           cat, first)
                recorded = list(_plane_bytes(gen_planes.get(key, ""), cells_n) or [])
                if len(recorded) == len(current):
                    plane_cells += sum(1 for a, b in zip(current, recorded) if a != b)
        except Exception:
            plane_cells = 0     # an unreadable map is not a reason to refuse
        print("--discard-edits will destroy: %d hand-painted cells, %d hand-placed or "
              "hand-moved objects, %d hand-edited prop and cliff cells. This cannot be "
              "undone except from git." % (cells, pinned, plane_cells))
        print("It re-seeds the base layer from data/world/overworld.json as it stands. "
              "If you have already imported once, edits from that import are part of "
              "that file and will survive as terrain — run python3 tools/make_world.py "
              "first for a genuinely clean seed.")

    tmj, tileset, plane_tilesets, env, stats = build(args)
    if args.dry_run:
        print("dry run: %dx%d, %d overrides kept, %d objects pinned, %d added, "
              "%d kept that the generator no longer makes"
              % (stats["w"], stats["h"], stats["edits"], stats["moved"],
                 stats["added"], stats["orphans"]))
        for name in sorted(stats["planes"]):
            counts = stats["planes"][name]
            print("  %s: %s" % (name, "untouched" if counts is None else
                                "%d placed, %d deleted, %d retyped by hand"
                                % (counts["placed"], counts["removed"],
                                   counts["changed"])))
        return 0

    os.makedirs(WORLD_DIR, exist_ok=True)
    write_json(TSJ, tileset)
    for name, payload in plane_tilesets.items():
        write_json(plane_tsj(name), payload)
    write_json(TMJ, tmj)
    if not os.path.exists(PROJECT):
        write_json(PROJECT, PROJECT_JSON)

    print("world/overworld.tmj  %dx%d, %d tiles in the set"
          % (stats["w"], stats["h"], stats["tiles"]))
    if stats["reseed"]:
        print("  base    re-seeded from data/world/overworld.json (locked)")
        print("  edits   %d cells kept" % stats["edits"])
        print("  objects %d pinned by hand, %d new from the generator, %d kept that "
              "the generator no longer produces"
              % (stats["moved"], stats["added"], stats["orphans"]))
    else:
        print("  nothing to seed: data/world/overworld.json is this map's own "
              "composite, so base, edits and objects are all untouched.")
        print("  edits   %d cells" % stats["edits"])
    for name in sorted(stats["planes"]):
        counts = stats["planes"][name]
        if counts is None:
            print("  %-7s untouched" % name)
        else:
            print("  %-7s %d objects — %d placed by hand, %d deleted, %d retyped"
                  % (name, counts["total"], counts["placed"], counts["removed"],
                     counts["changed"]))

    if not args.no_verify:
        ok, detail = verify(TMJ)
        sys.stdout.flush()
        if ok:
            print("  round trip: %s" % detail)
        else:
            print("  ROUND TRIP FAILED: with your edits stripped back out this map "
                  "does not reproduce data/world/overworld.json byte for byte — %s.\n"
                  "  Something in the world schema is not surviving the trip. Do not "
                  "edit until it is fixed; the import would lose it." % detail,
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
