class_name HJTapWalk
extends Control
## The map as the control: tap a tile, walk there.
##
## Lives as a child of HJTileWorld and fills it, because the tile world draws
## everything in one pass and takes no input at all (MOUSE_FILTER_IGNORE) — so
## the only way to make the map tappable without turning a thousand cells into a
## thousand Controls is one transparent sheet over the top of it.
##
## It also draws the route it is about to walk, which is the honest thing to do
## when a single tap is about to spend a dozen steps.

signal cell_tapped(cell: Vector2i)

## A tap that travelled further than this was somebody's finger sliding, not a
## destination. Slightly wider than HJUI.TapCard's twelve because a map invites
## a drag and the cost of a misfire here is real steps.
const SLOP := 16.0

var _world: HJTileWorld
var _path: Array[Vector2i] = []
var _source := ""
var _travel := 0.0
var _down := Vector2.ZERO


func _init(tile_world: HJTileWorld) -> void:
	_world = tile_world
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	# STOP: this sheet is the control, and the map sits in a plain page column
	# with no scroller above it to hand a drag on to.
	mouse_filter = Control.MOUSE_FILTER_STOP


func _ready() -> void:
	set_process(true)


func _process(_delta: float) -> void:
	# The camera moves under the route while it is being walked, so the markers
	# have to be redrawn with it. Only while there is something to draw.
	if not _path.is_empty():
		queue_redraw()


func show_path(path: Array[Vector2i]) -> void:
	_path = path.duplicate()
	queue_redraw()


## Touch wins and may take a live press off the mouse — see HJMovePad for why
## the emulated mouse press must not be allowed to claim the gesture.
func _gui_input(event: InputEvent) -> void:
	if event is InputEventScreenTouch:
		var touch: InputEventScreenTouch = event
		if touch.pressed:
			_begin("touch", touch.position)
		elif _source == "touch":
			_finish(touch.position)
		accept_event()
	elif event is InputEventScreenDrag and _source == "touch":
		_travel += (event as InputEventScreenDrag).relative.length()
	elif event is InputEventMouseButton:
		var button: InputEventMouseButton = event
		if button.button_index != MOUSE_BUTTON_LEFT:
			return
		if button.pressed:
			if _source == "":
				_begin("mouse", button.position)
		elif _source == "mouse":
			_finish(button.position)
		accept_event()
	elif event is InputEventMouseMotion and _source == "mouse":
		_travel += (event as InputEventMouseMotion).relative.length()


func _begin(source: String, at: Vector2) -> void:
	_source = source
	_travel = 0.0
	_down = at


func _finish(_at: Vector2) -> void:
	_source = ""
	if _travel >= SLOP:
		return
	cell_tapped.emit(cell_at(_down))


# --- the camera ---------------------------------------------------------------

## Which tile is under a point on this sheet.
##
## This mirrors the camera in HJTileWorld._draw, which is not exposed — the
## renderer computes it per frame as a local. Duplicated rather than reached
## for because the alternative is a screen editing the renderer; if a third
## caller ever wants it, HJTileWorld should grow `cell_at_point()` and this
## should call it.
func cell_at(point: Vector2) -> Vector2i:
	var scale := float(HJTileWorld.TILE * HJTileWorld.ZOOM)
	var at := (point + _camera()) / scale
	return Vector2i(int(floor(at.x)), int(floor(at.y)))


func _camera() -> Vector2:
	var world: HJWorld = _world.world
	var scale := float(HJTileWorld.TILE * HJTileWorld.ZOOM)
	var extent := Vector2(float(world.w), float(world.h)) * scale
	var half := float(HJTileWorld.TILE) * 0.5
	var focus := (_character_px() + Vector2(half, half)) * float(HJTileWorld.ZOOM)
	var cam := focus - size * 0.5
	cam.x = clampf(cam.x, 0.0, maxf(0.0, extent.x - size.x))
	cam.y = clampf(cam.y, 0.0, maxf(0.0, extent.y - size.y))
	if extent.x < size.x:
		cam.x = -(size.x - extent.x) * 0.5
	if extent.y < size.y:
		cam.y = -(size.y - extent.y) * 0.5
	return cam


## Interpolated, not snapped. Mid-stride the camera is up to a whole tile away
## from the tile the character legally occupies, and a whole tile here is 96
## screen pixels — enough to send a tap one cell wide of where it was aimed.
func _character_px() -> Vector2:
	var tile := float(HJTileWorld.TILE)
	var a := Vector2(_world._from) * tile
	var b := Vector2(_world.cell()) * tile
	return a.lerp(b, _world._t) if _world._moving else b


func _draw() -> void:
	if _path.is_empty() or _world == null or _world.world == null:
		return
	var scale := float(HJTileWorld.TILE * HJTileWorld.ZOOM)
	var cam := _camera()
	var last := _path.size() - 1
	for i in range(_path.size()):
		var centre := (Vector2(_path[i]) + Vector2(0.5, 0.5)) * scale - cam
		if i == last:
			# The destination is a ring in the same vocabulary as a node marker,
			# so "this is a place I am going" reads the same way everywhere.
			draw_arc(centre, scale * 0.34, 0.0, TAU, 20, Palette.ca("accent", 0.95), 3.0, true)
		else:
			draw_circle(centre, scale * 0.09, Palette.ca("accent", 0.5))
