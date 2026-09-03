extends Node
## Run orchestrator. Owns the run, drives the loop, and is the only thing that
## mutates player state. Screens call in here and listen to Events.

var run: HJRun = null
var screen: String = "title"
## The screen before this one, so a screen reachable from two places can send
## the player back where they actually came from.
var previous_screen: String = "title"
var summary: Dictionary = {}
var event: Dictionary = {}     ## popup currently on the event screen
var rng := RandomNumberGenerator.new()

## What a resolved node yields, and what an item does. Split out so this file
## stays the answer to "what is the game doing", not also to "what does a cache
## pay" and "what does the Tonic do".
var outcomes := HJOutcomes.new(self)
var items := HJItems.new(self)


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


func start_run(run_seed: int = 0) -> void:
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

	# You wake in the world. There is no sequence to be at the start of — the
	# deadline runs until you find something, and what you find is decided by
	# how far you are willing to walk.
	run.zone = 0
	run.deadline_unix = HJClock.now() + HJClock.hours_to_seconds(
		maxf(1.0, 24.0 + Rules.value("area.deadline_bonus_hours", run.ctx(), 0.0)))
	Notify.sync()
	changed()
	goto("overworld")


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
			finish_node(id)
			_show_text(String(node.get("label", "")), String(node.get("text", "")))
		"echo":
			finish_node(id)
			outcomes.give_echo()
		"cache":
			finish_node(id)
			var amount := int(round(float(node.get("grit", 10))
				* Rules.value("loot.cache_mult", run.ctx(), 1.0)))
			add_grit(amount)
			_show_text("Worth Picking Up",
				"You pocket what's there. +%d %s." % [amount, Palette.word("grit")])
		"mirror":
			finish_node(id)
			outcomes.mirror()
		"trinket":
			finish_node(id)
			outcomes.offer_boons()
		"spite":
			finish_node(id)
			outcomes.spite()
		"warden":
			outcomes.warden(id)
		"threshold":
			finish_node(id)
			# The threshold is the way out of the anomaly. It used to be the way
			# on to the next chapter, and there is no next any more.
			leave_anomaly(true)
	changed()


func finish_node(id: String) -> void:
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
	add_grit(award)

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
	finish_node(id)

	var loot_table := String(node.get("loot", ""))
	if loot_table != "":
		outcomes.roll_loot(loot_table)

	changed()
	if run.pending_boons.is_empty() and event.is_empty():
		goto("area")


func skip_task() -> void:
	run.pending_node = ""
	changed()
	goto("area")


# --- rewards -------------------------------------------------------------------

## The only place run grit changes. Public because HJOutcomes pays out through it.
func add_grit(amount: int) -> void:
	run.grit = maxi(0, run.grit + amount)


func summary_event_then_end(title: String, text: String, outcome: String) -> void:
	event = {"kind": "warden", "title": title, "text": text, "footer": "", "then_end": outcome}
	goto("event")


# --- area flow -----------------------------------------------------------------

## Last-resort way out of an area that has somehow run dry.
##
## Walks to the threshold if there is an unfinished one, so the exit is taken
## the way the player would have taken it — clear bonus, hooks and all — and
## falls back to simply stepping outside if there is not.
func force_advance() -> void:
	if not has_active_run():
		return
	if run.anomaly.is_empty():
		# Standing in an area that is not an anomaly should not be reachable.
		# If it happens anyway, the way out is the world, not a dead screen.
		run.area = {}
		run.completed = []
		changed()
		goto("overworld")
		return
	for id in run.area.get("order", []):
		var node_id := String(id)
		if String(run.node(node_id).get("type", "")) == "threshold" and not run.is_done(node_id):
			finish_node(node_id)
			leave_anomaly(true)
			return
	leave_anomaly(true)


# --- boons ---------------------------------------------------------------------
# Screens call these on Game; the work is HJOutcomes'.

func offer_boons(count: int = 3) -> void:
	outcomes.offer_boons(count)


func take_boon(trinket_id: String) -> void:
	outcomes.take_boon(trinket_id)


# --- events --------------------------------------------------------------------

func _show_text(title: String, text: String) -> void:
	if text.strip_edges() == "":
		return
	show_event({"kind": "text", "title": title, "text": text, "footer": ""})


## Put a popup on screen. Public because HJOutcomes speaks through it.
func show_event(payload: Dictionary) -> void:
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
	return items.use(id)


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
				add_grit(int(round(amount)))
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
# The file lives in HJRunStore; these stay because the whole app calls them.

func save_run() -> void:
	HJRunStore.write(run)


func load_run() -> void:
	var restored := HJRunStore.read()
	if restored == null:
		# Either there was nothing to load, or it was written under a run model
		# this build no longer understands. Both mean: start clean.
		HJRunStore.erase()
		return
	run = restored
	rng.seed = run.seed
	Palette.use(run.theme_id)
	rebuild_rules()


func clear_saved_run() -> void:
	HJRunStore.erase()


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
		# The clear bonus and the on_area_clear hook used to hang off the old
		# chapter advance, which nothing could reach once anomalies replaced it.
		# `run.clear_bonus` sat in config at 40 and a trinket added 50 to it, and
		# neither number had been payable for as long as anomalies have existed.
		var bonus := int(round(Rules.value("run.clear_bonus", run.ctx(), 40)
			* Meta.streak_multiplier()))
		add_grit(bonus)
		apply_effects(Rules.hook("on_area_clear", run.ctx()))
		Meta.note_anomaly_closed()
		say("The anomaly closes. +%d %s, and you walk at your own pace again."
			% [bonus, Palette.word("grit")], "good")
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
