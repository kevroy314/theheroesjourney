extends Node
## Loads everything under res://data/ into memory. Drop a new .json into the
## right folder and it is picked up on next launch — no code change required.

const DATA_ROOT := "res://data"

var themes: Dictionary = {}       ## id -> theme
var rulesets: Dictionary = {}     ## id -> ruleset
var movements: Dictionary = {}    ## id -> movement (with "pack" stamped on)
var packs: Dictionary = {}        ## id -> pack meta
var pack_order: Array = []
var areas: Dictionary = {}        ## id -> area definition
var echoes: Array = []            ## ordered story fragments
var echo_reveals: Dictionary = {}
var chapters: Array = []
var trinkets: Dictionary = {}
var items: Dictionary = {}
var item_order: Array = []
var loot: Dictionary = {}
var upgrades: Array = []
var achievements: Dictionary = {}
var spite: Dictionary = {}
var rooms: Array = []
var palace: Dictionary = {}
var config: Dictionary = {}

var _loaded := false


func _ready() -> void:
	load_all()


func load_all() -> void:
	if _loaded:
		return
	_loaded = true

	for file_name in list_json(DATA_ROOT + "/themes"):
		var t: Variant = read_json(DATA_ROOT + "/themes/" + file_name)
		if t is Dictionary and t.has("id"):
			themes[t["id"]] = t

	for file_name in list_json(DATA_ROOT + "/rulesets"):
		var r: Variant = read_json(DATA_ROOT + "/rulesets/" + file_name)
		if r is Dictionary and r.has("id"):
			rulesets[r["id"]] = r

	for file_name in list_json(DATA_ROOT + "/areas"):
		var a: Variant = read_json(DATA_ROOT + "/areas/" + file_name)
		if a is Dictionary and a.has("id"):
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
		if doc.has("chapters"):
			chapters.append_array(doc["chapters"])
		if doc.has("upgrades"):
			upgrades.append_array(doc["upgrades"])
		if doc.has("loot"):
			loot.merge(doc["loot"], true)
		if doc.has("spite"):
			spite = doc["spite"]
		if doc.has("rooms"):
			rooms.append_array(doc["rooms"])
		if doc.has("palace"):
			palace.merge(doc["palace"], true)
		if doc.has("axes"):
			achievements = doc
		for t in doc.get("trinkets", []):
			trinkets[t["id"]] = t
		for i in doc.get("items", []):
			items[i["id"]] = i
			if not item_order.has(i["id"]):
				item_order.append(i["id"])

	chapters.sort_custom(func(a, b): return int(a.get("id", 0)) < int(b.get("id", 0)))
	# Cheapest first, so the free starter pack heads the list in Camp.
	pack_order.sort_custom(func(a, b): return int(packs[a].get("cost", 0)) < int(packs[b].get("cost", 0)))

	if themes.is_empty() or chapters.is_empty():
		push_error("Content: data failed to load from %s" % DATA_ROOT)


func _add_pack(pack: Dictionary, movement_list: Array) -> void:
	if pack.is_empty():
		return
	packs[pack["id"]] = pack
	if not pack_order.has(pack["id"]):
		pack_order.append(pack["id"])
	for m in movement_list:
		var movement: Dictionary = (m as Dictionary).duplicate(true)
		movement["pack"] = pack["id"]
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


## Chapter definition by 1-based id.
func chapter(id: int) -> Dictionary:
	for c in chapters:
		if int(c.get("id", 0)) == id:
			return c
	return {}


func chapter_count() -> int:
	return chapters.size()


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
