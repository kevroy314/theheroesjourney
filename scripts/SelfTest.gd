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

## Disposable copies of the two story stores. Both are written to by ordinary
## play, so the harness must never be pointed at the real ones.
const OBJECTIVES_SCRATCH := "user://objectives_selftest.json"
const DIALOGUE_SCRATCH := "user://dialogue_selftest.json"
const BUFFS_SCRATCH := "user://buffs_selftest.json"
const DISCOVERY_SCRATCH := "user://discovery_selftest.json"
const CRITTERS_SCRATCH := "user://critters_selftest.json"

## Held for the length of a run, so two harnesses cannot overlap.
##
## They already have, and it cost a real save. BACKUP is one fixed path with no
## lock: process A snapshots the player's state and starts mutating it, process
## B snapshots *A's mutated state*, and whichever finishes last restores its own
## snapshot over the top. The developer came out of that with a Warden already
## met, a claimed Wheel node and a full Codex, on a save that had done none of
## those things — and the failures it caused looked like bugs in the working
## tree for an hour.
const LOCK := "user://selftest.lock"
## Old enough to be a corpse rather than a peer.
##
## A suite run is about three minutes, so ten is already three times the longest
## honest one. Thirty was the first guess and it was wrong in the expensive
## direction: a killed process — which happens, one agent killed another's Godot
## by accident this session — leaves the file behind, and every run for the next
## half hour is refused with no way to tell a corpse from a peer.
const LOCK_STALE_SECONDS := 600
## How long to queue behind a live run before giving up. Long enough for two
## full suites ahead of us, short enough that a genuinely wedged run does not
## hold CI all afternoon.
const LOCK_WAIT_SECONDS := 900.0


static func run_all(host: Node) -> int:
	if not await _take_lock(host):
		push_error("selftest: waited %ds for %s and it is still held"
			% [int(LOCK_WAIT_SECONDS), LOCK])
		print("selftest: gave up waiting for another run to finish. Two "
			+ "harnesses sharing one backup file destroys the save, so this "
			+ "one will not start.")
		return 1

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

	# Two more stores that ordinary play writes to, and both of them cost
	# something real. Every anomaly the harness closes would be recorded against
	# the player's own town objective, and the one conversation Spite is allowed
	# to have would be spent on a test. This has already happened once: a run
	# wrote closed-anomaly cells into a developer's store and the save had to
	# come back from a backup.
	#
	# The scratch files are removed *before* the redirect rather than after it.
	# `use_path` loads immediately, so deleting the file afterwards would leave
	# the last run's leftovers sitting in memory with nothing on disk to explain
	# them — which is the same failure wearing a different hat.
	# Buffs is the third and the worst of them: the checks below do not merely
	# write to it, they time-travel it, rewinding every timestamp in the file
	# hours into the past to prove that a buff expires while the app is shut.
	DirAccess.remove_absolute(ProjectSettings.globalize_path(OBJECTIVES_SCRATCH))
	DirAccess.remove_absolute(ProjectSettings.globalize_path(DIALOGUE_SCRATCH))
	DirAccess.remove_absolute(ProjectSettings.globalize_path(BUFFS_SCRATCH))
	Objectives.use_path(OBJECTIVES_SCRATCH)
	Dialogue.use_path(DIALOGUE_SCRATCH)
	Buffs.use_path(BUFFS_SCRATCH)
	# Six runs of walking would otherwise carve the harness's route into the
	# player's own fog, which is the whole thing History's comment warns about.
	_discard_scratch(DISCOVERY_SCRATCH, Discovery.PATH)
	Discovery.use_path(DISCOVERY_SCRATCH)
	_discard_scratch(CRITTERS_SCRATCH, Critters.SAVE_PATH)
	Critters.use_path(CRITTERS_SCRATCH)

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
	# Measured against an empty codex, not against whatever the person running
	# the harness happens to have found. Read from the ambient save this number
	# silently stops meaning anything the moment somebody has collected all
	# sixteen echoes — it prints zero forever and reads as a regression. The
	# snapshot above already holds the real codex and `_restore` puts it back.
	Meta.codex = []
	# The same treatment for the two pieces of save state the fuzz loop makes
	# assertions about. "The Warden turns you back the first time" is only a
	# statement about the game if the player has not already met them and has not
	# already claimed the balance that lets them walk out — read from the ambient
	# save it flips from a test into a report on whoever is running it, and a
	# developer who has finished the game once can never make it green again.
	Meta.seen_warden = false
	Meta.claimed = []

	for i in range(RUNS):
		var result: Dictionary = await _play_one(host, 4000 + i * 7919, failures)
		tasks += int(result.get("tasks", 0))
		if result.get("cleared", false):
			cleared += 1

	var echoes_found := Meta.codex.size()

	print("\n--- The Heroes' Journey self-test ---")
	print("runs: %d   full journeys: %d   tasks completed: %d   echoes found: %d" % [
		RUNS, cleared, tasks, echoes_found])
	print("resolve: %d   loops: %d   deepest ring: %d" % [Meta.resolve, Meta.loops, Meta.deepest_ring])

	_check(failures, "tasks actually happen", tasks > RUNS * 3, "%d tasks" % tasks)
	_check(failures, "the world is walked out to its furthest ring",
		Meta.deepest_ring >= 3, "deepest ring %d" % Meta.deepest_ring)
	_check(failures, "the Warden turns you back the first time", Meta.seen_warden and cleared == 0,
		"seen=%s cleared=%d" % [str(Meta.seen_warden), cleared])
	# Six runs that hand out no story at all is a real defect, and it used to
	# read as a quiet zero because the baseline came from the ambient save.
	_check(failures, "playing turns up story", echoes_found > 0,
		"%d echoes from %d runs" % [echoes_found, RUNS])

	await _advance_checks(host, failures)
	await _choice_checks(host, failures)
	await _warden_checks(host, failures)
	await _deadline_checks(host, failures)
	_persistence_checks(failures)
	_streak_checks(failures)
	_wheel_checks(failures)
	_palace_checks(failures)
	_reveal_checks(failures)
	await _anomaly_checks(host, failures)
	await _story_checks(host, failures)
	_buff_checks(failures)
	_interactable_checks(failures)
	_tutorial_checks(failures)
	await _screen_checks(host, failures)

	_check(failures, "finished runs are archived", History.count() > 0,
		"%d rows" % History.count())
	_archive_checks(failures)
	_discard_scratch(History.path, History.PATH)
	History.use_path(History.PATH)

	_discard_scratch(Objectives.path, Objectives.PATH)
	_discard_scratch(Dialogue.path, Dialogue.PATH)
	Objectives.use_path(Objectives.PATH)
	Dialogue.use_path(Dialogue.PATH)

	# Whatever the harness left running is not the player's. Clearing before the
	# redirect so the scratch file goes with it, then pointing back at the real
	# one, which reloads and settles it exactly as a cold start would.
	Buffs.clear_all()
	_discard_scratch(Buffs.path, Buffs.SAVE_PATH)
	Buffs.use_path(Buffs.SAVE_PATH)
	_discard_scratch(DISCOVERY_SCRATCH, Discovery.PATH)
	Discovery.use_path(Discovery.PATH)
	_discard_scratch(CRITTERS_SCRATCH, Critters.SAVE_PATH)
	Critters.use_path(Critters.SAVE_PATH)

	_restore(saved_meta)
	# The run finished, so the on-disk copy has done its job. Leaving it would
	# make the next run think this one crashed.
	DirAccess.remove_absolute(ProjectSettings.globalize_path(BACKUP))
	_release_lock()

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
	# Schema, references and vocabulary, checked against data/schema.json. The
	# self-test only ever finds a broken rule by playing over it, and a rule that
	# quietly does nothing plays exactly like a rule that legally did nothing —
	# so this is the one check here that does not need a seed to get lucky.
	# tools/validate_data.py runs the rest (the GDScript source scan) in CI.
	var problems: Array = Content.validate()
	for problem in problems:
		failures.append("content: %s" % problem)
	_check(failures, "content passes schema validation", problems.is_empty(),
		"%d problem(s)" % problems.size())

	_check(failures, "themes loaded", Content.themes.size() >= 1, str(Content.themes.keys()))
	_check(failures, "rulesets loaded", Content.rulesets.size() >= 1, str(Content.rulesets.keys()))
	_check(failures, "named areas loaded", Content.areas.size() == 8, "%d areas" % Content.areas.size())
	_check(failures, "every named world region resolves to an area",
		_all_regions_have_areas(), "")
	_check(failures, "movements loaded", Content.movements.size() >= 8, "%d movements" % Content.movements.size())
	_check(failures, "starter pack covers every axis", _starter_covers_axes(), "")
	_check(failures, "echoes loaded", Content.echoes.size() >= 10, "%d echoes" % Content.echoes.size())
	_check(failures, "items loaded", Content.items.size() >= 6, "%d items" % Content.items.size())
	_check(failures, "trinkets loaded", Content.trinkets.size() >= 6, "%d trinkets" % Content.trinkets.size())
	_check(failures, "wheel configured", Content.axes().size() == 6, "%d axes" % Content.axes().size())
	_check(failures, "config loaded", Content.config.has("run.grit_mult"), "%d keys" % Content.config.size())


## Every anchor the world generator writes must name an area that exists. This
## used to check the chapter list; the world's own region table is the honest
## replacement, because it is what `enter_anomaly` actually reads.
static func _all_regions_have_areas() -> bool:
	for id in HJWorld.shared().regions.keys():
		if Content.area(String(id)).is_empty():
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
		var progress := run.completed.size() + run.zone * 100 + run.anomalies_cleared.size() * 10
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
						"seed %d ring %d %s — %s" % [seed_value, run.zone,
							run.area.get("id", ""), _dump_nodes(run)])
					Game.abandon_run()
					break
				Game.tap_node(_pick_node(run, available))
			"task":
				var node := run.node(run.pending_node)
				if String(node.get("type", "")) == "choice":
					_answer(node, seed_value)
					continue
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


## Claim the lock, **waiting** for it rather than refusing.
##
## The first version refused outright, which was right about the danger and
## wrong about the remedy. Two harnesses sharing one backup file destroys the
## save — that part stands — but refusing turns every collision into a failed
## run somebody has to notice and retry, and with several agents testing at once
## the retries cost more than the collisions ever did. Queueing serialises them
## instead: the second run waits its turn and then passes.
##
## A lock left by a killed process would block everything, so one older than
## LOCK_STALE_SECONDS is treated as abandoned and taken.
static func _take_lock(host: Node) -> bool:
	var waited := 0.0
	while FileAccess.file_exists(LOCK):
		var age := HJClock.now() - int(FileAccess.get_modified_time(LOCK))
		if age >= LOCK_STALE_SECONDS:
			print("selftest: taking a lock %d seconds old; assuming it was abandoned" % age)
			break
		if waited >= LOCK_WAIT_SECONDS:
			return false
		if waited == 0.0:
			print("selftest: another run holds the lock; waiting for it")
		await host.get_tree().create_timer(2.0).timeout
		waited += 2.0
	if waited > 0.0:
		print("selftest: lock free after %ds, starting" % int(waited))
	var f := FileAccess.open(LOCK, FileAccess.WRITE)
	if f == null:
		# Cannot write the lock: better to run than to refuse forever on a
		# read-only user dir.
		return true
	f.store_string(str(HJClock.now()))
	f.close()
	return true


static func _release_lock() -> void:
	if FileAccess.file_exists(LOCK):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(LOCK))


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


## Answer the choice node sitting in the task slot.
##
## The harness used to assume the run's pending thing was always a movement. A
## `choice` node borrows `run.pending_node` and the task screen without being a
## task: it has no movement, so `movement_options` comes back empty, and the
## `skip_task()` fallback then put the node straight back in the available set —
## tapped and re-offered for ever, which reads as a stall a long way from the
## line at fault. `salt` varies the answer so a suite of seeds walks the
## survey's conditional branches rather than only its unconditional default.
static func _answer(node: Dictionary, salt: int) -> void:
	var options: Array = node.get("options", [])
	HJSurvey.answer(String(Game.run.pending_node), salt % maxi(1, options.size()), "Ada")


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
				var pending := Game.run.node(Game.run.pending_node)
				if String(pending.get("type", "")) == "choice":
					_answer(pending, actions)
					continue
				var options := Game.movement_options(pending)
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


# --- being asked something ------------------------------------------------------

## A choice node is not a task, and the one place that matters is `skip_task`.
##
## It borrows `run.pending_node` and the task screen, so every caller that
## reaches for the task vocabulary reaches it too — and skipping is the only bit
## of that vocabulary that is wrong here. Backing out of ten push-ups is a real
## answer; backing out of a question is not, and clearing `pending_node` without
## finishing the node put the same question straight back in the available set.
## The harness span on that for two hundred actions before anybody saw it, so
## the guard is worth a test of its own.
static func _choice_checks(host: Node, failures: Array) -> void:
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(550001)
	Steps.grant(2000)
	# The waking room is a named cell, so stepping onto it always builds the
	# survey rather than drawing from the tier's pool.
	var cell := HJWorld.shared().anchor("waking_room")
	Game.enter_anomaly(cell)
	await host.get_tree().process_frame
	_check(failures, "the waking room is the survey",
		String(Game.run.area.get("id", "")) == "waking_room",
		String(Game.run.area.get("id", "?")))

	var available := HJAreaGen.available_ids(Game.run)
	_check(failures, "the survey opens on a question", not available.is_empty(),
		_dump_nodes(Game.run))
	if available.is_empty():
		Game.abandon_run()
		return
	var first := String(available[0])
	Game.tap_node(first)
	var node := Game.run.node(first)
	_check(failures, "a question is a choice node, not a task",
		String(node.get("type", "")) == "choice" and Game.run.pending_node == first,
		"%s, pending '%s'" % [String(node.get("type", "?")), Game.run.pending_node])
	_check(failures, "a question asks for no movement",
		Game.movement_options(node).is_empty(),
		"%d movements" % Game.movement_options(node).size())

	# The regression guard: skipping must not quietly un-ask the question.
	Game.skip_task()
	_check(failures, "backing out of a question does not count as answering it",
		Game.run.pending_node == first and not Game.run.is_done(first),
		"pending '%s', done=%s" % [Game.run.pending_node, str(Game.run.is_done(first))])

	# And answering it does.
	_answer(node, 1)
	_check(failures, "answering a question finishes it",
		Game.run.pending_node == "" and Game.run.is_done(first),
		"pending '%s', done=%s" % [Game.run.pending_node, str(Game.run.is_done(first))])
	_check(failures, "an answer is a tag the rest of the area can read",
		not Game.run.tags.is_empty(), str(Game.run.tags))

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
	# The Summit is a place, not the last of a sequence, so the way to test it is
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
				var pending := Game.run.node(Game.run.pending_node)
				if String(pending.get("type", "")) == "choice":
					_answer(pending, actions)
					continue
				var options := Game.movement_options(pending)
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

	var zone := Game.run.zone
	var completed := Game.run.completed.size()
	var deadline := Game.run.deadline_unix

	Game.run = null
	Game.load_run()
	_check(failures, "a run survives being closed", Game.run != null, "run did not reload")
	if Game.run != null:
		_check(failures, "reloaded run keeps its grit", Game.run.grit == 77, str(Game.run.grit))
		_check(failures, "reloaded run keeps its place",
			Game.run.zone == zone and Game.run.completed.size() == completed,
			"ring %d, %d done" % [Game.run.zone, Game.run.completed.size()])
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
		"task", "boon", "event", "summary", "dialogue"]

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
	await _layout_checks(host, failures)

	Game.abandon_run()
	Game.goto("title")
	await host.get_tree().process_frame


## Layout, asserted rather than eyeballed.
##
## Three separate papercuts shipped in one pass — a toast on top of the action
## button, a speaker's name set one letter per line, and a default that put the
## toast across the run header — and all three were "verified" by looking at a
## screenshot of a path that happened to look fine. A screenshot proves one
## frame. These prove the property, on every run, in eight seconds.
static func _layout_checks(host: Node, failures: Array) -> void:
	# The toast column must clear the bottom controls.
	Game.goto("overworld")
	# Two frames: one to build, one for the container to lay its children out.
	await host.get_tree().process_frame
	await host.get_tree().process_frame
	var was_pos := Meta.ui_toast_pos
	Meta.ui_toast_pos = "bottom"
	host.call("_place_toasts")
	var screen: Node = host.get("current")
	var act: Control = screen.get("_act") if screen != null else null
	if act != null and is_instance_valid(act) and act.size.y > 0.0:
		var toasts: Control = host.get("toasts")
		# Both measured from the bottom edge of the frame, which is what the
		# toast column is anchored to.
		var band_bottom := -float(toasts.offset_bottom)
		# The toast column is anchored to the frame, which fills the viewport, so
		# the viewport's height is the right zero to measure both from.
		var frame_h := act.get_viewport_rect().size.y
		var act_top := frame_h - act.global_position.y
		_check(failures, "a bottom toast clears the action button",
			band_bottom >= act_top,
			"band %.0f from the bottom, button top %.0f" % [band_bottom, act_top])
	else:
		_check(failures, "the walk screen has a laid-out action button", false,
			"no _act to measure")
	Meta.ui_toast_pos = was_pos
	host.call("_place_toasts")

	# A word must not be broken down the screen.
	#
	# Squeezed into a shrink-wrapped container, "Tobin" set one letter per line
	# and still passed every check there was, because none of them looked at a
	# Label. The general form of that bug is a label given less width than one
	# word needs, so the rule is general: a run of text with no spaces in it may
	# not occupy more lines than it has words.
	# The doorstep conversation is `once: true`, and by this point in the harness
	# it has already been seen — which is precisely why the first version of this
	# check passed while the bug was in the tree. It found no dialogue at all and
	# reported success. Forget it first, so the check always has something to
	# measure, and assert that it really opened.
	Dialogue.seen.erase("spite_doorstep")
	var opened := Dialogue.start("spite_doorstep")
	_check(failures, "the doorstep conversation opens for the layout check",
		opened and Dialogue.active(), "start=%s" % opened)
	if opened:
		Game.goto("dialogue")
		await host.get_tree().process_frame
		await host.get_tree().process_frame
		var squeezed := ""
		var lines := 0
		for node in _labels(host.get("current")):
			var label: Label = node
			var text := label.text.strip_edges()
			if text == "":
				continue
			var words: int = text.split(" ", false).size()
			if label.get_line_count() > maxi(1, words):
				squeezed = text
				lines = label.get_line_count()
				break
		_check(failures, "no label breaks a word down the screen",
			squeezed == "", "'%s' takes %d lines" % [squeezed, lines])
		Dialogue.stop()


## Every Label under a node, depth first.
static func _labels(root: Node) -> Array:
	var out: Array = []
	if root == null:
		return out
	if root is Label:
		out.append(root)
	for child in root.get_children():
		out.append_array(_labels(child))
	return out


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
				var pending := Game.run.node(Game.run.pending_node)
				if String(pending.get("type", "")) == "choice":
					_answer(pending, guard)
					continue
				var options := Game.movement_options(pending)
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

	_discard_scratch(scratch, History.PATH)
	History.use_path(live)


# --- the reveal ladder ---------------------------------------------------------

## Which rooms a save can see, and when. `reveal_after` in rooms.json is the
## ladder, and it is content rather than code — which is exactly why it needs a
## test: reordering it is a one-line edit in a JSON file that nothing else
## would notice was wrong.
static func _reveal_checks(failures: Array) -> void:
	# God mode shows everything, so a developer who left it on would make every
	# assertion below vacuously true.
	var was_god := Debug.god
	Debug.god = false
	Meta.revealed = []
	Meta.rooms_owned = []
	Meta.room_grid = {}
	Meta.palace_size = 0
	Meta.ensure_palace()

	_check(failures, "a fresh save can already see the Hearth",
		Meta.room_revealed("hearth"), str(Meta.rooms_owned))
	_check(failures, "a fresh save cannot yet see the Observatory",
		not Meta.room_revealed("observatory"), str(Meta.rooms_owned))
	_check(failures, "the Observatory sits one rung above the Workshop",
		String(Content.room("observatory").get("reveal_after", "")) == "workshop",
		String(Content.room("observatory").get("reveal_after", "?")))

	Meta.resolve = 1000
	var bought := Meta.buy_room("workshop")
	_check(failures, "the rung below the Observatory can be bought", bought, str(Meta.rooms_owned))
	_check(failures, "buying the Workshop reveals the Observatory",
		Meta.room_revealed("observatory"), str(Meta.rooms_owned))

	Debug.god = was_god
	Meta.revealed = []
	Meta.rooms_owned = []
	Meta.room_grid = {}
	Meta.palace_size = 0
	Meta.ensure_palace()
	Game.rebuild_rules()


# --- the story layer -----------------------------------------------------------

## Dialogue, objectives and the Finder — the three halves of Beat 6.
##
## The conversation is walked the way a player walks it rather than driven node
## by node, because the interesting failures are all in the seams: a reply that
## is visible when it should not be, a `next` that ends the conversation instead
## of following it, an effect that fires twice. None of those show up if the
## test reaches into the graph and asserts about the data.
static func _story_checks(host: Node, failures: Array) -> void:
	# Both stores are scratch copies, but earlier sections have already played
	# thirty-odd anomalies over them. Start from nothing so "the objective is
	# active" is a statement about `start()` rather than about the fuzz loop.
	Objectives.wipe()
	Dialogue.wipe()

	var dialogue_problems := Dialogue.problems()
	for problem in dialogue_problems:
		failures.append("dialogue: %s" % problem)
	_check(failures, "every conversation's gotos and conditions resolve",
		dialogue_problems.is_empty(), "%d problem(s)" % dialogue_problems.size())

	var objective_problems := Objectives.problems()
	for problem in objective_problems:
		failures.append("objectives: %s" % problem)
	_check(failures, "every objective's goal is one the code implements",
		objective_problems.is_empty(), "%d problem(s)" % objective_problems.size())

	_finder_checks(failures)

	# --- walking the doorstep conversation end to end --------------------------
	var doc: Dictionary = Content.dialogues.get("spite_doorstep", {})
	_check(failures, "Spite is waiting on the doorstep in the data",
		not doc.is_empty() and bool(doc.get("once", false)),
		"%d node(s)" % (doc.get("nodes", []) as Array).size())
	if doc.is_empty():
		return
	_check(failures, "the gift node still carries the reply gated on how far you have walked",
		_gated_reply_index("spite_doorstep", "gift") >= 0, "no zone_gte reply")

	Game.run = null
	Game.clear_saved_run()
	Game.start_run(510001)
	Game.run.zone = 0

	_check(failures, "an unseen once-only conversation is on offer",
		Dialogue.available("spite_doorstep"), "already seen")
	_check(failures, "the doorstep conversation starts", Dialogue.start("spite_doorstep"),
		"start() refused")
	var view := Dialogue.current()
	_check(failures, "a conversation opens on the first line of its first node",
		String(view.get("node", "")) == "arrival" and int(view.get("line", 0)) == 1,
		"%s line %d" % [String(view.get("node", "?")), int(view.get("line", 0))])
	_check(failures, "replies stay hidden until the speaker has finished talking",
		(view.get("replies", []) as Array).is_empty() and bool(view.get("can_continue", false)),
		"%d replies on line 1" % (view.get("replies", []) as Array).size())

	_advance_to_last_line("arrival")
	view = Dialogue.current()
	_check(failures, "the last line of a node is where the replies appear",
		(view.get("replies", []) as Array).size() == 3 and not bool(view.get("can_continue", true)),
		"%d replies" % (view.get("replies", []) as Array).size())

	# A tap on an unanswered question must do nothing at all — not advance, not
	# fall through to the next node, not end.
	Dialogue.advance()
	var after := Dialogue.current()
	_check(failures, "tapping past an unanswered question does nothing",
		String(after.get("node", "")) == "arrival" and int(after.get("line", 0)) == int(view.get("line", 0)),
		"%s line %d" % [String(after.get("node", "?")), int(after.get("line", 0))])

	Dialogue.choose(0)
	_check(failures, "choosing a reply moves the conversation on",
		String(Dialogue.current().get("node", "")) == "want",
		String(Dialogue.current().get("node", "?")))

	# --- the objective the conversation hands over -----------------------------
	_check(failures, "arriving at Spite's demand leaves the town objective running",
		Objectives.is_active("close_town_anomalies"),
		Objectives.state("close_town_anomalies"))

	_advance_to_last_line("want")
	Dialogue.choose(2)
	_check(failures, "a reply with no gate reaches the gift",
		String(Dialogue.current().get("node", "")) == "gift",
		String(Dialogue.current().get("node", "?")))
	_check(failures, "the gift node hands over the Finder", Meta.item_count("finder") > 0,
		"%d carried" % Meta.item_count("finder"))

	# --- the gate is the ordinary condition engine, not a second one -----------
	_advance_to_last_line("gift")
	Game.run.zone = 0
	var near_home: Array = Dialogue.current().get("replies", [])
	Game.run.zone = 3
	var far_out: Array = Dialogue.current().get("replies", [])
	_check(failures, "a reply gated on how far you have walked is hidden close to home",
		near_home.size() == 1, "%d replies at ring 0" % near_home.size())
	_check(failures, "the same reply appears once you have been out past the foothills",
		far_out.size() == 2, "%d replies at ring 3" % far_out.size())

	# --- once means once -------------------------------------------------------
	var take_it := -1
	for reply in far_out:
		if int((reply as Dictionary)["index"]) != _gated_reply_index("spite_doorstep", "gift"):
			take_it = int((reply as Dictionary)["index"])
	Dialogue.choose(take_it)
	var guard := 0
	while Dialogue.active() and guard < 40:
		guard += 1
		Dialogue.advance()
	_check(failures, "the conversation reaches its end", not Dialogue.active(),
		"still on %s after %d taps" % [String(Dialogue.current().get("node", "?")), guard])
	_check(failures, "a finished conversation is remembered", Dialogue.seen.has("spite_doorstep"), "")
	_check(failures, "a once-only conversation refuses to run twice",
		not Dialogue.start("spite_doorstep"), "started again")

	# --- the objective outlives the loop and the disk --------------------------
	var ring_zero := _ring_zero_cells()
	_check(failures, "the town has anomalies for the objective to count",
		ring_zero.size() >= 2, "%d in ring 0" % ring_zero.size())
	if ring_zero.size() < 2:
		Game.abandon_run()
		return

	Game.run.anomalies_cleared.append(Game._cell_key(ring_zero[0]))
	Game.changed()
	var closed_one := Objectives.progress("close_town_anomalies")
	_check(failures, "closing an anomaly moves the objective on",
		int(closed_one["done"]) == 1 and int(closed_one["total"]) == ring_zero.size(),
		"%d/%d" % [int(closed_one["done"]), int(closed_one["total"])])

	Game.end_run("loop")
	Game.start_run(510002)
	var after_loop := Objectives.progress("close_town_anomalies")
	_check(failures, "the loop takes the world back and leaves the errand standing",
		Objectives.is_active("close_town_anomalies")
			and int(after_loop["done"]) == int(closed_one["done"]),
		"%s %d/%d" % [Objectives.state("close_town_anomalies"),
			int(after_loop["done"]), int(after_loop["total"])])

	Objectives.load_store()
	var after_disk := Objectives.progress("close_town_anomalies")
	_check(failures, "the errand survives being read back off disk",
		Objectives.is_active("close_town_anomalies")
			and int(after_disk["done"]) == int(closed_one["done"])
			and int(after_disk["total"]) == int(closed_one["total"]),
		"%s %d/%d" % [Objectives.state("close_town_anomalies"),
			int(after_disk["done"]), int(after_disk["total"])])

	# --- and it pays exactly once ---------------------------------------------
	var reward := _resolve_reward("close_town_anomalies")
	_check(failures, "finishing the town is worth something", reward > 0, "%d resolve" % reward)
	var before_reward := Meta.resolve
	for i in range(1, ring_zero.size()):
		Game.run.anomalies_cleared.append(Game._cell_key(ring_zero[i]))
	Game.changed()
	_check(failures, "closing the last hole in town finishes the objective",
		Objectives.is_complete("close_town_anomalies"),
		Objectives.state("close_town_anomalies"))
	var paid := Meta.resolve - before_reward
	_check(failures, "finishing an objective pays its reward", paid == reward,
		"%+d, expected %+d" % [paid, reward])
	Game.changed()
	_check(failures, "an objective already finished does not pay again",
		Meta.resolve - before_reward == reward,
		"%+d after a second harvest" % (Meta.resolve - before_reward))

	Game.abandon_run()
	await host.get_tree().process_frame


## The Finder is a deliberately poor instrument, which makes it easy to get
## wrong in a way nobody notices: too honest and it is a map, too noisy and it
## is a random number. Both failures are invisible on screen.
static func _finder_checks(failures: Array) -> void:
	var ring_zero := _ring_zero_cells()
	if ring_zero.is_empty():
		_check(failures, "there is an anomaly to point the Finder at", false, "none in ring 0")
		return
	var here: Vector2i = ring_zero[0]
	var far := here + Vector2i(200, 200)
	_check(failures, "the Finder's target is open before it is read",
		not Objectives.is_cell_closed(here), "already closed")

	var now := float(HJClock.now())
	_check(failures, "the Finder reads high standing on a hole",
		Objectives.finder_reading_at(here, now) > 0.85,
		"%.3f" % Objectives.finder_reading_at(here, now))

	# One sample at range is not a measurement: the noise is a pair of sines and
	# a single unlucky moment can put it anywhere inside the noise band. What the
	# design promises is that the *reading* is low out there, so average it.
	var near_low := 1.0
	var far_total := 0.0
	var far_low := 1.0
	var far_high := 0.0
	var out_of_range := 0
	var samples := 64
	for i in range(samples):
		var t := now + float(i) * 0.7
		var near_reading := Objectives.finder_reading_at(here, t)
		var far_reading := Objectives.finder_reading_at(far, t)
		if near_reading < 0.0 or near_reading > 1.0 or far_reading < 0.0 or far_reading > 1.0:
			out_of_range += 1
		near_low = minf(near_low, near_reading)
		far_low = minf(far_low, far_reading)
		far_high = maxf(far_high, far_reading)
		far_total += far_reading
	var far_mean := far_total / float(samples)

	_check(failures, "no Finder reading escapes the bar it is drawn in",
		out_of_range == 0, "%d of %d samples outside 0..1" % [out_of_range, samples])
	_check(failures, "the Finder reads low a long walk away from anything",
		far_mean < 0.2, "mean %.3f over %d samples" % [far_mean, samples])
	_check(failures, "the Finder wobbles at range rather than sitting still",
		far_high - far_low > 0.05, "spread %.3f" % (far_high - far_low))
	_check(failures, "the Finder does not wobble away from a hole it is standing on",
		near_low > 0.6, "dipped to %.3f" % near_low)


## The index of the one reply on `node_id` that carries a `when`, or -1.
static func _gated_reply_index(dialogue_id: String, node_id: String) -> int:
	var replies: Array = Dialogue.node_of(dialogue_id, node_id).get("replies", [])
	for i in range(replies.size()):
		if not (replies[i] as Dictionary).get("when", {}).is_empty():
			return i
	return -1


## Tap through to the last line of the node the conversation is on.
static func _advance_to_last_line(node_id: String) -> void:
	var guard := 0
	while guard < 20:
		guard += 1
		var view := Dialogue.current()
		if String(view.get("node", "")) != node_id:
			return
		if int(view.get("line", 0)) >= int(view.get("lines", 0)):
			return
		Dialogue.advance()


static func _ring_zero_cells() -> Array[Vector2i]:
	var out: Array[Vector2i] = []
	for entry in HJWorld.shared().anomalies:
		var spawn: Dictionary = entry
		if int(spawn.get("tier", -1)) == 0:
			out.append(Vector2i(int(spawn.get("x", 0)), int(spawn.get("y", 0))))
	return out


static func _resolve_reward(objective_id: String) -> int:
	var total := 0
	for e in (Objectives.definition(objective_id).get("reward", []) as Array):
		var effect: Dictionary = e
		if String(effect.get("type", "")) == "resolve":
			total += int(round(float(effect.get("amount", 0))))
	return total


# --- buffs ---------------------------------------------------------------------

## A buff is only a bundle of modifiers, so most of what can go wrong is in the
## clock: a timer measured in frames, a chain that starts from now instead of
## from the expiry it is owed to, an expired buff that is still tuning numbers
## because nothing has swept it up yet. All three survive a screenshot.
static func _buff_checks(failures: Array) -> void:
	Game.run = null
	Game.clear_saved_run()
	Buffs.clear_all()
	Game.rebuild_rules()

	# --- a buff is an ordinary Rules source -----------------------------------
	var plain := Rules.value("run.grit_mult")
	_check(failures, "breakfast is in the catalogue",
		not Buffs.definition("breakfast").is_empty(), "no such buff")
	_check(failures, "breakfast applies", Buffs.apply("breakfast", true), "apply() refused")
	var fed := Rules.value("run.grit_mult")
	_check(failures, "breakfast is worth half again as much Grit, read through the rules",
		is_equal_approx(fed, plain * 1.5), Rules.explain("run.grit_mult"))

	var left := Buffs.seconds_left("breakfast")
	_check(failures, "breakfast runs for four hours", absi(left - 4 * 3600) <= 2, "%ds left" % left)
	var showing := Buffs.active()
	_check(failures, "a running buff is something the Steps counter can draw",
		showing.size() == 1 and String((showing[0] as Dictionary).get("icon", "")) == "fuel",
		"%d active, icon '%s'" % [showing.size(),
			String((showing[0] as Dictionary).get("icon", "")) if not showing.is_empty() else ""])

	Buffs.break_buff("breakfast", true)
	_check(failures, "the numbers go back where they were when a buff ends",
		is_equal_approx(Rules.value("run.grit_mult"), plain), Rules.explain("run.grit_mult"))

	# --- the wall clock runs while the app does not ---------------------------
	Buffs.apply("breakfast", true)
	Buffs.save_state()
	_check(failures, "the buff file is on disk to be rewound",
		_rewind_buffs(5 * 3600), "nothing written")
	Buffs.load_state()
	_check(failures, "four hours of breakfast does not survive five hours of being closed",
		not Buffs.has("breakfast"), "%ds left" % Buffs.seconds_left("breakfast"))
	_check(failures, "and the number it was bending comes back with it",
		is_equal_approx(Rules.value("run.grit_mult"), plain), Rules.explain("run.grit_mult"))

	# --- the chain settles from the expiry, not from now ----------------------
	Buffs.clear_all()
	Buffs.apply("coffee", true)
	_check(failures, "coffee is what the crash is chained to",
		String(Buffs.definition("coffee").get("then", "")) == "coffee_crash",
		String(Buffs.definition("coffee").get("then", "?")))
	_rewind_buffs(4 * 3600)
	Buffs.load_state()
	_check(failures, "three hours of coffee is spent after four hours away",
		not Buffs.has("coffee"), "still running")
	_check(failures, "and the crash it was borrowing against has started",
		Buffs.has("coffee_crash"), "no crash")
	var crash_left := Buffs.seconds_left("coffee_crash")
	# Two hours of crash that began when the coffee ended, an hour ago. Settling
	# from now instead would leave the whole two hours of it in front of you.
	_check(failures, "the crash is settled from when the coffee ended, not from now",
		absi(crash_left - 3600) <= 60, "%ds left, expected about 3600" % crash_left)
	_check(failures, "the crash makes every tile slower to walk",
		Steps.step_time() > 0.17, "%.3fs a tile" % Steps.step_time())

	_rewind_buffs(3 * 3600)
	Buffs.load_state()
	_check(failures, "a chain that has run out leaves nothing behind",
		Buffs.active().is_empty() and not Buffs.has("coffee_crash"),
		"%d still running" % Buffs.active().size())

	# --- a buff with no timer at all ------------------------------------------
	Steps.reset_run()
	Steps.grant(500)
	Buffs.clear_all()
	Buffs.apply("white_room", true)
	_check(failures, "the Boon of the White Room has no timer on it",
		Buffs.seconds_left("white_room") == -1, "%ds" % Buffs.seconds_left("white_room"))
	_check(failures, "walking is free inside the white room",
		is_zero_approx(Steps.step_cost()), "%.3f a tile" % Steps.step_cost())
	var spent_before := Steps.spent
	for i in range(20):
		Steps.spend(1)
	_check(failures, "twenty free tiles cost nothing", Steps.spent == spent_before,
		"%d -> %d" % [spent_before, Steps.spent])

	Buffs.save_state()
	Buffs.load_state()
	_check(failures, "a buff with no timer survives the app being closed",
		Buffs.has("white_room") and is_zero_approx(Steps.step_cost()),
		"%.3f a tile" % Steps.step_cost())

	_check(failures, "stepping outdoors breaks the boon", Buffs.trigger("outdoors") == 1,
		"nothing was listening")
	_check(failures, "and it is gone rather than merely quiet", not Buffs.has("white_room"), "")
	Steps.set_burn(1.0)
	spent_before = Steps.spent
	for i in range(3):
		Steps.spend(1)
	_check(failures, "the next three tiles cost three", Steps.spent == spent_before + 3,
		"%d -> %d" % [spent_before, Steps.spent])

	# --- expired but not yet swept up -----------------------------------------
	# `active()` and `sources()` both filter rather than settle, because a screen
	# that asked what to draw and got a state change back would rebuild itself
	# from inside its own build. That filter is the only thing standing between
	# the player and a buff that keeps working for the second before _process
	# notices, so it is worth an assertion of its own.
	Buffs.clear_all()
	Buffs.apply("breakfast", true)
	Buffs.shift(-5 * 3600)
	_check(failures, "an expired buff nobody has settled yet is still on the books",
		Buffs.has("breakfast"), "it settled early")
	_check(failures, "but it is not drawn", Buffs.active().is_empty(),
		"%d shown" % Buffs.active().size())
	_check(failures, "and it is not still bending numbers",
		_buff_source_names().is_empty() and is_equal_approx(Rules.value("run.grit_mult"), plain),
		Rules.explain("run.grit_mult"))

	# --- pausing, and the end of a run ----------------------------------------
	Buffs.clear_all()
	Buffs.apply("breakfast", true)
	var before_pause := Buffs.seconds_left("breakfast")
	Buffs.shift(600)
	var after_pause := Buffs.seconds_left("breakfast")
	_check(failures, "a paused night does not eat the breakfast you paid for",
		absi(after_pause - (before_pause + 600)) <= 2,
		"%ds -> %ds" % [before_pause, after_pause])

	Game.run = null
	Game.clear_saved_run()
	Game.start_run(520001)
	Buffs.apply("breakfast", true)
	Game.end_run("loop")
	_check(failures, "new run, new legs: the loop closing clears every buff",
		Buffs.active().is_empty() and not Buffs.has("breakfast"),
		"%d survived" % Buffs.active().size())
	Buffs.clear_all()
	Steps.reset_run()
	Game.rebuild_rules()


## Move every timestamp in the buff file back by `seconds`, which is the only
## honest way to test a wall clock: there is no injectable now(), and a test
## that waited four hours is not a test.
static func _rewind_buffs(seconds: int) -> bool:
	if not FileAccess.file_exists(Buffs.path):
		return false
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(Buffs.path))
	if not (parsed is Dictionary):
		return false
	var doc: Dictionary = parsed
	var rows: Array = doc.get("buffs", [])
	if rows.is_empty():
		return false
	for entry in rows:
		var e: Dictionary = entry
		e["started"] = int(e.get("started", 0)) - seconds
		if int(e.get("expires", 0)) > 0:
			e["expires"] = int(e.get("expires", 0)) - seconds
	var file := FileAccess.open(Buffs.path, FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(JSON.stringify(doc))
	file.close()
	return true


static func _buff_source_names() -> Array:
	var out: Array = []
	for source in Buffs.sources():
		out.append(String((source as Dictionary).get("name", "")))
	return out


# --- things in the world you can act on -----------------------------------------

## Interactables, on placements this file owns rather than on wherever the house
## agent has left the furniture. Where the stove stands is a design decision and
## it will move; that reach, price and tombstone all work is not, and a test
## that read the world file would break every time somebody dragged a door.
static func _interactable_checks(failures: Array) -> void:
	var real := HJWorld.shared().interactables
	var here := Vector2i(10, 10)
	Game.interactables.use_placements([
		{"x": 11, "y": 10, "type": "front_door", "label": "Front door"},
		{"x": 9, "y": 9, "type": "stove"},
		{"x": 10, "y": 11, "type": "dog"},
		{"x": 20, "y": 20, "type": "counter"},
	])

	Game.run = null
	Game.clear_saved_run()
	Game.start_run(530001)
	# Stand where the test says the player is standing. `interactables_near`
	# takes a cell, but `Game.interact` reads `run.world_pos` — which now holds
	# the real spawn rather than the (-1,-1) it used to, so a harness that
	# positioned itself only in the argument was reaching across the map. It
	# passed until `act()` learned to check reach, which is the check working.
	Game.run.world_pos = here
	Buffs.clear_all()
	Game.rebuild_rules()

	# --- reach ----------------------------------------------------------------
	var within := Game.interactables_near(here)
	var ids: Array = []
	for row in within:
		ids.append(String((row as Dictionary).get("id", "")))
	ids.sort()
	_check(failures, "everything beside you is within reach",
		ids.has("front_door") and ids.has("stove") and ids.has("dog"), str(ids))
	_check(failures, "and the thing across the room is not", not ids.has("counter"), str(ids))

	var door := _placed_row(within, "front_door")
	_check(failures, "the door is one of the things you can reach", not door.is_empty(), str(ids))
	if door.is_empty():
		Game.interactables.use_placements(real)
		Game.abandon_run()
		return

	# --- priced in data, worded in data ---------------------------------------
	var door_cost := int(round(Content.base("interact.door_cost")))
	_check(failures, "the door costs what the config says it costs",
		int(door["cost"]) == door_cost and door_cost == 25,
		"%d, config says %d" % [int(door["cost"]), door_cost])
	_check(failures, "the door's verb comes from the catalogue rather than the code",
		String(door["verb"]) == String(Content.interactable("front_door").get("verb", "")),
		String(door["verb"]))

	# --- the door is a purchase, and it is the exit ---------------------------
	var key := String(door["key"])
	Game.run.grit = 0
	_check(failures, "with no Grit the door will not open", not Game.interact(key), "it opened")
	_check(failures, "and a refused door leaves no mark on the run",
		not Game.has_tag("front_door_open"), str(Game.run.tags))

	Game.run.grit = 100
	_check(failures, "with Grit in hand the door opens", Game.interact(key), "it refused")
	_check(failures, "an open door is something the run remembers",
		Game.has_tag("front_door_open"), str(Game.run.tags))
	_check(failures, "opening the door costs exactly what it said it would",
		Game.run.grit == 100 - door_cost, "%d Grit left" % Game.run.grit)
	_check(failures, "a door already open cannot be bought again",
		not Game.interact(key), "it charged twice")
	_check(failures, "and refusing it costs nothing", Game.run.grit == 100 - door_cost,
		"%d Grit left" % Game.run.grit)

	# --- the stove pays for a buff, the dog is free ---------------------------
	var coffee_cost := int(round(Content.base("interact.coffee_cost")))
	Game.run.grit = 100
	Buffs.clear_all()
	_check(failures, "the stove makes coffee", Game.interact("stove@9,9"), "it refused")
	_check(failures, "coffee costs what the config says",
		Game.run.grit == 100 - coffee_cost, "%d Grit left" % Game.run.grit)
	_check(failures, "and leaves you with coffee running", Buffs.has("coffee"),
		str(Buffs.active().size()))

	Game.run.grit = 0
	_check(failures, "the dog does not charge you", Game.interact("dog@10,11"), "it refused")
	_check(failures, "and petting him leaves your Grit alone", Game.run.grit == 0,
		"%d Grit" % Game.run.grit)

	Buffs.clear_all()
	Game.interactables.use_placements(real)

	# --- the gate is a wall, not a label --------------------------------------
	# This one has to use the real placements: the world's own collision reads
	# the interactables out of overworld.json, which is the only way the door
	# can actually stop a path query.
	var world := HJWorld.shared()
	var door_cell := Vector2i(-1, -1)
	for entry in real:
		if entry is Dictionary and String((entry as Dictionary).get("type", "")) == "front_door":
			door_cell = Vector2i(int((entry as Dictionary).get("x", 0)),
				int((entry as Dictionary).get("y", 0)))
	_check(failures, "the world has a front door standing in it", door_cell.x >= 0,
		"%d placements" % real.size())
	if door_cell.x >= 0:
		Game.run = null
		Game.clear_saved_run()
		Game.start_run(530002)
		_check(failures, "a run that has not bought the door does not have the tag",
			not Game.has_tag("front_door_open"), str(Game.run.tags))
		_check(failures, "a shut front door is a cell you cannot walk onto",
			not world.walkable(door_cell.x, door_cell.y), str(door_cell))
		Game.run.tags.append("front_door_open")
		_check(failures, "and an open one is a cell you can",
			world.walkable(door_cell.x, door_cell.y), str(door_cell))

	Game.abandon_run()
	Buffs.clear_all()


static func _placed_row(rows: Array, id: String) -> Dictionary:
	for row in rows:
		if String((row as Dictionary).get("id", "")) == id:
			return row
	return {}


# --- the first thirty minutes ---------------------------------------------------

## The tutorial is a sequence of one-shots, and a one-shot is the hardest thing
## in the codebase to test by playing: by the time you notice it fired twice,
## the save that would have proved it is gone. Each beat here is un-fired first
## — `Meta.revealed` is in the snapshot, so that is safe — and then fired.
static func _tutorial_checks(failures: Array) -> void:
	var world := HJWorld.shared()
	_check(failures, "the house has an inside for the tutorial to be inside of",
		not world.indoors.is_empty(), "%d rooms" % world.indoors.size())

	# --- beat 1: the boon, and only on the first run --------------------------
	Meta.revealed.erase("beat:left_house")
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(540001)
	_check(failures, "a player who has never left the house wakes with the boon",
		Buffs.has("white_room"), str(Buffs.active().size()))
	Game.abandon_run()

	if not Meta.revealed.has("beat:left_house"):
		Meta.revealed.append("beat:left_house")
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(540002)
	_check(failures, "a player who has already been outside does not get it again",
		not Buffs.has("white_room"), str(Buffs.active().size()))
	Game.abandon_run()

	# --- beat 5: crossing the threshold ---------------------------------------
	Meta.revealed.erase("beat:left_house")
	Dialogue.stop()
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(540003)
	_check(failures, "the threshold beat starts with the boon to break",
		Buffs.has("white_room"), str(Buffs.active().size()))

	var inside := world.spawn
	_check(failures, "you wake up indoors", world.is_indoors(inside), str(inside))
	Game.tutorial.note_moved(inside)
	_check(failures, "walking about inside the house changes nothing",
		Buffs.has("white_room") and not Meta.revealed.has("beat:left_house"), str(inside))

	var outside := _outdoor_cell(world)
	_check(failures, "there is somewhere outside to walk to", outside.x >= 0, str(outside))
	if outside.x >= 0:
		# _story_checks already walked spite_doorstep, and `once: true` means he
		# will not come out twice. That is correct for a save and wrong for this
		# check, which is about the beat rather than about the leftovers of an
		# earlier section. Forget him first, so what follows tests the tutorial.
		Dialogue.wipe()
		Game.tutorial.note_moved(outside)
		_check(failures, "stepping outside breaks the Boon of the White Room",
			not Buffs.has("white_room"), str(Buffs.active().size()))
		_check(failures, "and the beat is marked as having happened",
			Meta.revealed.has("beat:left_house"), str(Meta.revealed.size()))

		# Beats 5 and 6 are the busiest moment in the game and until now nothing
		# checked the two things that make them a tutorial rather than a step:
		# somebody is waiting outside, and they give you a reason to walk.
		_check(failures, "Spite is on the doorstep the first time you go out",
			Dialogue.current().get("dialogue", "") == "spite_doorstep",
			"in %s, screen %s" % [Dialogue.current().get("dialogue", "-"), Game.screen])
		_check(failures, "and the game is showing him rather than the world",
			Game.screen == Dialogue.SCREEN, Game.screen)

		# Walk the conversation to its end, taking the first reply each time,
		# and the objective he hands over must be live at the other side.
		var turns := 0
		while turns < 40 and not Dialogue.current().is_empty() \
				and not bool(Dialogue.current().get("done", false)):
			var view: Dictionary = Dialogue.current()
			if bool(view.get("can_continue", false)):
				Dialogue.advance()
			elif not (view.get("replies", []) as Array).is_empty():
				Dialogue.choose(int((view["replies"][0] as Dictionary)["index"]))
			else:
				break
			turns += 1
		_check(failures, "the doorstep conversation reaches an end",
			turns < 40, "%d turns and still talking" % turns)
		_check(failures, "and it leaves you with somewhere to be",
			Objectives.is_active("close_town_anomalies") \
				or Objectives.is_complete("close_town_anomalies"),
			Objectives.state("close_town_anomalies"))
		_check(failures, "which the Hearth can show you",
			not Objectives.active().is_empty() or not Objectives.completed().is_empty(),
			"%d active" % Objectives.active().size())

		# Once. A beat that fires on every step outside would re-break a boon the
		# player had been given again, and re-introduce Spite for ever.
		Dialogue.stop()
		Buffs.apply("white_room", true)
		Game.tutorial.note_moved(outside)
		_check(failures, "crossing out a second time does not fire the beat again",
			Buffs.has("white_room"), "the boon broke twice")
	Buffs.clear_all()
	Dialogue.stop()
	Game.abandon_run()

	# --- beat 2: the first hole does not let go -------------------------------
	var closed_before := Meta.anomalies_closed
	Meta.anomalies_closed = 0
	Game.run = null
	Game.clear_saved_run()
	Game.start_run(540004)
	Steps.grant(2000)
	_check(failures, "standing in the world, nothing is holding you",
		not Game.tutorial.holds_you_in(), "held with no anomaly")
	var cell := _next_anomaly(Game.run)
	_check(failures, "there is an anomaly to be held by", cell.x >= 0, "world exhausted")
	if cell.x >= 0:
		Game.enter_anomaly(cell)
		_check(failures, "the first anomaly of a save will not let you walk back out",
			Game.tutorial.holds_you_in(), "screen=%s" % Game.screen)
		Meta.anomalies_closed = 1
		_check(failures, "every anomaly after the first one will",
			not Game.tutorial.holds_you_in(), "still held")
	Meta.anomalies_closed = closed_before
	Game.abandon_run()
	Buffs.clear_all()
	Steps.reset_run()


## A walkable cell outside every indoor rectangle, or (-1,-1).
static func _outdoor_cell(world: HJWorld) -> Vector2i:
	for entry in world.anomalies:
		var spawn: Dictionary = entry
		var cell := Vector2i(int(spawn.get("x", 0)), int(spawn.get("y", 0)))
		if not world.is_indoors(cell):
			return cell
	return Vector2i(-1, -1)


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
		# The tutorial beats are one-shots recorded here, and the checks below
		# have to un-fire them to test them at all.
		"revealed": Meta.revealed.duplicate(),
		# What the survey wrote down about the player. The harness answers five
		# questions a run and every answer is kept, so without this the person
		# running the test ends up remembered as whoever the fuzzer said it was.
		"self_description": Meta.self_description.duplicate(true),
		"deepest_ring": Meta.deepest_ring, "anomalies_closed": Meta.anomalies_closed,
		"loops": Meta.loops,
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
	Meta.revealed = s.get("revealed", Meta.revealed)
	Meta.self_description = s.get("self_description", Meta.self_description)
	Meta.deepest_ring = s["deepest_ring"]
	Meta.anomalies_closed = s["anomalies_closed"]
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


## Delete a scratch store, and refuse to delete anything that is not one.
##
## Every teardown here is two lines — remove the file, then point the store back
## at the player's own — and the two lines are only safe in that order. Reversed
## they delete the player's archive instead of the harness's, which is not a
## failing test but a support ticket, and the reversal is exactly the kind of
## thing a merge does quietly. So the deletion is told what the live path is and
## will not touch it.
static func _discard_scratch(scratch_path: String, live_path: String) -> void:
	if scratch_path == "" or scratch_path == live_path:
		push_error("selftest: refusing to delete '%s' — that is the live store" % scratch_path)
		return
	DirAccess.remove_absolute(ProjectSettings.globalize_path(scratch_path))


static func _check(failures: Array, what: String, ok: bool, detail: String) -> void:
	if not ok:
		failures.append("%s  (%s)" % [what, detail])
