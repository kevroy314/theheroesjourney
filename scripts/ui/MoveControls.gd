class_name HJMoveControls
extends VBoxContainer
## Everything that drives walking, and the one line that says what walking is
## currently doing.
##
## Which control you get is `Meta.ui_move_control`:
##
##   "dpad"      four keys, hold a direction        (the original)
##   "pad4"      round trackpad, lean, four ways
##   "pad8"      the same pad with diagonals
##   "tap_path"  tap a tile on the map and walk there
##
## They are genuinely different controls rather than four skins, and one of them
## is a rules change:
##
## **A diagonal costs one step and covers two tiles of ground.** HJTileWorld
## charges `Steps.spend(1)` on arrival at a new tile, whatever direction it came
## from, so on "pad8" the same journey that took seven steps takes four. Steps
## are this game's currency, so choosing "pad8" makes the whole world about a
## third cheaper to cross. Charging more for a diagonal would mean a
## `walk.diagonal_cost` in config.json and a change in HJTileWorld._try_move,
## which is a deliberate balance decision and not one this file should make on
## its own.
##
## The status line is kept for every control, including the ones that do not
## need it, because "what is the player doing right now" is the one thing a
## screen with no verbs on it cannot otherwise say.

## Above which the walk gives up on a route it cannot make progress on. A door
## that shuts, or a cell that stopped being walkable underneath a plan, would
## otherwise leave the character leaning into it forever.
const STALL := 1.5

var _world: HJTileWorld
var _mode := "dpad"
var _status: Label
var _pad: HJMovePad = null
var _tap: HJTapWalk = null
var _stop: Button = null

## The route the tap control is walking, next cell first. Empty when idle.
var _path: Array[Vector2i] = []
var _goal := Vector2i.ZERO
var _stall := 0.0


func _init(tile_world: HJTileWorld) -> void:
	_world = tile_world
	_mode = mode()
	add_theme_constant_override("separation", 8)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL


## The chosen control, defended against a value nothing here can build. A
## setting that silently does nothing is worse than a setting that falls back
## loudly to the one everybody has already learned.
static func mode() -> String:
	var chosen := String(Meta.ui_move_control)
	return chosen if chosen in ["dpad", "pad4", "pad8", "tap_path"] else "dpad"


func _ready() -> void:
	# One line, always one line. HJUI.label defaults to word wrap, and a status
	# that grows to two lines moves the pad under the player's thumb between one
	# step and the next. Trimmed rather than allowed to overflow, because an
	# un-clipped label widens its container and this one is inside the page.
	_status = HJUI.label("", HJUI.FS_TINY, "muted", HORIZONTAL_ALIGNMENT_CENTER)
	_status.autowrap_mode = TextServer.AUTOWRAP_OFF
	_status.clip_text = true
	_status.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	_status.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_child(_status)

	match _mode:
		"pad4", "pad8":
			_pad = HJMovePad.new(_mode == "pad8")
			_pad.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
			_pad.direction_changed.connect(_on_pad)
			add_child(_pad)
		"tap_path":
			# The control is the map, so nothing is built down here except the
			# way out of a walk you no longer want.
			_stop = _make_stop()
			add_child(_stop)
			_tap = HJTapWalk.new(_world)
			_tap.cell_tapped.connect(_on_tap)
			_world.add_child(_tap)
		_:
			add_child(_dpad())

	if is_instance_valid(_world):
		_world.moved.connect(_on_moved)
		_world.blocked.connect(_on_blocked)
	set_process(true)
	_sync()


func _exit_tree() -> void:
	# The screen tears the world down with us, but a mode swap does not have to
	# leave a dead sheet sitting on top of the map.
	if _tap != null and is_instance_valid(_tap):
		_tap.queue_free()
		_tap = null


# --- the four controls --------------------------------------------------------

## The original: a four-way pad. The world is on a grid, so a stick would only
## be a less accurate way of saying one of four things.
func _dpad() -> Control:
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
		var key := PadButton.new(direction)
		key.changed.connect(func(dir: Vector2i, down: bool) -> void:
			_drive(dir if down else Vector2i.ZERO))
		grid.add_child(key)
	return grid


## The only thing tap-to-walk needs down here, because the control is the map.
## Always present rather than appearing when a walk starts: a button that
## materialises under a thumb already on its way down is how you cancel a
## journey you meant to take.
func _make_stop() -> Button:
	var walking := not _path.is_empty()
	var b := HJUI.button("Stop", "primary" if walking else "quiet", walking)
	b.custom_minimum_size.y = 84
	if walking:
		# Deferred: this handler swaps the button that is emitting it.
		b.pressed.connect(func() -> void: _cancel_path.call_deferred())
	return b


func _on_pad(direction: Vector2i) -> void:
	_drive(direction)


## Straight to the world, cancelling any route in progress: a hand on the
## control always outranks a plan the player made a moment ago.
func _drive(direction: Vector2i) -> void:
	if not is_instance_valid(_world):
		return
	if direction != Vector2i.ZERO and not _path.is_empty():
		_clear_path()
	_world.hold(direction)
	_sync()


## The keyboard, which is a fifth control nobody chose and every mode has. Fed
## from the screen so there is exactly one place that knows how to start a walk.
func hold_from_key(direction: Vector2i) -> void:
	_drive(direction)


## A release anywhere on the screen ends the walk, whether or not it landed back
## on the key or the pad that started it.
func _input(event: InputEvent) -> void:
	var up := false
	if event is InputEventScreenTouch:
		up = not (event as InputEventScreenTouch).pressed
	elif event is InputEventMouseButton:
		var mb: InputEventMouseButton = event
		up = mb.button_index == MOUSE_BUTTON_LEFT and not mb.pressed
	if not up:
		return
	if _pad != null and is_instance_valid(_pad):
		_pad.release()
	for child in get_children():
		if child is GridContainer:
			for key in child.get_children():
				if key is PadButton:
					key.release()
	_sync()


# --- tap to walk --------------------------------------------------------------

func _on_tap(cell: Vector2i) -> void:
	if not is_instance_valid(_world):
		return
	if cell == _world.cell():
		_cancel_path()
		return
	var route := HJMovePath.route_to(_world.world, _world.cell(), cell)
	if route.is_empty():
		_clear_path()
		_world.hold(Vector2i.ZERO)
		_status.text = "No way through to there."
		return
	_path = route
	_goal = route[route.size() - 1]
	_stall = 0.0
	_advance()
	_sync()


func _advance() -> void:
	if not is_instance_valid(_world):
		return
	if _path.is_empty():
		_world.hold(Vector2i.ZERO)
		return
	var step := _path[0] - _world.cell()
	if absi(step.x) + absi(step.y) != 1:
		# Something moved him off the route — a key press, a teleport, a door.
		# Replan rather than hand HJTileWorld a two-tile "direction", which it
		# would happily walk as a jump.
		var again := HJMovePath.route_to(_world.world, _world.cell(), _goal)
		if again.is_empty():
			_cancel_path()
			return
		_path = again
		if _tap != null and is_instance_valid(_tap):
			_tap.show_path(_path)
		step = _path[0] - _world.cell()
	_world.hold(step)


func _cancel_path() -> void:
	_clear_path()
	if is_instance_valid(_world):
		_world.hold(Vector2i.ZERO)
	_sync()


func _clear_path() -> void:
	_path.clear()
	if _tap != null and is_instance_valid(_tap):
		_tap.show_path(_path)


## Fires once per tile, from inside the world's own movement resolution and
## *before* it reads the held direction again — so setting the next leg here
## lands on the same frame and the walk does not stutter at every corner.
func _on_moved(cell: Vector2i) -> void:
	if _path.is_empty():
		return
	_stall = 0.0
	if cell == _path[0]:
		_path.remove_at(0)
	if _tap != null and is_instance_valid(_tap):
		_tap.show_path(_path)
	_advance()
	_sync()


## Out of steps.
##
## The hold is dropped, not just the route. HJTileWorld only calls _try_move
## while a direction is held and never starts moving when the budget is empty,
## so a held key with nothing left in the bank emitted `blocked` — and therefore
## a toast — on *every frame*, sixty a second, for as long as the thumb stayed
## down. Letting go on the player's behalf turns that into one message, and the
## cost is that walking again is a re-press rather than a lean.
func _on_blocked() -> void:
	if is_instance_valid(_world):
		_world.hold(Vector2i.ZERO)
	if _pad != null and is_instance_valid(_pad):
		_pad.release()
	if not _path.is_empty():
		_clear_path()
	_sync()


func _process(delta: float) -> void:
	if not _path.is_empty():
		_stall += delta
		if _stall > STALL:
			_cancel_path()
			_status.text = "The way is shut."
			return
	_fix_diagonal_facing()


## The sprite sheet has four rows and HJTileWorld.FACINGS has four entries, so a
## diagonal heading falls through to the default — which is the *south* row, and
## a character walking north-east while facing the camera looks broken.
##
## Nudged from out here rather than fixed at the source because the renderer is
## not this agent's to change; the real fix is for _try_move to keep facing on
## the cardinal it is nearest to. Horizontal wins because the side-on sprite
## reads as motion and the front-on one reads as standing.
func _fix_diagonal_facing() -> void:
	if _mode != "pad8" or not is_instance_valid(_world):
		return
	var facing: Vector2i = _world._facing
	if facing.x != 0 and facing.y != 0:
		_world._facing = Vector2i(facing.x, 0)


# --- the status line ----------------------------------------------------------

func _sync() -> void:
	if _status == null or not is_instance_valid(_status):
		return
	_status.text = _describe()
	if _mode == "tap_path" and _stop != null and is_instance_valid(_stop):
		var walking := not _path.is_empty()
		if _stop.disabled == walking:
			var index := _stop.get_index()
			remove_child(_stop)
			_stop.queue_free()
			_stop = _make_stop()
			add_child(_stop)
			move_child(_stop, index)


func _describe() -> String:
	if not is_instance_valid(_world):
		return ""
	if not _path.is_empty():
		var place := _goal_name()
		var steps := _path.size()
		var tail := "%d step%s" % [steps, "" if steps == 1 else "s"]
		return "Walking to %s — %s" % [place, tail] if place != "" \
			else "Walking there — %s" % tail
	var held := _held()
	if held != Vector2i.ZERO:
		return "Walking %s." % compass(held)
	match _mode:
		"pad4", "pad8":
			return "Lean out from the middle to walk."
		"tap_path":
			return "Tap a tile to walk there."
		_:
			return "Hold a direction to walk."


func _held() -> Vector2i:
	if _pad != null and is_instance_valid(_pad):
		return _pad.direction()
	if is_instance_valid(_world):
		return _world._held
	return Vector2i.ZERO


## What the player would call the place they tapped. Usually nothing, and saying
## nothing is right — "Walking there" is honest about a patch of grass in a way
## that "Walking to Outside" is not.
func _goal_name() -> String:
	if not is_instance_valid(_world):
		return ""
	var id := String(_world.node_at.get(_goal, ""))
	var run: HJRun = Game.run
	if id != "" and run != null:
		return String(run.node(id).get("label", ""))
	if not _world.world.anomaly_at(_goal).is_empty():
		return "the anomaly"
	var thing: Dictionary = _world.world.interactable_at(_goal)
	if not thing.is_empty():
		var kind := Content.interactable(String(thing.get("type", "")))
		var named := String(kind.get("name", ""))
		if named != "":
			return named
	return ""


## Compass rather than up/down/left/right: this is a world with a north on it,
## and the map screen already talks that way.
static func compass(direction: Vector2i) -> String:
	if direction == Vector2i.ZERO:
		return ""
	var ns := "" if direction.y == 0 else ("north" if direction.y < 0 else "south")
	var ew := "" if direction.x == 0 else ("east" if direction.x > 0 else "west")
	if ns != "" and ew != "":
		return "%s-%s" % [ns, ew]
	return ns + ew


## One key of the d-pad: a drawn arrowhead that reports being *held*, not tapped.
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
