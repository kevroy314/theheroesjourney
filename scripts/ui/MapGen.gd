class_name HJMapGen
extends RefCounted
## Turns an area's node graph into somewhere you can walk.
##
## The area already *is* a graph — entry at the top, the door at the bottom,
## branches side by side. The map is that graph laid on the ground: each node
## gets a tile you can stand on, and the edges become corridors you have to walk
## down. Nothing about the progression changes; what changes is that reaching a
## node costs steps and you choose the order.
##
## Generated rather than authored, because there are eight chapters and the node
## layout is itself generated per run. Deterministic from the run's seed, so
## walking back into an area finds it exactly as you left it.

## Indices into assets/tiles/tileset.png. See docs/OVERWORLD-ART.md.
enum {
	T_BOARDS, T_STONE, T_GRASS, T_TALL, T_PATH,
	T_DOOR, T_PLASTER, T_WALL, T_WATER, T_ROCK, T_VOID,
}

const SOLID := [T_PLASTER, T_WALL, T_WATER, T_ROCK, T_VOID]

const ROW_PITCH := 5        ## tiles between one depth of the graph and the next
const SIDE_PITCH := 6       ## tiles between two nodes at the same depth
const MARGIN := 3

## Which materials each chapter is made of: [ground, corridor, wall].
const PALETTES := {
	"waking_room": [T_BOARDS, T_BOARDS, T_PLASTER],
	"the_house": [T_BOARDS, T_STONE, T_PLASTER],
	"the_town": [T_STONE, T_PATH, T_WALL],
	"tall_grass": [T_TALL, T_PATH, T_ROCK],
	"long_road": [T_GRASS, T_PATH, T_ROCK],
	"foothills": [T_GRASS, T_PATH, T_ROCK],
	"observatory": [T_STONE, T_STONE, T_WALL],
	"summit": [T_STONE, T_PATH, T_ROCK],
}

var w: int = 0
var h: int = 0
var tiles: PackedInt32Array = PackedInt32Array()
var spawn := Vector2i.ZERO
var node_at: Dictionary = {}     ## Vector2i -> node id
var cell_of: Dictionary = {}     ## node id -> Vector2i


func at(x: int, y: int) -> int:
	if x < 0 or y < 0 or x >= w or y >= h:
		return T_VOID
	return tiles[y * w + x]


func _put(x: int, y: int, tile: int) -> void:
	if x < 0 or y < 0 or x >= w or y >= h:
		return
	tiles[y * w + x] = tile


func walkable(x: int, y: int) -> bool:
	return not SOLID.has(at(x, y))


## Depth of every node from the entry, the same measure the area graph uses to
## decide its rows. Side nodes ride along with whatever they hang off.
static func depths(run: HJRun) -> Dictionary:
	var depth: Dictionary = {}
	var entry := String(run.area.get("entry", ""))
	if entry == "":
		return depth
	var frontier: Array = [entry]
	depth[entry] = 0
	var guard := 0
	while frontier.size() > 0 and guard < 500:
		guard += 1
		var id: String = frontier.pop_front()
		for nxt in run.node(id).get("next", []):
			var next_id := String(nxt)
			var d := int(depth[id]) + 1
			if not depth.has(next_id) or int(depth[next_id]) < d:
				depth[next_id] = d
				frontier.append(next_id)
	for id in run.area.get("order", []):
		var node := run.node(String(id))
		var anchor := String(node.get("side_of", ""))
		if anchor != "" and depth.has(anchor):
			depth[String(id)] = int(depth[anchor])
	return depth


static func build(run: HJRun) -> HJMapGen:
	var map := HJMapGen.new()
	var area_id := String(run.chapter_def().get("area", "waking_room"))
	var palette: Array = PALETTES.get(area_id, [T_GRASS, T_PATH, T_ROCK])
	var ground: int = palette[0]
	var corridor: int = palette[1]
	var wall: int = palette[2]

	var depth := depths(run)
	var by_row: Dictionary = {}
	for id in run.area.get("order", []):
		var key := int(depth.get(String(id), 0))
		var row: Array = by_row.get(key, [])
		row.append(String(id))
		by_row[key] = row
	var keys: Array = by_row.keys()
	keys.sort()
	if keys.is_empty():
		keys = [0]
		by_row[0] = []

	var widest := 1
	for key in keys:
		widest = maxi(widest, by_row[key].size())

	map.w = MARGIN * 2 + (widest - 1) * SIDE_PITCH + 1
	map.w = maxi(map.w, 15)
	map.h = MARGIN * 2 + (keys.size() - 1) * ROW_PITCH + 1
	map.h = maxi(map.h, 11)
	map.tiles = PackedInt32Array()
	map.tiles.resize(map.w * map.h)
	map.tiles.fill(wall)

	# Deterministic per run and per chapter, so the same area is the same place
	# every time you walk back into it.
	var rng := RandomNumberGenerator.new()
	rng.seed = hash("%d/%s" % [run.seed, area_id])

	# The floor: an open field of ground with a ragged edge, so the room is not a
	# perfect rectangle. Corridors are cut through it afterwards.
	for y in range(1, map.h - 1):
		for x in range(1, map.w - 1):
			map._put(x, y, ground)
	for i in range(int(map.w * map.h * 0.04)):
		var bx := rng.randi_range(1, map.w - 2)
		var by := rng.randi_range(1, map.h - 2)
		map._put(bx, by, wall)

	# Node positions: depth is the row, position within the row is the column,
	# centred.
	for row_index in range(keys.size()):
		var ids: Array = by_row[keys[row_index]]
		var y := MARGIN + row_index * ROW_PITCH
		var span := (ids.size() - 1) * SIDE_PITCH
		var x0 := int((map.w - 1 - span) * 0.5)
		for i in range(ids.size()):
			var cell := Vector2i(x0 + i * SIDE_PITCH, y)
			map.node_at[cell] = ids[i]
			map.cell_of[ids[i]] = cell

	# Corridors along the real edges, so the shape of the walk matches the shape
	# of the graph. Carved after the blockages so a route is never sealed.
	for id in map.cell_of:
		var from: Vector2i = map.cell_of[id]
		for nxt in run.node(String(id)).get("next", []):
			var to: Vector2i = map.cell_of.get(String(nxt), from)
			if to == from:
				continue
			map._carve(from, to, corridor)

	# A clearing around every node, so you can always stand next to one and it is
	# never walled in by the rubble scattered above.
	for cell in map.node_at:
		for dy in range(-1, 2):
			for dx in range(-1, 2):
				map._put(cell.x + dx, cell.y + dy, corridor)

	# The way out is a door you can see from across the room.
	for cell in map.node_at:
		if String(run.node(String(map.node_at[cell])).get("type", "")) == "threshold":
			map._put(cell.x, cell.y, T_DOOR)

	var entry := String(run.area.get("entry", ""))
	map.spawn = map.cell_of.get(entry, Vector2i(int(map.w * 0.5), MARGIN))
	return map


## An L-shaped corridor: along x, then along y. Two tiles wide on the turn so a
## corner never becomes a one-tile pinch you can miss.
func _carve(from: Vector2i, to: Vector2i, tile: int) -> void:
	var x := from.x
	while x != to.x:
		x += signi(to.x - x)
		_put(x, from.y, tile)
		_put(x, from.y + 1, tile)
	var y := from.y
	while y != to.y:
		y += signi(to.y - y)
		_put(to.x, y, tile)
		_put(to.x + 1, y, tile)
