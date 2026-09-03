extends Node
## Run orchestrator. Owns the run, drives the loop, and is the only thing that
## mutates player state. Screens call in here and listen to Events.

const RUN_PATH := "user://heroes_run.json"

var run: HJRun = null
var screen: String = "title"
## The screen before this one, so a screen reachable from two places can send
## the player back where they actually came from.
var previous_screen: String = "title"
var summary: Dictionary = {}
var event: Dictionary = {}     ## popup currently on the event screen
var rng := RandomNumberGenerator.new()


func boot() -> void:
	Palette.ensure_loaded()
	rebuild_rules()
	load_run()
	if run != null and not run.finished:
		check_deadline()
	goto("title")
	Notify.sync()


func goto(screen_name: String) -> void:
	if screen_name != screen:
		previous_screen = screen
	screen = screen_name
	Events.screen_changed.emit(screen_name)


## Where the app *should* be, computed from run state. Screens that find
## themselves on the wrong screen call this rather than guessing a destination —
## a guess made during build() can land after the next real transition and
## strand the app somewhere it does not belong.
func resync_screen(from_screen: String = "") -> void:
	# Deferred by a screen that thinks it is wrong. If something has legitimately
	# moved us on in the meantime, that decision wins.
	if from_screen != "" and screen != from_screen:
		return
	if run == null:
		goto("palace")
	elif run.finished:
		goto("summary")
	elif not event.is_empty():
		goto("event")
	elif not run.pending_boons.is_empty():
		goto("boon")
	elif run.pending_node != "":
		goto("task")
	elif run.area.is_empty():
		# No area means you are out in the world between anomalies, which is a
		# place, not a gap. The Journey is somewhere you choose to go.
		goto("overworld")
	else:
		goto("area")


func say(text: String, kind: String = "info") -> void:
	Events.logged.emit(text, kind)


func changed() -> void:
	save_run()
	Events.run_changed.emit()


# --- rules ---------------------------------------------------------------------

func rebuild_rules() -> void:
	Rules.clear()
	Rules.add_source("meta", {"modifiers": Meta.active_modifiers()})
	if run == null:
		Rules.add_source("ruleset", Content.ruleset(Meta.selected_ruleset))
		return
	Rules.add_source("ruleset", Content.ruleset(run.ruleset_id))
	for id in run.trinkets:
		Rules.add_source("trinket:" + String(id), Content.trinkets.get(id, {}))


# --- run lifecycle -------------------------------------------------------------

func has_active_run() -> bool:
	return run != null and not run.finished


func start_run(run_seed: int = 0, from_chapter: int = 1) -> void:
	run = HJRun.new()
	run.seed = run_seed if run_seed != 0 else randi()
	run.started_unix = HJClock.now()
	run.theme_id = Meta.selected_theme
	run.ruleset_id = Meta.selected_ruleset
	rng.seed = run.seed

	Palette.use(run.theme_id)
	rebuild_rules()
	# Second Wind, if one was spent on the loop that just closed.
	if Meta.resume_at.x >= 0:
		run.world_pos = Meta.resume_at
		run.zone = Meta.deepest_ring
		Meta.resume_at = Vector2i(-1, -1)
		Meta.save_game()
		say("You wake where you stood.", "good")

	# New run, new legs. The stipend exists so the first room is reachable
	# without having walked anywhere yet — you should never open the game to a
	# world you cannot move in.
	Steps.reset_run()
	Steps.grant(int(Rules.value("steps.starting_grant", run.ctx())))
	apply_effects(Rules.hook("on_run_start", run.ctx()))

	# You wake in the world, not in a chapter. There is no sequence to be at the
	# start of any more — the deadline runs until you find something, and what
	# you find is decided by how far you are willing to walk.
	run.zone = 0
	run.deadline_unix = HJClock.now() + HJClock.hours_to_seconds(
		maxf(1.0, 24.0 + Rules.value("area.deadline_bonus_hours", run.ctx(), 0.0)))
	Notify.sync()
	changed()
	goto("overworld")


func enter_chapter(index: int) -> void:
	var chapter := Content.chapter(index)
	if chapter.is_empty():
		end_run("cleared")
		return

	run.chapter = index
	run.completed = []
	run.locked = []
	run.revealed = false
	run.chosen_movement = ""
	run.pending_node = ""
	run.pending_boons = []

	var area_def := Content.area(String(chapter.get("area", "")))
	if area_def.is_empty():
		push_error("Game: chapter %d has no area definition" % index)
		end_run("cleared")
		return

	rng.seed = run.seed + index * 7919
	run.area = HJAreaGen.build(area_def, rng, run.ctx())

	var hours := float(chapter.get("deadline_hours", 24)) + Rules.value("area.deadline_bonus_hours", run.ctx(), 0.0)
	run.deadline_unix = HJClock.now() + HJClock.hours_to_seconds(maxf(1.0, hours))

	Meta.chapters_reached = maxi(Meta.chapters_reached, index)
	Meta.save_game()
	Notify.sync()

	apply_effects(Rules.hook("on_area_enter", run.ctx()))
	changed()
	goto("area")


func end_run(outcome: String) -> void:
	if run == null or run.finished:
		return
	run.finished = true
	run.outcome = outcome

	var cleared := outcome == "cleared"
	var ctx := run.ctx()
	var rate := Rules.value("run.resolve_rate", ctx, 0.25)
	var keep := Rules.value("run.loop_keep", ctx, 0.5)
	var earned := Meta.bank(run.grit, rate, keep, cleared)

	# Auto items act on the loop closing rather than on a tap.
	if not cleared:
		for id in Content.item_order:
			var item := Content.item(String(id))
			if String(item.get("where", "")) == "auto" and Meta.item_count(String(id)) > 0:
				if use_item(String(id)):
					Meta.take_item(String(id))

	var first_reset := false
	if not cleared and not Meta.seen_first_reset:
		Meta.seen_first_reset = true
		first_reset = true
		Meta.find_echo(String(Content.echo_reveals.get("first_loop_reset", "e01")))
		Meta.save_game()

	summary = {
		"outcome": outcome,
		"cleared": cleared,
		"grit": run.grit,
		"earned": earned,
		"zone": run.zone,
		"trinkets": run.trinkets.duplicate(),
		"echoes": run.echoes.duplicate(),
		"keep": keep,
		"rate": rate,
		"first_reset": first_reset,
		"repeats": Meta.runs_completed_today(),
	}
	# Archived after banking, so `earned` is the real number. Records what makes a
	# run distinguishable rather than only what it scored — where you got to, how
	# much of it you finished, and what walking it cost.
	History.record({
		"outcome": outcome,
		"cleared": cleared,
		"seed": run.seed,
		"zone": run.zone,
		"deepest_ring": Meta.deepest_ring,
		"anomalies_cleared": run.anomalies_cleared.size(),
		"grit": run.grit,
		"earned": earned,
		"steps_walked": Steps.walked,
		"steps_spent": Steps.spent,
		"final_burn": Steps.burn,
		"axis_tasks": run.axis_tasks.duplicate(),
		"echoes": run.echoes.duplicate(),
		"trinkets": run.trinkets.duplicate(),
		"minutes": int((HJClock.now() - run.started_unix) / 60),
	})

	Notify.sync()
	clear_saved_run()
	goto("summary")


func abandon_run() -> void:
	if has_active_run():
		end_run("abandoned")
	else:
		goto("palace")


## The deadline is firm. Missing it is the story, not a bug.
func check_deadline() -> bool:
	if not has_active_run() or Meta.paused:
		return false
	if not run.expired():
		return false
	say("The loop closes.", "bad")
	end_run("loop")
	return true


func tick() -> void:
	if has_active_run() and run.expired() and screen in ["area", "task", "worldmap", "boon", "event", "overworld"]:
		check_deadline()


# --- nodes ---------------------------------------------------------------------

func tap_node(id: String) -> void:
	if not has_active_run() or check_deadline():
		return
	if not HJAreaGen.is_available(run, id):
		return
	var node := run.node(id)

	match String(node.get("type", "")):
		"task":
			run.pending_node = id
			changed()
			goto("task")
		"free":
			_finish_node(id)
			_show_text(String(node.get("label", "")), String(node.get("text", "")))
		"echo":
			_finish_node(id)
			_give_echo()
		"cache":
			_finish_node(id)
			var amount := int(round(float(node.get("grit", 10)) * Rules.value("loot.cache_mult", run.ctx(), 1.0)))
			_add_grit(amount)
			_show_text("Worth Picking Up", "You pocket what's there. +%d %s." % [amount, Palette.word("grit")])
		"mirror":
			_finish_node(id)
			_mirror()
		"trinket":
			_finish_node(id)
			offer_boons()
		"spite":
			_finish_node(id)
			_spite()
		"warden":
			_warden(id)
		"threshold":
			_finish_node(id)
			# Inside an anomaly the threshold is the way out of *it*, not the way
			# on to the next chapter.
			if not run.anomaly.is_empty():
				leave_anomaly(true)
			else:
				clear_area()
	changed()


func _finish_node(id: String) -> void:
	if not run.completed.has(id):
		run.completed.append(id)
		# Doing the thing is what buys you more world. A task pays a flat stipend
		# and nudges the rate at which real steps convert, so a run where you do
		# the work opens up further than one where you do not — and the reward
		# for exercising is more room to explore, which is the whole thesis.
		Steps.grant(int(Rules.value("steps.reward_per_node", run.ctx())))
		Steps.set_multiplier(Steps.multiplier
			+ float(Rules.value("steps.multiplier_per_node", run.ctx())))
	# An exclusive fork closes its siblings the moment one is taken.
	for other_id in run.area.get("nodes", {}).keys():
		var other: Dictionary = run.area["nodes"][other_id]
		if not other.get("exclusive_next", false):
			continue
		var branches: Array = other.get("next", [])
		if branches.has(id):
			for sibling in branches:
				if String(sibling) != id and not run.locked.has(sibling):
					run.locked.append(sibling)


# --- tasks ---------------------------------------------------------------------

## Movements the player may pick for a node, resolving $choose / $other / literal.
func movement_options(node: Dictionary) -> Array:
	var token := String(node.get("task", {}).get("movement", ""))
	if token.begins_with("$choose:"):
		return Content.unlocked_movements(token.trim_prefix("$choose:"))
	if token.begins_with("$other:"):
		var axis := token.trim_prefix("$other:")
		var all := Content.unlocked_movements(axis)
		var others := all.filter(func(m): return String(m.get("id", "")) != run.chosen_movement)
		# With only the starter pack most axes have a single movement, so "do a
		# different one" has to fall back to "do that one again" rather than
		# handing the player a node they cannot complete. Buying a pack is what
		# turns this back into a real choice.
		return others if not others.is_empty() else all
	if token == "$same":
		var same := Content.movement(run.chosen_movement)
		return [] if same.is_empty() else [same]
	var literal := Content.movement(token)
	return [] if literal.is_empty() else [literal]


func task_units(node: Dictionary, movement: Dictionary) -> int:
	var units: Variant = node.get("task", {}).get("units", 1)
	if typeof(units) == TYPE_STRING and String(units) == "$set":
		return maxi(1, int(movement.get("set", 1)))
	return maxi(1, int(units))


## Seconds the confirm button stays disabled for. A speed bump, not a lie detector.
func task_seconds(node: Dictionary, movement: Dictionary) -> int:
	var units := task_units(node, movement)
	var per := float(movement.get("seconds_per_unit", 3))
	return maxi(int(Rules.value("task.min_seconds", run.ctx(), 3)), int(round(units * per)))


func complete_task(movement_id: String, scaled: bool) -> void:
	if not has_active_run() or run.pending_node == "":
		return
	var id := run.pending_node
	var node := run.node(id)
	var movement := Content.movement(movement_id)
	var axis := String(movement.get("axis", "move"))

	var token := String(node.get("task", {}).get("movement", ""))
	if token.begins_with("$choose:"):
		run.chosen_movement = movement_id

	var ctx := run.ctx({"axis": axis})
	var multiplier := Rules.value("run.grit_mult", ctx, 1.0) * Meta.streak_multiplier()
	if scaled and not run.full_scale:
		multiplier *= clampf(Rules.value("task.partial_grit", ctx, 0.6), 0.0, 1.0)
	if run.full_scale:
		run.full_scale = false

	var award := maxi(1, int(round(float(node.get("grit", 5)) * multiplier)))
	_add_grit(award)

	for tag in node.get("grants", []):
		if not run.tags.has(tag):
			run.tags.append(tag)

	run.axis_tasks[axis] = int(run.axis_tasks.get(axis, 0)) + 1
	Meta.record_task(axis, scaled)
	if Meta.touch_streak():
		say("%s: %d %s." % [Palette.word("streak"), Meta.streak, "day" if Meta.streak == 1 else "days"], "good")
		Notify.sync()

	apply_effects(Rules.hook("on_task_complete", ctx))

	run.pending_node = ""
	_finish_node(id)

	var loot_table := String(node.get("loot", ""))
	if loot_table != "":
		_roll_loot(loot_table)

	changed()
	if run.pending_boons.is_empty() and event.is_empty():
		goto("area")


func skip_task() -> void:
	run.pending_node = ""
	changed()
	goto("area")


# --- rewards -------------------------------------------------------------------

func _add_grit(amount: int) -> void:
	run.grit = maxi(0, run.grit + amount)


func _roll_loot(table_id: String) -> void:
	var table: Array = Content.loot.get(table_id, [])
	if table.is_empty():
		return
	var ctx := run.ctx()
	var total := 0.0
	var weights: Array = []
	for entry in table:
		var w := float(entry.get("w", 1))
		if entry.has("scaled_by"):
			w *= Rules.value(String(entry["scaled_by"]), ctx, 1.0)
		weights.append(w)
		total += w
	if total <= 0.0:
		return
	var roll := rng.randf() * total
	for i in range(table.size()):
		roll -= float(weights[i])
		if roll <= 0.0:
			_award(table[i])
			return


func _award(entry: Dictionary) -> void:
	match String(entry.get("type", "")):
		"grit":
			var amount := int(round(float(entry.get("amount", 5)) * Rules.value("run.grit_mult", run.ctx(), 1.0)))
			_add_grit(amount)
			say("+%d %s" % [amount, Palette.word("grit")], "good")
		"echo":
			_give_echo()
		"trinket":
			offer_boons()
		"item":
			var item_id := Meta.random_item(rng)
			if item_id != "":
				Meta.give_item(item_id)
				say("Found: %s" % Content.item(item_id).get("name", item_id), "good")


func _give_echo() -> void:
	var id := Meta.next_echo_id()
	if id == "":
		_add_grit(10)
		say("Nothing new in it, but you pocket something anyway.", "info")
		return
	Meta.find_echo(id)
	if not run.echoes.has(id):
		run.echoes.append(id)
	var e := Content.echo(id)
	_show_event({
		"kind": "echo",
		"title": String(e.get("title", Palette.word("echo"))),
		"text": String(e.get("text", "")),
		"footer": "%s %d of %d — kept in the Codex" % [Palette.word("echo"), int(e.get("order", 0)), Content.echoes.size()],
	})


func _mirror() -> void:
	var lines := [
		"You catch yourself in the glass. The reflection arrives a beat after you do.",
		"For a moment the face is yours with twenty more years on it. Then it isn't.",
		"Your reflection finishes the movement slightly before you start it.",
	]
	_show_event({
		"kind": "mirror",
		"title": "A Reflection",
		"text": String(lines[rng.randi_range(0, lines.size() - 1)]),
		"footer": Palette.data.get("mountain_line", ""),
	})
	var reveal := String(Content.echo_reveals.get("first_mirror", ""))
	if reveal != "" and not Meta.codex.has(reveal):
		Meta.find_echo(reveal)


# --- spite ---------------------------------------------------------------------

func _spite() -> void:
	var spite: Dictionary = Content.spite
	var events: Array = spite.get("events", [])
	if events.is_empty():
		return

	if run.ward:
		run.ward = false
		_show_event({"kind": "spite", "title": "Spite", "text": String(spite.get("warded", "")), "footer": ""})
		return

	var kind_weight := Rules.value("spite.kind_weight", run.ctx(), 1.0)
	if run.kind_spite:
		kind_weight = 999.0
		run.kind_spite = false

	var total := 0.0
	var weights: Array = []
	for e in events:
		var w := float(e.get("weight", 1))
		if String(e.get("alter", "")) == "kind":
			w *= kind_weight
		weights.append(w)
		total += w

	var roll := rng.randf() * total
	var picked: Dictionary = events[events.size() - 1]
	for i in range(events.size()):
		roll -= float(weights[i])
		if roll <= 0.0:
			picked = events[i]
			break

	var alter_line := ""
	for alter in spite.get("alters", []):
		if alter.get("id", "") == picked.get("alter", ""):
			alter_line = String(alter.get("line", ""))

	_apply_spite_effect(picked.get("effect", {}))
	_show_event({
		"kind": "spite",
		"title": "Spite",
		"text": alter_line + "\n\n" + String(picked.get("text", "")),
		"footer": "",
	})

	var reveal := String(Content.echo_reveals.get("first_spite", ""))
	if reveal != "" and not Meta.codex.has(reveal):
		Meta.find_echo(reveal)


func _apply_spite_effect(effect: Dictionary) -> void:
	match String(effect.get("type", "")):
		"grit":
			var amount := int(effect.get("amount", 0))
			_add_grit(amount)
			say("%+d %s" % [amount, Palette.word("grit")], "good" if amount > 0 else "bad")
		"item":
			var id := Meta.random_item(rng)
			if id != "":
				Meta.give_item(id)
				say("Spite left you a %s." % Content.item(id).get("name", id), "good")
		"steal_item":
			var held: Array = Meta.inventory.keys()
			if held.size() > 0:
				var id := String(held[rng.randi_range(0, held.size() - 1)])
				Meta.take_item(id)
				say("Your %s is gone." % Content.item(id).get("name", id), "bad")
		"trinket":
			offer_boons()
		"reveal_area":
			run.revealed = true
		"hide_area":
			run.revealed = false
		"deadline":
			run.deadline_unix += HJClock.hours_to_seconds(float(effect.get("amount", -1)))
			Notify.sync()


# --- the Warden ----------------------------------------------------------------

func _warden(id: String) -> void:
	if not Meta.seen_warden:
		Meta.seen_warden = true
		Meta.find_echo(String(Content.echo_reveals.get("reach_summit", "e14")))
		Meta.save_game()
		summary_event_then_end(
			"The Warden of the Loop",
			"They turn around, and it is your face, thirty years further on, and they are not surprised to see you.\n\n\"Every morning you got back,\" they say, \"you got back because I sent it. You are not being punished. You are being built.\"\n\nThey are kind about it. That is the worst part.\n\n\"Not yet,\" they say. \"Come back when you are looking after all of it.\"",
			"loop")
		return

	if not Meta.balance_unlocked():
		summary_event_then_end(
			"Not Yet",
			"The Warden looks at you for a long moment and shakes their head.\n\n\"You are strong in one direction. That is not the same as being ready.\"\n\nBalance the Wheel — every spoke off the mark — and the door will open.",
			"loop")
		return

	_finish_node(id)
	_show_event({
		"kind": "warden",
		"title": "The Loop Opens",
		"text": "\"There it is,\" they say, and they sound relieved, and they sound tired.\n\n\"You looked after all of it. That is the whole trick. I can stop now.\"\n\nThey step aside.",
		"footer": "",
	})


func summary_event_then_end(title: String, text: String, outcome: String) -> void:
	event = {"kind": "warden", "title": title, "text": text, "footer": "", "then_end": outcome}
	goto("event")


# --- area flow -----------------------------------------------------------------

func clear_area() -> void:
	var bonus := int(round(Rules.value("run.clear_bonus", run.ctx(), 40) * Meta.streak_multiplier()))
	_add_grit(bonus)
	var cleared_name := String(run.area.get("name", "Area"))
	say("%s cleared. +%d %s." % [cleared_name, bonus, Palette.word("grit")], "good")
	apply_effects(Rules.hook("on_area_clear", run.ctx()))

	if run.chapter >= Content.chapter_count():
		end_run("cleared")
		return

	# Always start the next thing. Parking the player on a finished map with
	# nothing to tap is the one state this screen must never be in, and a
	# deadline a day out is no reason to hold the next area back.
	var next_index := run.chapter + 1
	var next_chapter := Content.chapter(next_index)
	enter_chapter(next_index)
	_show_event({
		"kind": "text",
		"title": "%s is behind you" % cleared_name,
		"text": "%s\n\n%s" % [next_chapter.get("blurb", ""), next_chapter.get("scene", "")],
		"footer": "%s — due %s" % [next_chapter.get("name", ""), HJClock.format_deadline(run.deadline_unix)],
	})


## Last-resort way out of an area that has somehow run dry.
func force_advance() -> void:
	if not has_active_run():
		return
	for id in run.area.get("order", []):
		var node_id := String(id)
		if String(run.node(node_id).get("type", "")) == "threshold" and not run.is_done(node_id):
			_finish_node(node_id)
			if not run.anomaly.is_empty():
				leave_anomaly(true)
			else:
				clear_area()
			return
	clear_area()


# --- boons ---------------------------------------------------------------------

func offer_boons(count: int = 3) -> void:
	var pool: Array = []
	for id in Content.trinkets.keys():
		if not run.trinkets.has(id):
			pool.append(id)
	if pool.is_empty():
		_add_grit(15)
		return
	pool.shuffle()
	run.pending_boons = pool.slice(0, mini(count, pool.size()))
	goto("boon")


func take_boon(trinket_id: String) -> void:
	if trinket_id != "":
		run.trinkets.append(trinket_id)
		rebuild_rules()
		say("Gained %s." % Content.trinkets.get(trinket_id, {}).get("name", trinket_id), "good")
	run.pending_boons = []
	changed()
	goto("area")


# --- events --------------------------------------------------------------------

func _show_text(title: String, text: String) -> void:
	if text.strip_edges() == "":
		return
	_show_event({"kind": "text", "title": title, "text": text, "footer": ""})


func _show_event(payload: Dictionary) -> void:
	event = payload
	goto("event")


func dismiss_event() -> void:
	var then_end := String(event.get("then_end", ""))
	event = {}
	if then_end != "":
		end_run(then_end)
		return
	if not run.pending_boons.is_empty():
		goto("boon")
		return
	if has_active_run() and run.node("out").size() > 0 and run.is_done("warden"):
		goto("area")
		return
	goto("area" if has_active_run() else "palace")


# --- items ---------------------------------------------------------------------

func use_item(id: String) -> bool:
	var item := Content.item(id)
	if item.is_empty() or Meta.item_count(id) <= 0:
		return false

	match String(item.get("use", "")):
		"resume_run":
			# Consumed when the loop closes rather than tapped — `where: "auto"`.
			# The item was written for chapters ("begin again at the chapter you
			# reached") and did nothing at all, because nothing implemented the
			# verb. Under zone levels it means something better: the loop still
			# resets the world, but you wake where you were standing instead of
			# walking back out from town.
			Meta.resume_at = run.world_pos if has_active_run() else Vector2i(-1, -1)
			Meta.save_game()
			say("Second Wind. You will wake where you stood.", "good")
		"keep_streak":
			if not Meta.spend_rest_token():
				say("Nothing to protect today.", "warn")
				return false
			say("Rest counts. %s: %d days." % [Palette.word("streak"), Meta.streak], "good")
			return true
		"extend_deadline":
			if not has_active_run():
				return false
			Meta.take_item(id)
			run.deadline_unix += HJClock.hours_to_seconds(float(item.get("amount", 12)))
			Notify.sync()
			say("The hour hand slips back. %s left." % HJClock.format_remaining(run.seconds_left()), "good")
		"ward":
			if not has_active_run():
				return false
			Meta.take_item(id)
			run.ward = true
			say("Tonic ready. The next setback will slide off.", "good")
		"skip_to_threshold":
			if not has_active_run() or _tasks_done_here() <= 0:
				say("Do at least one thing here first.", "warn")
				return false
			Meta.take_item(id)
			for node_id in run.area.get("order", []):
				if String(run.node(String(node_id)).get("type", "")) == "threshold":
					say("You walk straight for the door.", "warn")
					tap_node(String(node_id))
					break
		"reveal_area":
			if not has_active_run():
				return false
			Meta.take_item(id)
			run.revealed = true
			say("The room gives up its corners.", "good")
		"full_scale":
			if not has_active_run():
				return false
			Meta.take_item(id)
			run.full_scale = true
			say("Take the easier version. It costs you nothing.", "good")
		"guarantee_kind_spite":
			if not has_active_run():
				return false
			Meta.take_item(id)
			run.kind_spite = true
			say("If they find you now, it will be the good half.", "good")
		"reveal_echo":
			Meta.take_item(id)
			_give_echo()
			return true
		_:
			return false

	changed()
	return true


func _tasks_done_here() -> int:
	var n := 0
	for id in run.completed:
		if String(run.node(String(id)).get("type", "")) == "task":
			n += 1
	return n


# --- pause ---------------------------------------------------------------------

func set_paused(value: bool) -> void:
	if value == Meta.paused:
		return
	if value:
		Meta.paused = true
		Meta.pause_started = HJClock.now()
		Notify.sync()
		say("Paused. Nothing is counting.", "info")
	else:
		var elapsed := HJClock.now() - Meta.pause_started
		Meta.paused = false
		if has_active_run() and elapsed > 0:
			run.deadline_unix += elapsed
			Notify.sync()
			save_run()
		say("Welcome back. The clock starts again now.", "info")
	Meta.save_game()
	Events.meta_changed.emit()


# --- effects -------------------------------------------------------------------

func apply_effects(effects: Array) -> void:
	if run == null:
		return
	for effect in effects:
		var amount := float(effect.get("amount", 0))
		var silent := bool(effect.get("silent", false))
		match String(effect.get("type", "")):
			"grit":
				_add_grit(int(round(amount)))
				if not silent:
					say("%+d %s." % [int(round(amount)), Palette.word("grit")], "good")
			"item":
				var id := Meta.random_item(rng)
				if id != "":
					Meta.give_item(id)
			"deadline":
				run.deadline_unix += HJClock.hours_to_seconds(amount)
			"log":
				say(String(effect.get("text", "")), String(effect.get("kind", "info")))


# --- persistence ---------------------------------------------------------------

func save_run() -> void:
	if run == null or run.finished:
		return
	var f := FileAccess.open(RUN_PATH, FileAccess.WRITE)
	if f == null:
		return
	f.store_string(JSON.stringify(run.to_dict()))
	f.close()


func load_run() -> void:
	if not FileAccess.file_exists(RUN_PATH):
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(RUN_PATH))
	if not (parsed is Dictionary):
		return
	var restored := HJRun.from_dict(parsed)
	if restored == null:
		clear_saved_run()
		return
	run = restored
	rng.seed = run.seed
	Palette.use(run.theme_id)
	rebuild_rules()


func clear_saved_run() -> void:
	if FileAccess.file_exists(RUN_PATH):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(RUN_PATH))
		if FileAccess.file_exists(RUN_PATH):
			var f := FileAccess.open(RUN_PATH, FileAccess.WRITE)
			if f != null:
				f.store_string("{}")
				f.close()


# --- anomalies -----------------------------------------------------------------

## Step into one.
##
## The chapter graph used to be the content of a *region*; it is now the content
## of an anomaly. Same generator, same node schema, same screens — what changes
## is that you chose this one by walking to it, and how hard it is was decided
## by how far from town you were willing to go.
func enter_anomaly(cell: Vector2i) -> void:
	if not has_active_run() or check_deadline():
		return
	var spawn := HJWorld.shared().anomaly_at(cell)
	if spawn.is_empty() or run.anomalies_cleared.has(_cell_key(cell)):
		return

	var tier := int(spawn.get("tier", 0))
	rng.seed = run.seed ^ (cell.x * 73856093) ^ (cell.y * 19349663)

	# A named cell is one of the eight written beats and always serves the same
	# place; everywhere else draws from the tier's pool. That is the whole of
	# what is left of chapters: they are locations now, not a sequence.
	var area_id := String(spawn.get("area", ""))
	var template: Dictionary = Content.area(area_id) if area_id != "" \
		else Content.anomaly_for(tier, rng)
	if template.is_empty():
		push_error("Game: no anomaly for tier %d at %s" % [tier, str(cell)])
		return

	run.anomaly = {"x": cell.x, "y": cell.y, "tier": tier,
		"sector": String(spawn.get("sector", "")), "area": area_id}
	run.zone = maxi(run.zone, tier)
	Meta.note_ring(tier)
	run.completed = []
	run.locked = []
	run.revealed = false
	run.chosen_movement = ""
	run.pending_node = ""
	run.pending_boons = []
	run.area = HJAreaGen.build(template, rng, run.ctx())

	# Every anomaly resets the clock. That is what they are *for*: the loop does
	# not close while you keep finding them, so the pressure is on finding one
	# rather than on any single deadline.
	var hours := 24.0 + Rules.value("area.deadline_bonus_hours", run.ctx(), 0.0)
	run.deadline_unix = HJClock.now() + HJClock.hours_to_seconds(maxf(1.0, hours))

	Notify.sync()
	apply_effects(Rules.hook("on_area_enter", run.ctx()))
	changed()
	goto("area")


## Walk back out, finished or not.
##
## Leaving early is allowed and is not a failure state — it is priced. Every
## tile of walking costs more until the next anomaly you actually finish, so
## what a half-done anomaly takes from you is *reach*. Since difficulty is a
## function of how far you can get, that is the whole difficulty curve, and it
## needs no tuning knob: burn fast and the mountain is simply out of range.
func leave_anomaly(finished: bool = false) -> void:
	if not has_active_run() or run.anomaly.is_empty():
		return

	# The Summit is still the ending. Retiring chapters removed the sequence, not
	# the destination: walking out of the Summit having got past the Warden is
	# how a loop is closed, and it is the only anomaly that ends a run rather
	# than returning you to the world.
	if finished and String(run.anomaly.get("area", "")) == "summit" \
			and run.is_done("warden"):
		run.anomaly = {}
		end_run("cleared")
		return
	var total := int(run.area.get("order", []).size())
	var done := int(run.completed.size())
	var share := 1.0 if total <= 0 else clampf(float(done) / float(total), 0.0, 1.0)

	# Reaching the threshold *is* a full clear, whatever the share says. Optional
	# side nodes are counted in the total, so a player who walked the whole chain
	# and skipped a cache would otherwise be penalised for a clean run — which
	# would teach exactly the wrong lesson about what "finishing" means.
	var penalty := float(Rules.value("steps.burn_penalty", run.ctx()))
	Steps.set_burn(1.0 if finished else 1.0 + penalty * (1.0 - share))
	if finished or share >= 0.999:
		run.anomalies_cleared.append(_cell_key(Vector2i(
			int(run.anomaly.get("x", 0)), int(run.anomaly.get("y", 0)))))
		say("The anomaly closes. You walk at your own pace again.", "good")
	elif share <= 0.0:
		say("You back out. Nothing here is finished.", "warn")
	else:
		say("You leave it half-done. Every step costs more now.", "warn")

	run.anomaly = {}
	run.area = {}
	run.completed = []
	changed()
	goto("overworld")


static func _cell_key(cell: Vector2i) -> String:
	return "%d,%d" % [cell.x, cell.y]
