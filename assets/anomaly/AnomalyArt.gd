extends RefCounted
## Draws an anomaly — the animated tear you walk onto to open a task graph.
##
## Art and rationale: tools/make_anomaly.py. Sheets: anomaly.png (24-frame loop,
## 5 tier rows) and anomaly_collapse.png (16-frame one shot, same rows).
##
## Deliberately not a node. TileWorld draws its whole world in one immediate-mode
## `_draw`, and a Control's children draw *after* all of it — there is no
## ordering that puts a child node between the ground and the Y-sorted scenery
## pass, so a shaded ColorRect would either hide under the grass or paint over
## the character's legs when he stands on the tear. Blitting a strip from inside
## `_draw_scenery`'s row loop inherits the Y-sort for free and costs one
## `draw_texture_rect_region` per visible anomaly, no node, no material, no
## allocation.
##
## No `class_name`: this is a helper for one renderer, reached by preload.
##
##     const AnomalyArt := preload("res://assets/anomaly/AnomalyArt.gd")
##     var _anomalies := AnomalyArt.new()
##
## Then, inside `_draw_scenery`'s inner loop — before the prop blit, so the tear
## is in the ground and a prop standing on the same cell is on top of it:
##
##     var tier := world.anomaly_at(x, y)          # -1 where there is none
##     if tier >= 0:
##         _anomalies.draw_at(self, Vector2i(x, y), tier, cam, TILE, ZOOM)
##
## and in `_process`, next to the walk cycle:
##
##     _anomalies.advance(delta)
##
## When the mechanic clears one, `_anomalies.collapse(cell)` starts the one shot.
## `finished(cell)` goes true when it has played out, which is the caller's cue
## to stop passing that cell to `draw_at` — after which `forget(cell)` drops the
## bookkeeping.

## Must match tools/make_anomaly.py. assets/anomaly/anomaly.json carries the same
## numbers if you would rather read them than trust this comment.
const CELL := 72
const FPS := 12
const FRAMES := 24
const END_FRAMES := 16
const TIERS := 5

var _loop: Texture2D = load("res://assets/anomaly/anomaly.png")
var _end: Texture2D = load("res://assets/anomaly/anomaly_collapse.png")

## Vector2i -> seconds since the collapse started. Only ever a handful of
## entries, and only while one is actually playing.
var _closing: Dictionary = {}


## One anomaly, centred on its cell.
##
## Centred rather than anchored to its foot the way a prop is: a prop stands on
## the ground and grows upward out of its cell, and a tear lies *in* the ground,
## so its middle is the cell's middle. `cam` is the same camera offset the rest
## of the pass uses; `tile` and `zoom` are TileWorld's TILE and ZOOM.
func draw_at(canvas: CanvasItem, cell: Vector2i, tier: int,
		cam: Vector2, tile: int, zoom: int) -> void:
	if _loop == null:
		return
	var tex := _loop
	var frames := FRAMES
	# One clock for every looping anomaly on screen, so two of them in frame read
	# as two mouths of one thing rather than as two unrelated props. A collapsing
	# one is on its own clock because it started when the player cleared it.
	var f := int(Time.get_ticks_msec() * FPS / 1000) % FRAMES
	if _closing.has(cell):
		tex = _end
		frames = END_FRAMES
		f = int(float(_closing[cell]) * FPS)
		if f >= END_FRAMES:
			return
	if tex == null:
		return
	var row := clampi(tier, 0, TIERS - 1)
	var origin := Vector2(cell.x * tile + tile / 2 - CELL / 2,
			cell.y * tile + tile / 2 - CELL / 2)
	canvas.draw_texture_rect_region(tex,
		Rect2(origin * float(zoom) - cam, Vector2(CELL, CELL) * float(zoom)),
		Rect2(f * CELL, row * CELL, CELL, CELL))


## Start the one shot. Idempotent: calling it twice does not restart the close.
func collapse(cell: Vector2i) -> void:
	if not _closing.has(cell):
		_closing[cell] = 0.0


func closing(cell: Vector2i) -> bool:
	return _closing.has(cell)


## True once the one shot has played out. The last frame is fully transparent,
## so nothing is drawn from here on either way — this is just the caller's cue
## that the anomaly can be removed from the world.
func finished(cell: Vector2i) -> bool:
	return _closing.has(cell) \
		and float(_closing[cell]) >= float(END_FRAMES) / float(FPS)


func forget(cell: Vector2i) -> void:
	_closing.erase(cell)


## Advance every collapse in flight. Costs nothing when none is.
func advance(delta: float) -> void:
	for cell in _closing:
		_closing[cell] = float(_closing[cell]) + delta
