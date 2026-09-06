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
var _pad: Control


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
	_pad = _make_pad()
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


## A four-way pad rather than a stick. The world is on a grid, so a stick would
## only be a less accurate way of saying one of four things.
func _make_pad() -> Control:
	var grid := GridContainer.new()
	grid.columns = 3
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	grid.size_flags_horizontal = Control.SIZE_SHRINK_CENTER

	var layout := [
		Vector2i.ZERO, Vector2i.UP, Vector2i.ZERO,
		Vector2i.LEFT, Vector2i.ZERO, Vector2i.RIGHT,
		Vector2i.ZERO, Vector2i.DOWN, Vector2i.ZERO,
	]
	for direction in layout:
		if direction == Vector2i.ZERO:
			var gap := Control.new()
			gap.custom_minimum_size = Vector2(84, 84)
			grid.add_child(gap)
			continue
		var b := PadButton.new(direction)
		b.changed.connect(func(dir: Vector2i, down: bool) -> void:
			_world.hold(dir if down else Vector2i.ZERO))
		grid.add_child(b)
	return grid


## One key of the pad: a drawn arrowhead that reports being *held*, not tapped.
##
## Not a Button. With `pointing/emulate_touch_from_mouse` on, one press arrives
## as both a touch and a mouse event, and Button resolves that pair into an
## immediate down-then-up — so holding a direction walked exactly one tile per
## press however long you leaned on it. Same trick as HJUI.TapCard: only the
## input family that started a press is allowed to end it.
##
## The arrow is drawn rather than typed because a pixel display face has no
## dependable arrowhead glyph, and "^" renders as a speck at this size.
class PadButton extends PanelContainer:
	signal changed(direction: Vector2i, down: bool)

	var _dir := Vector2i.UP
	var _pressing := false
	var _source := ""

	func _init(direction: Vector2i) -> void:
		_dir = direction
		custom_minimum_size = Vector2(84, 84)
		# STOP, not PASS: the pad is not inside a scroller, and a stray drag off
		# a key must not become a page gesture.
		mouse_filter = Control.MOUSE_FILTER_STOP
		_restyle()

	func _restyle() -> void:
		var fill := Palette.ca("panel_alt", 0.9 if _pressing else 0.55)
		add_theme_stylebox_override("panel", HJUI.stylebox(
			fill, 12, Palette.ca("accent" if _pressing else "line", 0.8), 2, "button"))
		queue_redraw()

	func _gui_input(event: InputEvent) -> void:
		if event is InputEventScreenTouch:
			_press("touch", event.pressed)
		elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
			_press("mouse", event.pressed)

	func _press(source: String, is_down: bool) -> void:
		if is_down:
			if _pressing:
				return              # the duplicate from the other input family
			_pressing = true
			_source = source
		else:
			if not _pressing or _source != source:
				return
			_pressing = false
			_source = ""
		accept_event()
		_restyle()
		changed.emit(_dir, is_down)

	## Let go from anywhere. Releasing outside the key you pressed still has to
	## stop the walk, and MOUSE_EXIT cannot do this job: with touch emulation the
	## press itself drops hover, so an exit arrives immediately and the character
	## walked exactly one tile per press no matter how long you held.
	func release() -> void:
		if not _pressing:
			return
		_pressing = false
		_source = ""
		_restyle()
		changed.emit(_dir, false)

	func _draw() -> void:
		var c := size * 0.5
		var r := minf(size.x, size.y) * 0.26
		var forward := Vector2(_dir)
		var side := Vector2(-forward.y, forward.x)
		draw_colored_polygon(PackedVector2Array([
			c + forward * r,
			c - forward * r * 0.7 + side * r * 0.85,
			c - forward * r * 0.7 - side * r * 0.85,
		]), HJUI.tint(Palette.c("accent" if _pressing else "text"), "text"))


## A release anywhere on the screen ends the walk, whether or not it landed back
## on the key that started it.
func _input(event: InputEvent) -> void:
	var up := false
	if event is InputEventScreenTouch:
		up = not (event as InputEventScreenTouch).pressed
	elif event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		up = mb.button_index == MOUSE_BUTTON_LEFT and not mb.pressed
	if not up or _pad == null or not is_instance_valid(_pad):
		return
	for key in _pad.get_children():
		if key is PadButton:
			key.release()


func _unhandled_input(event: InputEvent) -> void:
	if _world == null or not (event is InputEventKey):
		return
	var key := event as InputEventKey
	var direction := Vector2i.ZERO
	match key.keycode:
		KEY_W, KEY_UP: direction = Vector2i.UP
		KEY_S, KEY_DOWN: direction = Vector2i.DOWN
		KEY_A, KEY_LEFT: direction = Vector2i.LEFT
		KEY_D, KEY_RIGHT: direction = Vector2i.RIGHT
		_: return
	_world.hold(direction if key.pressed else Vector2i.ZERO)
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
func _on_anomaly(cell: Vector2i) -> void:
	var spawn := HJWorld.shared().anomaly_at(cell)
	if spawn.is_empty():
		return
	var run: HJRun = Game.run
	if run != null and run.anomalies_cleared.has(Game._cell_key(cell)):
		return
	var tier := int(spawn.get("tier", 0))
	_set_anomaly_act(tier, cell)


func _set_anomaly_act(tier: int, cell: Vector2i) -> void:
	if _act == null or not is_instance_valid(_act):
		return
	var names := ["a stall", "an eddy", "a seam", "a hollow", "a wound"]
	var label := "Step into %s" % names[clampi(tier, 0, names.size() - 1)]
	var replacement := HJUI.button(label, "primary")
	replacement.custom_minimum_size.y = 84
	replacement.size_flags_vertical = Control.SIZE_SHRINK_END
	replacement.pressed.connect(func() -> void: Game.enter_anomaly(cell))
	var parent := _act.get_parent()
	var index := _act.get_index()
	parent.remove_child(_act)
	_act.queue_free()
	_act = replacement
	parent.add_child(_act)
	parent.move_child(_act, index)
