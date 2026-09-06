extends Node
## What you are trying to do, and whether it is done yet.
##
## The minimum viable version of quests. An objective is data — an id, a title,
## a description, one completion goal, and a reward — and this file is the only
## thing that knows whether one is running, how far along it is, and what
## happens when it finishes.
##
## Three things make this different from the Wheel, which is the closest
## existing system:
##
##   * an objective is *given*, not earned. Spite hands the first one over on
##     the doorstep; nothing about your play unlocks it.
##   * progress **outlives the run**. The town objective survives a loop reset,
##     which is the whole point of it: the loop takes the world back and leaves
##     the errand standing.
##   * it is displayed. The Hearth is objectives now, so `active()` and
##     `progress()` are a read API somebody else renders.
##
## Persistence is its own file, the way History's is, rather than a field in the
## save blob. Meta.save_game() runs on nearly every meaningful action and
## rewrites the whole blob each time; this changes a handful of times per run.
## `Meta.wipe()` should call `Objectives.wipe()` — see the report.

signal changed(objective_id: String)

const PATH := "user://objectives.json"
const VERSION := 1

const INACTIVE := "inactive"
const ACTIVE := "active"
const COMPLETE := "complete"

## Where the store lives. A variable rather than the constant so the self-test
## can point it somewhere disposable — the harness plays real runs, and every
## anomaly it closes would otherwise be recorded against the player's own
## objectives. History learned this the hard way.
var path := PATH

## id -> { state, started_unix, completed_unix }
var _state: Dictionary = {}

## Every anomaly cell ever closed, as "x,y" -> true.
##
## This is the field the town objective actually needs and nothing else in the
## game keeps. `run.anomalies_cleared` is per-run and dies with the loop;
## `Meta.anomalies_closed` is a lifetime *count*, which cannot tell "the two in
## town" from "two out past the foothills". Neither can answer "is the town
## finished", so this records the cells themselves.
var _closed: Dictionary = {}

var _loaded := false


func _ready() -> void:
	Events.run_changed.connect(_on_run_changed)
	load_store()


# --- definitions ---------------------------------------------------------------

func definition(id: String) -> Dictionary:
	return Content.objectives.get(id, {})


func title(id: String) -> String:
	return String(definition(id).get("title", id))


# --- state ---------------------------------------------------------------------

func state(id: String) -> String:
	return String((_state.get(id, {}) as Dictionary).get("state", INACTIVE))


func is_active(id: String) -> bool:
	return state(id) == ACTIVE


func is_complete(id: String) -> bool:
	return state(id) == COMPLETE


## Give the player an objective. Returns false if it does not exist or is
## already running or finished — starting one twice must not reset its progress.
func start(id: String) -> bool:
	if definition(id).is_empty() or _state.has(id):
		return false
	_state[id] = {"state": ACTIVE, "started_unix": HJClock.now(), "completed_unix": 0}
	save_store()
	Game.say("New objective: %s" % title(id), "good")
	changed.emit(id)
	# A goal that is already satisfied when it is handed over finishes at once
	# rather than sitting on the Hearth looking complete and not saying so.
	refresh()
	return true


## Read API for the Hearth: every objective currently being pursued, newest
## first, each already carrying its progress so the screen does no work.
func active() -> Array:
	return _rows(ACTIVE)


## Finished objectives, for the same screen's second list.
func completed() -> Array:
	return _rows(COMPLETE)


func _rows(want: String) -> Array:
	var out: Array = []
	for id in Content.objective_order:
		var key := String(id)
		if state(key) != want:
			continue
		var row: Dictionary = definition(key).duplicate(true)
		var bar := progress(key)
		row["state"] = want
		row["done"] = bar["done"]
		row["total"] = bar["total"]
		row["fraction"] = bar["fraction"]
		row["started_unix"] = int((_state[key] as Dictionary).get("started_unix", 0))
		row["completed_unix"] = int((_state[key] as Dictionary).get("completed_unix", 0))
		out.append(row)
	out.sort_custom(func(a, b): return int(a["started_unix"]) > int(b["started_unix"]))
	return out


## How far along one objective is. `total` is 0 for a goal with nothing to
## count, which a bar should read as "no progress to show" rather than divide by.
func progress(id: String) -> Dictionary:
	var goal: Dictionary = definition(id).get("goal", {})
	var done := 0
	var total := 0
	match String(goal.get("type", "")):
		"anomalies_in_ring":
			var ring := int(goal.get("ring", 0))
			for entry in HJWorld.shared().anomalies:
				var spawn: Dictionary = entry
				if int(spawn.get("tier", -1)) != ring:
					continue
				total += 1
				if is_cell_closed(Vector2i(int(spawn.get("x", 0)), int(spawn.get("y", 0)))):
					done += 1
	var fraction := 0.0 if total <= 0 else clampf(float(done) / float(total), 0.0, 1.0)
	return {"done": done, "total": total, "fraction": fraction}


func met(id: String) -> bool:
	var bar := progress(id)
	return int(bar["total"]) > 0 and int(bar["done"]) >= int(bar["total"])


## Recompute every running objective and finish the ones that are done.
func refresh() -> void:
	for id in _state.keys():
		var key := String(id)
		if state(key) != ACTIVE or not met(key):
			continue
		var row: Dictionary = _state[key]
		row["state"] = COMPLETE
		row["completed_unix"] = HJClock.now()
		save_store()
		Game.say("Objective complete: %s" % title(key), "good")
		apply_effects(definition(key).get("reward", []))
		changed.emit(key)


# --- what the world has closed -------------------------------------------------

func is_cell_closed(cell: Vector2i) -> bool:
	return _closed.has(_key(cell))


func closed_cells() -> Array:
	return _closed.keys()


## Record one closed anomaly. Idempotent, so harvesting the same run twice is
## free.
func note_closed(cell: Vector2i) -> bool:
	var key := _key(cell)
	if _closed.has(key):
		return false
	_closed[key] = true
	save_store()
	return true


## The run is the source of truth for what was closed *this* loop; this is where
## it becomes permanent.
##
## Harvesting rather than being told is deliberate. `Game.leave_anomaly` already
## appends to `run.anomalies_cleared` and calls `Meta.note_anomaly_closed()`,
## neither of which carries the cell anywhere that survives the run. Watching
## `run_changed` means objectives learn about a closed anomaly without Game
## having to know objectives exist.
func _on_run_changed() -> void:
	var run: HJRun = Game.run
	if run == null:
		return
	var gained := false
	for key in run.anomalies_cleared:
		if not _closed.has(String(key)):
			_closed[String(key)] = true
			gained = true
	if gained:
		save_store()
	refresh()


static func _key(cell: Vector2i) -> String:
	return "%d,%d" % [cell.x, cell.y]


# --- effects -------------------------------------------------------------------

## The one place a story effect is applied.
##
## Dialogue lines, dialogue replies and objective rewards all speak the same
## small vocabulary, and it is deliberately mostly *the existing one*: `grit`,
## `deadline` and the random `item` are handed straight to `Game.apply_effects`
## rather than reimplemented, so there is one payer of grit in the codebase.
## What is added here is the handful of verbs a conversation needs and a hook
## never did — a *named* item, Resolve, a run tag, and starting an objective.
func apply_effects(effects: Array) -> void:
	for e in effects:
		var effect: Dictionary = e
		var amount := int(round(float(effect.get("amount", 0))))
		match String(effect.get("type", "")):
			"grit", "deadline":
				Game.apply_effects([effect])
			"resolve":
				Meta.resolve = maxi(0, Meta.resolve + amount)
				Meta.stats["resolve_earned"] = int(Meta.stats.get("resolve_earned", 0)) + maxi(0, amount)
				Meta.save_game()
				Events.meta_changed.emit()
				if not bool(effect.get("silent", false)):
					Game.say("%+d %s." % [amount, Palette.word("resolve")], "good")
			"item":
				var item_id := String(effect.get("item", ""))
				if item_id == "":
					Game.apply_effects([effect])     # the existing random-item verb
				elif Content.items.has(item_id):
					Meta.give_item(item_id, maxi(1, int(effect.get("count", 1))))
					if not bool(effect.get("silent", false)):
						Game.say("You are carrying the %s."
							% String(Content.item(item_id).get("name", item_id)), "good")
				else:
					# Loud rather than silent: an item id that names nothing is a
					# beat that quietly does not happen.
					push_warning("Objectives: effect names unknown item '%s'" % item_id)
			"tag":
				var run: HJRun = Game.run
				var tag := String(effect.get("tag", ""))
				if run != null and tag != "" and not run.tags.has(tag):
					run.tags.append(tag)
					Game.changed()
			"objective":
				start(String(effect.get("objective", "")))
			"log":
				Game.say(String(effect.get("text", "")), String(effect.get("kind", "info")))
			_:
				push_warning("Objectives: unknown effect type '%s'"
					% String(effect.get("type", "")))


# --- the Finder ----------------------------------------------------------------
# Spite's parting gift: a bar that fills as you close on the nearest hole that
# is still open. It lives here because "which anomalies are still open" is the
# question this file already answers, and nowhere else does.
#
# It is deliberately a poor instrument. The noise is largest at range and falls
# away as you approach, so the Finder tells you which way to walk and refuses to
# tell you where to stand — forced exploration with a hint, not a solved map.

const FINDER_ITEM := "finder"


func has_finder() -> bool:
	return Meta.item_count(FINDER_ITEM) > 0


## The nearest anomaly that has never been closed, or {} if there is none.
func nearest_open_anomaly(from: Vector2i) -> Dictionary:
	var best: Dictionary = {}
	var best_distance := INF
	for entry in HJWorld.shared().anomalies:
		var spawn: Dictionary = entry
		var cell := Vector2i(int(spawn.get("x", 0)), int(spawn.get("y", 0)))
		if is_cell_closed(cell):
			continue
		var d: float = Vector2(from - cell).length()
		if d < best_distance:
			best_distance = d
			best = spawn
	return best


## 0..1 for the bar above the player's head, or -1.0 for "nothing to say" —
## no Finder, no run, or every anomaly in the world already closed. Render -1
## as an absent bar, not as an empty one.
func finder_reading() -> float:
	var run: HJRun = Game.run
	if run == null or not has_finder() or run.world_pos.x < 0:
		return -1.0
	return finder_reading_at(run.world_pos, float(HJClock.now()))


## The core, split out so it can be tested without a run: what the bar reads
## from `cell` at time `at_unix`.
func finder_reading_at(cell: Vector2i, at_unix: float) -> float:
	var target := nearest_open_anomaly(cell)
	if target.is_empty():
		return -1.0
	var to := Vector2i(int(target.get("x", 0)), int(target.get("y", 0)))
	var reach: float = maxf(1.0, Rules.value("finder.range", {}, 48.0))
	var distance: float = Vector2(cell - to).length()
	var truth: float = clampf(1.0 - distance / reach, 0.0, 1.0)

	# Two slow sines rather than a random number: the bar has to breathe, not
	# flicker, or it reads as broken instead of unreliable. Position is in the
	# phase, so standing still and waiting does not average the lie away.
	var amplitude: float = clampf(Rules.value("finder.noise", {}, 0.22), 0.0, 0.5)
	var seed_phase := float(cell.x) * 0.61 + float(cell.y) * 0.37
	var drift := at_unix * 0.35
	var wobble: float = sin(seed_phase + drift) * 0.62 + sin(seed_phase * 2.7 - drift * 0.41) * 0.38
	# Honest up close, vague at distance. The opposite would make it a map.
	return clampf(truth + wobble * amplitude * (0.25 + 0.75 * (1.0 - truth)), 0.0, 1.0)


## What the Finder says out loud when it is tapped. HJItems.use dispatches one
## line to this; see the report.
func finder_line() -> String:
	var reading := finder_reading()
	if reading < 0.0:
		if not has_finder():
			return "You are not carrying it."
		return "The disc lies flat and still. Nothing left open within reach of it."
	if reading > 0.8:
		return "The disc is hot and will not sit flat. It is close."
	if reading > 0.55:
		return "The disc pulls, steadily, one way."
	if reading > 0.3:
		return "A twitch, now and then. Something out there."
	return "Barely a tremor. Whatever it wants, it is a long walk."


# --- persistence ---------------------------------------------------------------

func use_path(new_path: String) -> void:
	path = new_path
	_loaded = false
	_state = {}
	_closed = {}
	load_store()


func load_store() -> void:
	_state = {}
	_closed = {}
	_loaded = true
	if not FileAccess.file_exists(path):
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Dictionary):
		return
	var doc: Dictionary = parsed
	if int(doc.get("version", 0)) != VERSION:
		return
	for id in (doc.get("objectives", {}) as Dictionary).keys():
		_state[String(id)] = (doc["objectives"] as Dictionary)[id]
	for key in (doc.get("closed", []) as Array):
		_closed[String(key)] = true


func save_store() -> void:
	var doc := {
		"version": VERSION,
		"objectives": _state,
		"closed": _closed.keys(),
	}
	var tmp := path + ".tmp"
	var f := FileAccess.open(tmp, FileAccess.WRITE)
	if f == null:
		push_warning("Objectives: could not write %s" % tmp)
		return
	f.store_string(JSON.stringify(doc, "  "))
	f.close()
	var dir := DirAccess.open(path.get_base_dir())
	if dir == null or dir.rename(tmp.get_file(), path.get_file()) != OK:
		push_warning("Objectives: could not replace %s" % path)


## Called from Meta.wipe(): a save reset must take the errands with it.
func wipe() -> void:
	_state = {}
	_closed = {}
	save_store()
	changed.emit("")


# --- self-check ----------------------------------------------------------------

## Everything wrong with the loaded objectives, as human-readable lines.
##
## The schema checks shape; this checks the things a JSON schema cannot see —
## that a goal type is one this file implements, and that a `when` clause speaks
## the vocabulary `Rules.passes` actually knows. Both would otherwise fail
## silently: an unknown goal type counts zero forever, and an unknown condition
## makes `Rules.passes` warn once and pass.
func problems() -> Array[String]:
	var out: Array[String] = []
	var goals: Array = Content.schema().get("vocabulary", {}).get("objective_goals", [])
	for id in Content.objectives.keys():
		var goal: Dictionary = (Content.objectives[id] as Dictionary).get("goal", {})
		var kind := String(goal.get("type", ""))
		if not goals.has(kind):
			out.append("objective '%s': goal type '%s' is not one Objectives.progress implements"
				% [String(id), kind])
	return out
