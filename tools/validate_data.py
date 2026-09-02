#!/usr/bin/env python3
"""Validate everything under data/ against data/schema.json.

This is the build-time half of the check. The other half lives in
Content.validate() and runs inside the game, over the merged runtime view.
They deliberately do not overlap completely:

  * Content sees what actually *loaded* -- packs stamped onto movements, files
    merged by top-level key, ids collided across files -- and it runs on a
    player's device, where it must log and carry on rather than refuse to boot.

  * This tool sees the source tree, which Content cannot: it reads the GDScript
    to work out which modifier keys any Rules.value() call actually reads, which
    words each `match` in the engine implements, and whether the vocabulary
    lists in the schema still agree with the code they claim to describe. It
    also reaches data/world/overworld.json and assets/tiles/tiles.json, which
    are the art pipeline's contract rather than Content's.

Severity is the interesting part:

  ERROR  the data contradicts itself -- a typo, a dangling reference, an
         unknown key. Fixable inside data/ alone. Fatal.
  WARN   the data is internally consistent but something outside data/ makes it
         dead -- a verb no code implements, a prop on a biome the world
         generator never produces. Fixing it needs a code or art decision, so
         it is reported loudly and does not fail the build. --strict promotes
         every warning to an error.

Usage:
    python3 tools/validate_data.py [--strict] [--quiet]
"""

import argparse
import base64
import glob
import json
import os
import re
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SCRIPTS = os.path.join(ROOT, "scripts")
SCHEMA_PATH = os.path.join(DATA, "schema.json")


# --- reporting -----------------------------------------------------------------

class Report(object):
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, where, message):
        self.errors.append("%s: %s" % (where, message))

    def warn(self, where, message):
        self.warnings.append("%s: %s" % (where, message))


# --- path grammar --------------------------------------------------------------
# Shared with Content.gd. See the "_paths" note in data/schema.json.

def walk_path(root, path):
    """Every (value, trail) the dotted path selects, in document order.

    The trail is the id of each object passed through on the way down, so a
    complaint about a node can name the area it is in. "anomaly a_wound > node c"
    is actionable; "node c" is a search.
    """
    def trail_of(parent, key, container):
        step = parent[:]
        if isinstance(container, dict) and "id" in container:
            step.append(str(container["id"]))
        elif key:
            step.append(key)
        return step

    if path == ".":
        return [(root, trail_of([], "", root))]
    current = [(root, [])]
    for segment in path.split("."):
        expand = None
        if segment.endswith("[]"):
            segment, expand = segment[:-2], "list"
        elif segment.endswith("{}"):
            segment, expand = segment[:-2], "dict"
        nxt = []
        for node, trail in current:
            if segment == "":
                value = node
            elif isinstance(node, dict):
                value = node.get(segment)
            else:
                value = None
            if value is None:
                continue
            here = trail_of(trail, segment, node)
            if expand == "list" and isinstance(value, list):
                nxt.extend((item, here) for item in value)
            elif expand == "dict" and isinstance(value, dict):
                nxt.extend((item, here + [str(key)]) for key, item in value.items())
            elif expand is None:
                nxt.append((value, here))
        current = nxt
    return current


# --- loading -------------------------------------------------------------------

def load_data_files():
    """{relative path -> parsed document} for every content file under data/.

    data/schema.json is the description, not the described, and Content never
    reads data/ itself -- only its subdirectories -- so the root is skipped.
    """
    docs = {}
    for path in sorted(glob.glob(os.path.join(DATA, "*", "**", "*.json"), recursive=True)):
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as handle:
            docs[rel] = json.load(handle)
    return docs


def docs_in(docs, directory):
    prefix = os.path.join("data", directory) + os.sep
    return [(rel, doc) for rel, doc in docs.items() if rel.startswith(prefix)]


def gather(docs, spec):
    """Records of one schema type, as (origin, record) triples with a trail."""
    out = []
    sources = [spec["files"]] + spec["files"].get("also", [])
    for source in sources:
        for rel, doc in docs_in(docs, source["dir"]):
            for path in source["paths"]:
                for record, trail in walk_path(doc, path):
                    out.append((rel, record, trail))
    return out


# --- GDScript source scanning --------------------------------------------------
# None of this is clever parsing. It reads the engine's own `match` statements
# and literal call sites so the vocabulary lists in the schema cannot silently
# stop describing the code -- a schema that has drifted is worse than no schema,
# because it validates confidently against the wrong words.

def gd_sources():
    return sorted(glob.glob(os.path.join(SCRIPTS, "**", "*.gd"), recursive=True))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def func_body(path, name):
    """The lines of `func name(...)`, up to the next top-level declaration."""
    lines = read(path).splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^func\s+%s\s*\(" % re.escape(name), line):
            start = i + 1
            break
    if start is None:
        return None
    body = []
    for line in lines[start:]:
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


def match_arms(body):
    """String literals used as `match` arm labels: `"a", "b":` on its own line."""
    arms = set()
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.endswith(":") or not stripped.startswith('"'):
            continue
        labels = re.findall(r'"([^"]*)"', stripped[:-1])
        if labels and re.fullmatch(r'(\s*"[^"]*"\s*,?)+\s*', stripped[:-1]):
            arms.update(labels)
    return arms


def const_array(path, name):
    text = read(path)
    match = re.search(r"const\s+%s\s*:?=\s*\[(.*?)\]" % re.escape(name), text, re.S)
    if not match:
        return None
    return re.findall(r'"([^"]*)"', match.group(1))


def const_dict_keys(path, name):
    text = read(path)
    match = re.search(r"const\s+%s\s*:?=\s*\{(.*?)\n\}" % re.escape(name), text, re.S)
    if not match:
        return None
    return re.findall(r'"([^"]*)"\s*:', match.group(1))


LITERAL_RULES_CALL = re.compile(r'Rules\.(?:value_int|value|apply)\(\s*"([^"]+)"')
ANY_RULES_CALL = re.compile(r'Rules\.(?:value_int|value|apply)\(\s*(.)')


def scan_rules_keys(report, dynamic_fields, data_dynamic_keys):
    """Every modifier key some Rules.value()/apply() call actually reads.

    Two flavours. Most call sites name the key as a literal and are found by
    grep. One does not: Game.gd rolls loot with

        Rules.value(String(entry["scaled_by"]), ctx, 1.0)

    so the keys it reads come from the data, not the source. Those are declared
    in the schema as dynamic_key_fields and folded in here. Any *other*
    non-literal call site is reported, because it means a reader exists that
    this scan cannot see and the "key nobody reads" check has a blind spot.
    """
    keys = set()
    for path in gd_sources():
        text = read(path)
        keys.update(LITERAL_RULES_CALL.findall(text))
        for line_no, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue          # prose about Rules.value() is not a call to it
            for match in ANY_RULES_CALL.finditer(line):
                if match.group(1) in ('"', ")"):
                    continue
                if any(field in line for field in dynamic_fields):
                    continue
                report.warn(
                    "%s:%d" % (os.path.relpath(path, ROOT), line_no),
                    "Rules key is computed, not a literal, so the unread-key check "
                    "cannot see what it reads. Add its data field to "
                    "vocabulary.dynamic_key_fields in data/schema.json if it takes "
                    "one: %s" % line.strip())
    keys.update(data_dynamic_keys)
    return keys


def reconcile(report, schema, source_words, name, where):
    """Fail if the schema's vocabulary and the engine's disagree, either way."""
    declared = set(schema["vocabulary"][name])
    if source_words is None:
        report.warn("data/schema.json", "could not read '%s' from %s -- the "
                    "vocabulary check for it is running blind" % (name, where))
        return
    actual = set(source_words)
    for word in sorted(declared - actual):
        report.error("data/schema.json", "vocabulary.%s lists '%s' but %s does not "
                     "implement it" % (name, word, where))
    for word in sorted(actual - declared):
        report.error("data/schema.json", "%s implements '%s' but vocabulary.%s does "
                     "not list it, so data using it would be rejected"
                     % (where, word, name))


# --- schema pass ---------------------------------------------------------------

def build_id_sets(docs, schema):
    """Named sets of ids that `refs` can point at."""
    sets = {}
    for type_name, spec in schema["types"].items():
        space = spec.get("id_space", type_name)
        bucket = sets.setdefault(space, set())
        for _origin, record, _trail in gather(docs, spec):
            if isinstance(record, dict) and "id" in record:
                bucket.add(record["id"])
    # Sets that are not a type's ids: loot tables are the keys of a map, and
    # config keys are the tunables a modifier or a scaled_by may name.
    sets["loot"] = set()
    sets["config_keys"] = set()
    for _rel, doc in docs_in(docs, "content"):
        sets["loot"].update(doc.get("loot", {}).keys())
        sets["config_keys"].update(doc.get("config", {}).keys())
    return sets


def check_record(report, where, spec, vocab, record, id_sets):
    if not isinstance(record, dict):
        report.error(where, "expected an object, got %s" % type(record).__name__)
        return

    allowed = set(spec["required"]) | set(spec.get("optional", []))
    for key in spec["required"]:
        if key not in record:
            report.error(where, "missing required key '%s'" % key)
    # The check that actually catches typos: "whn" is only an error because
    # unknown keys are errors.
    for key in record:
        if key.startswith("_"):
            continue        # _comment and friends are documentation, always fine
        if key not in allowed:
            report.error(where, "unknown key '%s' (allowed: %s)"
                         % (key, ", ".join(sorted(allowed))))

    for field, vocab_name in spec.get("enum", {}).items():
        if field not in record:
            continue
        extra = spec.get("enum_extra", {}).get(field, [])
        allowed_values = list(vocab[vocab_name]) + list(extra)
        if record[field] not in allowed_values:
            report.error(where, "%s '%s' is not one of: %s"
                         % (field, record[field], ", ".join(map(str, allowed_values))))

    for field, set_name in spec.get("refs", {}).items():
        if field not in record:
            continue
        wanted = record[field]
        values = wanted if isinstance(wanted, list) else [wanted]
        for value in values:
            if value not in id_sets.get(set_name, set()):
                report.error(where, "%s '%s' names no known %s" % (field, value, set_name))

    for field, set_name in spec.get("key_refs", {}).items():
        for key in (record.get(field) or {}):
            if key not in id_sets.get(set_name, set()):
                report.error(where, "%s has an entry for '%s', which names no known %s"
                             % (field, key, set_name))

    # Movement and unit fields accept a literal id or one of the authoring
    # tokens; anything else is a token the resolver will not recognise, and an
    # unrecognised token fails soft (int("$one") is 0), which is the exact
    # silence this whole file exists to remove.
    for field, set_name in spec.get("token_ref", {}).items():
        value = record.get(field)
        if not isinstance(value, str):
            continue
        if value.startswith("$"):
            if value in vocab["movement_tokens"]:
                continue
            if any(value.startswith(p) for p in vocab["movement_token_prefixes"]):
                axis = value.split(":", 1)[1] if ":" in value else ""
                if axis not in id_sets.get("axes", set()):
                    report.error(where, "%s '%s' names no known axis" % (field, value))
                continue
            report.error(where, "%s '%s' is not a movement token (%s)"
                         % (field, value, ", ".join(vocab["movement_tokens"]
                                                   + vocab["movement_token_prefixes"])))
            continue
        if value not in id_sets.get(set_name, set()):
            report.error(where, "%s '%s' names no known %s" % (field, value, set_name))

    for field, vocab_name in spec.get("token_enum", {}).items():
        value = record.get(field)
        if isinstance(value, str) and value not in vocab[vocab_name]:
            report.error(where, "%s '%s' is not a %s token (%s) and is not a number"
                         % (field, value, field, ", ".join(vocab[vocab_name])))

    if "req_type_vocab" in spec:
        req_type = (record.get("req") or {}).get("type")
        if req_type not in vocab[spec["req_type_vocab"]]:
            report.error(where, "req.type '%s' is not implemented" % req_type)

    if "effect_vocab" in spec:
        effect_type = (record.get("effect") or {}).get("type")
        if effect_type not in vocab[spec["effect_vocab"]]:
            report.error(where, "effect.type '%s' is not implemented" % effect_type)


def schema_pass(report, docs, schema, id_sets):
    vocab = schema["vocabulary"]
    for type_name, spec in schema["types"].items():
        records = gather(docs, spec)
        # A type whose locator selects nothing is a schema typo that looks like
        # a clean bill of health -- it silently validates an empty set. It bit
        # once already: "loot{}[]" parses as the field "loot{}", not as "expand
        # the map, then expand each list", which is "loot{}.[]".
        if not records:
            report.warn("data/schema.json",
                        "type '%s' matches no records; check its files.paths "
                        "(and runtime, which is checked the same way inside "
                        "Content)" % type_name)
        seen = {}
        for origin, record, trail in records:
            crumbs = list(trail)
            own = str(record.get("id")) if isinstance(record, dict) and "id" in record else ""
            if own and (not crumbs or crumbs[-1] != own):
                crumbs.append(own)
            where = "%s [%s %s]" % (origin, type_name, " > ".join(crumbs) or "?")
            check_record(report, where, spec, vocab, record, id_sets)
            if spec.get("unique_ids", True) and isinstance(record, dict) and "id" in record:
                if record["id"] in seen:
                    report.error(where, "duplicate %s id, already defined in %s"
                                 % (type_name, seen[record["id"]]))
                seen[record["id"]] = origin


# --- graph pass ----------------------------------------------------------------
# Areas and anomalies share a shape, so they share a check. This is the class of
# problem the self-test can only find by happening to walk the broken edge.

def graph_pass(report, docs):
    areas = []
    for rel, doc in docs_in(docs, "areas"):
        areas.append((rel, doc))
    for rel, doc in docs_in(docs, "content"):
        for anomaly in doc.get("anomalies", []):
            areas.append((rel, anomaly))

    for origin, area in areas:
        where = "%s [area %s]" % (origin, area.get("id", "?"))
        nodes = area.get("nodes", [])
        ids = [n.get("id") for n in nodes if isinstance(n, dict)]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_where = "%s node '%s'" % (where, node.get("id", "?"))
            for target in node.get("next", []):
                if target not in ids:
                    report.error(node_where, "next names '%s', which is not a node in "
                                             "this area" % target)
            if node.get("exclusive_next") and len(node.get("next", [])) < 2:
                report.error(node_where, "exclusive_next on a node with fewer than two "
                                         "next entries closes nothing")
        if ids and not any(n.get("type") == "threshold" for n in nodes if isinstance(n, dict)):
            report.error(where, "no threshold node, so the area has no way out")

        for index, slot in enumerate(area.get("slots", [])):
            if not isinstance(slot, dict):
                continue
            slot_where = "%s slot %d" % (where, index)
            attach = slot.get("attach")
            # attach becomes side_of on the generated node, and side nodes are
            # gated on their anchor being done -- an anchor that does not exist
            # is a side node that never becomes available.
            if attach is not None and attach not in ids:
                report.error(slot_where, "attach '%s' is not a node in this area" % attach)
            total = sum(float(entry.get("w", 1)) for entry in slot.get("table", [])
                        if isinstance(entry, dict))
            if total <= 0:
                report.error(slot_where, "table weights sum to %g, so AreaGen._pick "
                                         "returns nothing and the slot never rolls" % total)

        # A node nothing points at is not stranded -- it is the opposite.
        # AreaGen.is_available gates a node on its predecessors, and a node with
        # no predecessors has nothing to wait for, so it is walkable the moment
        # you enter. On a threshold that means the exit is open before the room
        # has asked you for anything.
        pointed_at = set()
        for node in nodes:
            if isinstance(node, dict):
                pointed_at.update(node.get("next", []))
        for index, node in enumerate(nodes):
            if not isinstance(node, dict) or index == 0:
                continue
            if node.get("id") not in pointed_at:
                report.error("%s node '%s'" % (where, node.get("id", "?")),
                             "nothing lists it in `next` and it is not the entry node, "
                             "so it has no predecessors to wait for and is available "
                             "from the moment the area opens")


# --- modifiers and hooks -------------------------------------------------------
# Deliberately a structural walk rather than a per-type declaration. Modifiers
# are one vocabulary across rulesets, trinkets, traits, Wheel nodes and Palace
# adjacency, so a new content type that carries them is validated for free
# instead of being validated once somebody remembers to declare it.

def each_named(doc, name):
    if isinstance(doc, dict):
        for key, value in doc.items():
            if key == name:
                yield value
            for found in each_named(value, name):
                yield found
    elif isinstance(doc, list):
        for item in doc:
            for found in each_named(item, name):
                yield found


MODIFIER_KEYS = {"key", "op", "value", "when", "per_level", "_level"}


def modifier_pass(report, docs, schema, readable_keys, config_keys):
    vocab = schema["vocabulary"]
    used = set()
    for rel, doc in docs.items():
        if rel == "data/schema.json":
            continue
        for block in each_named(doc, "modifiers"):
            if not isinstance(block, list):
                report.error(rel, "modifiers must be a list, got %s" % type(block).__name__)
                continue
            for modifier in block:
                if not isinstance(modifier, dict):
                    report.error(rel, "modifier must be an object")
                    continue
                where = "%s [modifier %s]" % (rel, modifier.get("key", "?"))
                for key in modifier:
                    if key not in MODIFIER_KEYS:
                        report.error(where, "unknown modifier key '%s' (allowed: %s)"
                                     % (key, ", ".join(sorted(MODIFIER_KEYS))))
                for required in ("key", "op", "value"):
                    if required not in modifier:
                        report.error(where, "missing required key '%s'" % required)
                if modifier.get("op") not in vocab["ops"]:
                    report.error(where, "op '%s' is not one of: %s"
                                 % (modifier.get("op"), ", ".join(vocab["ops"])))
                for condition in (modifier.get("when") or {}):
                    if condition not in vocab["when_keys"]:
                        report.error(where, "when condition '%s' is not implemented "
                                            "(Rules.passes knows: %s)"
                                     % (condition, ", ".join(vocab["when_keys"])))
                key = modifier.get("key")
                if key is not None:
                    used.add(key)
                    if key not in readable_keys:
                        report.error(where, "no Rules.value() call reads '%s', so this "
                                            "modifier tunes nothing" % key)

        for block in each_named(doc, "hooks"):
            if not isinstance(block, dict):
                report.error(rel, "hooks must be an object")
                continue
            for hook_name, effects in block.items():
                where = "%s [hook %s]" % (rel, hook_name)
                if hook_name not in vocab["hooks"]:
                    report.error(where, "no Rules.hook() call fires '%s', so nothing "
                                        "registered on it ever runs" % hook_name)
                for effect in effects if isinstance(effects, list) else []:
                    if not isinstance(effect, dict):
                        continue
                    if effect.get("type") not in vocab["hook_effects"]:
                        report.error(where, "effect type '%s' is not implemented by "
                                            "Game.apply_effects" % effect.get("type"))

    for key in sorted(config_keys - readable_keys):
        report.warn("data/content/config.json",
                    "'%s' has a base value but no Rules.value() call reads it -- it is "
                    "a tunable that tunes nothing" % key)
    return used


# --- world and tileset ---------------------------------------------------------

def theme_pass(report, docs, schema):
    """Every node type a theme has to draw needs a glyph in that theme.

    Palette.glyph falls back to a middle dot, so a missing one is a node that
    renders as an anonymous blob rather than a crash -- which is why it warns
    rather than errors, and also why nobody has noticed.
    """
    drawn = set(schema["vocabulary"]["node_types"]) | set(schema["vocabulary"]["side_types"])
    for rel, doc in docs_in(docs, "themes"):
        glyphs = doc.get("glyphs", {})
        for node_type in sorted(drawn - set(glyphs)):
            report.warn("%s [theme %s]" % (rel, doc.get("id")),
                        "no glyph for node type '%s'; it draws as the fallback dot"
                        % node_type)
        # Godot's built-in font renders dingbats and geometric shapes as tofu.
        for name, glyph in sorted(glyphs.items()):
            try:
                str(glyph).encode("latin-1")
            except UnicodeEncodeError:
                report.error("%s [theme %s]" % (rel, doc.get("id")),
                             "glyph '%s' is outside Latin-1 and will render as tofu"
                             % name)


def world_pass(report, docs, schema):
    world_path = os.path.join(DATA, "world", "overworld.json")
    tiles_path = os.path.join(ROOT, "assets", "tiles", "tiles.json")
    if not os.path.exists(world_path) or not os.path.exists(tiles_path):
        report.warn("data/world", "world or tileset missing; skipping the prop check")
        return
    with open(world_path, encoding="utf-8") as handle:
        world = json.load(handle)
    with open(tiles_path, encoding="utf-8") as handle:
        tiles = json.load(handle)

    spec = schema["world"]
    for key in spec["required"]:
        if key not in world:
            report.error("data/world/overworld.json", "missing required key '%s'" % key)

    areas = set()
    for _rel, doc in docs_in(docs, "areas"):
        areas.add(doc.get("id"))
    for name in world.get("regions", {}):
        if name not in areas:
            report.error("data/world/overworld.json",
                         "region '%s' names no area" % name)
    for entry in world.get("anomalies", []):
        target = entry.get("area")
        if target is not None and target not in areas:
            report.error("data/world/overworld.json",
                         "anomaly at (%s,%s) points at area '%s', which does not exist"
                         % (entry.get("x"), entry.get("y"), target))

    order = tiles["order"]
    walkable = tiles["walkable"]
    width, height = int(world["w"]), int(world["h"])
    try:
        grid = zlib.decompress(base64.b64decode(world["tiles_b64_deflate"]))
    except Exception as exc:                                  # pragma: no cover
        report.error("data/world/overworld.json", "tiles plane will not decode: %s" % exc)
        return
    if len(grid) != width * height:
        report.error("data/world/overworld.json",
                     "tiles plane is %d bytes, expected %d (w*h)" % (len(grid), width * height))
        return

    # A prop scatters only onto cells that are of its biome, walkable, and not
    # road or doorway -- see scatter_props() in tools/make_world.py. Counting raw
    # cells of the material is not enough: it is what tools/add_prop.py does, and
    # it passes `forest`, which has 8590 cells and is not walkable, so not one
    # forest prop has ever been placed.
    excluded = {order.index(name) for name in spec["scatter_excluded_materials"]
                if name in order}
    placeable = {}
    for material_id, name in enumerate(order):
        if not walkable.get(name, False) or material_id in excluded:
            placeable[name] = 0
        else:
            placeable[name] = grid.count(material_id)

    # Ground truth beats inference. The world file carries the prop plane the
    # generator actually produced, so the honest question is "did this prop get
    # placed", not "does the rule I think it follows allow it". The two diverged
    # the moment road furniture started being offered to cells *beside* a road:
    # the inference said never, the world said fourteen signposts.
    present = set()
    plane = _plane(world, "props_b64_deflate", width * height)
    if plane:
        by_plane = {p["plane"]: p["id"] for p in tiles["props"]["list"]}
        for value in set(plane):
            if value:
                present.add(by_plane.get(value, ""))

    for prop in tiles["props"]["list"]:
        biome = prop["biome"]
        if biome == "placed":
            continue                      # put somewhere on purpose, not scattered
        if biome not in order:
            report.error("assets/tiles/tiles.json",
                         "prop '%s' declares biome '%s', which is not a material"
                         % (prop["id"], biome))
            continue
        if plane and prop["id"] in present:
            continue                      # observed in the world; nothing to say
        if placeable[biome] == 0 or plane:
            total = grid.count(order.index(biome))
            if total == 0:
                reason = "the world contains no %s at all" % biome
            elif not walkable.get(biome, False):
                reason = "%s exists (%d cells) but is not walkable, and scatter_props " \
                         "only places on walkable cells" % (biome, total)
            else:
                reason = "%s exists (%d cells) but scatter_props refuses to place on it" \
                         % (biome, total)
            if plane and placeable[biome] != 0:
                reason = ("%s has %d placeable cells but the generator placed none "
                          "-- density too low, or crowded out" % (biome, placeable[biome]))
            report.warn("assets/tiles/tiles.json",
                        "prop '%s' does not appear in the world: %s" % (prop["id"], reason))


def _plane(world, key, expected):
    """One byte per cell, or None when the key is absent or malformed."""
    raw = world.get(key)
    if not raw:
        return None
    try:
        out = zlib.decompress(base64.b64decode(raw))
    except Exception:
        return None
    return out if len(out) == expected else None


# --- entry point ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as errors")
    parser.add_argument("--quiet", action="store_true",
                        help="print only problems")
    args = parser.parse_args()

    report = Report()
    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    docs = load_data_files()
    vocab = schema["vocabulary"]

    # The schema claims to describe the engine. Check that claim first: every
    # later check trusts these lists.
    game = os.path.join(SCRIPTS, "autoload", "Game.gd")
    rules = os.path.join(SCRIPTS, "autoload", "Rules.gd")
    meta = os.path.join(SCRIPTS, "autoload", "Meta.gd")
    main_gd = os.path.join(SCRIPTS, "Main.gd")

    def arms(path, name):
        body = func_body(path, name)
        return None if body is None else match_arms(body)

    reconcile(report, schema, const_array(rules, "_OP_ORDER"), "ops", "Rules._OP_ORDER")
    reconcile(report, schema, arms(rules, "passes"), "when_keys", "Rules.passes")
    reconcile(report, schema, arms(game, "apply_effects"), "hook_effects", "Game.apply_effects")
    reconcile(report, schema, arms(game, "_apply_spite_effect"), "spite_effects",
              "Game._apply_spite_effect")
    reconcile(report, schema, arms(game, "use_item"), "item_uses", "Game.use_item")
    reconcile(report, schema, arms(meta, "wheel_met"), "wheel_reqs", "Meta.wheel_met")
    reconcile(report, schema, arms(game, "tap_node"), "node_types", "Game.tap_node")
    reconcile(report, schema, arms(game, "_award"), "loot_types", "Game._award")
    reconcile(report, schema, const_dict_keys(main_gd, "SCREENS"), "screens", "Main.SCREENS")

    hook_names = set()
    for path in gd_sources():
        hook_names.update(re.findall(r'Rules\.hook\(\s*"([^"]+)"', read(path)))
    reconcile(report, schema, hook_names, "hooks", "the Rules.hook() call sites")

    id_sets = build_id_sets(docs, schema)
    schema_pass(report, docs, schema, id_sets)
    graph_pass(report, docs)

    dynamic_fields = vocab["dynamic_key_fields"]
    dynamic_keys = set()
    for rel, doc in docs.items():
        if rel == "data/schema.json":
            continue
        for field in dynamic_fields:
            dynamic_keys.update(v for v in each_named(doc, field) if isinstance(v, str))
    readable = scan_rules_keys(report, dynamic_fields, dynamic_keys)
    used = modifier_pass(report, docs, schema, readable, id_sets["config_keys"])

    theme_pass(report, docs, schema)
    world_pass(report, docs, schema)

    # An item `use` is data naming a code path, and the item's `where` decides
    # how bad an unimplemented one is. A "home" or "run" item is used by a button
    # that calls Game.use_item, so a verb missing from that match is a dead
    # button: an error. A "where": "auto" item is applied by code somewhere else
    # entirely, so a missing verb means the feature was never written -- still a
    # bug, but one that needs new code rather than a data edit, so it warns.
    for rel, doc in docs_in(docs, "content"):
        for item in doc.get("items", []):
            if item.get("use") in vocab["item_uses"]:
                continue
            where = "%s [items %s]" % (rel, item.get("id"))
            message = ("use '%s' is not implemented (Game.use_item knows: %s)"
                       % (item.get("use"), ", ".join(vocab["item_uses"])))
            if item.get("where") == "auto":
                report.warn(where, message + " -- the item is on sale and inert")
            else:
                report.error(where, message)

    if not args.quiet:
        print("validate_data: %d files, %d types, %d modifier keys in use, "
              "%d readable keys" % (len(docs), len(schema["types"]), len(used), len(readable)))

    for warning in report.warnings:
        print("WARN  %s" % warning)
    for error in report.errors:
        print("ERROR %s" % error)

    failed = report.errors or (args.strict and report.warnings)
    if failed:
        print("\nFAIL — %d error(s), %d warning(s)" % (len(report.errors), len(report.warnings)))
        return 1
    if not args.quiet:
        print("OK — no errors, %d warning(s)" % len(report.warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
