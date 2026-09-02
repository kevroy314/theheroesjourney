#!/usr/bin/env python3
"""Import the hand-edited Tiled map back into the game's world data.

    python3 tools/tiled_to_world.py          # world/overworld.tmj -> data/world/overworld.json

The other half of tools/world_to_tiled.py; read that file's docstring first, it
carries the design.

What this does is composite. The map holds a generated `base` layer and a
hand-authored `edits` layer, and the tile the game sees is the override where
there is one and the generated tile everywhere else. Objects come back as the
records they came from — region anchors, spawn, and whatever collections of
{x, y, ...} the world model grows next — including any Kevin added by hand that
the generator has never heard of.

Everything this tool does not understand about the schema was stashed in the
map's `hj_schema` property on export and is written straight back out, in the
original key order, with the original JSON formatting. That is what makes an
edit-free round trip byte-identical rather than merely equivalent, and it is
what lets the world model grow an elevation field without this file changing.

`--check` composites and diffs without writing, so you can see what your edits
did to the game data before committing to it.
"""
import argparse
import base64
import json
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from world_to_tiled import (  # noqa: E402  (path fixup has to come first)
    BASE_LAYER, EDIT_LAYER, MARKER_LAYER, P_GEN_X, P_GEN_Y, P_JSON, P_KEYS,
    P_MARKER, P_SCHEMA, TMJ, TSJ, WORLD_JSON, decode_layer, derive_blocked,
    encode_plane, firstgid_for, layer_by_name, objects_to_plane, plane_catalogue,
    plane_tsj, prop_dict, props_by_plane, px_to_cell, tile_meta,
)


def envelope(tmj):
    props = prop_dict(tmj)
    if P_SCHEMA not in props:
        raise SystemExit("world/overworld.tmj has no %s property. It was not written "
                         "by tools/world_to_tiled.py, or the property was deleted — "
                         "re-export before importing." % P_SCHEMA)
    return json.loads(props[P_SCHEMA])


def encode_tiles(ids, env):
    """Back to the generator's own encoding: same byte width, same zlib level.

    Both were measured on export rather than assumed, so a world model that
    moves to two bytes a cell for a four-hundred tile set needs nothing here.
    """
    width = env.get("cell_bytes", 1)
    if width == 1:
        if any(i > 255 for i in ids):
            raise SystemExit(
                "a tile id above 255 does not fit the one-byte-per-cell encoding "
                "the generator used. The generator has to widen the encoding "
                "first; this tool follows whatever it writes.")
        raw = bytes(bytearray(ids))
    else:
        fmt = {2: "<%dH", 4: "<%dI"}[width] % len(ids)
        raw = struct.pack(fmt, *ids)
    return base64.b64encode(zlib.compress(raw, env.get("zlib_level", 9))).decode("ascii")


def object_to_record(obj, size):
    """A Tiled point object back to its {x, y, ...} record.

    The cell is the cell the point lands in, so nudging a marker a few pixels
    inside its square is a no-op — only dragging it to another tile counts.
    """
    props = prop_dict(obj)
    json_keys = set(str(props.get(P_JSON, "")).split(",")) - {""}
    record = {"x": px_to_cell(obj.get("x", 0), size),
              "y": px_to_cell(obj.get("y", 0), size)}
    for name, value in props.items():
        if name.startswith("hj_"):
            continue
        record[name] = json.loads(value) if name in json_keys else value
    order = str(props.get(P_KEYS, "")).split(",") if P_KEYS in props else None
    if order:
        ordered = {k: record[k] for k in order if k in record}
        ordered.update({k: v for k, v in record.items() if k not in ordered})
        record = ordered
    return record


def compose(tmj):
    """The .tmj as the world dict the game loads."""
    env = envelope(tmj)
    w, h = int(tmj["width"]), int(tmj["height"])
    cells = w * h
    size = int(tmj.get("tilewidth", tile_meta()["size"]))

    base = layer_by_name(tmj, BASE_LAYER)
    if base is None:
        raise SystemExit("the map has no %r layer" % BASE_LAYER)
    base_gids = decode_layer(base, cells)
    edit_layer = layer_by_name(tmj, EDIT_LAYER)
    edit_gids = decode_layer(edit_layer, cells) if edit_layer else [0] * cells

    # By name, not "whichever came last": the map carries a props and a cliffs
    # tileset now, and reading the terrain layers against the props atlas would
    # turn every tile into a negative id.
    firstgid = firstgid_for(tmj, os.path.basename(TSJ))
    if firstgid is None:
        firstgid = 1

    ids = []
    for i in range(cells):
        gid = edit_gids[i] or base_gids[i]
        if gid == 0:
            # A hole in the *base* layer, which the generator never leaves. It
            # means someone erased in a locked layer, or the map was resized in
            # Tiled rather than by regenerating. Either way there is no tile to
            # give the game, and silently substituting id 0 would paint
            # floorboards across the hole.
            raise SystemExit(
                "cell (%d, %d) is empty in both layers. The base layer must cover "
                "the whole map — re-run npm run world:export to rebuild it."
                % (i % w, i // w))
        ids.append(gid - firstgid)

    # --- the editable byte planes, folded back out of their object layers ---
    #
    # The plane is still what the game loads: scripts/ui/TileWorld.gd indexes it
    # per cell every frame, and 4,779 objects would be a quarter of a megabyte of
    # JSON to parse at launch for a lookup one byte already answers. Objects are
    # the editing format; this is where they stop being objects.
    planes, plane_layers = {}, {}
    for key, cat_name in env.get("planes", {}).items():
        cat = plane_catalogue(cat_name)
        layer = layer_by_name(tmj, cat["layer"])
        if layer is None:
            raise SystemExit(
                "the map has no %r layer, but the world file has a %s plane. "
                "Deleting the layer would empty it — re-export if that is what "
                "you meant." % (cat["layer"], key))
        first = firstgid_for(tmj, os.path.basename(plane_tsj(cat_name)))
        planes[key] = objects_to_plane(layer.get("objects", []), w, h, cat, first)
        plane_layers[cat["layer"]] = key

    # blocked is derived from those, never edited and never carried verbatim,
    # which is the only way a prop you placed by hand can block. tools/make_world.py
    # calls the same function on the same planes, so the generated file and the
    # imported one agree byte for byte.
    by_cat = {name: key for key, name in env.get("planes", {}).items()}
    for key in env.get("derived", {}):
        planes[key] = derive_blocked(planes.get(by_cat.get("props")),
                                     planes.get(by_cat.get("cliffs")),
                                     w, h, props_by_plane())

    collections, markers = {}, {}
    known = set(env.get("collections", {})) | {MARKER_LAYER} | set(plane_layers)
    for layer in tmj.get("layers", []):
        if layer.get("type") != "objectgroup":
            continue
        name = layer.get("name")
        objects = layer.get("objects", [])
        if name in plane_layers:
            continue        # already folded into its plane above
        if name == MARKER_LAYER:
            for obj in objects:
                markers[obj.get("name")] = object_to_record(obj, size)
            continue
        shape = env.get("collections", {}).get(name)
        if shape is None:
            # An object layer Kevin added by hand. Guess its shape from the
            # objects: named ones are a dict, unnamed ones a list. Better than
            # dropping the layer, which would lose work with no warning.
            shape = "dict" if all(o.get("name") for o in objects) else "list"
        if shape == "dict":
            collections[name] = {o.get("name"): object_to_record(o, size)
                                 for o in objects}
        else:
            collections[name] = [object_to_record(o, size) for o in objects]
        known.add(name)

    world = {}
    for key in env["key_order"]:
        if key == env["w_key"]:
            world[key] = w
        elif key == env["h_key"]:
            world[key] = h
        elif key == env["tiles_key"]:
            world[key] = encode_tiles(ids, env)
        elif key in planes:
            world[key] = encode_plane(planes[key],
                                      env.get("plane_zlib", {}).get(key, 9))
        elif key in collections:
            world[key] = collections[key]
        elif key in markers:
            world[key] = markers[key]
        elif key in env["passthrough"]:
            world[key] = env["passthrough"][key]
        # A key in the recorded order that no longer has a source is one Kevin
        # deleted the layer or object for. Dropping it is the right answer;
        # inventing a value for it is not.
    # Anything added in Tiled since the export lands at the end, in map order.
    for key, value in collections.items():
        world.setdefault(key, value)
    for key, value in markers.items():
        world.setdefault(key, value)
    return world, env


def render(composed):
    """The exact bytes make_world.py would have written.

    json.dump's indent and the trailing newline are both recorded on export
    rather than hardcoded, because they are the generator's choices and this
    tool has no business having an opinion about them.
    """
    world, env = composed
    text = json.dumps(world, indent=env.get("indent", 1))
    if env.get("trailing_newline", True):
        text += "\n"
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="composite and report the difference against the current "
                         "data/world/overworld.json without writing it")
    args = ap.parse_args()

    if not os.path.exists(TMJ):
        raise SystemExit("%s missing — run npm run world:export first" % TMJ)
    with open(TMJ, encoding="utf-8") as handle:
        tmj = json.load(handle)
    composed = compose(tmj)
    text = render(composed)

    previous = b""
    if os.path.exists(WORLD_JSON):
        with open(WORLD_JSON, "rb") as handle:
            previous = handle.read()

    world, env = composed
    if text.encode("utf-8") == previous:
        print("data/world/overworld.json unchanged (byte-identical round trip)")
        return 0

    # Say what actually moved, not just that something did. A one-line "the file
    # changed" on a 4KB base64 blob tells you nothing about whether the import
    # did what you meant.
    changed_cells = 0
    if previous:
        try:
            old = json.loads(previous)
            old_raw = zlib.decompress(base64.b64decode(old[env["tiles_key"]]))
            new_raw = zlib.decompress(base64.b64decode(world[env["tiles_key"]]))
            if len(old_raw) == len(new_raw):
                changed_cells = sum(1 for a, b in zip(old_raw, new_raw) if a != b)
            else:
                changed_cells = -1
        except Exception:
            changed_cells = -1
    where = "%d cells differ" % changed_cells if changed_cells >= 0 \
        else "the grid changed shape"
    if args.check:
        print("would rewrite data/world/overworld.json: %s" % where)
        return 0
    with open(WORLD_JSON, "w", encoding="utf-8") as handle:
        handle.write(text)
    print("data/world/overworld.json written: %s" % where)
    return 0


if __name__ == "__main__":
    sys.exit(main())
