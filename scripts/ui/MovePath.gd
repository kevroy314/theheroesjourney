class_name HJMovePath
## Walking routes across the overworld.
##
## HJWorld knows what is walkable and where the nearest walkable cell is, but it
## has never known how to get anywhere: until tap-to-walk, every mover in the
## game was a player holding a direction, so a route was never needed. This is
## the missing piece, kept outside HJWorld because it is a question about a
## journey rather than a fact about the map.
##
## Four-way even when the pad in use is eight-way. A tapped destination is a
## promise about cost — the status line quotes the number of steps before you
## commit — and a route that quietly took diagonals would spend a different
## number than the one the player was shown.

## A journey longer than this is not a tap, it is a plan, and the map window is
## about seven tiles across so nothing visible is anywhere near it. It also
## bounds the search: without a depth cap a tap into a walled courtyard would
## flood all 65536 cells of the overworld looking for a way in.
const MAX_STEPS := 64
## Belt and braces for the pathological case — a tap onto a walkable cell inside
## a large sealed region, where the depth cap alone still lets the frontier
## sprawl. Six thousand cells is far more than a 64-step disc can contain.
const MAX_VISITS := 6000

const DIRS := [Vector2i.UP, Vector2i.RIGHT, Vector2i.DOWN, Vector2i.LEFT]


## The cells to walk through to get from `from` to `to` — `from` excluded, `to`
## included. Empty when there is no route within the budget, which the caller
## must say out loud rather than swallow: a tap that does nothing at all is
## indistinguishable from a tap that missed.
static func find(world: HJWorld, from: Vector2i, to: Vector2i) -> Array[Vector2i]:
	var out: Array[Vector2i] = []
	if world == null or not world.loaded or from == to:
		return out
	if not world.walkable(to.x, to.y):
		return out

	# Breadth-first, so the first route found is the cheapest one, and steps are
	# the currency this game is actually about. A* would need a heuristic and a
	# priority queue to save a few milliseconds on a 64-step disc.
	var came: Dictionary = {from: from}
	var depth: Dictionary = {from: 0}
	var queue: Array[Vector2i] = [from]
	var head := 0
	var found := false
	while head < queue.size() and came.size() < MAX_VISITS:
		var cell: Vector2i = queue[head]
		head += 1
		if cell == to:
			found = true
			break
		var d: int = depth[cell]
		if d >= MAX_STEPS:
			continue
		for step in DIRS:
			var next: Vector2i = cell + step
			if came.has(next) or not world.walkable(next.x, next.y):
				continue
			came[next] = cell
			depth[next] = d + 1
			queue.append(next)
	if not found:
		return out

	var walk := to
	while walk != from:
		out.append(walk)
		walk = came[walk]
	out.reverse()
	return out


## Same, but forgiving about where the thumb landed. A tap on the wall beside a
## doorway is a tap on the doorway; a tap in the middle of the sea is not, which
## is why the search radius is three cells and not forty.
static func route_to(world: HJWorld, from: Vector2i, target: Vector2i) -> Array[Vector2i]:
	var none: Array[Vector2i] = []
	if world == null or not world.loaded:
		return none
	var goal := target
	if not world.walkable(goal.x, goal.y):
		goal = world.nearest_walkable(goal, 3)
	return find(world, from, goal)
