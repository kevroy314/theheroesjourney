extends Node
## Loads everything under res://data/ into memory. Drop a new .json into the
## right folder and it is picked up on next launch — no code change required.

const DATA_ROOT := "res://data"
## The declarative shape of everything under data/, shared with
## tools/validate_data.py. See validate() at the bottom of this file.
const SCHEMA_PATH := "res://data/schema.json"

var themes: Dictionary = {}       ## id -> theme
var rulesets: Dictionary = {}     ## id -> ruleset
var movements: Dictionary = {}    ## id -> movement (with "pack" stamped on)
var packs: Dictionary = {}        ## id -> pack meta
var pack_order: Array = []
var areas: Dictionary = {}        ## id -> area definition
var echoes: Array = []            ## ordered story fragments
var echo_reveals: Dictionary = {}
var trinkets: Dictionary = {}
var items: Dictionary = {}
var item_order: Array = []
var loot: Dictionary = {}
var upgrades: Array = []
var achievements: Dictionary = {}
var spite: Dictionary = {}
var rooms: Array = []
## Anomaly templates, the roguelite content. Keyed by nothing — picked by tier
## and weight at the moment you step into one.
var anomalies: Array = []
var palace: Dictionary = {}
var config: Dictionary = {}

var _loaded := false

## Ids that collided while merging. Nothing else can see these: Content merges
## by top-level key and the second definition simply overwrites the first, so by
## the time anyone reads `trinkets` the duplicate is gone without a trace.
var _collisions: Array[String] = []


func _ready() -> void:
	load_all()


func load_all() -> void:
	if _loaded:
		return
	_loaded = true

	for file_name in list_json(DATA_ROOT + "/themes"):
		var t: Variant = read_json(DATA_ROOT + "/themes/" + file_name)
		if t is Dictionary and t.has("id"):
			_claim(themes, String(t["id"]), "theme")
			themes[t["id"]] = t

	for file_name in list_json(DATA_ROOT + "/rulesets"):
		var r: Variant = read_json(DATA_ROOT + "/rulesets/" + file_name)
		if r is Dictionary and r.has("id"):
			_claim(rulesets, String(r["id"]), "ruleset")
			rulesets[r["id"]] = r

	for file_name in list_json(DATA_ROOT + "/areas"):
		var a: Variant = read_json(DATA_ROOT + "/areas/" + file_name)
		if a is Dictionary and a.has("id"):
			_claim(areas, String(a["id"]), "area")
			areas[a["id"]] = a

	for file_name in list_json(DATA_ROOT + "/movements"):
		var doc: Variant = read_json(DATA_ROOT + "/movements/" + file_name)
		if not (doc is Dictionary):
			continue
		if doc.has("pack"):
			_add_pack(doc["pack"], doc.get("movements", []))
		for group in doc.get("packs", []):
			_add_pack(group.get("pack", {}), group.get("movements", []))

	for file_name in list_json(DATA_ROOT + "/echoes"):
		var doc: Variant = read_json(DATA_ROOT + "/echoes/" + file_name)
		if doc is Dictionary:
			echoes.append_array(doc.get("echoes", []))
			echo_reveals.merge(doc.get("reveals", {}), true)
	echoes.sort_custom(func(a, b): return int(a.get("order", 0)) < int(b.get("order", 0)))

	for file_name in list_json(DATA_ROOT + "/content"):
		var doc: Variant = read_json(DATA_ROOT + "/content/" + file_name)
		if not (doc is Dictionary):
			continue
		if doc.has("config"):
			config.merge(doc["config"], true)
		if doc.has("upgrades"):
			upgrades.append_array(doc["upgrades"])
		if doc.has("loot"):
			loot.merge(doc["loot"], true)
		if doc.has("spite"):
			spite = doc["spite"]
		if doc.has("rooms"):
			rooms.append_array(doc["rooms"])
		if doc.has("anomalies"):
			anomalies.append_array(doc["anomalies"])
		if doc.has("palace"):
			palace.merge(doc["palace"], true)
		if doc.has("axes"):
			achievements = doc
		for t in doc.get("trinkets", []):
			_claim(trinkets, String(t["id"]), "trinket")
			trinkets[t["id"]] = t
		for i in doc.get("items", []):
			_claim(items, String(i["id"]), "item")
			items[i["id"]] = i
			if not item_order.has(i["id"]):
				item_order.append(i["id"])

	# Cheapest first, so the free starter pack heads the list in Camp.
	pack_order.sort_custom(func(a, b): return int(packs[a].get("cost", 0)) < int(packs[b].get("cost", 0)))

	if themes.is_empty() or areas.is_empty():
		push_error("Content: data failed to load from %s" % DATA_ROOT)

	_report(validate())


## Records a duplicate id without changing what load_all does about it — later
## still wins, exactly as before. The point is only that it stops being silent.
func _claim(bucket: Dictionary, id: String, kind: String) -> void:
	if bucket.has(id):
		_collisions.append(("%s '%s' is defined twice; the later file wins and the "
			+ "first definition is gone") % [kind, id])


func _add_pack(pack: Dictionary, movement_list: Array) -> void:
	if pack.is_empty():
		return
	_claim(packs, String(pack["id"]), "pack")
	packs[pack["id"]] = pack
	if not pack_order.has(pack["id"]):
		pack_order.append(pack["id"])
	for m in movement_list:
		var movement: Dictionary = (m as Dictionary).duplicate(true)
		movement["pack"] = pack["id"]
		_claim(movements, String(movement["id"]), "movement")
		movements[movement["id"]] = movement


# --- lookups -------------------------------------------------------------------

func base(key: String, fallback: float = 0.0) -> float:
	return float(config.get(key, fallback))


func theme(id: String) -> Dictionary:
	return themes.get(id, {})


func ruleset(id: String) -> Dictionary:
	return rulesets.get(id, {})


func movement(id: String) -> Dictionary:
	return movements.get(id, {})


func area(id: String) -> Dictionary:
	return areas.get(id, {})


func echo(id: String) -> Dictionary:
	for e in echoes:
		if e.get("id", "") == id:
			return e
	return {}


func item(id: String) -> Dictionary:
	return items.get(id, {})


func room(id: String) -> Dictionary:
	for r in rooms:
		if r.get("id", "") == id:
			return r
	return {}


## Every movement on an axis that the player has unlocked.
func unlocked_movements(axis: String = "") -> Array:
	var out: Array = []
	for id in movements.keys():
		var m: Dictionary = movements[id]
		if axis != "" and String(m.get("axis", "")) != axis:
			continue
		if Meta.pack_unlocked(String(m.get("pack", "starter"))):
			out.append(m)
	out.sort_custom(func(a, b): return String(a.get("name", "")) < String(b.get("name", "")))
	return out


func axes() -> Array:
	return achievements.get("axes", [])


func axis_name(id: String) -> String:
	for a in axes():
		if a.get("id", "") == id:
			return String(a.get("name", id))
	return id.capitalize()


# --- file helpers --------------------------------------------------------------
# Godot imports .json as a JSON resource, so exported builds must go through
# load(). Source checkouts and hand-dropped files fall back to raw file reads.

static func read_json(path: String) -> Variant:
	if ResourceLoader.exists(path):
		var res: Variant = load(path)
		if res is JSON:
			return (res as JSON).data
	if FileAccess.file_exists(path):
		return JSON.parse_string(FileAccess.get_file_as_string(path))
	push_warning("Content: could not read %s" % path)
	return null


## Lists .json files in a directory, normalising the .remap / .import suffixes
## that show up inside exported builds.
static func list_json(dir_path: String) -> Array:
	var out: Array = []
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return out
	for f in dir.get_files():
		var entry := f
		if entry.ends_with(".remap"):
			entry = entry.trim_suffix(".remap")
		elif entry.ends_with(".import"):
			entry = entry.trim_suffix(".import")
		if entry.ends_with(".json") and not out.has(entry):
			out.append(entry)
	out.sort()
	return out


## An anomaly template for a ring.
##
## Near town the distribution is narrow and easy; further out it widens as well
## as hardens, because the owner's brief was that anomalies close to town are
## "more predictable" — so variance is part of the difficulty, not just the mean.
## A tier with no templates of its own borrows from the nearest band below it
## rather than failing, so adding a tier to the world cannot strand a spawn.
func anomaly_for(tier: int, rng: RandomNumberGenerator) -> Dictionary:
	var spread := 0 if tier <= 1 else (1 if tier == 2 else 2)
	var pool: Array = []
	var total := 0
	for entry in anomalies:
		var t := int(entry.get("tier", 0))
		if t > tier or t < tier - spread:
			continue
		var weight := maxi(1, int(entry.get("weight", 1)))
		# Nearer the player's tier is likelier, so the spread widens the tail
		# rather than flattening the whole distribution.
		weight *= maxi(1, 3 - (tier - t))
		pool.append({"entry": entry, "weight": weight})
		total += weight
	if pool.is_empty():
		return anomalies[0] if anomalies.size() > 0 else {}
	var roll := rng.randi_range(0, total - 1)
	for option in pool:
		roll -= int(option["weight"])
		if roll < 0:
			return option["entry"]
	return pool[pool.size() - 1]["entry"]


# --- validation ----------------------------------------------------------------
# Checks the merged runtime view against res://data/schema.json.
#
# This is the half of the schema check that runs *inside the game*, and it is
# here rather than in the build tool for two reasons. It sees what actually
# loaded — packs stamped onto movements, files merged by top-level key, an id
# defined twice and silently overwritten — which the files on disk do not show.
# And it ships, so a hand-dropped .json on a device is checked the same way a
# checked-in one is.
#
# What it deliberately does *not* do is the source scan: whether any
# Rules.value() call actually reads a modifier key is a question about
# GDScript, and the source is not in the export. tools/validate_data.py owns
# that, and CI runs it. See docs/DATA.md.
#
# Loud in the editor, tolerant on a player's device: _report() pushes errors
# from a source checkout (where you can fix the file) and only prints from an
# exported build (where the player cannot). SelfTest turns the same list into
# test failures, which is what makes ./test.sh and CI fail.

## Keys a modifier may carry. Shared vocabulary: rulesets, trinkets, traits,
## Wheel nodes and Palace adjacency all use it, so a typo here is a rule that
## quietly does nothing everywhere at once.
const MODIFIER_KEYS := ["key", "op", "value", "when", "per_level", "_level"]

var _schema: Dictionary = {}


func schema() -> Dictionary:
	if _schema.is_empty():
		var parsed: Variant = read_json(SCHEMA_PATH)
		if parsed is Dictionary:
			_schema = parsed
	return _schema


## Every problem with the loaded content, as human-readable lines. Empty is good.
func validate() -> Array[String]:
	var problems: Array[String] = []
	problems.append_array(_collisions)

	var doc := schema()
	if doc.is_empty():
		problems.append("schema: %s is missing or unreadable, so nothing was checked"
			% SCHEMA_PATH)
		return problems

	var vocab: Dictionary = doc.get("vocabulary", {})
	var id_sets := _build_id_sets(doc)
	for type_name in doc.get("types", {}).keys():
		var spec: Dictionary = doc["types"][type_name]
		for pair in _records(spec):
			_check_record(problems, "%s %s" % [type_name, pair["label"]], spec, vocab,
				pair["record"], id_sets)

	_check_graphs(problems)
	_check_modifiers(problems, vocab)
	return problems


func _report(problems: Array[String]) -> void:
	if problems.is_empty():
		return
	# A player cannot fix our data file, so a shipped build says its piece to the
	# log and carries on. A source checkout — editor, headless self-test — gets
	# real errors, because there the file is one edit away.
	var loud := OS.has_feature("editor")
	for problem in problems:
		if loud:
			push_error("Content: %s" % problem)
		else:
			print("Content: content check — %s" % problem)
	if not loud:
		print("Content: %d content problem(s); continuing anyway" % problems.size())


# --- schema plumbing -----------------------------------------------------------

## One step of the locator grammar documented in data/schema.json. Handles the
## Content node itself so a runtime path's first segment can name a property.
static func _field(container: Variant, name: String) -> Variant:
	if container is Dictionary:
		return (container as Dictionary).get(name, null)
	if container is Object:
		return (container as Object).get(name)
	return null


## Every value a dotted runtime path selects, paired with the id trail that
## reached it — "a_wound > c" is actionable, "c" is a search.
func _walk(path: String) -> Array:
	var current: Array = [{"value": self, "trail": PackedStringArray()}]
	for segment in path.split("."):
		var expand := ""
		if segment.ends_with("[]"):
			segment = segment.substr(0, segment.length() - 2)
			expand = "list"
		elif segment.ends_with("{}"):
			segment = segment.substr(0, segment.length() - 2)
			expand = "dict"
		var next_step: Array = []
		for entry in current:
			var value: Variant = _field(entry["value"], segment) if segment != "" else entry["value"]
			if value == null:
				continue
			var trail: PackedStringArray = entry["trail"].duplicate()
			var owner: Variant = entry["value"]
			if owner is Dictionary and (owner as Dictionary).has("id"):
				trail.append(str((owner as Dictionary)["id"]))
			match expand:
				"list":
					for item in (value as Array):
						next_step.append({"value": item, "trail": trail})
				"dict":
					for key in (value as Dictionary).keys():
						var sub := trail.duplicate()
						sub.append(String(key))
						next_step.append({"value": (value as Dictionary)[key], "trail": sub})
				_:
					next_step.append({"value": value, "trail": trail})
		current = next_step
	return current


## Records of one schema type, each as { record, label }.
func _records(spec: Dictionary) -> Array:
	var out: Array = []
	for path in spec.get("runtime", []):
		for entry in _walk(String(path)):
			var trail: PackedStringArray = entry["trail"]
			var record: Variant = entry["value"]
			if record is Dictionary and (record as Dictionary).has("id"):
				var own := str((record as Dictionary)["id"])
				if trail.is_empty() or trail[trail.size() - 1] != own:
					trail.append(own)
			out.append({"record": record, "label": "?" if trail.is_empty() else " > ".join(trail)})
	return out


func _build_id_sets(doc: Dictionary) -> Dictionary:
	var sets: Dictionary = {}
	for type_name in doc.get("types", {}).keys():
		var spec: Dictionary = doc["types"][type_name]
		var space := String(spec.get("id_space", type_name))
		if not sets.has(space):
			sets[space] = {}
		for pair in _records(spec):
			var record: Variant = pair["record"]
			if record is Dictionary and (record as Dictionary).has("id"):
				sets[space][str((record as Dictionary)["id"])] = true
	sets["loot"] = {}
	for key in loot.keys():
		sets["loot"][str(key)] = true
	sets["config_keys"] = {}
	for key in config.keys():
		sets["config_keys"][str(key)] = true
	return sets


func _check_record(problems: Array[String], where: String, spec: Dictionary,
		vocab: Dictionary, record: Variant, id_sets: Dictionary) -> void:
	if not (record is Dictionary):
		problems.append("%s: expected an object" % where)
		return
	var data: Dictionary = record

	var allowed: Dictionary = {}
	for key in spec.get("required", []):
		allowed[key] = true
		if not data.has(key):
			problems.append("%s: missing required key '%s'" % [where, key])
	for key in spec.get("optional", []):
		allowed[key] = true
	# The check that earns its keep: "whn" is only an error because unknown keys
	# are errors. Leading underscore is documentation (_comment and friends).
	for key in data.keys():
		var name := String(key)
		if not name.begins_with("_") and not allowed.has(name):
			problems.append("%s: unknown key '%s'" % [where, name])

	for field in spec.get("enum", {}).keys():
		if not data.has(field):
			continue
		var words: Array = vocab.get(String(spec["enum"][field]), [])
		var extra: Array = spec.get("enum_extra", {}).get(field, [])
		if not words.has(data[field]) and not extra.has(data[field]):
			problems.append("%s: %s '%s' is not one of: %s"
				% [where, field, str(data[field]), ", ".join(PackedStringArray(words))])

	for field in spec.get("refs", {}).keys():
		if not data.has(field):
			continue
		var set_name := String(spec["refs"][field])
		var wanted: Array = data[field] if data[field] is Array else [data[field]]
		for value in wanted:
			if not (id_sets.get(set_name, {}) as Dictionary).has(str(value)):
				problems.append("%s: %s '%s' names no known %s"
					% [where, field, str(value), set_name])

	for field in spec.get("key_refs", {}).keys():
		var set_name := String(spec["key_refs"][field])
		for key in (data.get(field, {}) as Dictionary).keys():
			if not (id_sets.get(set_name, {}) as Dictionary).has(str(key)):
				problems.append("%s: %s has an entry for '%s', which names no known %s"
					% [where, field, str(key), set_name])

	# A movement or units field takes a literal id or an authoring token. An
	# unrecognised token fails soft — int("$one") is 0 — which is the exact kind
	# of silence this pass exists to end.
	for field in spec.get("token_ref", {}).keys():
		if not (data.get(field, null) is String):
			continue
		var value := String(data[field])
		if value.begins_with("$"):
			if (vocab.get("movement_tokens", []) as Array).has(value):
				continue
			var matched := false
			for prefix in vocab.get("movement_token_prefixes", []):
				if value.begins_with(String(prefix)):
					matched = true
					var axis := value.split(":", true, 1)[1] if value.contains(":") else ""
					if not (id_sets.get("axes", {}) as Dictionary).has(axis):
						problems.append("%s: %s '%s' names no known axis" % [where, field, value])
			if not matched:
				problems.append("%s: %s '%s' is not a movement token" % [where, field, value])
		elif not (id_sets.get(String(spec["token_ref"][field]), {}) as Dictionary).has(value):
			problems.append("%s: %s '%s' names no known %s"
				% [where, field, value, String(spec["token_ref"][field])])

	for field in spec.get("token_enum", {}).keys():
		if data.get(field, null) is String:
			var words: Array = vocab.get(String(spec["token_enum"][field]), [])
			if not words.has(data[field]):
				problems.append("%s: %s '%s' is not a token (%s) and is not a number"
					% [where, field, String(data[field]), ", ".join(PackedStringArray(words))])

	if spec.has("req_type_vocab"):
		var req_type: Variant = (data.get("req", {}) as Dictionary).get("type", "")
		if not (vocab.get(String(spec["req_type_vocab"]), []) as Array).has(req_type):
			problems.append("%s: req.type '%s' is not implemented" % [where, str(req_type)])

	if spec.has("effect_vocab"):
		var effect_type: Variant = (data.get("effect", {}) as Dictionary).get("type", "")
		if not (vocab.get(String(spec["effect_vocab"]), []) as Array).has(effect_type):
			problems.append("%s: effect.type '%s' is not implemented" % [where, str(effect_type)])


# --- graph integrity -----------------------------------------------------------
# Areas and anomalies are the same shape, so they get the same check. This is the
# class of bug the self-test can only find by happening to walk the broken edge.

func _check_graphs(problems: Array[String]) -> void:
	var graphs: Array = []
	for id in areas.keys():
		graphs.append(areas[id])
	graphs.append_array(anomalies)

	for area_def in graphs:
		var where := "area %s" % str((area_def as Dictionary).get("id", "?"))
		var nodes: Array = (area_def as Dictionary).get("nodes", [])
		var ids: Dictionary = {}
		var pointed_at: Dictionary = {}
		for n in nodes:
			ids[str((n as Dictionary).get("id", ""))] = true
		for n in nodes:
			var node: Dictionary = n
			for target in node.get("next", []):
				pointed_at[str(target)] = true
				if not ids.has(str(target)):
					problems.append("%s node '%s': next names '%s', which is not a node here"
						% [where, str(node.get("id", "?")), str(target)])
			if bool(node.get("exclusive_next", false)) and (node.get("next", []) as Array).size() < 2:
				problems.append(("%s node '%s': exclusive_next with fewer than two next "
					+ "entries closes nothing") % [where, str(node.get("id", "?"))])

		var has_threshold := false
		for n in nodes:
			if String((n as Dictionary).get("type", "")) == "threshold":
				has_threshold = true
		if not nodes.is_empty() and not has_threshold:
			problems.append("%s: no threshold node, so the area has no way out" % where)

		for i in range(nodes.size()):
			if i == 0:
				continue
			var id := str((nodes[i] as Dictionary).get("id", "?"))
			# Not stranded — the opposite. AreaGen.is_available gates a node on
			# its predecessors, so a node nobody points at has nothing to wait
			# for and is walkable the moment the area opens.
			if not pointed_at.has(id):
				problems.append(("%s node '%s': nothing lists it in `next`, so it has no "
					+ "predecessors to wait for and is available immediately") % [where, id])

		for i in range((area_def as Dictionary).get("slots", []).size()):
			var slot: Dictionary = area_def["slots"][i]
			var attach := String(slot.get("attach", ""))
			# attach becomes side_of on the generated node, and a side node is
			# gated on its anchor being done — an anchor that does not exist is
			# a side node that never becomes available.
			if attach != "" and not ids.has(attach):
				problems.append("%s slot %d: attach '%s' is not a node here"
					% [where, i, attach])
			var total := 0.0
			for entry in slot.get("table", []):
				total += float((entry as Dictionary).get("w", 1))
			if total <= 0.0:
				problems.append(("%s slot %d: table weights sum to %.2f, so AreaGen._pick "
					+ "returns nothing and the slot never rolls") % [where, i, total])


# --- modifiers and hooks -------------------------------------------------------
# A structural walk rather than a per-type declaration, deliberately: modifiers
# are one vocabulary shared by rulesets, trinkets, traits, Wheel nodes and Palace
# adjacency, so a new kind of content that carries them is checked for free
# instead of whenever somebody remembers to declare it.

func _check_modifiers(problems: Array[String], vocab: Dictionary) -> void:
	# Roots come from the schema's runtime paths rather than a hand-written list,
	# so a content type someone adds to data/schema.json gets its modifiers
	# walked without anyone remembering to add it here as well.
	var roots: Dictionary = {}
	for type_name in schema().get("types", {}).keys():
		for path in schema()["types"][type_name].get("runtime", []):
			var head := String(path).split(".")[0]
			roots[head.trim_suffix("[]").trim_suffix("{}")] = true
	for name in roots.keys():
		_walk_modifiers(problems, vocab, get(String(name)))


func _walk_modifiers(problems: Array[String], vocab: Dictionary, node: Variant) -> void:
	if node is Array:
		for item in (node as Array):
			_walk_modifiers(problems, vocab, item)
		return
	if not (node is Dictionary):
		return
	var data: Dictionary = node
	for m in data.get("modifiers", []):
		var modifier: Dictionary = m
		var where := "modifier %s" % str(modifier.get("key", "?"))
		for key in modifier.keys():
			if not MODIFIER_KEYS.has(String(key)):
				problems.append("%s: unknown modifier key '%s'" % [where, String(key)])
		for required in ["key", "op", "value"]:
			if not modifier.has(required):
				problems.append("%s: missing required key '%s'" % [where, required])
		if not (vocab.get("ops", []) as Array).has(modifier.get("op", "")):
			problems.append("%s: op '%s' is not one of: %s"
				% [where, str(modifier.get("op", "")),
					", ".join(PackedStringArray(vocab.get("ops", [])))])
		for condition in (modifier.get("when", {}) as Dictionary).keys():
			if not (vocab.get("when_keys", []) as Array).has(String(condition)):
				problems.append("%s: when condition '%s' is not implemented by Rules.passes"
					% [where, String(condition)])
	for hook_name in (data.get("hooks", {}) as Dictionary).keys():
		if not (vocab.get("hooks", []) as Array).has(String(hook_name)):
			problems.append(("hook '%s': nothing fires it, so anything registered on it "
				+ "never runs") % String(hook_name))
		for effect in data["hooks"][hook_name]:
			if not (vocab.get("hook_effects", []) as Array).has((effect as Dictionary).get("type", "")):
				problems.append(("hook '%s': effect type '%s' is not implemented by "
					+ "Game.apply_effects") % [String(hook_name),
						str((effect as Dictionary).get("type", ""))])
	for key in data.keys():
		if key != "modifiers" and key != "hooks":
			_walk_modifiers(problems, vocab, data[key])
