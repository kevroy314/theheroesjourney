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
	if run == null or run.finished or run.area.is_empty():
		Game.resync_screen.call_deferred("overworld")
		return

	var v := page(10)

	# Panelled, not bare: the map runs edge to edge underneath, and unbacked text
	# over a tiled floor is unreadable.
	var head_panel := HJUI.panel("panel")
	var head := HJUI.hbox(10)
	var titles := HJUI.vbox(2)
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_child(HJUI.label(String(run.area.get("name", "Area")), HJUI.FS_HEAD, "text"))
	_where = HJUI.label(Steps.describe(), HJUI.FS_TINY, "muted")
	titles.add_child(_where)
	head.add_child(titles)
	var back := HJUI.button("Map", "quiet")
	back.custom_minimum_size = Vector2(120, 62)
	back.size_flags_horizontal = Control.SIZE_SHRINK_END
	back.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	back.pressed.connect(func(): Game.goto("worldmap"))
	head.add_child(back)
	head_panel.add_child(head)
	v.add_child(head_panel)

	var chips := HJUI.hbox(8)
	_steps_chip = HJUI.chip("Steps left", str(Steps.budget()), "accent")
	_budget = _steps_chip.get_meta("value_label")
	chips.add_child(_steps_chip)
	chips.add_child(HJUI.chip(Palette.word("grit"), str(run.grit), "accent", "grit"))
	v.add_child(chips)

	_world = HJTileWorld.new(run, run.world_pos)
	_world.node_entered.connect(_on_node)
	_world.blocked.connect(_on_blocked)
	# The world does not reset when the screen does. Remember where he stopped.
	_world.moved.connect(func(cell: Vector2i) -> void: run.world_pos = cell)
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

	Steps.budget_changed.connect(_sync_budget)
	_sync_budget()


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
	if enabled:
		replacement.pressed.connect(func() -> void: Game.tap_node(id))
	var parent := _act.get_parent()
	var index := _act.get_index()
	parent.remove_child(_act)
	_act.queue_free()
	_act = replacement
	parent.add_child(_act)
	parent.move_child(_act, index)
