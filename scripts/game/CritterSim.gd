extends SceneTree
## Numeric proof that the animals behave, run headless and printed as numbers.
##
##     godot --headless --path . --script scripts/game/CritterSim.gd
##
## A screenshot cannot show hysteresis. A follower that looks fine for the ten
## seconds you watch it can still be drifting a cell further away every minute,
## and a wary animal that vibrates on its own threshold looks, in a still, like
## an animal standing still. So the check is a distance series: walk the player
## a known path, tick the real state machine, and print what the distance
## actually did, with the assertions stated as bands rather than as eyeballs.
##
## Seven things are proved here:
##
##   1. FOLLOW. The dog's distance stays inside a band and never exceeds a
##      bound, over a long walk with turns.
##   2. LAG. He is *not* standing on the player's previous cell. That is the
##      failure this design exists to avoid and it is invisible in a still.
##   3. HYSTERESIS. The cat's distance goes up, comes back to a hold band, and
##      then stops changing. Oscillation is counted, not judged.
##   4. PATHING. He walks round a wall through its one gap rather than through
##      the wall, and he is on the far side of it at the end.
##   5. GIVING UP. Sealed in a pocket with no exit, he strays, abandons the
##      path and reappears in his band -- the failure mode that otherwise loses
##      a follower for the rest of the run.
##   6. AN ESCORT IS EXPRESSIBLE. A species that is not shipped -- the mountain
##      woman's friend from #78, "follow, but stop if the player gets too far,
##      and fail after N tiles apart" -- is built here as data alone and driven
##      to its fail state with no engine change. If this stops passing, #57 has
##      built the wrong primitive.
##   7. THE CONTRACTS. It survives a save and a load, a save from another run is
##      discarded, and views() carries everything the renderer needs and nothing
##      it has to interpret.
##
## Nothing here writes to the player's save: the critter store is pointed at a
## scratch path and g.run is a bare model that is put back afterwards.

const SCRATCH := "user://critter_sim.json"

var _failures: Array[String] = []

## Resolved at run time, not written as bare `Game` and `Critters`.
##
## A `--script` main loop is compiled before the autoloads are registered, so an
## autoload named directly in the source is "Identifier not found: Game" and the
## whole harness fails to load. The nodes are there by the time _initialize runs
## -- the SceneTree builds them first -- so they are looked up rather than
## referenced. Worth knowing before writing the next standalone tool.
## The same problem, one step worse. HJWorld and HJRun are ordinary global
## classes, but HJWorld's *own* source names the Content autoload, so naming
## HJWorld here makes it a compile-time dependency of a script compiled before
## the autoloads exist -- and the whole harness fails to load with an error
## pointing at World.gd. Loaded by path inside _initialize instead, where the
## autoload identifiers are live and the compile succeeds.
var g: Node        ## the Game autoload
var cr: Node       ## the Critters autoload
var ru: Node       ## the Rules autoload
var _WorldClass: GDScript
var _RunClass: GDScript


func _initialize() -> void:
	g = root.get_node("Game")
	cr = root.get_node("Critters")
	ru = root.get_node("Rules")
	_WorldClass = load("res://scripts/ui/World.gd")
	_RunClass = load("res://scripts/model/Run.gd")
	var previous_run = g.run
	g.run = _RunClass.new()
	g.run.seed = 424242
	cr.use_path(SCRATCH)
	cr.use_run_seed(424242)

	_dog_follows_with_lag()
	_dog_paths_around_a_wall()
	_dog_recovers_from_being_stuck()
	_cat_flees_then_holds_without_oscillating()
	_cat_breaks_off_when_crowded()
	_escort_is_expressible_in_data()
	_survives_a_save_and_load()
	_the_renderer_gets_what_it_needs()

	g.run = previous_run
	if FileAccess.file_exists(SCRATCH):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(SCRATCH))

	print("")
	if _failures.is_empty():
		print("critter-sim: OK")
		quit(0)
		return
	for line in _failures:
		print("critter-sim: FAIL  %s" % line)
	print("critter-sim: %d failure(s)" % _failures.size())
	quit(1)


# --- the fixtures ---------------------------------------------------------------

## A world with nothing in it. HJWorld with no planes and no solid set is
## walkable everywhere, which is what an open field is, and it makes the
## distance series about the behaviour rather than about the furniture.
func _field(w: int = 48, h: int = 48):
	var world = _WorldClass.new()
	world.w = w
	world.h = h
	world.loaded = true
	return world


## The same field with a wall across it and one gap, which is the shape of every
## room a follower actually gets stuck in.
func _room_with_a_wall(gap: int):
	var world = _field()
	world.blocked = PackedByteArray()
	world.blocked.resize(world.w * world.h)
	for x in range(6, 34):
		if x == gap:
			continue
		world.blocked[20 * world.w + x] = 1
	return world


func _place(world, id: String, at: Vector2i) -> String:
	var key := "%s@%d,%d" % [id, at.x, at.y]
	cr.use_world(world)
	cr.use_placements([{"key": key, "critter": id, "x": at.x, "y": at.y}])
	cr.spawn_all()
	return key


## Walk the player along `path` at the player's real walking speed, and return
## the distance to the critter after each cell.
##
## The critter clock is finer than the player's stride on purpose -- a pace is
## seconds per cell and must not be quantised to the think tick -- so a step of
## the player's is however many think-ticks fit inside walk.step_time.
func _walk(key: String, path: Array, per_step: int = 1) -> Array[int]:
	var out: Array[int] = []
	var tick: float = cr.tick_seconds()
	var stride: float = ru.value("walk.step_time", {}, 0.17)
	var ticks := maxi(1, int(round(stride / tick)))
	for cell in path:
		cr.note_player(cell)
		for _i in range(per_step * ticks):
			cr.think(tick)
		out.append(cr.distance_to_player(key))
	return out


## Stand still and let the clock run.
func _wait(key: String, ticks: int) -> Array[int]:
	var out: Array[int] = []
	var tick: float = cr.tick_seconds()
	for _i in range(ticks):
		cr.think(tick)
		out.append(cr.distance_to_player(key))
	return out


static func _line(from: Vector2i, step: Vector2i, n: int) -> Array:
	var out: Array = []
	var at := from
	for _i in range(n):
		at += step
		out.append(at)
	return out


static func _series(values: Array) -> String:
	var parts := PackedStringArray()
	for v in values:
		parts.append(str(v))
	return " ".join(parts)


func _check(ok: bool, what: String) -> void:
	print("    %s  %s" % ["pass" if ok else "FAIL", what])
	if not ok:
		_failures.append(what)


# --- 1 and 2: the dog ------------------------------------------------------------

func _dog_follows_with_lag() -> void:
	print("")
	print("dog: follows, with lag")
	var world = _field()
	var start := Vector2i(20, 20)
	var key := _place(world, "dog", start)
	cr.note_player(Vector2i(21, 20))
	_check(cr.event(key, "petted"), "petting him starts him following")
	_check(cr.state_of(key) == "following", "he is in the `following` state")

	# East 14, south 10, west 14 -- two turns, because a follower that only ever
	# walks in a straight line has not been asked the interesting question.
	var path: Array = []
	path.append_array(_line(Vector2i(21, 20), Vector2i(1, 0), 14))
	path.append_array(_line(Vector2i(35, 20), Vector2i(0, 1), 10))
	path.append_array(_line(Vector2i(35, 30), Vector2i(-1, 0), 14))
	var d: Array[int] = _walk(key, path)

	print("    distance: %s" % _series(d))
	var settled := d.slice(4)
	var worst := 0
	var closest := 99
	for v in settled:
		worst = maxi(worst, v)
		closest = mini(closest, v)
	print("    after the first four steps: min %d, max %d" % [closest, worst])
	_check(worst <= 4, "never further than 4 cells (was %d)" % worst)
	_check(closest >= 1, "never inside the player's own cell (min %d)" % closest)

	# The lag. A follower that stands on the cell you just left every single
	# step is the uncanny failure -- it reads as the renderer being one frame
	# behind rather than as an animal.
	var on_previous := 0
	var previous: Vector2i = path[0]
	for i in range(1, path.size()):
		cr.note_player(path[i])
		cr.think(cr.tick_seconds())
		if cr.cell_of(key) == previous:
			on_previous += 1
		previous = path[i]
	print("    stood on the player's previous cell %d of %d steps"
		% [on_previous, path.size() - 1])
	_check(on_previous * 3 < path.size(),
		"he trails rather than mirrors (%d/%d on the previous cell)"
			% [on_previous, path.size() - 1])


func _dog_paths_around_a_wall() -> void:
	print("")
	print("dog: paths around a wall rather than through it")
	var world = _room_with_a_wall(30)
	var key := _place(world, "dog", Vector2i(10, 24))
	cr.note_player(Vector2i(11, 24))
	cr.event(key, "petted")

	# East along the south side, north through the one gap, then west along the
	# north side. The wall is 27 cells of solid and the only way through is a
	# single cell, so a follower that cannot path will be stranded by it.
	var path: Array = []
	path.append_array(_line(Vector2i(11, 24), Vector2i(1, 0), 19))
	path.append_array(_line(Vector2i(30, 24), Vector2i(0, -1), 8))
	path.append_array(_line(Vector2i(30, 16), Vector2i(-1, 0), 20))
	var d: Array[int] = _walk(key, path)
	print("    distance: %s" % _series(d))
	var worst := 0
	for v in d:
		worst = maxi(worst, v)
	var walls := 0
	for x in range(6, 34):
		if x != 30 and not world.walkable(x, 20):
			walls += 1
	var ended: Vector2i = cr.cell_of(key)
	print("    wall of %d solid cells with one gap; he ends at %s" % [walls, ended])
	_check(walls == 27, "the wall was really there")
	_check(worst <= 4, "he stayed within 4 the whole way round (max %d)" % worst)
	_check(ended.y < 20, "and he is on the far side of it")
	_check(world.walkable(ended.x, ended.y), "standing somewhere he could stand")


func _dog_recovers_from_being_stuck() -> void:
	print("")
	print("dog: sealed in, gives up on the path, and comes back")
	var world = _field()
	world.blocked = PackedByteArray()
	world.blocked.resize(world.w * world.h)
	# A pocket with no way out at all. Not a contrived case: it is what a room
	# whose door has closed behind him looks like to a path search, and a
	# follower with no answer to it is lost for the rest of the run.
	for cell in [Vector2i(9, 24), Vector2i(11, 24), Vector2i(10, 23), Vector2i(10, 25)]:
		world.blocked[cell.y * world.w + cell.x] = 1
	var key := _place(world, "dog", Vector2i(10, 24))
	cr.note_player(Vector2i(10, 22))
	cr.event(key, "petted")

	var d: Array[int] = _walk(key, _line(Vector2i(14, 30), Vector2i(1, 0), 16))
	print("    distance: %s" % _series(d))
	var stranded := 0
	for v in d:
		stranded = maxi(stranded, v)
	var collapse := 0
	for i in range(1, d.size()):
		collapse = maxi(collapse, d[i - 1] - d[i])
	print("    furthest he got: %d, biggest one-tick recovery: %d, ends at %d"
		% [stranded, collapse, d[d.size() - 1]])
	_check(stranded >= 10, "he really was sealed away first (%d cells)" % stranded)
	_check(collapse >= 5, "he gave up on the path in one tick (closed %d cells)" % collapse)
	_check(d[d.size() - 1] <= 4, "and is back in his band (%d)" % d[d.size() - 1])
	_check(cr.state_of(key) == "following", "without leaving the follow state")


# --- 3 and 4: the cat -------------------------------------------------------------

func _cat_flees_then_holds_without_oscillating() -> void:
	print("")
	print("cat: retreat, then approach, then hold")
	var world = _field()
	var key := _place(world, "cat", Vector2i(24, 24))
	cr.note_player(Vector2i(23, 24))
	_check(cr.event(key, "petted"), "petting it sets it off")
	_check(cr.state_of(key) == "bolting", "it is in the `bolting` state")

	# The player does not move. Everything below is the cat's own clock, which
	# is the point: the animal is not waiting for you to spend a step.
	var d: Array[int] = _wait(key, 340)
	print("    distance: %s" % _series(d))
	var peak := 0
	for v in d:
		peak = maxi(peak, v)
	_check(peak >= 6, "it ran to at least 6 cells (peak %d)" % peak)

	var last := d.slice(d.size() - 110)
	var lo := 99
	var hi := 0
	var turns := 0
	for i in range(last.size()):
		lo = mini(lo, last[i])
		hi = maxi(hi, last[i])
		if i > 0 and last[i] != last[i - 1]:
			turns += 1
	print("    last 110 ticks: %d..%d, %d changes of distance, state '%s'"
		% [lo, hi, turns, cr.state_of(key)])
	_check(lo >= 3 and hi <= 4, "it settles in the 3..4 hold band (%d..%d)" % [lo, hi])
	_check(turns == 0, "and stops moving there -- %d changes in 110 ticks" % turns)
	_check(cr.state_of(key) == "watching", "it ends up `watching`")


func _cat_breaks_off_when_crowded() -> void:
	print("")
	print("cat: breaks off when you close in, and the thresholds do not agree")
	var world = _field()
	var key := _place(world, "cat", Vector2i(25, 24))
	cr.note_player(Vector2i(24, 24))
	# Pet it first. An unpetted cat only mooches -- it has no reason to be wary
	# of you yet, and if it fled at two cells you could never reach it to pet it
	# at one. Wariness is something you teach it.
	cr.event(key, "petted")
	_wait(key, 300)
	var held: String = cr.state_of(key)
	var at: int = cr.distance_to_player(key)
	print("    holding at %d in state '%s'" % [at, held])

	# Walk in one cell at a time. The break must happen at 2 and not at 4,
	# because 4 is where it *stops approaching* -- if those were the same number
	# the animal would jitter on the boundary forever.
	var broke_at := -1
	var here: Vector2i = cr.cell_of(key) - Vector2i(5, 0)
	cr.note_player(here)
	cr.think(cr.tick_seconds())
	var broke_state := ""
	for _i in range(5):
		here += Vector2i(1, 0)
		cr.note_player(here)
		# Measured *before* the tick. Afterwards the cat has already reacted, so
		# a post-tick distance reports where it ran to rather than what set it
		# off -- which reads as a threshold one cell wider than the data says.
		var d: int = cr.distance_to_player(key)
		for _t in range(3):
			cr.think(cr.tick_seconds())
		broke_state = cr.state_of(key)
		print("    player closes to %d -> state '%s'" % [d, broke_state])
		if broke_state == "bolting" and broke_at < 0:
			broke_at = d
	_check(broke_at >= 0 and broke_at <= 2,
		"it bolts only once you are within 2 (broke at %d)" % broke_at)


# --- 5: the escort, which is the whole point of doing it this way ----------------

## The mountain woman's friend from #78, built out of the shipped vocabulary and
## nothing else. No new goal, no new condition, no new field: three states and
## four transitions, and the failure sets an ordinary run tag through the same
## g.apply_effects every hook and interactable uses.
const ESCORT := {
	"id": "escortee",
	"name": "the woman from the city",
	"sprite": "cat",
	"start": "waiting",
	"states": {
		"waiting": {"goal": "hold"},
		"escorting": {"goal": "approach", "keep": 1, "trail": 2, "pace": 1.0},
		"waiting_up": {"goal": "hold", "say": "She stops. \"Not so fast.\""},
		"lost": {"goal": "hold", "say": "You have lost her."},
	},
	"transitions": [
		{"from": "waiting", "on": "petted", "to": "escorting"},
		{"from": ["escorting", "waiting_up"], "when": {"dist_gte": 12}, "to": "lost",
			"effect": {"type": "tag", "tag": "escort_failed", "silent": true}},
		{"from": "escorting", "when": {"dist_gte": 6}, "to": "waiting_up"},
		{"from": "waiting_up", "when": {"dist_lte": 3}, "to": "escorting"},
	],
}


func _escort_is_expressible_in_data() -> void:
	print("")
	print("escort (#78): follow, stop if the player gets too far, fail at 12")
	cr.use_species([ESCORT])
	var world = _field()
	var key := _place(world, "escortee", Vector2i(20, 20))
	cr.note_player(Vector2i(21, 20))
	cr.event(key, "petted")
	_check(cr.state_of(key) == "escorting", "she sets off")

	# Two cells per tick: the player breaks into a run and she cannot keep up.
	var seen: Dictionary = {}
	var d: Array[int] = []
	var here := Vector2i(21, 20)
	var tick: float = cr.tick_seconds()
	for _i in range(14):
		here += Vector2i(2, 0)
		cr.note_player(here)
		for _t in range(maxi(1, int(round(float(ru.value("walk.step_time", {}, 0.17)) / tick)))):
			cr.think(tick)
		d.append(cr.distance_to_player(key))
		seen[cr.state_of(key)] = true
	print("    distance: %s" % _series(d))
	print("    states seen: %s" % ", ".join(PackedStringArray(seen.keys())))
	_check(seen.has("waiting_up"), "she stops rather than sprinting after you")
	_check(cr.state_of(key) == "lost", "and is lost past 12 cells")
	_check(g.has_tag("escort_failed"),
		"the failure set an ordinary run tag, so a quest can read it")
	print("    -- built from the shipped vocabulary with no engine change")
	cr.use_species([])


# --- 6: it survives being killed -------------------------------------------------

func _survives_a_save_and_load() -> void:
	print("")
	print("persistence: the dog is still following after the app dies")
	cr.use_species([])
	cr._species_loaded = false        # back to the shipped catalogue
	var world = _field()
	var key := _place(world, "dog", Vector2i(20, 20))
	cr.note_player(Vector2i(21, 20))
	cr.event(key, "petted")
	_walk(key, _line(Vector2i(21, 20), Vector2i(1, 0), 6))
	var was: Vector2i = cr.cell_of(key)
	cr.save_state()

	# Everything in memory goes, exactly as it does when Android kills the app.
	cr.use_placements([{"key": key, "critter": "dog", "x": 20, "y": 20}])
	cr.use_world(world)
	var loaded: bool = cr.load_state()
	_check(loaded, "the saved set came back")
	_check(cr.cell_of(key) == was,
		"he is where he was (%s, expected %s)" % [cr.cell_of(key), was])
	_check(cr.state_of(key) == "following", "and still following")

	# A different run must not inherit yesterday's dog. The store keys on the
	# run's own seed, so this is what a new loop actually looks like.
	g.run.seed = 999
	cr.use_run_seed(999)
	_check(not cr.load_state(), "a save from another run is discarded")
	g.run.seed = 424242
	cr.use_run_seed(424242)


# --- 7: the read API the renderer is handed --------------------------------------

func _the_renderer_gets_what_it_needs() -> void:
	print("")
	print("renderer: views() is drawable without knowing anything else")
	var world = _field()
	var key := _place(world, "cat", Vector2i(20, 20))
	cr.note_player(Vector2i(19, 20))
	cr.event(key, "petted")
	cr.think(cr.tick_seconds())
	cr.animate(0.05)
	var views: Array = cr.views()
	_check(views.size() == 1, "one entry per live animal (%d)" % views.size())
	var v: Dictionary = views[0]
	print("    %s" % v)
	_check(v.has("sprite") and v.has("cell") and v.has("from") and v.has("t")
			and v.has("row") and v.has("col"),
		"it carries sprite, cell, from, t, row and col")
	_check(int(v["row"]) >= 0 and int(v["row"]) <= 3, "row is a sheet row")
	_check(int(v["col"]) >= 0 and int(v["col"]) <= 3, "col is a sheet column")
	var sheet: String = cr.sheet_path(String(v["sprite"]))
	_check(FileAccess.file_exists(sheet), "and the sheet exists: %s" % sheet)
	var homes: Dictionary = cr.home_cells()
	_check(homes.has(Vector2i(20, 20)),
		"home_cells names the placement, so the static prop can be suppressed")
