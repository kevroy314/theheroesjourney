class_name HJTileWorld
extends Control
## The walkable map: tiles, a character, a camera that follows them, and a step
## budget that decides whether they get to move at all.
##
## Everything is drawn in one _draw pass rather than built as nodes. A 25x40 map
## is a thousand cells, and a thousand TextureRects is a thousand Controls the
## layout engine has to size every frame for no benefit — nothing here is
## interactive except the character.

signal node_entered(id: String)
signal blocked                      ## tried to move with nothing left to spend

const TILE := 32
const FRAME_W := 24
const FRAME_H := 32
const ZOOM := 3                     ## the character is ~4mm tall at 1:1 on a phone
const STEP_TIME := 0.17             ## seconds to cross one tile

## Column order of the walk cycle. Neutral sits between the two steps on
## purpose: 0,1,2 gives a limp, because there is no neutral to pass through.
const CYCLE := [1, 0, 2, 0]

const FACINGS := {
	Vector2i.DOWN: 0, Vector2i.UP: 1, Vector2i.LEFT: 2, Vector2i.RIGHT: 3,
}

var map: HJMapGen
var run: HJRun

var _tiles: Texture2D
var _player: Texture2D
var _cell := Vector2i.ZERO           ## the tile the character occupies
var _from := Vector2i.ZERO           ## where the current move started
var _facing := Vector2i.DOWN
var _moving := false
var _t := 0.0                        ## progress across the current tile, 0..1
var _cycle := 0                      ## which entry of CYCLE this step is using
var _held := Vector2i.ZERO           ## direction the player is holding


func _init(run_ref: HJRun) -> void:
	run = run_ref
	map = HJMapGen.build(run_ref)
	_cell = map.spawn
	_from = _cell
	texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = true
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	size_flags_vertical = Control.SIZE_EXPAND_FILL


func _ready() -> void:
	_tiles = load("res://assets/tiles/tileset.png")
	_player = load("res://assets/sprites/player.png")
	set_process(true)


## Called by the screen's d-pad and by the keyboard. Holding keeps walking.
func hold(direction: Vector2i) -> void:
	_held = direction


func here() -> String:
	return String(map.node_at.get(_cell, ""))


func _process(delta: float) -> void:
	if _moving:
		_t += delta / STEP_TIME
		if _t < 1.0:
			queue_redraw()
			return
		_t = 0.0
		_moving = false
		_from = _cell
		var arrived := here()
		if arrived != "":
			node_entered.emit(arrived)
	if _held != Vector2i.ZERO:
		_try_move(_held)
	queue_redraw()


func _try_move(direction: Vector2i) -> void:
	_facing = direction
	var target := _cell + direction
	if not map.walkable(target.x, target.y):
		return
	# The budget is spent on arrival at a new tile, never on turning on the spot
	# and never on walking into a wall. You are charged for ground covered.
	if not Steps.spend(1):
		blocked.emit()
		return
	_from = _cell
	_cell = target
	_moving = true
	_t = 0.0
	_cycle = (_cycle + 1) % CYCLE.size()


## Where the character is in pixels, interpolated across the tile it is crossing.
func _character_px() -> Vector2:
	var a := Vector2(_from) * float(TILE)
	var b := Vector2(_cell) * float(TILE)
	return a.lerp(b, _t) if _moving else b


func _draw() -> void:
	if map == null or _tiles == null:
		return
	var scale := float(TILE * ZOOM)

	# Camera: the character sits in the middle of the view, except near the edges
	# of the map, where the view stops rather than showing void.
	var world := Vector2(map.w, map.h) * scale
	var focus := (_character_px() + Vector2(TILE, TILE) * 0.5) * float(ZOOM)
	var cam := focus - size * 0.5
	cam.x = clampf(cam.x, 0.0, maxf(0.0, world.x - size.x))
	cam.y = clampf(cam.y, 0.0, maxf(0.0, world.y - size.y))
	if world.x < size.x:
		cam.x = -(size.x - world.x) * 0.5
	if world.y < size.y:
		cam.y = -(size.y - world.y) * 0.5

	# Only the cells actually on screen. Drawing the whole map would be fine at
	# this size and wrong at any other.
	var first := Vector2i(int(floor(cam.x / scale)), int(floor(cam.y / scale)))
	var last := Vector2i(
		int(ceil((cam.x + size.x) / scale)), int(ceil((cam.y + size.y) / scale)))
	for y in range(maxi(0, first.y), mini(map.h, last.y + 1)):
		for x in range(maxi(0, first.x), mini(map.w, last.x + 1)):
			var index := map.at(x, y)
			var dst := Rect2(Vector2(x, y) * scale - cam, Vector2(scale, scale))
			draw_texture_rect_region(_tiles, dst,
				Rect2(index * TILE, 0, TILE, TILE))

	_draw_markers(cam, scale)
	_draw_character(cam)


## A mark on every node tile, in the same vocabulary as the chalk board: amber
## for what you can do now, muted for what you cannot, and nothing at all for
## what you have not discovered.
func _draw_markers(cam: Vector2, scale: float) -> void:
	for cell in map.node_at:
		var id := String(map.node_at[cell])
		if not HJAreaGen.is_visible(run, id):
			continue
		var done := run.is_done(id)
		var available := HJAreaGen.is_available(run, id)
		var colour := Palette.ca("good", 0.9) if done \
			else (Palette.ca("accent", 0.95) if available else Palette.ca("muted", 0.5))
		var centre := (Vector2(cell) + Vector2(0.5, 0.5)) * scale - cam
		# A ring rather than a fill: the tile underneath is the place, and a
		# solid blob would paint over it.
		var radius := scale * 0.34
		draw_arc(centre, radius, 0.0, TAU, 20, colour, 3.0, true)
		if available and not done:
			# The one you can act on breathes, so the eye finds it without
			# reading anything.
			var pulse := 0.5 + 0.5 * sin(float(Time.get_ticks_msec()) * 0.004)
			draw_arc(centre, radius + 4.0 + pulse * 4.0, 0.0, TAU, 20,
				Color(colour.r, colour.g, colour.b, 0.30 * (1.0 - pulse)), 2.0, true)


func _draw_character(cam: Vector2) -> void:
	if _player == null:
		return
	var row := int(FACINGS.get(_facing, 0))
	# Standing still is column 0 with no special case — that is why the sheet
	# puts neutral there.
	var col := int(CYCLE[_cycle]) if _moving else 0
	var px := _character_px()
	# The sprite is 24x32 against a 32x32 tile: centre it horizontally and stand
	# it on the tile's bottom edge, which is where its feet are drawn.
	var dst := Rect2(
		(px + Vector2((TILE - FRAME_W) * 0.5, TILE - FRAME_H)) * float(ZOOM) - cam,
		Vector2(FRAME_W, FRAME_H) * float(ZOOM))
	draw_texture_rect_region(_player, dst,
		Rect2(col * FRAME_W, row * FRAME_H, FRAME_W, FRAME_H))
