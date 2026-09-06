class_name HJStateCode
extends RefCounted
## Old-video-game passwords, for testing. Type a short code, land in a state.
##
## Two halves, because one shape cannot do both jobs.
##
## **Named presets**, in data/content/statecodes.json. A preset is a declarative
## patch over a fresh install: some Meta fields, optionally a run, some buffs, a
## conversation or two already had. Authoring one is a content edit, reading one
## is reading English, and the schema catches a typo in it. This is the right
## shape for the beats — "the moment before stepping outside" is a *named* state
## and nobody should have to spell it out in hex.
##
## **Structured overrides**, appended with `-`. A preset cannot express "the
## deep-run preset but at ring 2 with 400 Grit", and enumerating every such
## combination as its own preset is how a testing tool becomes a second content
## pipeline. So: `DP3-D2-T400`. Seven single-letter keys, decimal numbers, and
## the legend is printed under the field because a mnemonic you have to remember
## is a mnemonic you will get wrong at eleven at night.
##
## **Typability**, which drives the alphabet. Issue #60: the pixel font's
## ambiguous glyphs are `e c u o a s G R B 8 0 O 1 l I`. Codes are folded to
## upper case on input and drawn only from letters outside that set, which
## leaves no vowels at all — so preset codes are consonant skeletons rather than
## words, and that is fine, because the presets are also a *tappable list* three
## rows further up the screen. The code is what you write on a sticky note or
## paste into a bug report; the list is what you use.
##
## Digits are the exception and deliberately so: ambiguity only bites where a
## glyph could be either a letter or a digit. Inside an override value you are
## reading a number and nothing else, so `400` is unambiguous even though `0` is
## on the list. Preset codes carry only 2-6, which are safe either way.
##
## A code always begins with a preset, and applying one always resets first.
## "Load a test start state" is the whole feature; an override-only code that
## patched the live game would look identical and do something completely
## different.


const PATH := "res://data/content/statecodes.json"

## Safe in the pixel font, folded to upper case. See #60.
const ALPHABET := "DFHJKMNPQTVWXY23456"

## Override keys. First letter of the thing wherever that letter is safe, and a
## letter from the word wherever it is not — `resolve` cannot be R, `grit`
## cannot be G. The legend is on screen, so unambiguity beats mnemonic purity.
const KEYS := {
	"D": {"field": "ring", "name": "ring depth", "max": 8},
	"T": {"field": "grit", "name": "Grit carried", "max": 99999},
	"V": {"field": "resolve", "name": "Resolve banked", "max": 999999},
	"P": {"field": "steps", "name": "steps granted", "max": 99999},
	"K": {"field": "loops", "name": "loops closed", "max": 9999},
	"N": {"field": "anomalies", "name": "anomalies closed", "max": 9999},
	"X": {"field": "streak", "name": "day streak", "max": 999},
}


static var _presets: Array = []


static func presets() -> Array:
	if _presets.is_empty():
		var doc: Variant = Content.read_json(PATH)
		if doc is Dictionary:
			_presets = (doc as Dictionary).get("statecodes", [])
	return _presets


static func find(code: String) -> Dictionary:
	var wanted := normalise(code)
	for entry in presets():
		if String((entry as Dictionary).get("code", "")).to_upper() == wanted:
			return entry
	return {}


## Upper case, and anything that is not a code character thrown away. A phone
## keyboard will happily insert a space after a dash and autocapitalise the rest;
## none of that should be the difference between a code working and not.
static func normalise(text: String) -> String:
	var out := ""
	for ch in text.to_upper():
		if ch == "-" or (ch >= "0" and ch <= "9") or (ch >= "A" and ch <= "Z"):
			out += ch
	return out


## The legend, as the line printed under the field.
static func legend() -> String:
	var parts: Array = []
	for key in KEYS.keys():
		parts.append("%s%s" % [key, String((KEYS[key] as Dictionary)["name"])])
	return ", ".join(parts)


# --- parsing -------------------------------------------------------------------

## { ok, error, code, preset, overrides }
static func parse(text: String) -> Dictionary:
	var clean := normalise(text)
	if clean == "":
		return _bad("Type a code, or tap one from the list.")
	var parts := clean.split("-", false)
	if parts.size() == 0:
		return _bad("Type a code, or tap one from the list.")
	var head := String(parts[0])
	var preset := find(head)
	if preset.is_empty():
		return _bad("No preset called %s. Valid codes: %s." % [head, ", ".join(codes())])

	var overrides: Dictionary = {}
	for i in range(1, parts.size()):
		var seg := String(parts[i])
		if seg.length() < 2:
			return _bad("'%s' is too short to be an override. Try D3 or T400." % seg)
		var key := seg.substr(0, 1)
		if not KEYS.has(key):
			return _bad("'%s' is not an override key. Keys are: %s." % [key, legend()])
		var digits := seg.substr(1)
		if not digits.is_valid_int():
			return _bad("'%s' needs a whole number after the %s." % [seg, key])
		var spec: Dictionary = KEYS[key]
		overrides[String(spec["field"])] = clampi(int(digits), 0, int(spec["max"]))

	return {"ok": true, "error": "", "code": clean, "preset": preset, "overrides": overrides}


static func codes() -> Array:
	var out: Array = []
	for entry in presets():
		out.append(String((entry as Dictionary).get("code", "")))
	return out


static func _bad(message: String) -> Dictionary:
	return {"ok": false, "error": message, "code": "", "preset": {}, "overrides": {}}


# --- applying ------------------------------------------------------------------

## Tear the character down and rebuild it as the preset describes.
##
## Takes a backup first. A state code is exactly as destructive as the reset
## button — it *is* the reset button with a patch applied — and during a testing
## pass the difference between "I lost that state" and "it is in backups" is one
## line of code.
##
## Returns { ok, message, screen }. The caller navigates; this does not, because
## a screen must not redirect from inside its own build and the safest place to
## make that decision is the one place that knows whether the run took.
static func apply(parsed: Dictionary) -> Dictionary:
	if not bool(parsed.get("ok", false)):
		return {"ok": false, "message": String(parsed.get("error", "")), "screen": ""}
	var preset: Dictionary = parsed["preset"]
	var over: Dictionary = parsed.get("overrides", {})

	HJSaveIO.write_backup("before %s" % String(parsed.get("code", "?")), true)
	HJSaveIO.hard_reset()

	_apply_meta(preset, over)
	Meta.save_game()

	var run_spec: Dictionary = preset.get("run", {})
	if not run_spec.is_empty():
		_apply_run(run_spec, over)

	_apply_stores(preset)
	Game.rebuild_rules()
	Events.meta_changed.emit()
	Events.run_changed.emit()

	var screen := String(preset.get("screen", ""))
	if screen == "":
		screen = "overworld" if Game.has_active_run() else "title"
	return {
		"ok": true,
		"screen": screen,
		"message": "%s — %s" % [String(preset.get("code", "?")), String(preset.get("name", ""))],
	}


static func _apply_meta(preset: Dictionary, over: Dictionary) -> void:
	Meta.resolve = int(over.get("resolve", preset.get("resolve", 0)))
	Meta.deepest_ring = int(over.get("ring", preset.get("deepest_ring", 0)))
	Meta.anomalies_closed = int(over.get("anomalies", preset.get("anomalies_closed", 0)))
	Meta.loops = int(over.get("loops", preset.get("loops", 0)))
	Meta.streak = int(over.get("streak", preset.get("streak", 0)))
	Meta.best_streak = maxi(Meta.streak, int(preset.get("best_streak", 0)))
	if Meta.streak > 0:
		# A streak with no last-active day breaks the moment refresh_streak runs.
		Meta.last_active_day = HJClock.today()
	# Loops is a spoiler on the title screen until the loop has actually closed
	# once, and this flag is what the title screen reads.
	Meta.seen_first_reset = Meta.loops > 0

	for id in preset.get("revealed", []):
		if not Meta.revealed.has(String(id)):
			Meta.revealed.append(String(id))
	Meta.self_description = (preset.get("self_description", {}) as Dictionary).duplicate(true)

	for id in (preset.get("items", {}) as Dictionary).keys():
		Meta.inventory[String(id)] = int((preset["items"] as Dictionary)[id])
	for axis in (preset.get("axis_tasks", {}) as Dictionary).keys():
		Meta.axis_tasks[String(axis)] = int((preset["axis_tasks"] as Dictionary)[axis])

	if bool(preset.get("unlock_all", false)):
		for id in Content.packs.keys():
			_add(Meta.unlocked, String(id))
		for id in Content.themes.keys():
			_add(Meta.unlocked, String(id))
		for id in Content.rulesets.keys():
			_add(Meta.unlocked, String(id))
		for up in Content.upgrades:
			var costs: Array = (up as Dictionary).get("cost", [])
			Meta.levels[String((up as Dictionary)["id"])] = costs.size()

	if bool(preset.get("rooms_all", false)):
		_fill_palace()

	if bool(preset.get("codex_all", false)):
		for e in Content.echoes:
			_add(Meta.codex, String((e as Dictionary).get("id", "")))

	if bool(preset.get("wheel_all", false)):
		# Claimed rather than merely met: the Wheel's unclaimed badge is itself a
		# thing worth testing, and "everything unlocked" means nothing is owed.
		for node in Meta.wheel_all_nodes():
			if Meta.wheel_met(node):
				_add(Meta.claimed, String((node as Dictionary).get("id", "")))


## Every room owned, revealed, and actually placed on the grid — an owned room
## sitting in the unplaced list is a different screen from a built palace, and
## the adjacency bonuses only exist once things are next to each other.
static func _fill_palace() -> void:
	Meta.palace_size = int(Meta.palace_config().get("max_size", 5))
	Meta.rooms_owned = []
	Meta.room_grid = {}
	var x := 0
	var y := 0
	for room in Content.rooms:
		var id := String((room as Dictionary)["id"])
		Meta.rooms_owned.append(id)
		_add(Meta.revealed, id)
		if y < Meta.palace_size:
			Meta.room_grid["%d,%d" % [x, y]] = id
		x += 1
		if x >= Meta.palace_size:
			x = 0
			y += 1


static func _apply_run(spec: Dictionary, over: Dictionary) -> void:
	# start_run does the honest thing — stipend, buffs cleared, tutorial beat,
	# deadline, the on_run_start hook — so the run is a real run rather than a
	# hand-assembled object that is subtly not one. Everything below is a patch
	# on top of that.
	Game.start_run(int(spec.get("seed", 0)))
	var run: HJRun = Game.run
	if run == null:
		return

	run.zone = int(over.get("ring", spec.get("zone", 0)))
	run.grit = int(over.get("grit", spec.get("grit", 0)))
	for id in spec.get("trinkets", []):
		_add(run.trinkets, String(id))
	for tag in spec.get("tags", []):
		_add(run.tags, String(tag))
	for id in spec.get("echoes", []):
		_add(run.echoes, String(id))
	run.revealed = bool(spec.get("revealed", false))

	for key in _closed_cells(spec):
		_add(run.anomalies_cleared, key)
	if int(over.get("anomalies", -1)) < 0 and Meta.anomalies_closed == 0:
		Meta.anomalies_closed = run.anomalies_cleared.size()

	run.world_pos = _anchor(String(spec.get("at", "spawn")), run.zone)
	if spec.has("started_ago"):
		run.started_unix = HJClock.now() - int(spec["started_ago"])
	if spec.has("deadline_in"):
		# The one that matters for the loop-about-to-close case: a deadline a
		# minute out is a state you otherwise have to wait a day for.
		run.deadline_unix = HJClock.now() + int(spec["deadline_in"])

	if over.has("steps"):
		Steps.grant(int(over["steps"]))
	elif spec.has("steps"):
		Steps.grant(int(spec["steps"]))

	if bool(spec.get("fog", false)):
		_walk_fog(run.world_pos)

	Meta.deepest_ring = maxi(Meta.deepest_ring, run.zone)
	Meta.save_game()
	Game.save_run()


static func _apply_stores(preset: Dictionary) -> void:
	for id in preset.get("buffs", []):
		Buffs.apply(String(id), true)
	for id in preset.get("dialogue_seen", []):
		Dialogue.seen[String(id)] = true
	if not (preset.get("dialogue_seen", []) as Array).is_empty():
		Dialogue.save_store()
	for id in preset.get("objectives", []):
		Objectives.start(String(id))
	# Objectives harvests closed cells off the run rather than being told, so
	# this is what turns "the run cleared these" into permanent progress — and
	# it is also what completes the town objective for the preset that wants it.
	Objectives._on_run_changed()


# --- the world -----------------------------------------------------------------

## Cells the preset says are already closed, as the "x,y" keys the run uses.
##
## Named by *area id* rather than by coordinate. The world is generated, and a
## preset that hardcoded (100,145) would silently start closing the wrong hole
## the first time somebody re-ran make_world.py.
static func _closed_cells(spec: Dictionary) -> Array:
	var out: Array = []
	var world := HJWorld.shared()
	var areas: Array = spec.get("close_areas", [])
	var to_tier := int(spec.get("close_to_tier", -1))
	for entry in world.anomalies:
		var a: Dictionary = entry
		var tier := int(a.get("tier", 0))
		var area := String(a.get("area", ""))
		if (to_tier >= 0 and tier <= to_tier) or (area != "" and areas.has(area)):
			out.append("%d,%d" % [int(a.get("x", 0)), int(a.get("y", 0))])
	return out


## Where the run is standing. Anchors rather than coordinates, same reason.
static func _anchor(name: String, tier: int) -> Vector2i:
	var world := HJWorld.shared()
	match name:
		"door":
			return world.nearest_walkable(_door() + Vector2i(0, -1))
		"outside":
			return _outside()
		"anomaly":
			return world.nearest_walkable(_anomaly_cell(tier))
		"town":
			return world.nearest_walkable(_anomaly_cell(0))
	return world.nearest_walkable(world.spawn)


static func _door() -> Vector2i:
	var world := HJWorld.shared()
	for entry in world.interactables:
		var e: Dictionary = entry
		if String(e.get("type", "")) == "front_door":
			return Vector2i(int(e.get("x", 0)), int(e.get("y", 0)))
	return world.spawn


## The first walkable cell past the door that the world does not call indoors.
## Stepping over the threshold is Beat 5 and it is defined by `is_indoors`, so
## this asks the same question the game does rather than guessing an offset.
static func _outside() -> Vector2i:
	var world := HJWorld.shared()
	var door := _door()
	for step in range(1, 10):
		var cell := door + Vector2i(0, step)
		if world.walkable(cell.x, cell.y) and not world.is_indoors(cell):
			return cell
	return world.nearest_walkable(door + Vector2i(0, 2))


static func _anomaly_cell(tier: int) -> Vector2i:
	var world := HJWorld.shared()
	var best := world.spawn
	var best_tier := -1
	for entry in world.anomalies:
		var a: Dictionary = entry
		var t := int(a.get("tier", 0))
		if t == tier:
			return Vector2i(int(a.get("x", 0)), int(a.get("y", 0)))
		if t < tier and t > best_tier:
			best_tier = t
			best = Vector2i(int(a.get("x", 0)), int(a.get("y", 0)))
	return best


## Fog along the way, so a deep run's world map looks like somebody walked there
## rather than teleported. Discovery reveals a segment between successive calls,
## which is exactly what a straight line from town wants.
static func _walk_fog(to: Vector2i) -> void:
	var world := HJWorld.shared()
	var from := world.spawn
	var steps := maxi(1, int(Vector2(to - from).length() / 6.0))
	for i in range(steps + 1):
		var t := float(i) / float(steps)
		var x := int(round(lerpf(float(from.x), float(to.x), t)))
		var y := int(round(lerpf(float(from.y), float(to.y), t)))
		Discovery.reveal(Vector2i(x, y))
	Discovery.save_store()


static func _add(list: Array, value: String) -> void:
	if value != "" and not list.has(value):
		list.append(value)
