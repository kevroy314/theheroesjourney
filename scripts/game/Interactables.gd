class_name HJInteractables
extends RefCounted
## Things in the world you can stand beside and act on.
##
## Two halves, deliberately apart:
##
##   * **The catalogue** — data/content/interactables.json — says what a *kind*
##     of object is: its verb, what it costs, what it does. One entry serves
##     every stove in the world.
##   * **The placements** — an `interactables` list in data/world/overworld.json —
##     say where they stand: { x, y, type, label? }. That shape is already what
##     the Tiled round trip classifies as an object layer, so the designer drags
##     a door around and retypes a stove as a counter with no code involved.
##     See docs/MAP-EDITING.md.
##
## The price is a *config key*, not a number, so it resolves through Rules and a
## trinket can bend it — same treatment as run.clear_bonus. The effect is one
## entry of the vocabulary hooks already use, so Game.apply_effects is the only
## place that knows how to make something happen.

## The world file is read for its `interactables` list alone. HJWorld parses the
## same file for its tile planes; the duplicate parse is one-off and lazy, and
## it is the price of not reaching into a file this system does not own.
const WORLD_PATH := "res://data/world/overworld.json"

var g: Node   ## the Game autoload

var _placed: Array = []
var _loaded := false


func _init(game: Node) -> void:
	g = game


# --- the catalogue -------------------------------------------------------------

func definition(id: String) -> Dictionary:
	return Content.interactable(id)


func catalogue() -> Array:
	return Content.interactables


# --- placements ----------------------------------------------------------------

func placements() -> Array:
	if not _loaded:
		_loaded = true
		_placed = _read_placements()
	return _placed


## Replace what the world says. For the self-test and for tools — a house that
## has not been drawn yet still needs its door to be provable.
func use_placements(list: Array) -> void:
	_placed = list
	_loaded = true


func _read_placements() -> Array:
	# FileAccess rather than load(): this mirrors HJWorld, which reads the same
	# file the same way and is the proof that the export ships it as a file.
	if not FileAccess.file_exists(WORLD_PATH):
		return []
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(WORLD_PATH))
	if not (parsed is Dictionary):
		return []
	var found: Variant = (parsed as Dictionary).get("interactables", [])
	return found if found is Array else []


# --- what is within reach ------------------------------------------------------

## Everything the player standing on `cell` could act on, already priced and
## already told whether it can be afforded. The screen renders this and calls
## `act` with the `key`; it never has to know what a stove is.
func near(cell: Vector2i) -> Array:
	var out: Array = []
	for entry in placements():
		if not (entry is Dictionary):
			continue
		var placement: Dictionary = entry
		var kind := definition(String(placement.get("type", "")))
		if kind.is_empty():
			continue
		if not _in_reach(kind, _cell_of(placement), cell):
			continue
		out.append(describe(placement, kind))
	return out


func describe(placement: Dictionary, def: Dictionary) -> Dictionary:
	var cell := _cell_of(placement)
	var key := _key_of(placement)
	var price := cost(def)
	var spent := _is_spent(def, key)
	var grit := 0
	if g.run != null:
		grit = int(g.run.grit)
	var affordable := grit >= price
	var reason := ""
	if spent:
		reason = String(def.get("spent_text", "Already done."))
	elif not affordable:
		reason = "Costs %d %s. You have %d." % [price, Palette.word("grit"), grit]
	return {
		"key": key,
		"id": String(def.get("id", "")),
		"name": String(placement.get("label", def.get("name", ""))),
		"verb": String(def.get("verb", "Use")),
		"desc": String(def.get("desc", "")),
		"icon": String(def.get("icon", "")),
		"cost": price,
		"x": cell.x, "y": cell.y,
		"spent": spent,
		"affordable": affordable,
		"available": not spent and affordable,
		"reason": reason,
	}


## What it costs, in Grit, resolved through the rule engine.
##
## `cost_key` names a config key rather than carrying a number, so the price is
## tunable in data and bendable by a trinket. An interactable with no cost_key
## is free, which is what a dog is.
func cost(def: Dictionary) -> int:
	if String(def.get("cost_key", "")) == "":
		return 0
	var ctx: Dictionary = {}
	if g.run != null:
		ctx = g.run.ctx()
	return maxi(0, int(round(Rules.value(String(def.get("cost_key", "")), ctx, 0.0))))


# --- doing it ------------------------------------------------------------------

## Act on one. Returns false having changed nothing, the same contract HJItems
## keeps, so a screen cannot charge for a no-op.
func act(key: String) -> bool:
	if not g.has_active_run():
		return false
	var placement := _find(key)
	if placement.is_empty():
		return false
	var def := definition(String(placement.get("type", "")))
	if def.is_empty():
		return false

	var view := describe(placement, def)
	if bool(view["spent"]):
		g.say(String(view["reason"]), "warn")
		return false
	if not bool(view["affordable"]):
		g.say(String(view["reason"]), "warn")
		return false

	var price := int(view["cost"])
	if price > 0:
		g.add_grit(-price)
	if bool(def.get("once", false)):
		# The tombstone is a run tag, so it is persisted with the run and gone
		# when the loop closes — the door is shut again next time you wake up.
		var spent_tag := "spent:" + key
		if not g.run.tags.has(spent_tag):
			g.run.tags.append(spent_tag)
	g.apply_effects([def.get("effect", {})])
	g.changed()
	return true


# --- internals -----------------------------------------------------------------

func _in_reach(def: Dictionary, at: Vector2i, from: Vector2i) -> bool:
	if String(def.get("reach", "adjacent")) == "on":
		return at == from
	# Adjacent means the eight cells around it as well as the cell itself: a
	# door you are standing in the doorway of is still a door you can open.
	return absi(at.x - from.x) <= 1 and absi(at.y - from.y) <= 1


func _is_spent(def: Dictionary, key: String) -> bool:
	if not bool(def.get("once", false)) or g.run == null:
		return false
	return g.run.tags.has("spent:" + key)


func _find(key: String) -> Dictionary:
	for entry in placements():
		if entry is Dictionary and _key_of(entry) == key:
			return entry
	return {}


## Identity of one placed object: its kind and where it stands. Two stoves in
## one house are two different things to have used.
static func _key_of(placement: Dictionary) -> String:
	return "%s@%d,%d" % [String(placement.get("type", "")),
		int(placement.get("x", 0)), int(placement.get("y", 0))]


static func _cell_of(placement: Dictionary) -> Vector2i:
	return Vector2i(int(placement.get("x", 0)), int(placement.get("y", 0)))
