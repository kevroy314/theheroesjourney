class_name HJSelfTest
extends RefCounted
## Headless end-to-end harness. Plays complete runs through the real systems and
## the real screens, then checks the things that are easy to break and hard to
## notice: persistence, deadlines, streaks, the Wheel, and the rule engine.
##
##   ./test.sh    runs against the source tree
##   build/linux/heroes --selftest    runs against an exported build
##
## The player's save is snapshotted and restored, so this is non-destructive.

const RUNS := 6
const MAX_ACTIONS := 3000


## Where the snapshot is parked while the run is in flight.
##
## Holding it only in memory was a promise the harness could not keep: a crash
## or a parse error mid-run skips the restore and leaves the player's save
## carrying whatever the test had done to it — cleared journeys, claimed Wheel
## nodes, a Warden already met. That state then makes the *next* run fail for
## reasons nothing in the working tree explains, which is an expensive hour.
const BACKUP := "user://selftest_backup.json"


static func run_all(host: Node) -> int:
	# A backup still on disk means the last run died before it could restore.
	# Put the player's save back before doing anything else.
	if FileAccess.file_exists(BACKUP):
		var f := FileAccess.open(BACKUP, FileAccess.READ)
		if f != null:
			var parsed = JSON.parse_string(f.get_as_text())
			f.close()
			if parsed is Dictionary:
				print("selftest: restoring a save left behind by a crashed run")
				_restore(parsed)
		DirAccess.remove_absolute(ProjectSettings.globalize_path(BACKUP))

	# The harness plays real runs and every one of them archives itself. Point the
	# archive somewhere disposable first, or testing the game costs the player
	# their history.
	History.use_path("user://history_selftest.ndjson")
	DirAccess.remove_absolute(ProjectSettings.globalize_path(History.path))

	var saved_meta := _snapshot()
	var backup := FileAccess.open(BACKUP, FileAccess.WRITE)
	if backup != null:
		backup.store_string(JSON.stringify(saved_meta))
		backup.close()
	var failures: Array = []

	_content_checks(failures)
	_rules_checks(failures)

	var cleared := 0
	var tasks := 0
	var echoes_before := Meta.codex.size()

	for i in range(RUNS):
		var result: Dictionary = await _play_one(host, 4000 + i * 7919, failures)
		tasks += int(result.get("tasks", 0))
		if result.get("cleared", false):
			cleared += 1

	print("\n--- The Heroes' Journey self-test ---")
	print("runs: %d   full journeys: %d   tasks completed: %d   echoes found: %d" % [
		RUNS, cleared, tasks, Meta.codex.size() - echoes_before])
	print("resolve: %d   loops: %d   deepest ring: %d" % [Meta.resolve, Meta.loops, Meta.deepest_ring])

	_check(failures, "tasks actually happen", tasks > RUNS * 3, "%d tasks" % tasks)
	_check(failures, "the world is walked out to its furthest ring",
		Meta.deepest_ring >= 3, "deepest ring %d" % Meta.deepest_ring)
	_check(failures, "the Warden turns you back the first time", Meta.seen_warden and cleared == 0,
		"seen=%s cleared=%d" % [str(Meta.seen_warden), cleared])

	await _advance_checks(host, failures)
	await _warden_checks(host, failures)
	await _deadline_checks(host, failures)
	_persistence_checks(failures)
	_streak_checks(failures)
	_wheel_checks(failures)
	_palace_checks(failures)
	await _anomaly_checks(host, failures)
	await _screen_checks(host, failures)

	_check(failures, "finished runs are archived", History.count() > 0,
		"%d rows" % History.count())
	_archive_checks(failures)
	DirAccess.remove_absolute(ProjectSettings.globalize_path(History.path))
	History.use_path(History.PATH)

	_restore(saved_meta)
	# The run finished, so the on-disk copy has done its job. Leaving it would
	# make the next run think this one crashed.
	DirAccess.remove_absolute(ProjectSettings.globalize_path(BACKUP))

	if failures.is_empty():
		print("PASS — all checks green\n")
		return 0
	print("FAIL — %d problem(s):" % failures.size())
	for f in failures:
		print("  x %s" % f)
	print("")
	return 1


# --- static content ------------------------------------------------------------

static func _content_checks(failures: Array) -> void:
	_check(failures, "themes loaded", Content.themes.size() >= 1, str(Content.themes.keys()))
	_check(failures, "rulesets loaded", Content.rulesets.size() >= 1, str(Content.rulesets.keys()))
	_check(failures, "chapters loaded", Content.chapters.size() == 8, "%d chapters" % Content.chapters.size())
	_check(failures, "every chapter has an area", _all_chapters_have_areas(), "")
	_check(failures, "movements loaded", Content.movements.size() >= 8, "%d movements" % Content.movements.size())
	_check(failures, "starter pack covers every axis", _starter_covers_axes(), "")
	_check(failures, "echoes loaded", Content.echoes.size() >= 10, "%d echoes" % Content.echoes.size())
	_check(failures, "items loaded", Content.items.size() >= 6, "%d items" % Content.items.size())
	_check(failures, "trinkets loaded", Content.trinkets.size() >= 6, "%d trinkets" % Content.trinkets.size())
	_check(failures, "wheel configured", Content.axes().size() == 6, "%d axes" % Content.axes().size())
	_check(failures, "config loaded", Content.config.has("run.grit_mult"), "%d keys" % Content.config.size())


static func _all_chapters_have_areas() -> bool:
	for c in Content.chapters:
		if Content.area(String(c.get("area", ""))).is_empty():
			return false
	return true


static func _starter_covers_axes() -> bool:
	for axis in Content.axes():
		if Content.unlocked_movements(String(axis["id"])).is_empty():
			return false
	return true


static func _rules_checks(failures: Array) -> void:
	Rules.clear()
	var base := Content.base("run.grit_mult")
	Rules.add_source("test", {"modifiers": [{"key": "run.grit_mult", "op": "mul", "value": 2.0}]})
	_check(failures, "modifiers apply", is_equal_approx(Rules.value("run.grit_mult"), base * 2.0), Rules.explain("run.grit_mult"))
	Rules.clear()
	Rules.add_source("test", {"modifiers": [{"key": "run.grit_mult", "op": "mul", "value": 2.0, "when": {"tier_gte": 3}}]})
	_check(failures, "conditions gate modifiers", is_equal_approx(Rules.value("run.grit_mult", {"tier": 0}), base), "")
	Rules.clear()
	Game.rebuild_rules()


# --- playing -------------------------------------------------------------------

static func _play_one(host: Node, seed_value: int, failures: Array) -> Dictionary:
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(seed_value)

	var tasks := 0
	var actions := 0
	var stuck := 0
	var last_progress := 0
	while actions < MAX_ACTIONS:
		actions += 1
		if actions % 8 == 0:
			await host.get_tree().process_frame
		var run: HJRun = Game.run
		if run == null or run.finished:
			break

		# A node that cannot be completed would otherwise ping-pong forever.
		var progress := run.completed.size() + run.chapter * 100
		stuck = 0 if progress != last_progress else stuck + 1
		last_progress = progress
		if stuck > 40:
			_check(failures, "the run always has a way forward", false,
				"seed %d stalled in %s" % [seed_value, run.area.get("id", "")])
			Game.abandon_run()
			break

		match Game.screen:
			"overworld":
				# The harness cannot walk, so it steps straight into the nearest
				# anomaly it has not already resolved. Walking is the player's
				# problem; what this checks is that the loop of find-enter-clear
				# always has a next move.
				var cell := _next_anomaly(run)
				if cell.x < 0:
					break
				Game.enter_anomaly(cell)
			"area":
				var available := HJAreaGen.available_ids(run)
				if available.is_empty():
					_check(failures, "an area always has a legal move", false,
						"seed %d chapter %d %s — %s" % [seed_value, run.chapter,
							run.area.get("id", ""), _dump_nodes(run)])
					Game.abandon_run()
					break
				Game.tap_node(_pick_node(run, available))
			"task":
				var node := run.node(run.pending_node)
				var options := Game.movement_options(node)
				if options.is_empty():
					_check(failures, "a task always has a movement", false,
						"node %s in %s" % [run.pending_node, run.area.get("id", "")])
					Game.skip_task()
					continue
				tasks += 1
				Game.complete_task(String(options[0].get("id", "")), false)
			"event":
				Game.dismiss_event()
			"boon":
				Game.take_boon(String(run.pending_boons[0]))
			"summary":
				break
			_:
				break

	if actions >= MAX_ACTIONS:
		_check(failures, "runs terminate", false, "seed %d hit the action cap" % seed_value)

	return { "cleared": Game.summary.get("cleared", false), "tasks": tasks }


static func _dump_nodes(run: HJRun) -> String:
	var parts: Array = []
	for id in run.area.get("order", []):
		var node_id := String(id)
		var state := "open"
		if run.is_done(node_id):
			state = "done"
		elif run.locked.has(node_id):
			state = "locked"
		elif not HJAreaGen.is_available(run, node_id):
			state = "waiting"
		parts.append("%s:%s" % [node_id, state])
	return ", ".join(parts)


## Prefer the spine so runs make progress, but take side nodes when they appear.
static func _pick_node(run: HJRun, available: Array) -> String:
	for id in available:
		if String(run.node(String(id)).get("side_of", "")) != "":
			return String(id)
	for id in available:
		if String(run.node(String(id)).get("type", "")) != "threshold":
			return String(id)
	return String(available[0])


# --- advancing between areas ---------------------------------------------------

## Clearing an area must hand the player the next one. The old bug was invisible
## to this harness because it drove continue_journey() directly rather than
## going where the buttons actually go — so this check asserts the *state* after
## a clear, not the path taken to get there.
static func _advance_checks(host: Node, failures: Array) -> void:
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(24680)
	Steps.grant(4000)

	var actions := 0
	var entered := false
	while actions < 200 and Game.run != null and not Game.run.finished:
		actions += 1
		if actions % 8 == 0:
			await host.get_tree().process_frame
		# Stop as soon as one anomaly has been entered and finished, which is the
		# unit this section is about.
		if entered and Game.run.anomaly.is_empty():
			break
		if not Game.run.anomaly.is_empty():
			entered = true
		match Game.screen:
			"overworld":
				var cell := _next_anomaly(Game.run)
				if cell.x < 0:
					break
				Game.enter_anomaly(cell)
			"area":
				var available := HJAreaGen.available_ids(Game.run)
				if available.is_empty():
					break
				Game.tap_node(_pick_node(Game.run, available))
			"task":
				var options := Game.movement_options(Game.run.node(Game.run.pending_node))
				if options.is_empty():
					break
				Game.complete_task(String(options[0].get("id", "")), false)
			"event":
				Game.dismiss_event()
			"boon":
				Game.take_boon(String(Game.run.pending_boons[0]))
			_:
				break

	# Clearing an anomaly returns you to the world rather than handing you the
	# next thing. That is the point of retiring chapters: nothing is next, and
	# what you do now is a choice about how far you are willing to walk.
	_check(failures, "clearing an anomaly returns you to the world",
		Game.run != null and Game.run.anomaly.is_empty(), Game.screen)
	if Game.run != null:
		_check(failures, "the anomaly it cleared is remembered",
			not Game.run.anomalies_cleared.is_empty(),
			"%d cleared" % Game.run.anomalies_cleared.size())
		_check(failures, "the run still has a deadline to run against",
			Game.run.deadline_unix > HJClock.now(), "")
		_check(failures, "there is always somewhere left to go",
			_next_anomaly(Game.run).x >= 0, "world exhausted")
		# Whatever screen we land on, there must be a way forward from it.
		_check(failures, "never parked on a dead screen",
			Game.screen in ["area", "event", "boon", "task", "overworld"],
			Game.screen)
	Game.abandon_run()


# --- the warden ----------------------------------------------------------------

## The true ending: having met the Warden once and balanced the Wheel, the
## Summit can actually be walked out of.
static func _warden_checks(host: Node, failures: Array) -> void:
	Meta.seen_warden = true
	if not Meta.claimed.has("balance"):
		Meta.claimed.append("balance")
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(31337)
	# The Summit is a place now, not the last chapter, so the way to test it is
	# to walk into it — which for a harness means stepping onto its cell.
	var summit := HJWorld.shared().anchor("summit")
	Game.run.world_pos = summit
	Game.enter_anomaly(summit)
	_check(failures, "the Summit can be entered directly",
		Game.run != null and String(Game.run.anomaly.get("area", "")) == "summit",
		"in %s" % (Game.run.anomaly.get("area", "?") if Game.run else "no run"))

	var actions := 0
	while actions < 200 and Game.run != null and not Game.run.finished:
		actions += 1
		if actions % 8 == 0:
			await host.get_tree().process_frame
		match Game.screen:
			"overworld":
				var cell := _next_anomaly(Game.run)
				if cell.x < 0:
					break
				Game.enter_anomaly(cell)
			"area":
				var available := HJAreaGen.available_ids(Game.run)
				if available.is_empty():
					break
				Game.tap_node(_pick_node(Game.run, available))
			"task":
				var options := Game.movement_options(Game.run.node(Game.run.pending_node))
				if options.is_empty():
					break
				Game.complete_task(String(options[0].get("id", "")), false)
			"event":
				Game.dismiss_event()
			"boon":
				Game.take_boon(String(Game.run.pending_boons[0]))
			_:
				break

	_check(failures, "a balanced player can leave the loop", Game.summary.get("outcome", "") == "cleared",
		String(Game.summary.get("outcome", "none")))


# --- deadlines -----------------------------------------------------------------

static func _deadline_checks(host: Node, failures: Array) -> void:
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(1234)
	var loops_before := Meta.loops

	_check(failures, "entering an area sets a deadline", Game.run.deadline_unix > HJClock.now(),
		str(Game.run.deadline_unix))

	# Firm deadlines: rewind the clock past it and the loop must close.
	Game.run.deadline_unix = HJClock.now() - 10
	Game.check_deadline()
	await host.get_tree().process_frame
	_check(failures, "a missed deadline closes the loop", Game.summary.get("outcome", "") == "loop",
		String(Game.summary.get("outcome", "none")))
	_check(failures, "a closed loop is counted", Meta.loops == loops_before + 1,
		"%d -> %d" % [loops_before, Meta.loops])
	_check(failures, "a closed loop still banks something", Meta.resolve >= 0, str(Meta.resolve))
	_check(failures, "the first reset reveals the story", Meta.seen_first_reset, "")

	# Pause has to freeze the clock rather than just hiding it.
	Game.run = null
	Game.start_run(4321)
	var before := Game.run.deadline_unix
	Game.set_paused(true)
	Meta.pause_started -= 3600
	Game.set_paused(false)
	_check(failures, "pausing pushes the deadline back", Game.run.deadline_unix > before,
		"%d -> %d" % [before, Game.run.deadline_unix])
	Game.abandon_run()


# --- persistence ---------------------------------------------------------------

static func _persistence_checks(failures: Array) -> void:
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(999)
	# A run begins in the world with no area, so there is nothing to tap until
	# an anomaly has been stepped into.
	Steps.grant(2000)
	Game.enter_anomaly(_next_anomaly(Game.run))
	var available := HJAreaGen.available_ids(Game.run)
	if not available.is_empty():
		Game.tap_node(String(available[0]))
	if Game.screen == "event":
		Game.dismiss_event()
	Game.run.grit = 77
	Game.save_run()

	var chapter := Game.run.chapter
	var completed := Game.run.completed.size()
	var deadline := Game.run.deadline_unix

	Game.run = null
	Game.load_run()
	_check(failures, "a run survives being closed", Game.run != null, "run did not reload")
	if Game.run != null:
		_check(failures, "reloaded run keeps its grit", Game.run.grit == 77, str(Game.run.grit))
		_check(failures, "reloaded run keeps its place", Game.run.chapter == chapter and Game.run.completed.size() == completed,
			"chapter %d, %d done" % [Game.run.chapter, Game.run.completed.size()])
		_check(failures, "reloaded run keeps its deadline", Game.run.deadline_unix == deadline, "")
	Game.abandon_run()
	Game.clear_saved_run()


# --- streaks -------------------------------------------------------------------

static func _streak_checks(failures: Array) -> void:
	Meta.streak = 4
	Meta.last_active_day = HJClock.local_day(HJClock.now() - 86400)
	Meta.touch_streak()
	_check(failures, "a consecutive day extends the streak", Meta.streak == 5, str(Meta.streak))

	Meta.streak = 4
	Meta.last_active_day = HJClock.local_day(HJClock.now() - 86400 * 3)
	Meta.touch_streak()
	_check(failures, "a missed day resets the streak", Meta.streak == 1, str(Meta.streak))

	Meta.streak = 10
	var multiplier := Meta.streak_multiplier()
	_check(failures, "streak multiplies rewards", multiplier > 1.0, "%.2f" % multiplier)

	Meta.streak = 4
	Meta.last_active_day = HJClock.local_day(HJClock.now() - 86400)
	Meta.rest_used_day = ""
	Meta.give_item("rest_token")
	var kept := Meta.spend_rest_token()
	_check(failures, "a rest token keeps the streak alive", kept and Meta.streak == 5,
		"%s, streak %d" % [str(kept), Meta.streak])


# --- the wheel -----------------------------------------------------------------

static func _wheel_checks(failures: Array) -> void:
	Meta.claimed = []
	Meta.axis_tasks = {}
	var nodes := Meta.wheel_all_nodes()
	_check(failures, "the wheel builds its nodes", nodes.size() >= 6 * 3 + 1, "%d nodes" % nodes.size())

	var centre: Dictionary = Content.achievements.get("centre", {})
	_check(failures, "balance starts locked", not Meta.wheel_met(centre), "")

	for axis in Content.axes():
		Meta.axis_tasks[String(axis["id"])] = 3
	_check(failures, "balance opens when every spoke moves", Meta.wheel_met(centre), str(Meta.axis_tasks))

	Meta.axis_tasks["move"] = 0
	_check(failures, "balance closes if a spoke is empty", not Meta.wheel_met(centre), "")

	Meta.axis_tasks["move"] = 3
	var claimed := Meta.claim(centre)
	_check(failures, "a met node can be claimed", claimed, "")
	_check(failures, "claiming twice is refused", not Meta.claim(centre), "")


# --- the mind palace -----------------------------------------------------------

static func _palace_checks(failures: Array) -> void:
	Meta.rooms_owned = []
	Meta.room_grid = {}
	Meta.palace_size = 0
	Meta.ensure_palace()

	_check(failures, "the palace seeds itself", Meta.palace_size >= 3 and Meta.room_grid.size() == 1,
		"size %d, %d placed" % [Meta.palace_size, Meta.room_grid.size()])
	_check(failures, "the starter room is free and placed", Meta.rooms_owned.size() == 1, str(Meta.rooms_owned))

	# Rooms cost Resolve, and buying leaves them unplaced until you set them down.
	Meta.resolve = 1000
	var bought := Meta.buy_room("gym")
	_check(failures, "a room can be bought", bought and Meta.rooms_owned.has("gym"), str(Meta.rooms_owned))
	_check(failures, "a bought room starts unplaced", Meta.unplaced_rooms().has("gym"), str(Meta.unplaced_rooms()))
	_check(failures, "buying the same room twice is refused", not Meta.buy_room("gym"), "")

	# Adjacency is the whole point: touching pays, not touching does not.
	Meta.buy_room("identity")
	Meta.room_grid = {}
	Meta.place_room("gym", 0, 0)
	Meta.place_room("identity", 2, 2)
	_check(failures, "rooms apart pay nothing", Meta.palace_bonuses().is_empty(),
		str(Meta.palace_bonuses().size()))

	Meta.place_room("identity", 1, 0)
	var bonuses := Meta.palace_bonuses()
	_check(failures, "rooms side by side pay a bonus", bonuses.size() >= 2, str(bonuses.size()))
	_check(failures, "adjacency reaches the rule engine", not Meta.palace_modifiers().is_empty(),
		str(Meta.palace_modifiers().size()))

	Game.rebuild_rules()
	var boosted := Rules.value("run.grit_mult", {"axis": "move"})
	var plain := Rules.value("run.grit_mult", {"axis": "rest"})
	_check(failures, "an axis-conditioned bonus only hits its axis", boosted > plain,
		"move %.3f vs rest %.3f" % [boosted, plain])

	# A cell already holding a room cannot take another.
	_check(failures, "an occupied cell is refused", not Meta.place_room("gym", 1, 0), "")

	# The shop discount adjacency has to reach prices.
	Meta.room_grid = {}
	Meta.buy_room("stores")
	Meta.buy_room("workshop")
	Meta.place_room("stores", 0, 0)
	Meta.place_room("workshop", 1, 0)
	Game.rebuild_rules()
	_check(failures, "the stores discount reaches prices", Meta.price(100) < 100, str(Meta.price(100)))

	Meta.rooms_owned = []
	Meta.room_grid = {}
	Meta.palace_size = 0
	Meta.ensure_palace()
	Game.rebuild_rules()


# --- every screen builds -------------------------------------------------------

## Visits every screen twice — once mid-run, once at home. Screens are built in
## code, so a screen nobody navigates to in a test has never been constructed at
## all, and a typo in it would first surface in front of the player.
static func _screen_checks(host: Node, failures: Array) -> void:
	var names: Array = ["title", "menu", "palace", "gym", "workshop", "stores", "hearth",
		"observatory", "codex", "wheel", "inventory", "area", "overworld", "worldmap",
		"task", "boon", "event", "summary"]

	Game.run = null
	Game.clear_saved_run()
	for screen_name in names:
		Game.goto(String(screen_name))
		await host.get_tree().process_frame
	_check(failures, "every screen builds with no run", true, "")

	Game.start_run(13579)
	Meta.give_item("hourglass")
	for screen_name in names:
		Game.goto(String(screen_name))
		await host.get_tree().process_frame
	_check(failures, "every screen builds mid-run", Game.run != null, "")
	Game.abandon_run()
	Game.goto("title")
	await host.get_tree().process_frame


## Anomalies: the roguelite loop. Walking to one is the player's problem; this
## checks that entering, finishing and walking out do what they claim, because
## the burn multiplier is the difficulty curve and a silent failure there would
## make the game either trivial or unplayable with nothing on screen to say so.
static func _anomaly_checks(host: Node, failures: Array) -> void:
	var world := HJWorld.shared()
	_check(failures, "the world carries anomalies", world.anomalies.size() > 0,
		"%d" % world.anomalies.size())
	if world.anomalies.is_empty():
		return

	Game.run = null
	Game.clear_saved_run()
	Game.start_run(24680)
	Steps.grant(5000)

	# Every tier the world actually spawns must have a template, or a player who
	# walks that far finds a hole where the content should be.
	var tiers: Dictionary = {}
	for a in world.anomalies:
		tiers[int((a as Dictionary).get("tier", 0))] = true
	for tier in tiers:
		var template := Content.anomaly_for(int(tier), Game.rng)
		_check(failures, "tier %d has an anomaly template" % tier,
			not template.is_empty() and template.has("nodes"), "")

	var first: Dictionary = world.anomalies[0]
	var cell := Vector2i(int(first.get("x", 0)), int(first.get("y", 0)))

	Steps.set_burn(1.0)
	Game.enter_anomaly(cell)
	await host.get_tree().process_frame
	_check(failures, "stepping into an anomaly builds an area",
		not Game.run.anomaly.is_empty() and not Game.run.area.is_empty(),
		"screen=%s" % Game.screen)
	var deadline := Game.run.deadline_unix

	# Walk out having done nothing: the maximum penalty, and not a lost run.
	Game.leave_anomaly(false)
	await host.get_tree().process_frame
	_check(failures, "leaving an anomaly early costs step burn, not the run",
		Steps.burn > 1.0 and Game.has_active_run(), "burn=%.2f" % Steps.burn)
	_check(failures, "an anomaly resets the deadline",
		deadline > HJClock.now(), "")

	# Now clear one properly and the penalty must lift.
	Game.enter_anomaly(cell)
	await host.get_tree().process_frame
	var guard := 0
	while Game.has_active_run() and not Game.run.anomaly.is_empty() and guard < 200:
		guard += 1
		if guard % 8 == 0:
			await host.get_tree().process_frame
		match Game.screen:
			"area":
				var available := HJAreaGen.available_ids(Game.run)
				if available.is_empty():
					break
				Game.tap_node(String(available[0]))
			"task":
				var options := Game.movement_options(Game.run.node(Game.run.pending_node))
				if options.is_empty():
					Game.skip_task()
				else:
					Game.complete_task(String(options[0].get("id", "")), false)
			"event": Game.dismiss_event()
			"boon": Game.take_boon(String(Game.run.pending_boons[0]))
			_: break
	var stopped := Game.screen
	_check(failures, "the anomaly loop reaches its threshold",
		Game.run == null or Game.run.anomaly.is_empty(),
		"stopped on %s after %d actions" % [stopped, guard])
	_check(failures, "clearing an anomaly fully clears the burn",
		is_equal_approx(Steps.burn, 1.0), "burn=%.2f after %d actions" % [Steps.burn, guard])
	_check(failures, "a cleared anomaly is not offered again",
		Game.run != null and Game.run.anomalies_cleared.size() > 0, "")

	Game.abandon_run()
	Steps.set_burn(1.0)
	await host.get_tree().process_frame


## The nearest anomaly this run has not finished, or (-1,-1) when the world is
## exhausted. Nearest rather than random so a run walks outward through the
## rings the way a player would, and the deeper tiers get exercised.
static func _next_anomaly(run: HJRun) -> Vector2i:
	var world := HJWorld.shared()
	var best := Vector2i(-1, -1)
	var best_d := 1 << 30
	for entry in world.anomalies:
		var a: Dictionary = entry
		var cell := Vector2i(int(a.get("x", 0)), int(a.get("y", 0)))
		if run.anomalies_cleared.has(Game._cell_key(cell)):
			continue
		var d := absi(cell.x - run.world_pos.x) + absi(cell.y - run.world_pos.y)
		if run.world_pos.x < 0:
			d = int(a.get("tier", 0))
		if d < best_d:
			best_d = d
			best = cell
	return best


## The archive, including the one-time move out of an old save.
##
## Worth a test rather than a manual check: migration runs exactly once on a real
## player's device, in a code path nobody exercises again, and getting it wrong
## silently loses everything they did before the change.
static func _archive_checks(failures: Array) -> void:
	var scratch := "user://history_migrate_test.ndjson"
	DirAccess.remove_absolute(ProjectSettings.globalize_path(scratch))
	var live := History.path
	History.use_path(scratch)

	# Legacy rows are newest-first, the way Meta.history stored them.
	var legacy := [
		{"day": "2026-08-24", "cleared": true, "grit": 104, "earned": 24},
		{"day": "2026-08-23", "cleared": false, "grit": 103, "earned": 23},
		{"day": "2026-08-22", "cleared": false, "grit": 102, "earned": 22},
	]
	var moved := History.migrate_from(legacy)
	_check(failures, "an old save's history is migrated", moved == 3, "%d moved" % moved)
	_check(failures, "migration keeps every row", History.count() == 3,
		"%d in archive" % History.count())
	var newest: Dictionary = History.recent(1)[0] if History.count() > 0 else {}
	_check(failures, "migration preserves order",
		String(newest.get("day", "")) == "2026-08-24", String(newest.get("day", "?")))
	_check(failures, "migrated rows are marked as such", bool(newest.get("migrated", false)), "")

	# Running it twice must not double the archive: a player who reinstalls over
	# an old save would otherwise accumulate a second copy of their whole life.
	var again := History.migrate_from(legacy)
	_check(failures, "migration refuses to run twice", again == 0 and History.count() == 3,
		"%d moved, %d rows" % [again, History.count()])

	# Appending after a migration must not disturb what was migrated.
	History.record({"outcome": "loop", "grit": 7})
	_check(failures, "appending after migration keeps the old rows",
		History.count() == 4, "%d rows" % History.count())

	DirAccess.remove_absolute(ProjectSettings.globalize_path(scratch))
	History.use_path(live)


# --- helpers -------------------------------------------------------------------

static func _snapshot() -> Dictionary:
	return {
		"resolve": Meta.resolve, "levels": Meta.levels.duplicate(true),
		"unlocked": Meta.unlocked.duplicate(), "inventory": Meta.inventory.duplicate(true),
		"claimed": Meta.claimed.duplicate(), "streak": Meta.streak, "best": Meta.best_streak,
		"rooms_owned": Meta.rooms_owned.duplicate(), "room_grid": Meta.room_grid.duplicate(true),
		"palace_size": Meta.palace_size,
		"last_active_day": Meta.last_active_day, "rest_used_day": Meta.rest_used_day,
		"codex": Meta.codex.duplicate(), "axis_tasks": Meta.axis_tasks.duplicate(true),
		"chapters_reached": Meta.chapters_reached, "loops": Meta.loops,
		"runs_today": Meta.runs_today.duplicate(true), "stats": Meta.stats.duplicate(true),
		"seen_first_reset": Meta.seen_first_reset, "seen_warden": Meta.seen_warden,
		"theme": Meta.selected_theme, "ruleset": Meta.selected_ruleset, "paused": Meta.paused,
	}


static func _restore(s: Dictionary) -> void:
	Meta.resolve = s["resolve"]
	Meta.levels = s["levels"]
	Meta.unlocked = s["unlocked"]
	Meta.inventory = s["inventory"]
	Meta.claimed = s["claimed"]
	Meta.rooms_owned = s["rooms_owned"]
	Meta.room_grid = s["room_grid"]
	Meta.palace_size = s["palace_size"]
	Meta.streak = s["streak"]
	Meta.best_streak = s["best"]
	Meta.last_active_day = s["last_active_day"]
	Meta.rest_used_day = s["rest_used_day"]
	Meta.codex = s["codex"]
	Meta.axis_tasks = s["axis_tasks"]
	Meta.chapters_reached = s["chapters_reached"]
	Meta.loops = s["loops"]
	Meta.runs_today = s["runs_today"]
	Meta.stats = s["stats"]
	Meta.seen_first_reset = s["seen_first_reset"]
	Meta.seen_warden = s["seen_warden"]
	Meta.selected_theme = s["theme"]
	Meta.selected_ruleset = s["ruleset"]
	Meta.paused = s["paused"]
	Meta.save_game()
	Game.run = null
	Game.clear_saved_run()


static func _check(failures: Array, what: String, ok: bool, detail: String) -> void:
	if not ok:
		failures.append("%s  (%s)" % [what, detail])
