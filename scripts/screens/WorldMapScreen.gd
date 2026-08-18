extends HJScreen
## The drawn map of the world, with a mark where you are standing.
##
## It is a rendering of the same grid you walk on — tools/make_world.py writes
## both from one source — so it cannot tell you the coast is somewhere it is not.
##
## No place names on it. The persistence rule: nothing written down survives a
## loop, and a map with labels would be a record of a world that is about to
## forget you. What it carries instead are rings, drawn where the beats of this
## chapter sit, and one lit mark for the mountain.

const MAP := "res://assets/world/worldmap.png"

var _view: MapView


func build() -> void:
	var v := page(10)

	var head := HJUI.panel("panel")
	var row := HJUI.hbox(10)
	var titles := HJUI.vbox(2)
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	titles.add_child(HJUI.label("The Way Up", HJUI.FS_HEAD, "text"))
	titles.add_child(HJUI.label(
		Palette.data.get("mountain_line", "One light, still burning."),
		HJUI.FS_TINY, "muted"))
	row.add_child(titles)
	head.add_child(row)
	v.add_child(head)

	_view = MapView.new()
	_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	v.add_child(_view)

	var actions := HJUI.hbox(10)
	var walk := HJUI.button("Walk", "primary")
	walk.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	walk.pressed.connect(func(): Game.goto("overworld"))
	actions.add_child(walk)
	var list := HJUI.button("List", "ghost")
	list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list.pressed.connect(func(): Game.goto("area"))
	actions.add_child(list)
	v.add_child(actions)


## Draws the map scaled to fit, and puts you on it.
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
		queue_redraw()          # the "you are here" mark pulses

	## A world cell in this control's coordinates. A method rather than a local
	## Callable: calling through a Callable returns Variant, and the inferred
	## type then trips the treat-warnings-as-errors build.
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
		if run != null and not run.area.is_empty():
			# Once, not once per marker: place_nodes walks a spiral and spirals
			# are not free sixty times a second.
			var placed := world.place_nodes(run)
			for cell in placed:
				var done := run.is_done(String(placed[cell]))
				draw_arc(_to_screen(cell, origin, shown, world), 5.0, 0.0, TAU, 12,
					Palette.ca("good" if done else "accent", 0.85), 2.0, true)

		# You. A ring that breathes, because on a map this size a static dot is
		# indistinguishable from a feature of the terrain.
		if run != null and run.world_pos.x >= 0:
			var here := _to_screen(run.world_pos, origin, shown, world)
			var pulse := 0.5 + 0.5 * sin(float(Time.get_ticks_msec()) * 0.0035)
			draw_arc(here, 4.0, 0.0, TAU, 14, Palette.c("text"), 2.5, true)
			draw_arc(here, 7.0 + pulse * 5.0, 0.0, TAU, 18,
				Palette.ca("text", 0.45 * (1.0 - pulse)), 2.0, true)
