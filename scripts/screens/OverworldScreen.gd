extends HJScreen
## The area as somewhere you walk rather than a list you work down.
##
## Same graph, same gates, same tasks. What changes is that reaching a node
## costs steps you had to actually take, and the order is yours. A node you can
## see across the room but cannot afford to reach is a real decision, which the
## list version could never produce.

var _world: HJTileWorld
var _steps_chip: PanelContainer
var _budget: Label
var _where: Label
var _act: Button
var _pad: HJMoveControls


## No plate. The world *is* the place here — a room photograph behind a room you
## are walking around in would be two floors at once.
func backdrop_id() -> String:
	return ""


func build() -> void:
	var run: HJRun = Game.run
	# Deliberately not requiring an area. The overworld is where you are when you
	# are between anomalies, and an empty area is the normal state out here —
	# this screen was written when the area *was* the whole sequence, and the leftover
	# guard sent a player who had just walked out of an anomaly to the Journey,
	# which advanced the sequence behind their back.
	if run == null or run.finished:
		Game.resync_screen.call_deferred("overworld")
		return

	var v := page(10)

	# Panelled, not bare: the map runs edge to edge underneath, and unbacked text
	# over a tiled floor is unreadable.
	var head_panel := HJUI.panel("panel")
	var head := HJUI.hbox(10)
	var titles := HJUI.vbox(2)
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	# Outside an anomaly there is no area, and the fallback read "Area" — so a
	# player walking round their own house was told they were in "Area".
	var where := String(run.area.get("name", ""))
	if where == "":
		var at := run.world_pos
		if at.x < 0:
			at = HJWorld.shared().nearest_walkable(HJWorld.shared().spawn)
		where = HJWorld.shared().place_name(at)
	titles.add_child(HJUI.label(where, HJUI.FS_HEAD, "text"))
	_where = HJUI.label(Steps.describe(), HJUI.FS_TINY, "muted")
	titles.add_child(_where)
	# On Android the counter is useless until ACTIVITY_RECOGNITION is granted,
	# and a budget that silently never grows is worse than an obvious ask.
	if Steps.needs_permission():
		var allow := HJUI.button("Allow step counting", "primary")
		allow.custom_minimum_size.y = 64
		allow.pressed.connect(func() -> void: Steps.ask_permission())
		titles.add_child(allow)
	head.add_child(titles)
	# Everywhere else in the game, not just the map. This screen used to offer
	# the map and nothing else, which left a player who had closed their first
	# anomaly standing in the world with no route to two thirds of the game.
	var nav := HJUI.nav_bar("overworld")
	nav.size_flags_horizontal = Control.SIZE_SHRINK_END
	nav.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	head.add_child(nav)
	head_panel.add_child(head)
	v.add_child(head_panel)

	var chips := HJUI.hbox(8)
	_steps_chip = HJUI.chip("Steps left", str(Steps.budget()), "accent")
	_budget = _steps_chip.get_meta("value_label")
	chips.add_child(_steps_chip)
	chips.add_child(HJUI.chip(Palette.word("grit"), str(run.grit), "accent", "grit"))
	# Only shown when it is costing you something. A rate of 1.0 is the absence
	# of a penalty, and a chip reading "1.0x" every moment of a clean run is
	# noise that teaches the player to stop reading chips.
	if Steps.burn > 1.001:
		chips.add_child(HJUI.chip("Burn", "%.1fx" % Steps.burn, "danger", "deadline"))
	v.add_child(chips)

	# Beside the budget, because every buff currently in the game changes what
	# walking costs or what it earns. A buff the player cannot see is a number
	# that changed for no reason.
	v.add_child(HJUI.BuffStrip.new())

	_world = HJTileWorld.new(run, run.world_pos)
	_world.node_entered.connect(_on_node)
	_world.blocked.connect(_on_blocked)
	_world.anomaly_entered.connect(_on_anomaly)
	# Just walked out of one you finished: play it closing, so the thing you did
	# has a consequence you can see rather than only a number that stopped
	# rising.
	if not run.anomalies_cleared.is_empty() and run.world_pos.x >= 0:
		var key := Game._cell_key(run.world_pos)
		if run.anomalies_cleared.has(key):
			_world.collapse_anomaly(run.world_pos)
	# The world does not reset when the screen does. Remember where he stopped.
	_world.moved.connect(_on_moved)
	# The map is the screen. Everything else is a strip around it, so the world
	# takes whatever the strips leave and never less than a usable window.
	_world.custom_minimum_size.y = 300
	v.add_child(_world)

	_act = HJUI.button("Walk to something", "quiet", false)
	_act.custom_minimum_size.y = 84
	_act.size_flags_vertical = Control.SIZE_SHRINK_END
	v.add_child(_act)
	# Which control this is — four keys, a trackpad, or the map itself — is
	# Meta.ui_move_control, and it carries the status line with it.
	_pad = HJMoveControls.new(_world)
	_pad.size_flags_vertical = Control.SIZE_SHRINK_END
	v.add_child(_pad)

	_sync_budget()
	if run.world_pos.x >= 0:
		_offer_nearby.call_deferred(run.world_pos)


## Connected here rather than in build(): build() runs on every rebuild, and
## _exit_tree only fires on leaving, so connecting there reconnected an already
## connected signal every time anything refreshed the screen — an error per
## rebuild, on the device as well as in the harness.
func _enter_tree() -> void:
	super._enter_tree()
	Steps.budget_changed.connect(_sync_budget)


func _exit_tree() -> void:
	super._exit_tree()
	if Steps.budget_changed.is_connected(_sync_budget):
		Steps.budget_changed.disconnect(_sync_budget)


## The keyboard, which is every control's fifth option. Routed through the
## The action button and the movement pad, asked rather than assumed.
##
## The constant in Main cleared the pad and stopped there, so a toast landed on
## the action button — the one control it is most often talking about, and the
## one the player's thumb is already moving towards.
##
## Their *minimum* sizes rather than their laid-out rects, because both are
## SHRINK_END and therefore sit at exactly their minimum, and because a minimum
## is already correct before the first layout pass. Reading `position` instead
## was the first attempt and it silently returned nothing at all, which looks
## from the outside exactly like the bug it was meant to fix.
func toast_clearance() -> float:
	if _act == null or not is_instance_valid(_act):
		return 0.0
	if _pad == null or not is_instance_valid(_pad):
		return 0.0
	var gap := 0.0
	var box := _act.get_parent()
	if box is BoxContainer:
		gap = float((box as BoxContainer).get_theme_constant("separation"))
	return _act.get_combined_minimum_size().y \
		+ _pad.get_combined_minimum_size().y + gap * 2.0 + 8.0


## movement controls rather than straight at the world, so that a key press
## cancels a tap-to-walk route the same way a thumb on the pad does.
func _unhandled_input(event: InputEvent) -> void:
	if _world == null or _pad == null or not is_instance_valid(_pad) or not (event is InputEventKey):
		return
	var key := event as InputEventKey
	var direction := Vector2i.ZERO
	match key.keycode:
		KEY_W, KEY_UP: direction = Vector2i.UP
		KEY_S, KEY_DOWN: direction = Vector2i.DOWN
		KEY_A, KEY_LEFT: direction = Vector2i.LEFT
		KEY_D, KEY_RIGHT: direction = Vector2i.RIGHT
		_: return
	_pad.hold_from_key(direction if key.pressed else Vector2i.ZERO)
	accept_event()


func _sync_budget() -> void:
	if _budget == null or not is_instance_valid(_budget):
		return
	var left := Steps.budget()
	HJUI.set_chip(_steps_chip, str(left), "accent" if left > 20 else "danger")
	if _where != null and is_instance_valid(_where):
		_where.text = Steps.describe()


## Every step. Three things hang off it, and the order matters: remember where
## we are, let the tutorial see the threshold before anything else reacts to it,
## then offer whatever is within arm's reach.
func _on_moved(cell: Vector2i) -> void:
	var run: HJRun = Game.run
	if run == null:
		return
	run.world_pos = cell
	Game.tutorial.note_moved(cell)
	_offer_nearby(cell)


## The thing you are standing next to, as the primary action.
##
## Reuses the same button the node affordance uses, because a screen with two
## "the important one" buttons has none. A node underfoot wins — you walked onto
## it deliberately — and otherwise the nearest interactable takes the slot.
func _offer_nearby(cell: Vector2i) -> void:
	if _act == null or not is_instance_valid(_act):
		return
	if _world != null and is_instance_valid(_world) and _world.here() != "":
		return
	var near: Array = Game.interactables_near(cell)
	if near.is_empty():
		_set_act("Walk to something", false, "")
		return

	var it: Dictionary = near[0]
	var label := String(it.get("name", "?"))
	var verb := String(it.get("verb", "Use"))
	var cost := int(it.get("cost", 0))
	var key := String(it.get("key", ""))

	if bool(it.get("spent", false)):
		_set_act(String(it.get("spent_text", "%s — done" % label)), false, "")
		return
	if not bool(it.get("affordable", true)):
		# Naming the price on a button you cannot press is the point: this is
		# where the player learns Grit buys the world, and a greyed button with
		# no number teaches nothing.
		_set_act("%s — %d %s needed" % [verb, cost, Palette.word("grit")], false, "")
		return

	var text := verb if cost <= 0 else "%s — %d %s" % [verb, cost, Palette.word("grit")]
	_set_interact(text, key)


func _set_interact(text: String, key: String) -> void:
	var replacement := HJUI.button(text, "primary")
	replacement.custom_minimum_size.y = 84
	replacement.size_flags_vertical = Control.SIZE_SHRINK_END
	replacement.pressed.connect(func() -> void:
		if Game.interact(key):
			refresh())
	_swap_act(replacement)


func _on_blocked() -> void:
	Events.logged.emit("No steps left. Walk, and the world opens up.", "warn")


func _on_node(id: String) -> void:
	if _act == null or not is_instance_valid(_act):
		return
	var run: HJRun = Game.run
	if run == null:
		return
	var node := run.node(id)
	var label := String(node.get("label", "?"))
	if run.is_done(id):
		_set_act("%s — done" % label, false, id)
	elif HJAreaGen.is_available(run, id):
		_set_act("Do: %s" % label, true, id)
	else:
		_set_act("%s — not yet" % label, false, id)


func _set_act(text: String, enabled: bool, id: String) -> void:
	var replacement := HJUI.button(text, "primary" if enabled else "quiet", enabled)
	replacement.custom_minimum_size.y = 84
	replacement.size_flags_vertical = Control.SIZE_SHRINK_END
	if enabled and id != "":
		replacement.pressed.connect(func() -> void: Game.tap_node(id))
	_swap_act(replacement)


## Replace the action button in place, keeping its slot in the layout.
func _swap_act(replacement: Button) -> void:
	var parent := _act.get_parent()
	var index := _act.get_index()
	parent.remove_child(_act)
	_act.queue_free()
	_act = replacement
	parent.add_child(_act)
	parent.move_child(_act, index)


## Stepped onto one.
##
## Entering is not automatic. The anomaly resets the deadline and prices the
## walk out, so walking over one by accident on the way somewhere else would be
## a decision made for the player.
## Walking onto a hole in reality.
##
## It takes you. There is no button, because a hole in the world does not ask —
## and a confirm dialog in front of the most dramatic thing in the game is the
## surest way to make it feel like a menu. The player finds it by walking, which
## is the decision; stepping in is the consequence, not a second decision.
##
## Deferred rather than immediate: this fires from inside HJTileWorld's movement
## resolution during _process, and swapping the screen out from under the node
## that is mid-step is the same class of problem as redirecting during build().
func _on_anomaly(cell: Vector2i) -> void:
	var spawn := HJWorld.shared().anomaly_at(cell)
	if spawn.is_empty():
		return
	var run: HJRun = Game.run
	if run == null or run.anomalies_cleared.has(Game._cell_key(cell)):
		return
	Game.enter_anomaly.call_deferred(cell)


