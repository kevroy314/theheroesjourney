extends HJScreen
## The map. One screen for "where am I and where could I go".
##
## This replaces two. The Journey was a list of eight beats in the order you
## would be handed them, and once those beats became places that list was a lie —
## there is no order any more. The map was the other half of the same
## information and carried none of it: no anomalies, no rings, no way to tell a
## cleared one from a waiting one.
##
## What a player actually needs out here is three things: where they are, what
## is worth walking to, and how much further out the hard ones start. All three
## are spatial, so they belong on the picture rather than in a list beside it.
##
## ## What changed, and why it matters more than it sounds
##
## It used to draw the whole 256x256 world fitted to a phone screen with all 29
## anomalies on it, from the title screen onward. That is not a map, it is a
## legend — and it contradicted the design outright, because it presented the
## world as a fixed known quantity in a game whose persistence rule is that
## nothing in the world survives a loop.
##
## Now it is **fogged**, and it is a *view* rather than a fitted image: it opens
## centred on the player at a zoom where their surroundings are legible, and it
## drags and pinches like any other touch map. Three states, and the third one
## is the interesting one:
##
##   | never been there  | hidden entirely                                |
##   | been there before | faded, showing what was there **last** time    |
##   | been there now    | full, and it **overwrites** the faded memory   |
##
## Discovery itself lives in `Discovery` (scripts/game/Discovery.gd) and the fog
## texture in `HJMapFog`; this file is the camera and the marks.
##
## **Only anomalies go on the map.** From the feedback, verbatim: *"NPCs/quests/
## mobs ... should not be on the map — just special things like anomalies."*
## Every system that arrives will want a marker here. The map is readable only
## while it is nearly empty; say no.
##
## Still no place names. The persistence rule holds: nothing written down
## survives a loop, so the map carries marks and the marks carry meaning.

const MAP := "res://assets/world/worldmap.png"

var _view: MapView


func build() -> void:
	var v := page(10)

	var head := HJUI.panel("panel")
	var row := HJUI.hbox(10)
	var titles := HJUI.vbox(2)
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_child(HJUI.label("The Way Out", HJUI.FS_HEAD, "text"))
	titles.add_child(HJUI.label(_summary(), HJUI.FS_TINY, "muted"))
	row.add_child(titles)
	var back := HJUI.button("Back", "quiet")
	back.custom_minimum_size = Vector2(120, 62)
	back.size_flags_horizontal = Control.SIZE_SHRINK_END
	back.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	back.pressed.connect(func(): Game.goto(_back_to()))
	row.add_child(back)
	head.add_child(row)
	v.add_child(head)

	_view = MapView.new()
	_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_view.custom_minimum_size.y = 320
	v.add_child(_view)

	v.add_child(_legend())

	var walk := HJUI.button("Walk", "primary")
	walk.pressed.connect(func(): Game.goto("overworld"))
	v.add_child(walk)


## One line of state, not a screen of it.
##
## It counts what the player has *found*, not what exists. The old version read
## the whole world's anomaly list, which told anyone on the title screen exactly
## how many holes were left in a world they had not walked a step of.
func _summary() -> String:
	var run: HJRun = Game.run
	if run == null:
		return String(Palette.data.get("mountain_line", ""))
	var world := HJWorld.shared()
	var left := 0
	for entry in world.anomalies:
		var a: Dictionary = entry
		var cell := Vector2i(int(a.get("x", 0)), int(a.get("y", 0)))
		if Discovery.state_at(cell) == Discovery.UNKNOWN:
			continue
		if not run.anomalies_cleared.has(Game._cell_key(cell)):
			left += 1
	var burn := "" if Steps.burn <= 1.001 else "  ·  burning %.1fx" % Steps.burn
	var found := "nothing found yet" if left == 0 else "%d found, still open" % left
	return "Ring %d  ·  %s%s" % [run.zone, found, burn]


## The marks, explained once. A map whose symbols have to be guessed at is a
## picture; this is the difference between the two.
func _legend() -> Control:
	var panel := HJUI.panel("panel")
	var row := HJUI.hbox(12)
	for entry in [["you", "text", 1.0], ["open", "accent", 1.0], ["done", "good", 1.0],
			["hard", "danger", 1.0], ["last run", "accent", 0.4]]:
		var item := HJUI.hbox(5)
		var dot := MapDot.new(Palette.ca(String(entry[1]), float(entry[2])))
		item.add_child(dot)
		item.add_child(HJUI.label(String(entry[0]), HJUI.FS_TINY, "muted"))
		row.add_child(item)
	panel.add_child(row)
	return panel


func _back_to() -> String:
	if Game.previous_screen in ["overworld", "area", "menu", "title"]:
		return Game.previous_screen
	return "overworld" if Game.has_active_run() else "title"


## A small filled circle, so the legend uses the same mark the map does rather
## than describing it in words.
class MapDot extends Control:
	var _colour: Color

	func _init(colour: Color) -> void:
		_colour = colour
		custom_minimum_size = Vector2(16, 16)
		mouse_filter = Control.MOUSE_FILTER_IGNORE

	func _draw() -> void:
		draw_circle(size * 0.5, 5.0, _colour)


## The drawn map: a camera over the painting, the fog over that, and everything
## that moves painted on top.
class MapView extends Control:
	## Screen pixels per world cell, at rest. About sixty cells across a phone —
	## close enough to see what is around you, far enough to plan a walk.
	const CELLS_ACROSS := 60.0
	const MAX_ZOOM := 14.0
	## Below this the map is a thumbnail and the marks collide; the fitted whole
	## world is the other limit and is computed from the viewport.
	const MIN_ZOOM_FLOOR := 0.25

	var _tex: Texture2D
	var _fog := HJMapFog.new()

	## The camera. `_centre` is the world cell under the middle of the viewport.
	var _zoom := 0.0
	var _centre := Vector2.ZERO
	## The viewport size the camera was last set up for. A screen is laid out
	## over several frames and the first _draw can land on an intermediate size;
	## latching the opening zoom to that leaves the map permanently at the wrong
	## scale. So until the player touches anything, the camera keeps re-deriving
	## itself whenever the frame changes shape — which also covers a rotation.
	var _placed_for := Vector2.ZERO
	var _user_moved := false

	## Gesture state. Input arrives twice: `emulate_touch_from_mouse` turns a
	## mouse press into a touch, and `emulate_mouse_from_touch` turns finger 0
	## into a mouse, so *every* press lands as both and only one family may act
	## on it. HJUI.TapCard settles that by letting whoever arrives first own the
	## press — which is wrong here, and was: the emulated mouse press arrives
	## before the touch it was made from, claimed the gesture, and the map then
	## ignored the second finger entirely. One-finger drag worked; pinch was
	## silently dead, which is exactly the trap the skill warns about.
	##
	## So here **touch always wins** and may take a press off the mouse. The two
	## arrive back to back with no motion between them, so the handover costs
	## nothing, and it leaves the mouse path as a fallback for a build with
	## touch emulation off rather than as a competitor.
	var _gesture := ""                      ## "" | "touch" | "mouse"
	var _touches: Dictionary = {}           ## finger index -> position
	var _pinch := 0.0                       ## last two-finger distance
	var _mid := Vector2.ZERO                ## last two-finger midpoint

	func _init() -> void:
		mouse_filter = Control.MOUSE_FILTER_STOP
		clip_contents = true
		# LINEAR, not NEAREST. The painting is a painting and this screen zooms;
		# and the fog is one texel per four cells and *depends* on being
		# filtered up — nearest would turn it back into the checkerboard of
		# black squares the whole design is trying to avoid.
		texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
		if ResourceLoader.exists(MAP):
			_tex = load(MAP)

	func _ready() -> void:
		set_process(true)
		add_child(_controls())

	func _process(_delta: float) -> void:
		queue_redraw()

	# --- the camera ---------------------------------------------------------

	func _default_zoom() -> float:
		return clampf(size.x / CELLS_ACROSS, _min_zoom(), MAX_ZOOM)

	func _min_zoom() -> float:
		var world := HJWorld.shared()
		if not world.loaded or size.x <= 0.0:
			return 1.0
		return maxf(MIN_ZOOM_FLOOR, minf(size.x / float(world.w), size.y / float(world.h)))

	## Where the view starts: on the player, at a readable zoom. Not fitted to
	## the world — a map that opens showing everything has already answered the
	## only question fog is asking.
	func _place() -> void:
		var world := HJWorld.shared()
		if size.x <= 0.0 or not world.loaded:
			return
		if _user_moved or size.is_equal_approx(_placed_for):
			return
		_placed_for = size
		_zoom = _default_zoom()
		_centre = Vector2(_home())
		_clamp()

	func _home() -> Vector2i:
		var run: HJRun = Game.run
		if run != null and run.world_pos.x >= 0:
			return run.world_pos
		var world := HJWorld.shared()
		return world.spawn if world.loaded else Vector2i.ZERO

	## Keep the world under the viewport. Getting lost in a map screen — panning
	## off into grey and not knowing which way back — is a special kind of bad,
	## so the world edge never comes inside the frame at all.
	func _clamp() -> void:
		var world := HJWorld.shared()
		if not world.loaded or _zoom <= 0.0:
			return
		var half := size * 0.5 / _zoom
		var span := Vector2(float(world.w), float(world.h))
		_centre.x = span.x * 0.5 if span.x <= half.x * 2.0 \
			else clampf(_centre.x, half.x, span.x - half.x)
		_centre.y = span.y * 0.5 if span.y <= half.y * 2.0 \
			else clampf(_centre.y, half.y, span.y - half.y)

	func _to_screen(cell: Vector2) -> Vector2:
		return (cell - _centre) * _zoom + size * 0.5

	func _to_world(point: Vector2) -> Vector2:
		return (point - size * 0.5) / maxf(_zoom, 0.0001) + _centre

	func _pan(delta: Vector2) -> void:
		_user_moved = true
		_centre -= delta / maxf(_zoom, 0.0001)
		_clamp()

	## Zoom about a point, so the thing under the fingers stays under them.
	func _zoom_at(point: Vector2, factor: float) -> void:
		_user_moved = true
		var before := _to_world(point)
		_zoom = clampf(_zoom * factor, _min_zoom(), MAX_ZOOM)
		_centre += before - _to_world(point)
		_clamp()

	## Back to me. Also hands the camera back to the layout, so a rotation after
	## pressing it still does the sensible thing.
	func _recentre() -> void:
		_user_moved = false
		_placed_for = size
		_zoom = _default_zoom()
		_centre = Vector2(_home())
		_clamp()

	# --- input --------------------------------------------------------------

	func _gui_input(event: InputEvent) -> void:
		if event is InputEventScreenTouch:
			_on_touch(event)
		elif event is InputEventScreenDrag:
			if _gesture == "touch":
				_on_touch_drag(event)
		elif event is InputEventMouseButton:
			var button: InputEventMouseButton = event
			# The wheel has no touch twin, so it needs no arbitration — and it
			# is how zoom gets exercised on a desktop with one pointer.
			if button.button_index == MOUSE_BUTTON_WHEEL_UP and button.pressed:
				_zoom_at(button.position, 1.15)
				accept_event()
			elif button.button_index == MOUSE_BUTTON_WHEEL_DOWN and button.pressed:
				_zoom_at(button.position, 1.0 / 1.15)
				accept_event()
			elif button.button_index == MOUSE_BUTTON_LEFT and (_gesture == "" or _gesture == "mouse"):
				_gesture = "mouse" if button.pressed else ""
				accept_event()
		elif event is InputEventMouseMotion and _gesture == "mouse":
			_pan((event as InputEventMouseMotion).relative)
			accept_event()

	func _on_touch(event: InputEventScreenTouch) -> void:
		if event.pressed:
			_gesture = "touch"
			_touches[event.index] = event.position
		else:
			_touches.erase(event.index)
			if _touches.is_empty():
				_gesture = ""
		_sync_pinch()
		accept_event()

	func _on_touch_drag(event: InputEventScreenDrag) -> void:
		_touches[event.index] = event.position
		if _touches.size() >= 2:
			var keys := _touches.keys()
			var a: Vector2 = _touches[keys[0]]
			var b: Vector2 = _touches[keys[1]]
			var spread := a.distance_to(b)
			var mid := (a + b) * 0.5
			# Two fingers do both jobs at once, the way every other map does:
			# the gap between them is the zoom and the point between them is
			# the pan. Doing only one of the two feels broken in the hand.
			_pan(mid - _mid)
			if _pinch > 4.0 and spread > 4.0:
				_zoom_at(mid, spread / _pinch)
			_pinch = spread
			_mid = mid
		else:
			_pan(event.relative)
		accept_event()

	func _sync_pinch() -> void:
		if _touches.size() >= 2:
			var keys := _touches.keys()
			var a: Vector2 = _touches[keys[0]]
			var b: Vector2 = _touches[keys[1]]
			_pinch = a.distance_to(b)
			_mid = (a + b) * 0.5
		else:
			_pinch = 0.0
			_mid = Vector2.ZERO

	## Buttons, because a pinch needs two thumbs and a phone in a coat pocket
	## has one — and because "I panned away and cannot find myself" is the one
	## failure a map must not have. Anchored rather than laid out: this Control
	## is not a container, and a container here would fight the map for space.
	func _controls() -> Control:
		var bar := HJUI.hbox(8)
		for entry in [["Me", "primary"], ["+", "quiet"], ["-", "quiet"]]:
			var b := HJUI.button(String(entry[0]), String(entry[1]))
			b.custom_minimum_size = Vector2(74, 64)
			var label := String(entry[0])
			if label == "Me":
				b.pressed.connect(_recentre)
			elif label == "+":
				b.pressed.connect(func(): _zoom_at(size * 0.5, 1.4))
			else:
				b.pressed.connect(func(): _zoom_at(size * 0.5, 1.0 / 1.4))
			bar.add_child(b)
		# After the children, not before: PRESET_MODE_MINSIZE reads the minimum
		# size *now*, and an empty box has none — the bar ends up a zero-sized
		# rect pinned to the corner and nothing ever appears.
		bar.set_anchors_and_offsets_preset(
			Control.PRESET_BOTTOM_RIGHT, Control.PRESET_MODE_MINSIZE, 14)
		return bar

	# --- drawing ------------------------------------------------------------

	func _draw() -> void:
		var world := HJWorld.shared()
		if _tex == null or not world.loaded:
			return
		_place()
		if _zoom <= 0.0:
			return
		var fog_colour := Palette.c("bg")
		draw_rect(Rect2(Vector2.ZERO, size), fog_colour)

		# --- world space. One transform, so the painting, the rings and the
		# fog all agree about where a cell is without any of them doing the
		# arithmetic themselves.
		var span := Vector2(float(world.w), float(world.h))
		draw_set_transform(size * 0.5 - _centre * _zoom, 0.0, Vector2(_zoom, _zoom))
		draw_texture_rect(_tex, Rect2(Vector2.ZERO, span), false)
		_draw_rings(world)
		_draw_fog(world, fog_colour, span)
		draw_set_transform_matrix(Transform2D.IDENTITY)

		# --- screen space. Marks keep their size however far you zoom out; a
		# marker that shrinks with the map stops being a marker.
		_draw_memory()
		_draw_found(world)
		_draw_player()

	## The rings, faintly. Difficulty is distance, and that is the single most
	## useful thing this picture can say — but it is context, not content, so it
	## sits under the fog and is only visible through ground you have walked.
	func _draw_rings(world: HJWorld) -> void:
		var centre := Vector2(world.w, world.h) * 0.5
		for ring in range(1, 5):
			draw_arc(centre, 24.0 * float(ring), 0.0, TAU, 96,
				Palette.ca("line", 0.35), 1.2 / _zoom, true)

	## The fog covers the explored region as a filtered texture and everything
	## outside it as flat colour, because outside it nothing has ever been seen
	## and there is no gradient to draw.
	func _draw_fog(world: HJWorld, colour: Color, span: Vector2) -> void:
		_fog.sync(world)
		if _fog.texture == null:
			draw_rect(Rect2(Vector2.ZERO, span), colour)
			return
		var box := _fog.rect
		draw_texture_rect(_fog.texture, box, false, colour)
		# The four margins around the fog buffer. Cheaper and sharper than
		# padding the texture out to the whole world would be.
		draw_rect(Rect2(0.0, 0.0, span.x, box.position.y), colour)
		draw_rect(Rect2(0.0, box.end.y, span.x, span.y - box.end.y), colour)
		draw_rect(Rect2(0.0, box.position.y, box.position.x, box.size.y), colour)
		draw_rect(Rect2(box.end.x, box.position.y, span.x - box.end.x, box.size.y), colour)

	## What was here last time you looked.
	##
	## Drawn from Discovery's own record rather than from the world, which is
	## the whole mechanic: once anomalies relocate between loops (#73) the world
	## no longer knows where one used to be, and a remembered mark on ground you
	## have not revisited is the only thing that does. A block you *have*
	## revisited is skipped here and drawn from the world below, which is how
	## the memory gets overwritten — per block, as you rediscover, rather than
	## wholesale at the start of a run.
	func _draw_memory() -> void:
		var remembered: Dictionary = Discovery.remembered()
		for key in remembered:
			var parts := String(key).split(",")
			if parts.size() != 2:
				continue
			var block := Vector2i(int(parts[0]), int(parts[1]))
			if Discovery.block_state(block) != Discovery.REMEMBERED:
				continue
			for row in (remembered[key] as Array):
				var mark: Array = row
				if mark.size() < 4:
					continue
				var at := _to_screen(Vector2(float(mark[0]) + 0.5, float(mark[1]) + 0.5))
				if not _on_screen(at):
					continue
				var tier := int(mark[2])
				# Hollow, thin and dim, against the filled dot a found one gets.
				# Weight carries the difference as well as alpha does, because
				# the map underneath is a painting and alpha alone loses to it.
				var role := "good" if int(mark[3]) != 0 else \
					("danger" if tier >= 3 else "accent")
				draw_arc(at, 9.0, 0.0, TAU, 20, Palette.ca(role, 0.38), 1.5, true)

	## What is here now, on ground walked this run.
	func _draw_found(world: HJWorld) -> void:
		var run: HJRun = Game.run
		for entry in world.anomalies:
			var a: Dictionary = entry
			var cell := Vector2i(int(a.get("x", 0)), int(a.get("y", 0)))
			if Discovery.block_state(Discovery.block_of(cell)) != Discovery.KNOWN:
				continue
			var at := _to_screen(Vector2(cell) + Vector2(0.5, 0.5))
			if not _on_screen(at):
				continue
			var tier := int(a.get("tier", 0))
			if run != null and run.anomalies_cleared.has(Game._cell_key(cell)):
				# Closed. Still drawn, because knowing where you have been is
				# half of knowing where to go next.
				draw_circle(at, 3.5, Palette.ca("good", 0.8))
				draw_arc(at, 9.0, 0.0, TAU, 20, Palette.ca("good", 0.7), 2.0, true)
				continue
			# Size and colour both carry tier, so it survives being small, and
			# the filled centre is what separates "found this run" from the
			# hollow ring a memory gets.
			var role := "danger" if tier >= 3 else "accent"
			var radius := 7.5 + float(tier) * 1.2
			draw_circle(at, 3.5, Palette.ca(role, 0.95))
			draw_arc(at, radius, 0.0, TAU, 22, Palette.ca(role, 0.95), 2.2, true)
			if String(a.get("area", "")) != "":
				# A written beat. A second ring rather than a label, because
				# nothing in this world carries writing that outlives the loop.
				draw_arc(at, radius + 3.5, 0.0, TAU, 24, Palette.ca(role, 0.45), 1.0, true)

	func _draw_player() -> void:
		var run: HJRun = Game.run
		if run == null or run.world_pos.x < 0:
			return
		var here := _to_screen(Vector2(run.world_pos) + Vector2(0.5, 0.5))
		var pulse := 0.5 + 0.5 * sin(float(Time.get_ticks_msec()) * 0.0035)
		if _on_screen(here):
			draw_arc(here, 4.0, 0.0, TAU, 14, Palette.c("text"), 2.5, true)
			draw_arc(here, 7.0 + pulse * 5.0, 0.0, TAU, 18,
				Palette.ca("text", 0.45 * (1.0 - pulse)), 2.0, true)
			return
		# Panned off the edge: an arrow on the rim pointing home, so "where am
		# I" is answerable without pressing anything.
		var middle := size * 0.5
		var edge := (here - middle).normalized()
		var tip := middle + edge * (minf(size.x, size.y) * 0.5 - 26.0)
		var side := Vector2(-edge.y, edge.x) * 8.0
		draw_colored_polygon(PackedVector2Array([tip + edge * 11.0, tip - side, tip + side]),
			Palette.ca("text", 0.75))

	func _on_screen(point: Vector2) -> bool:
		return point.x > -20.0 and point.y > -20.0 \
			and point.x < size.x + 20.0 and point.y < size.y + 20.0
