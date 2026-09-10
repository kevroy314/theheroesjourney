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
    """The lines of `func name(...)`, up to the next top-level declaration.

    `static func` counts. HJLighting is a RefCounted with no instance and every
    function in it is static, so a matcher that only saw plain `func` would
    silently report "could not read" for a file whose arms are right there.
    """
    lines = read(path).splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^(?:static\s+)?func\s+%s\s*\(" % re.escape(name), line):
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


# --- critters ------------------------------------------------------------------
# The state machines that make things move. The generic schema pass checks the
# shape of a record; this checks the graph, which is where the failures are. A
# `to` that names no state is an animal that walks into a state with no goal and
# stands there forever, and it is indistinguishable in play from art direction.

def critter_pass(report, docs, schema):
    vocab = schema["vocabulary"]
    sprites = os.path.join(ROOT, "assets", "sprites")

    known = set()
    for rel, doc in docs_in(docs, "content"):
        for critter in doc.get("critters", []):
            if isinstance(critter, dict) and "id" in critter:
                known.add(critter["id"])
    # Not a schema `refs` entry, deliberately: Content.gd builds its id sets
    # from `runtime` paths and does not merge a `critters` key, so declaring the
    # reference in the schema would make the in-game validator reject every
    # placement on a player's device. Checked here, where the files are.
    for rel, doc in docs_in(docs, "content"):
        for entry in doc.get("interactables", []):
            name = entry.get("critter") if isinstance(entry, dict) else None
            if name is not None and name not in known:
                report.error("%s [interactables %s]" % (rel, entry.get("id")),
                             "critter '%s' names no critter in data/content" % name)

    for rel, doc in docs_in(docs, "content"):
        for critter in doc.get("critters", []):
            if not isinstance(critter, dict):
                continue
            where = "%s [critter %s]" % (rel, critter.get("id"))
            states = critter.get("states") or {}
            if not isinstance(states, dict) or not states:
                report.error(where, "states must be a non-empty object")
                continue

            start = critter.get("start")
            if start not in states:
                report.error(where, "start '%s' is not one of its states: %s"
                             % (start, ", ".join(sorted(states))))

            # The art has to exist. A sprite id that names no sheet is an
            # invisible animal that still blocks a cell and still answers a
            # verb, which reads as a haunting rather than as a missing file.
            sprite = critter.get("sprite")
            if sprite and not os.path.exists(os.path.join(sprites, "%s.png" % sprite)):
                report.error(where, "sprite '%s' has no assets/sprites/%s.png -- "
                             "run tools/make_sprites.py" % (sprite, sprite))

            reached = {start} if start in states else set()
            for i, rule in enumerate(critter.get("transitions") or []):
                if not isinstance(rule, dict):
                    report.error(where, "transition %d must be an object" % i)
                    continue
                spot = "%s transition %d" % (where, i)
                froms = rule.get("from")
                froms = froms if isinstance(froms, list) else [froms]
                for name in froms:
                    if name != "*" and name not in states:
                        report.error(spot, "from '%s' is not one of its states: %s"
                                     % (name, ", ".join(sorted(states))))
                target = rule.get("to")
                if target not in states:
                    report.error(spot, "to '%s' is not one of its states: %s"
                                 % (target, ", ".join(sorted(states))))
                else:
                    reached.add(target)
                for condition in (rule.get("when") or {}):
                    if condition not in vocab["critter_conditions"]:
                        report.error(spot, "when condition '%s' is not implemented "
                                     "(HJCritters._conditions_met knows: %s)"
                                     % (condition, ", ".join(vocab["critter_conditions"])))
                effect = rule.get("effect")
                if isinstance(effect, dict) and effect.get("type") not in vocab["hook_effects"]:
                    report.error(spot, "effect type '%s' is not implemented by "
                                 "Game.apply_effects" % effect.get("type"))

            # A state nothing can transition into is dead data. It warns rather
            # than errors because an author part-way through writing the third
            # state of a machine is a normal thing to be.
            for name in sorted(set(states) - reached):
                report.warn(where, "state '%s' is not the start state and no "
                            "transition leads to it, so it can never run" % name)


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

    # An interactable typed wrong in Tiled is silently invisible in game: the
    # placement is there, nothing in the catalogue matches it, and no affordance
    # ever appears. Exactly the failure mode this tool exists to catch.
    # gather(), not docs_in(): the catalogue is a list inside one file under
    # data/content, not a directory of files the way areas are. docs_in would
    # find nothing and report every placement as untyped, which is a validator
    # that fails loudly about itself.
    kinds = set()
    for _origin, record, _trail in gather(docs, schema["types"]["interactables"]):
        kinds.add(record.get("id"))
    for entry in world.get("interactables", []):
        kind = entry.get("type")
        if kind not in kinds:
            report.error("data/world/overworld.json",
                         "interactable at (%s,%s) is type '%s', which is in no catalogue"
                         % (entry.get("x"), entry.get("y"), kind))

    # The light contract. assets/tiles/tiles.json is where the art says where
    # the lamps are; scripts/ui/Lighting.gd is the only thing that reads it, and
    # it reads it by key. So a misspelt field does not draw a wrong light, it
    # draws no light at all, and a stove that has quietly stopped glowing is the
    # kind of loss nobody notices until somebody asks why the kitchen is dark.
    # BOTH PROP PLANES (#83). `props` is what occupies a cell and `clutter` is
    # what lies on it or sits on the thing standing there; the manifest emits
    # the same contracts on both, so every check below walks both. Checking
    # only `props` would have left the candle's light, the grit's `flat` claim
    # and every clutter entry's biome unchecked the moment they moved plane --
    # a whole catalogue silently outside the validator, which is the exact
    # failure this file exists to remove.
    plane_lists = {name: tiles[name]["list"] for name in ("props", "clutter")
                   if isinstance(tiles.get(name), dict)}
    plane_keys = {"props": "props_b64_deflate", "clutter": "clutter_b64_deflate"}
    every_prop = [(name, entry) for name in ("props", "clutter")
                  for entry in plane_lists.get(name, [])]

    # NOTHING ON THE CLUTTER PLANE MAY BE SOLID. The collision plane is derived
    # from `props` and `cliffs` alone, so a solid clutter entry is a prop that
    # says it stops you and then does not -- and nobody would find that by
    # walking into it, because walking into it works.
    for entry in plane_lists.get("clutter", []):
        if entry.get("solid"):
            report.error("assets/tiles/tiles.json",
                         "clutter '%s' is solid, but the clutter plane never "
                         "reaches the collision plane, so it would block "
                         "nothing while claiming to" % entry["id"])

    spec_light = spec.get("prop_light", {})
    hexcolour = re.compile(r"^#[0-9A-Fa-f]{6}$")
    emitters = set()
    for plane_name, prop in every_prop:
        light = prop.get("light")
        if light is None:
            continue
        # Keyed by (plane, value) because the two planes are numbered
        # independently: props 5 and clutter 5 are different things, and a set
        # of bare integers would say a candle was placed because a bench was.
        emitters.add((plane_name, prop["plane"]))
        where = "%s '%s' light" % (plane_name, prop["id"])
        for key in spec_light.get("required", []):
            if key not in light:
                report.error("assets/tiles/tiles.json",
                             "%s is missing '%s'" % (where, key))
        radius = light.get("radius")
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or radius <= 0:
            report.error("assets/tiles/tiles.json",
                         "%s radius is %r; it must be a number greater than 0"
                         % (where, radius))
        colour = light.get("color")
        if not isinstance(colour, str) or not hexcolour.match(colour):
            report.error("assets/tiles/tiles.json",
                         "%s color is %r; it must be #RRGGBB" % (where, colour))
        flicker = light.get("flicker")
        if isinstance(flicker, bool) or not isinstance(flicker, (int, float)) \
                or not 0.0 <= flicker <= 1.0:
            report.error("assets/tiles/tiles.json",
                         "%s flicker is %r; it must be between 0.0 and 1.0"
                         % (where, flicker))
        # `kind` is optional and defaults to 'lamp', so its failure mode is not
        # a dark prop -- it is a forge that goes out at breakfast, or a street
        # lamp that burns through noon. Silent and wrong rather than silent and
        # absent, which is the worse of the two, so a word the lighting pass
        # cannot resolve is an error and not a warning.
        if "kind" in light:
            kind = light.get("kind")
            if kind not in schema["vocabulary"]["light_kinds"]:
                report.error("assets/tiles/tiles.json",
                             "%s kind is %r; it must be one of %s"
                             % (where, kind,
                                ", ".join(schema["vocabulary"]["light_kinds"])))
        allowed = spec_light.get("required", []) + spec_light.get("optional", [])
        for key in light:
            if key not in allowed:
                report.warn("assets/tiles/tiles.json",
                            "%s carries '%s', which nothing reads" % (where, key))

    # And the same for motion, for the same reason. scripts/ui/Motion.gd reads
    # `sway` by key, so a misspelt field is a prop that has quietly stopped
    # moving -- which is even harder to notice than a lamp going out, because
    # stillness is what everything else is doing.
    spec_sway = spec.get("prop_sway", {})
    movers = set()
    for plane_name, prop in every_prop:
        sway = prop.get("sway")
        if sway is None:
            continue
        movers.add((plane_name, prop["plane"]))
        where = "%s '%s' sway" % (plane_name, prop["id"])
        for key in spec_sway.get("required", []):
            if key not in sway:
                report.error("assets/tiles/tiles.json",
                             "%s is missing '%s'" % (where, key))
        for key in ("amount", "speed"):
            value = sway.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                report.error("assets/tiles/tiles.json",
                             "%s %s is %r; it must be a number greater than 0"
                             % (where, key, value))
        mode = sway.get("mode", "sway")
        if mode not in ("sway", "breathe"):
            report.error("assets/tiles/tiles.json",
                         "%s mode is %r; it must be 'sway' or 'breathe'" % (where, mode))
        allowed = spec_sway.get("required", []) + spec_sway.get("optional", [])
        for key in sway:
            if key not in allowed:
                report.warn("assets/tiles/tiles.json",
                            "%s carries '%s', which nothing reads" % (where, key))

    # And the same for shafts, which have one wrinkle the other two do not: a
    # `shaft` is optics for a hole, and a hole with nothing to see through it is
    # not a thing. `light` is not required beside it -- a gap in a roof is dark
    # at night -- but a shaft whose numbers are nonsense is a window that throws
    # a beam of length nought, which looks exactly like a window that was never
    # given the key at all.
    spec_shaft = spec.get("prop_shaft", {})
    apertures = set()
    for plane_name, prop in every_prop:
        shaft = prop.get("shaft")
        if shaft is None:
            continue
        # A shaft is the optics of a hole in a wall, and a hole in a wall
        # occupies the cell it is in. HJLighting reads `shaft` off the prop
        # plane only, so one declared on clutter would be a window that throws
        # no beam and says nothing about why.
        if plane_name != "props":
            report.error("assets/tiles/tiles.json",
                         "%s '%s' declares a shaft, but only the props plane "
                         "is read for apertures -- a hole in a wall is a thing "
                         "that occupies its cell" % (plane_name, prop["id"]))
        apertures.add(prop["plane"])
        where = "%s '%s' shaft" % (plane_name, prop["id"])
        for key in spec_shaft.get("required", []):
            if key not in shaft:
                report.error("assets/tiles/tiles.json",
                             "%s is missing '%s'" % (where, key))
        for key in ("length", "width"):
            value = shaft.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or value <= 0:
                report.error("assets/tiles/tiles.json",
                             "%s %s is %r; it must be a number greater than 0"
                             % (where, key, value))
        for key in ("spread", "bars"):
            value = shaft.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or value < 0:
                report.error("assets/tiles/tiles.json",
                             "%s %s is %r; it must be a number of 0 or more"
                             % (where, key, value))
        if "color" in shaft:
            colour = shaft.get("color")
            if not isinstance(colour, str) or not hexcolour.match(colour):
                report.error("assets/tiles/tiles.json",
                             "%s color is %r; it must be #RRGGBB" % (where, colour))
        if "intensity" in shaft:
            value = shaft.get("intensity")
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not 0.0 <= value <= 1.0:
                report.error("assets/tiles/tiles.json",
                             "%s intensity is %r; it must be between 0.0 and 1.0"
                             % (where, value))
        allowed = spec_shaft.get("required", []) + spec_shaft.get("optional", [])
        for key in shaft:
            if key not in allowed:
                report.warn("assets/tiles/tiles.json",
                            "%s carries '%s', which nothing reads" % (where, key))

    # The flat contract. A prop's `flat` says it is texture lying on the ground
    # rather than a thing standing up off it, and scatter_props() in
    # tools/make_world.py reads it to decide what may be placed in a lane the
    # player walks down. So a prop that claims to be flat AND solid is asking
    # for an invisible boulder in the middle of a road, and a `flat` that is not
    # a boolean reads as truthy for any non-empty value -- which puts a tree in
    # the lane on a typo. Both are errors rather than warnings for that reason.
    for plane_name, prop in every_prop:
        if "flat" not in prop:
            continue
        where = "%s '%s'" % (plane_name, prop["id"])
        if not isinstance(prop["flat"], bool):
            report.error("assets/tiles/tiles.json",
                         "%s flat is %r; it must be true or false"
                         % (where, prop["flat"]))
        elif prop["flat"] and prop.get("solid"):
            report.error("assets/tiles/tiles.json",
                         "%s is both flat and solid. Flat means it lies on the "
                         "ground and the player walks over it, which is the one "
                         "thing a solid prop cannot do." % where)

    # An aperture nothing ever places throws no light anywhere. The same is not
    # worth saying about a lamp -- a lamppost with a density scatters itself --
    # but every aperture so far is hand-placed on a wall, so one that appears in
    # no world is a declaration that does nothing and will go on doing nothing.
    if apertures:
        planes = zlib.decompress(base64.b64decode(world["props_b64_deflate"]))
        standing = set(planes)
        for prop in tiles["props"]["list"]:
            if prop["plane"] in apertures and prop["plane"] not in standing:
                report.warn("assets/tiles/tiles.json",
                            "prop '%s' declares a shaft and stands nowhere in "
                            "the world" % prop["id"])

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

    # A prop scatters only onto cells that are of its biome, walkable, and not a
    # doorway or a bridge -- see scatter_props() in tools/make_world.py. Counting
    # raw cells of the material is not enough: it is what tools/add_prop.py does,
    # and it passes `forest`, which has 8590 cells and is not walkable, so not
    # one forest prop has ever been placed.
    #
    # And a road is excluded for SOME props and not others, which is why there
    # are two counts and not one. A prop marked `flat` is texture lying on the
    # ground -- grit, a rut, fallen leaves -- and a lane takes it; anything that
    # stands up off the ground does not go in a lane the player walks down. With
    # a single count this pass could not tell "declares path_dirt and can never
    # appear" from "declares path_dirt and appears on every lane in the vale",
    # and it warned about the second.
    excluded = {order.index(name) for name in spec["scatter_excluded_materials"]
                if name in order}
    standing_excluded = excluded | {
        order.index(name)
        for name in spec.get("scatter_excluded_standing_materials", [])
        if name in order}

    def placeable_on(name, flat):
        material_id = order.index(name)
        if not walkable.get(name, False):
            return 0
        if material_id in (excluded if flat else standing_excluded):
            return 0
        return grid.count(material_id)

    placeable = {name: placeable_on(name, False) for name in order}
    placeable_flat = {name: placeable_on(name, True) for name in order}

    # Ground truth beats inference. The world file carries the prop plane the
    # generator actually produced, so the honest question is "did this prop get
    # placed", not "does the rule I think it follows allow it". The two diverged
    # the moment road furniture started being offered to cells *beside* a road:
    # the inference said never, the world said fourteen signposts.
    # Per plane, because a byte only means something against the catalogue it
    # indexes. The scatter now writes standing props to `props` and ground
    # texture to `clutter`, so reading the grit's plane id out of the props
    # plane would report every scatter member as never placed.
    present = set()
    decoded = {}
    for name, key in plane_keys.items():
        bytes_ = _plane(world, key, width * height)
        decoded[name] = bytes_
        if not bytes_:
            continue
        by_plane = {p["plane"]: p["id"] for p in plane_lists.get(name, [])}
        for value in set(bytes_):
            if value:
                present.add((name, by_plane.get(value, "")))

    for plane_name, prop in every_prop:
        biome = prop["biome"]
        if biome == "placed":
            continue                      # put somewhere on purpose, not scattered
        if biome not in order:
            report.error("assets/tiles/tiles.json",
                         "prop '%s' declares biome '%s', which is not a material"
                         % (prop["id"], biome))
            continue
        if decoded.get(plane_name) and (plane_name, prop["id"]) in present:
            continue                      # observed in the world; nothing to say
        room = (placeable_flat if prop.get("flat") else placeable)[biome]
        seen_plane = decoded.get(plane_name)
        if room == 0 or seen_plane:
            total = grid.count(order.index(biome))
            if total == 0:
                reason = "the world contains no %s at all" % biome
            elif not walkable.get(biome, False):
                reason = "%s exists (%d cells) but is not walkable, and scatter_props " \
                         "only places on walkable cells" % (biome, total)
            elif prop.get("flat"):
                reason = "%s exists (%d cells) but scatter_props refuses to place on it" \
                         % (biome, total)
            else:
                reason = ("%s exists (%d cells) but this prop stands up off the "
                          "ground, and scatter_props keeps everything but flat "
                          "texture out of a lane" % (biome, total))
            if seen_plane and room != 0:
                reason = ("%s has %d placeable cells but the generator placed none "
                          "-- density too low, or crowded out" % (biome, room))
            report.warn("assets/tiles/tiles.json",
                        "%s '%s' does not appear in the world: %s"
                        % (plane_name, prop["id"], reason))

    # A declared light nobody ever placed lights nothing. Checking the placement
    # as well as the declaration is the same argument as the prop check above:
    # ground truth is the plane the generator produced, not the rule it follows.
    lit_somewhere = set()
    for name, bytes_ in decoded.items():
        for value in set(bytes_ or b""):
            if value:
                lit_somewhere.add((name, value))
    if emitters and lit_somewhere and not (emitters & lit_somewhere):
        report.warn("data/world/overworld.json",
                    "%d props declare a light and not one of them is placed "
                    "anywhere in the world" % len(emitters))

    # THE CLUTTER PLANE NEVER BLOCKS, PROVED AGAINST THE WORLD AND NOT ONLY
    # AGAINST THE CATALOGUE (#83). derive_blocked() is handed `props` and
    # `cliffs` and never `clutter`, so this can only fail if that changes --
    # which is exactly when it should be caught, because the symptom would be
    # an invisible wall on a cell with a cup on it.
    blocked = _plane(world, "blocked_b64_deflate", width * height)
    clutter_plane = decoded.get("clutter")
    props_plane = decoded.get("props")
    cliffs_plane = _plane(world, "cliffs_b64_deflate", width * height)
    if blocked and clutter_plane and props_plane and cliffs_plane:
        solid_planes = {p["plane"] for p in plane_lists.get("props", [])
                        if p.get("solid")}
        # A solid prop blocks its whole foot, which grows north, so a cell can
        # be blocked by a prop anchored up to `foot[1]-1` rows south of it.
        reach_north = max([p["foot"][1] for p in plane_lists.get("props", [])
                           if p.get("solid")] or [1])
        stray = 0
        for i, value in enumerate(blocked):
            if not value or cliffs_plane[i]:
                continue
            x, y = i % width, i // width
            if any(props_plane[(y + dy) * width + x] in solid_planes
                   for dy in range(reach_north) if y + dy < height):
                continue
            stray += 1
        if stray:
            report.error("data/world/overworld.json",
                         "%d blocked cell(s) are explained by neither a cliff "
                         "nor a solid prop. The clutter plane must never reach "
                         "collision -- see derive_blocked()." % stray)


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
    # Node outcomes and item verbs moved out of Game when it was split up. The
    # vocabulary checks below name a file and a function, so a move that is not
    # mirrored here turns every arm into a false "not implemented" -- which is
    # what happened, loudly, the first time this ran after the split.
    outcomes = os.path.join(SCRIPTS, "game", "Outcomes.gd")
    items_gd = os.path.join(SCRIPTS, "game", "Items.gd")

    def arms(path, name):
        body = func_body(path, name)
        return None if body is None else match_arms(body)

    reconcile(report, schema, const_array(rules, "_OP_ORDER"), "ops", "Rules._OP_ORDER")
    reconcile(report, schema, arms(rules, "passes"), "when_keys", "Rules.passes")
    reconcile(report, schema, arms(game, "apply_effects"), "hook_effects", "Game.apply_effects")
    reconcile(report, schema, arms(outcomes, "_apply_spite_effect"), "spite_effects",
              "HJOutcomes._apply_spite_effect")
    reconcile(report, schema, arms(items_gd, "use"), "item_uses", "HJItems.use")
    # A confirm gesture named in data that no class implements is a task the
    # player cannot finish, and the schema cannot see the registry on its own.
    gestures = os.path.join(SCRIPTS, "game", "Gestures.gd")
    reconcile(report, schema, const_dict_keys(gestures, "KINDS"),
              "confirm_kinds", "HJGestures.KINDS")
    reconcile(report, schema, arms(meta, "wheel_met"), "wheel_reqs", "Meta.wheel_met")
    reconcile(report, schema, arms(game, "tap_node"), "node_types", "Game.tap_node")
    reconcile(report, schema, arms(outcomes, "_award"), "loot_types", "HJOutcomes._award")
    reconcile(report, schema, const_dict_keys(main_gd, "SCREENS"), "screens", "Main.SCREENS")
    # Dialogue lines, dialogue replies and objective rewards all carry effects,
    # and Objectives.apply_effects is the single implementation -- three of its
    # arms delegate to Game.apply_effects rather than paying a second way.
    objectives_gd = os.path.join(SCRIPTS, "autoload", "Objectives.gd")
    reconcile(report, schema, arms(objectives_gd, "apply_effects"), "story_effects",
              "Objectives.apply_effects")

    hook_names = set()
    for path in gd_sources():
        hook_names.update(re.findall(r'Rules\.hook\(\s*"([^"]+)"', read(path)))
    reconcile(report, schema, hook_names, "hooks", "the Rules.hook() call sites")

    # The animals. Three vocabularies, all read out of the one file that
    # implements them, so data can never name a goal or a condition the state
    # machine does not have.
    critters_gd = os.path.join(SCRIPTS, "game", "Critters.gd")
    reconcile(report, schema, arms(critters_gd, "_step_for"), "critter_goals",
              "HJCritters._step_for")
    reconcile(report, schema, arms(critters_gd, "_conditions_met"), "critter_conditions",
              "HJCritters._conditions_met")
    reconcile(report, schema, const_array(critters_gd, "EVENTS"), "critter_events",
              "HJCritters.EVENTS")

    # The light kinds. A prop declares WHEN its light burns by naming one of
    # these in assets/tiles/tiles.json, and HJLighting.gain_for() is the only
    # thing that knows what a name means -- so a word in the schema with no arm
    # behind it is a lamp that silently falls back to being some other lamp,
    # and an arm with no word in the schema is a behaviour the art is forbidden
    # to ask for. Both directions matter, which is what reconcile() is for.
    lighting_gd = os.path.join(SCRIPTS, "ui", "Lighting.gd")
    reconcile(report, schema, arms(lighting_gd, "gain_for"), "light_kinds",
              "HJLighting.gain_for")

    id_sets = build_id_sets(docs, schema)
    schema_pass(report, docs, schema, id_sets)
    graph_pass(report, docs)
    critter_pass(report, docs, schema)

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
    # that calls HJItems.use, so a verb missing from that match is a dead
    # button: an error. A "where": "auto" item is applied by code somewhere else
    # entirely, so a missing verb means the feature was never written -- still a
    # bug, but one that needs new code rather than a data edit, so it warns.
    for rel, doc in docs_in(docs, "content"):
        for item in doc.get("items", []):
            if item.get("use") in vocab["item_uses"]:
                continue
            where = "%s [items %s]" % (rel, item.get("id"))
            message = ("use '%s' is not implemented (HJItems.use knows: %s)"
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
