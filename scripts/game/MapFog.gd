class_name HJMapFog
extends RefCounted
## Discovery state, turned into something a map can draw over itself.
##
## The obvious implementation of fog is a black square per undiscovered cell,
## and it looks exactly like what it is: a rendering artefact. AESTHETIC-EDA §8
## says that at map scale we stop tiling, and fog is the easiest place to obey
## that — an explored region should have a soft, wandering edge, because that is
## what the edge of what somebody knows looks like.
##
## So the fog is **one small texture, drawn once, filtered up**. One texel per
## 4x4-cell block; each texel's alpha is a smoothstepped, hash-jittered average
## of its 3x3 block neighbourhood; linear filtering does the rest. The edge ends
## up spanning roughly three blocks of gradient with a per-block wobble, which
## reads as fog and costs one draw call and no shader.
##
## It carries three states in one alpha channel, which is why there is only one
## texture:
##
##   * unknown    — alpha 1, the map underneath is entirely hidden
##   * remembered — alpha ~0.5, the painting shows through faded
##   * known      — alpha 0, full brightness
##
## The buffer covers only the chunks that have ever been visited, padded, so it
## stays proportional to how much ground the player has covered rather than to
## how big the world is. Everything outside `rect` is unknown by construction
## and is painted as flat fog by the caller.

## How much of the painted map a remembered place shows through. Low enough to
## read as memory at a glance, high enough that the shape of the land is still
## legible — which is the entire value of having been somewhere before.
const MEMORY := 0.44

## Blocks of dark margin around the explored chunks, so the gradient has
## somewhere to fall off into.
const PAD := 3

var texture: ImageTexture = null
## Where `texture` lives in world *cell* coordinates.
var rect := Rect2()

var _version := -1
var _size := Vector2i.ZERO


## Rebuild if discovery has moved since last time. Cheap to call every frame.
func sync(world: HJWorld) -> void:
	if not world.loaded:
		return
	if texture != null and _version == Discovery.version():
		return
	_version = Discovery.version()
	_build(world)


func _build(world: HJWorld) -> void:
	var blocks_w := int(ceil(float(world.w) / float(Discovery.BLOCK)))
	var blocks_h := int(ceil(float(world.h) / float(Discovery.BLOCK)))
	var chunks := Discovery.chunk_bounds()
	if chunks.size == Vector2i.ZERO:
		texture = null
		rect = Rect2()
		return

	var lo := Vector2i(
		maxi(0, chunks.position.x * Discovery.CHUNK - PAD),
		maxi(0, chunks.position.y * Discovery.CHUNK - PAD))
	var hi := Vector2i(
		mini(blocks_w, chunks.end.x * Discovery.CHUNK + PAD),
		mini(blocks_h, chunks.end.y * Discovery.CHUNK + PAD))
	_size = hi - lo
	if _size.x <= 0 or _size.y <= 0:
		texture = null
		rect = Rect2()
		return

	var img := Image.create(_size.x, _size.y, false, Image.FORMAT_RGBA8)
	for py in range(_size.y):
		for px in range(_size.x):
			var block := lo + Vector2i(px, py)
			# A jitter per block, from the block's own coordinates, so the
			# threshold moves about and the boundary stops following the grid.
			# Deterministic, so the fog does not crawl between frames.
			var jitter := _hash01(block.x, block.y) * 0.24 - 0.12
			var ever := _soft(_coverage(block, false), jitter)
			var known := _soft(_coverage(block, true), jitter)
			var shown: float = maxf(ever * MEMORY, known)
			img.set_pixel(px, py, Color(1.0, 1.0, 1.0, 1.0 - shown))
	texture = ImageTexture.create_from_image(img)
	rect = Rect2(Vector2(lo * Discovery.BLOCK), Vector2(_size * Discovery.BLOCK))


## Fraction of a block's 3x3 neighbourhood that is discovered, weighted so the
## block itself dominates. This is the whole of the softening — a binary field
## blurred once, then thresholded with a wobble.
func _coverage(block: Vector2i, this_run: bool) -> float:
	const WEIGHTS := [1.0, 2.0, 1.0, 2.0, 4.0, 2.0, 1.0, 2.0, 1.0]
	var total := 0.0
	var i := 0
	for dy in range(-1, 2):
		for dx in range(-1, 2):
			var at := block + Vector2i(dx, dy)
			var lit := Discovery.known_block(at) if this_run else Discovery.ever_block(at)
			if lit:
				total += WEIGHTS[i]
			i += 1
	return total / 16.0


func _soft(coverage: float, jitter: float) -> float:
	return smoothstep(0.26 + jitter, 0.76 + jitter, coverage)


## A stable pseudo-random 0..1 per block. Two odd multiplies and a couple of
## xor-shifts; nothing here needs to be a good hash, only a repeatable one.
static func _hash01(x: int, y: int) -> float:
	var n := (x * 73856093) ^ (y * 19349663)
	n = (n ^ (n >> 13)) * 1274126177
	return float((n ^ (n >> 16)) & 0xFFFF) / 65535.0
