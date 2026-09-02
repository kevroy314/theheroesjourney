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
signal moved(cell: Vector2i)
signal blocked                      ## tried to move with nothing left to spend

const TILE := 32
## 32x48 — one tile wide, a tile and a half tall, which is the genre convention
## and the reason the old 24x32 figure read as a bollard rather than a person.
## 32 wide is deliberate rather than tight: it makes the horizontal placement
## offset below exactly zero, so the sprite grid *is* the tile grid, and it
## leaves room for the baked contact shadow, which the frame clips rather than
## the tile.
const FRAME_W := 32
const FRAME_H := 48
const ZOOM := 3                     ## the character is ~4mm tall at 1:1 on a phone
const STEP_TIME := 0.17             ## seconds to cross one tile

## Column order of the walk cycle. Neutral sits between the two steps on
## purpose: 0,1,2 gives a limp, because there is no neutral to pass through.
const CYCLE := [1, 0, 2, 0]

const FACINGS := {
	Vector2i.DOWN: 0, Vector2i.UP: 1, Vector2i.LEFT: 2, Vector2i.RIGHT: 3,
}

var world: HJWorld
var run: HJRun
var node_at: Dictionary = {}         ## Vector2i -> node id, this chapter's beats

var _tiles: Texture2D
var _variants: Texture2D
var _overlays: Texture2D
var _props: Texture2D
var _cliffs: Texture2D
var _player: Texture2D
var _cell := Vector2i.ZERO           ## the tile the character occupies
var _from := Vector2i.ZERO           ## where the current move started
var _facing := Vector2i.DOWN
var _moving := false
var _t := 0.0                        ## progress across the current tile, 0..1
var _cycle := 0                      ## which entry of CYCLE this step is using
var _held := Vector2i.ZERO           ## direction the player is holding


func _init(run_ref: HJRun, start: Vector2i = Vector2i(-1, -1)) -> void:
	run = run_ref
	world = HJWorld.shared()
	node_at = world.place_nodes(run_ref)
	# Carry the player's position between visits. The world does not reset when
	# you close a screen — it is the same world, and you are still standing in it.
	_cell = start if start.x >= 0 else world.spawn
	_cell = world.nearest_walkable(_cell)
	_from = _cell
	texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = true
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	size_flags_vertical = Control.SIZE_EXPAND_FILL


func _ready() -> void:
	_tiles = load("res://assets/tiles/tileset.png")
	_variants = load("res://assets/tiles/tileset_var.png")
	_overlays = load("res://assets/tiles/overlays.png")
	_props = load("res://assets/tiles/props.png")
	_cliffs = load("res://assets/tiles/cliffs.png")
	_player = load("res://assets/sprites/player.png")
	set_process(true)


## Called by the screen's d-pad and by the keyboard. Holding keeps walking.
func hold(direction: Vector2i) -> void:
	_held = direction


func here() -> String:
	return String(node_at.get(_cell, ""))


func cell() -> Vector2i:
	return _cell


func _process(delta: float) -> void:
	if _moving:
		_t += delta / STEP_TIME
		if _t < 1.0:
			queue_redraw()
			return
		_t = 0.0
		_moving = false
		_from = _cell
		moved.emit(_cell)
		var arrived := here()
		if arrived != "":
			node_entered.emit(arrived)
	if _held != Vector2i.ZERO:
		_try_move(_held)
	queue_redraw()


func _try_move(direction: Vector2i) -> void:
	_facing = direction
	var target := _cell + direction
	if not world.walkable(target.x, target.y):
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
	if world == null or not world.loaded or _tiles == null:
		return
	var scale := float(TILE * ZOOM)

	# Camera: the character sits in the middle of the view, except near the edges
	# of the map, where the view stops rather than showing void.
	var extent := Vector2(world.w, world.h) * scale
	var focus := (_character_px() + Vector2(TILE, TILE) * 0.5) * float(ZOOM)
	var cam := focus - size * 0.5
	cam.x = clampf(cam.x, 0.0, maxf(0.0, extent.x - size.x))
	cam.y = clampf(cam.y, 0.0, maxf(0.0, extent.y - size.y))
	if extent.x < size.x:
		cam.x = -(size.x - extent.x) * 0.5
	if extent.y < size.y:
		cam.y = -(size.y - extent.y) * 0.5

	# Only the cells actually on screen. Drawing the whole map would be fine at
	# this size and wrong at any other.
	var first := Vector2i(int(floor(cam.x / scale)), int(floor(cam.y / scale)))
	var last := Vector2i(
		int(ceil((cam.x + size.x) / scale)), int(ceil((cam.y + size.y) / scale)))
	for y in range(maxi(0, first.y), mini(world.h, last.y + 1)):
		for x in range(maxi(0, first.x), mini(world.w, last.x + 1)):
			_draw_cell(x, y, Rect2(Vector2(x, y) * scale - cam, Vector2(scale, scale)))

	for y in range(maxi(0, first.y), mini(world.h, last.y + 2)):
		for x in range(maxi(0, first.x), mini(world.w, last.x + 1)):
			_draw_cliff(x, y, scale, cam)

	_draw_markers(cam, scale)
	_draw_scenery(cam, first, last)


## Deterministic per cell, so a tile keeps its variant. A cell that reshuffled
## its fill every frame would shimmer.
static func _wobble(x: int, y: int, salt: int) -> int:
	var h := (x * 73856093) ^ (y * 19349663) ^ (salt * 83492791)
	return absi(h)


## One cell: its own fill, then every higher-ranked neighbour bleeding into it.
##
## This is the transliteration of `overlay_plan()` in tools/make_tiles.py, and
## it is what turns a mosaic of squares into terrain. Without it every material
## meets every other along a 32-pixel straight edge, which is precisely what
## "a bunch of disjoint right angles" describes.
##
## Cheap in the common case: most cells sit inside a field of their own material
## and draw exactly once.
func _draw_cell(x: int, y: int, dst: Rect2) -> void:
	var mine := world.at(x, y)

	# The fill, from one of four variants so a large field does not visibly tile.
	var variant := 0
	if world.variant_count > 0:
		variant = _wobble(x, y, 11) % (1 + world.variant_count)
	if variant == 0 or _variants == null:
		draw_texture_rect_region(_tiles, dst, Rect2(mine * TILE, 0, TILE, TILE))
	else:
		draw_texture_rect_region(_variants, dst,
			Rect2(mine * TILE, (variant - 1) * TILE, TILE, TILE))

	if _overlays == null:
		return
	var my_rank: int = world.rank.get(mine, -1)
	if my_rank < 0:
		return          # architectural: floors, walls, roofs neither bleed nor take

	# Which neighbouring materials outrank this one, and on which sides.
	var sides: Dictionary = {}      # tile id -> side bitmask
	var corners: Dictionary = {}    # tile id -> corner bitmask
	const SIDE := [Vector2i(0, -1), Vector2i(1, 0), Vector2i(0, 1), Vector2i(-1, 0)]
	const DIAG := [Vector2i(1, -1), Vector2i(1, 1), Vector2i(-1, 1), Vector2i(-1, -1)]

	for i in range(4):
		var n := world.at(x + SIDE[i].x, y + SIDE[i].y)
		if n == mine or int(world.rank.get(n, -1)) <= my_rank:
			continue
		sides[n] = int(sides.get(n, 0)) | (1 << i)
	for i in range(4):
		var n := world.at(x + DIAG[i].x, y + DIAG[i].y)
		if n == mine or int(world.rank.get(n, -1)) <= my_rank:
			continue
		# Only when neither adjacent side already carries it — otherwise the
		# edge piece has covered this corner and a second draw doubles the ink.
		var a := world.at(x + SIDE[i].x, y + SIDE[i].y)
		var b := world.at(x + SIDE[(i + 1) % 4].x, y + SIDE[(i + 1) % 4].y)
		if a == n or b == n:
			continue
		corners[n] = int(corners.get(n, 0)) | (1 << i)

	# Lowest rank first, so a shore laps over sand before the road lies over both.
	var others := sides.keys()
	for k in corners:
		if not others.has(k):
			others.append(k)
	others.sort_custom(func(a, b): return int(world.rank.get(a, 0)) < int(world.rank.get(b, 0)))

	for other in others:
		var slot: int = world.overlay_slot.get(other, -1)
		if slot < 0:
			continue
		var v := _wobble(x, y, other) % 3
		var side_mask := int(sides.get(other, 0))
		if side_mask > 0:
			draw_texture_rect_region(_overlays, dst,
				Rect2(side_mask * TILE, (slot * 6 + v * 2) * TILE, TILE, TILE))
		var corner_mask := int(corners.get(other, 0))
		if corner_mask > 0:
			draw_texture_rect_region(_overlays, dst,
				Rect2(corner_mask * TILE, (slot * 6 + v * 2 + 1) * TILE, TILE, TILE))


## A mark on every node tile, in the same vocabulary as the chalk board: amber
## for what you can do now, muted for what you cannot, and nothing at all for
## what you have not discovered.
func _draw_markers(cam: Vector2, scale: float) -> void:
	for cell in node_at:
		var id := String(node_at[cell])
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


## Index into cliffs.png, which is a 4-wide grid in this order.
const CLIFF := {
	"lip_mid": 0, "lip_left": 1, "lip_right": 2, "lip_solo": 3,
	"face_mid": 7, "face_left": 8, "face_right": 9,
	"shadow_mid": 12, "shadow_left": 13, "shadow_right": 14, "shadow_solo": 15,
}
const CLIFF_COLS := 4


## The wall of a terrace, wherever the ground steps down.
##
## Three cells deep: a lip on the upper terrace so the edge is not a bare cut, a
## full face on the cell below it, and a cast shadow under that. Drawn after the
## terrain and before the props, so a tree standing at the foot of a cliff is in
## front of it.
##
## Which of the three horizontal pieces is used depends on whether the drop
## continues either side — a face with nothing to its left needs a finished end,
## or a bluff reads as a slab that was cut off by the tile grid.
func _draw_cliff(x: int, y: int, scale: float, cam: Vector2) -> void:
	if _cliffs == null:
		return
	var piece := world.cliff_at(x, y)
	if piece == 0:
		return
	var kind: String = ["", "left", "mid", "right"][piece]
	_blit_cliff(CLIFF["lip_%s" % kind], x, y - 1, scale, cam)
	_blit_cliff(CLIFF["face_%s" % kind], x, y, scale, cam)
	_blit_cliff(CLIFF["shadow_%s" % kind], x, y + 1, scale, cam)


func _blit_cliff(index: int, x: int, y: int, scale: float, cam: Vector2) -> void:
	draw_texture_rect_region(_cliffs,
		Rect2(Vector2(x, y) * scale - cam, Vector2(scale, scale)),
		Rect2((index % CLIFF_COLS) * TILE, (index / CLIFF_COLS) * TILE, TILE, TILE))


const PROP_W := 64
const PROP_H := 96
const PROP_COLS := 8

## Props and the character, drawn together in one Y-sorted pass.
##
## A prop is 64x96 standing on a 32x32 cell, so it reaches up and out of the
## cell it belongs to. That means two things the terrain pass does not have to
## care about: props must be drawn after all the ground, or a neighbour's fill
## paints over the top of a tree; and they must be drawn in order of the row
## they stand on, together with the character, or he walks in front of a trunk
## he should be behind.
##
## One row of overscan at each end, because a prop anchored a row below the
## viewport still has 64 pixels of itself inside it.
func _draw_scenery(cam: Vector2, first: Vector2i, last: Vector2i) -> void:
	if _props == null:
		return
	var here := _cell.y
	var drawn_character := false
	for y in range(maxi(0, first.y - 1), mini(world.h, last.y + 3)):
		if not drawn_character and y > here:
			_draw_character(cam)
			drawn_character = true
		for x in range(maxi(0, first.x - 1), mini(world.w, last.x + 2)):
			var plane := world.prop_at(x, y)
			if plane == 0:
				continue
			var slot := plane - 1
			# Anchored bottom-centre of the cell: the art grows upward from the
			# ground the prop is standing on, which is what makes it sit in the
			# world rather than float on the grid.
			var origin := Vector2(x * TILE + TILE / 2 - PROP_W / 2,
				y * TILE + TILE - PROP_H)
			draw_texture_rect_region(_props,
				Rect2(origin * float(ZOOM) - cam, Vector2(PROP_W, PROP_H) * float(ZOOM)),
				Rect2((slot % PROP_COLS) * PROP_W, (slot / PROP_COLS) * PROP_H,
					PROP_W, PROP_H))
	if not drawn_character:
		_draw_character(cam)


func _draw_character(cam: Vector2) -> void:
	if _player == null:
		return
	var row := int(FACINGS.get(_facing, 0))
	# Standing still is column 0 with no special case — that is why the sheet
	# puts neutral there.
	var col := int(CYCLE[_cycle]) if _moving else 0
	var px := _character_px()
	# Centred horizontally and standing on the tile's bottom edge, which is where
	# its feet are drawn. At 32 wide the centring term is zero; it is kept so the
	# geometry still reads correctly if the frame ever changes width.
	#
	# The figure is taller than its tile, so its head overlaps the row above —
	# exactly like a prop, which is why this is called from inside the Y-sorted
	# scenery pass rather than after it.
	var dst := Rect2(
		(px + Vector2((TILE - FRAME_W) * 0.5, TILE - FRAME_H)) * float(ZOOM) - cam,
		Vector2(FRAME_W, FRAME_H) * float(ZOOM))
	draw_texture_rect_region(_player, dst,
		Rect2(col * FRAME_W, row * FRAME_H, FRAME_W, FRAME_H))
