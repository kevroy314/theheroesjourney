extends HJScreen
## The map. One screen for "where am I and where could I go".
##
## This replaces two. The Journey was a list of eight chapters in the order you
## would be handed them, and once chapters became places that list was a lie —
## there is no order any more. The map was the other half of the same
## information and carried none of it: no anomalies, no rings, no way to tell a
## cleared one from a waiting one.
##
## What a player actually needs out here is three things: where they are, what
## is worth walking to, and how much further out the hard ones start. All three
## are spatial, so they belong on the picture rather than in a list beside it.
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
	v.add_child(_view)

	v.add_child(_legend())

	var walk := HJUI.button("Walk", "primary")
	walk.pressed.connect(func(): Game.goto("overworld"))
	v.add_child(walk)


## One line of state, not a screen of it.
func _summary() -> String:
	var run: HJRun = Game.run
	if run == null:
		return String(Palette.data.get("mountain_line", ""))
	var world := HJWorld.shared()
	var left := 0
	for entry in world.anomalies:
		var a: Dictionary = entry
		if not run.anomalies_cleared.has(
				Game._cell_key(Vector2i(int(a.get("x", 0)), int(a.get("y", 0))))):
			left += 1
	var burn := "" if Steps.burn <= 1.001 else "  ·  burning %.1fx" % Steps.burn
	return "Ring %d  ·  %d anomalies still open%s" % [run.zone, left, burn]


## The marks, explained once. A map whose symbols have to be guessed at is a
## picture; this is the difference between the two.
func _legend() -> Control:
	var panel := HJUI.panel("panel")
	var row := HJUI.hbox(14)
	for entry in [["you", "text"], ["open", "accent"], ["done", "good"], ["hard", "danger"]]:
		var item := HJUI.hbox(6)
		var dot := MapDot.new(Palette.c(String(entry[1])))
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


## The drawn map, with everything that moves painted on top of it.
class MapView extends Control:
	var _tex: Texture2D

	func _init() -> void:
		mouse_filter = Control.MOUSE_FILTER_IGNORE
		texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		if ResourceLoader.exists(MAP):
			_tex = load(MAP)

	func _ready() -> void:
		set_process(true)

	func _process(_delta: float) -> void:
		queue_redraw()

	func _to_screen(cell: Vector2i, origin: Vector2, shown: Vector2,
			world: HJWorld) -> Vector2:
		return origin + Vector2(
			(float(cell.x) + 0.5) / float(world.w) * shown.x,
			(float(cell.y) + 0.5) / float(world.h) * shown.y)

	func _draw() -> void:
		if _tex == null:
			return
		# Fit whole, never crop: a map you cannot see the edges of is a viewport.
		var src := Vector2(_tex.get_width(), _tex.get_height())
		var fit := minf(size.x / src.x, size.y / src.y)
		var shown := src * fit
		var origin := (size - shown) * 0.5
		draw_texture_rect(_tex, Rect2(origin, shown), false)

		var world := HJWorld.shared()
		if not world.loaded:
			return
		var run: HJRun = Game.run

		# The rings, faintly. Difficulty is distance, and that is the single most
		# useful thing this picture can say — but it is context, not content, so
		# it sits under everything and stays quiet.
		var centre := _to_screen(Vector2i(world.w / 2, world.h / 2), origin, shown, world)
		var ring_px := shown.x / float(world.w) * 24.0
		for ring in range(1, 5):
			draw_arc(centre, ring_px * float(ring), 0.0, TAU, 64,
				Palette.ca("line", 0.30), 1.0, true)

		for entry in world.anomalies:
			var a: Dictionary = entry
			var cell := Vector2i(int(a.get("x", 0)), int(a.get("y", 0)))
			var tier := int(a.get("tier", 0))
			var cleared := run != null and run.anomalies_cleared.has(Game._cell_key(cell))
			var at := _to_screen(cell, origin, shown, world)

			if cleared:
				# Closed. Still drawn, because knowing where you have been is
				# half of knowing where to go next.
				draw_arc(at, 4.0, 0.0, TAU, 12, Palette.ca("good", 0.65), 2.0, true)
				continue
			# Size and colour both carry tier, so it survives being small.
			var role := "danger" if tier >= 3 else "accent"
			var radius := 3.5 + float(tier) * 0.9
			draw_arc(at, radius, 0.0, TAU, 14, Palette.ca(role, 0.95), 2.0, true)
			if String(a.get("area", "")) != "":
				# A written beat. A second ring rather than a label, because
				# nothing in this world carries writing that outlives the loop.
				draw_arc(at, radius + 3.0, 0.0, TAU, 16, Palette.ca(role, 0.45), 1.0, true)

		if run != null and run.world_pos.x >= 0:
			var here := _to_screen(run.world_pos, origin, shown, world)
			var pulse := 0.5 + 0.5 * sin(float(Time.get_ticks_msec()) * 0.0035)
			draw_arc(here, 4.0, 0.0, TAU, 14, Palette.c("text"), 2.5, true)
			draw_arc(here, 7.0 + pulse * 5.0, 0.0, TAU, 18,
				Palette.ca("text", 0.45 * (1.0 - pulse)), 2.0, true)
