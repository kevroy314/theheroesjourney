extends RefCounted
## An anomaly: a hole in the world, drawn rather than shipped.
##
## The reference (docs/AESTHETIC-EDA.md §7) is Chrono Trigger's gate — a large
## circular swirl several tiles across, concentric distortion travelling inward,
## a bright core, and the character visibly standing *inside* it as it takes
## him. The thing this replaces was a 72x72 strip whose mouth was 17 to 29
## pixels wide: half a tile at tier 0, and still narrower than the character at
## tier 4. It read as a decal you step on, which is the complaint.
##
## Two decisions worth the words.
##
## **Size.** The character is 32x48 on a 32 tile, so "the size of the character
## model" is the *floor*, not the target. The mouth here is 60x40 world pixels
## at tier 0 — already wider than he is and about as tall — and 104x69 at tier
## 4, three tiles across, with the stain reaching four and a half. Because the
## pull-in is automatic now, the player never sees it from on top of it: the
## last frame he gets is from the tile next door, so it has to be big enough to
## be the thing he was walking towards.
##
## **Drawn, not shipped.** Every frame of this is arithmetic on TIME. A 24-frame
## strip at this size would be 1728x360 of payload per variant and would still
## be a 12fps loop; the swirl below is continuous, seamless by construction
## (every term is a `fract` or a full turn), and free to retune. It also means
## tier is a set of numbers rather than five rows of baked art, so a tier 4 can
## actually spin faster than a tier 0 rather than merely looking different.
##
## Deliberately not a node, for the reason `_draw_scenery` exists: a Control's
## children draw *after* the whole of the parent's `_draw`, and
## `show_behind_parent` puts them before all of it. There is no ordering that
## lands a shaded quad between the ground pass and the Y-sorted scenery pass, so
## a portal built as a child would either hide under the grass or paint over the
## character's legs when he stands in it. Called from inside the row loop it
## inherits the Y-sort for free.
##
## No `class_name`: a helper for one renderer, reached by preload.
##
##     const Portal := preload("res://scripts/ui/Portal.gd")
##     var _portals := Portal.new()
##
## then, from inside `_draw_scenery`'s row loop, and `advance(delta)` from
## `_process` beside the walk cycle.

const TIERS := 5

## Half-width of the mouth, in world pixels. The tile is 32.
##
## Read these as tiles: 1.9 wide at tier 0 rising to 3.25 at tier 4. The stain
## reaches HALO times further, so the whole object spans 2.7 to 4.6 tiles.
const MOUTH := [30.0, 35.0, 41.0, 46.0, 52.0]

## Vertical foreshortening. The world is drawn from a raised three-quarter
## angle — props stand up out of their cell and the character is a tile and a
## half tall — so a circular hole in the ground is an ellipse on screen. 0.66 is
## the ratio the sprite it replaces used, which is the one the rest of the art
## was drawn against.
const SQUASH := 0.66

## Stain radius as a multiple of the mouth: how far the ground is spoiled.
const HALO := 1.42

## How far the drawn object reaches beyond its own cell, in tiles, rounded up.
## The scenery pass overscans by this much so a portal anchored just off screen
## still paints the part of itself that is on it. Derived from the tier-4 halo:
## 52*1.42/32 = 2.31 across, times SQUASH = 1.53 down.
const REACH_X := 3
const REACH_Y := 2

const RIM_POINTS := 26
## Which run of rim points faces the camera and the light — east through south.
## Indices into a RIM_POINTS ring that starts at due east and turns clockwise on
## screen (y is down).
const LIT_FROM := 2
const LIT_TO := 12

const ARM_STEPS := 14

## Per tier. Arms and twist are shape; spin and churn are violence.
const ARMS := [3, 3, 4, 4, 5]
const SPIN := [0.13, 0.19, 0.26, 0.35, 0.46]      ## turns per second
const TWIST := [1.7, 2.0, 2.4, 2.8, 3.3]          ## radians of lag, rim to core
const JAG := [0.065, 0.08, 0.095, 0.11, 0.13]     ## how torn the rim is
const CRACKS := [3, 4, 6, 7, 9]
const STIPPLE := [20, 26, 32, 38, 44]
const MOTES := [2, 3, 4, 5, 6]
const RING_RATE := [0.30, 0.36, 0.44, 0.54, 0.66] ## rings swallowed per second
const RINGS := 3

## Tier hue: accent_2 to danger the long way round the wheel. A straight lerp
## between them lands on a dusty mid-grey at tier 2, which is the one colour the
## overworld is already made of.
const HUE := [
	Color(0.561, 0.749, 0.847),      # 8FBFD8  accent_2
	Color(0.522, 0.510, 0.847),      # 8582D8
	Color(0.737, 0.463, 0.847),      # BC76D8
	Color(0.851, 0.412, 0.675),      # D969AC
	Color(0.851, 0.404, 0.361),      # D9675C  danger
]

## Seconds the one shot takes to shut.
const COLLAPSE_TIME := 1.15

## Vector2i -> seconds since collapse() was called. Only ever a handful, and
## only while one is actually playing.
var _closing: Dictionary = {}
## Vector2i -> the static half of one portal, built once. Bounded by the number
## of anomalies in the world, which is twenty-nine.
var _shapes: Dictionary = {}

## Scratch geometry, sized once and refilled in place. The alternative is a new
## PackedVector2Array per ring per portal per frame, which is a hundred and
## fifty allocations a second for something whose whole job is to be free.
var _fill := PackedVector2Array()
var _ring := PackedVector2Array()
var _arm := PackedVector2Array()
var _armc := PackedColorArray()
## Short runs — a crack, the lit arc — kept apart from `_ring` so the closed
## ring never has to be resized and grown back twice a frame.
var _seg := PackedVector2Array()


func _init() -> void:
	_fill.resize(RIM_POINTS)
	_ring.resize(RIM_POINTS + 1)
	_arm.resize(ARM_STEPS)
	_armc.resize(ARM_STEPS)


## --- the animation clock --------------------------------------------------------

## Start the one shot. Idempotent: calling it twice does not restart the close.
func collapse(cell: Vector2i) -> void:
	if not _closing.has(cell):
		_closing[cell] = 0.0


func closing(cell: Vector2i) -> bool:
	return _closing.has(cell)


## True while any one shot is in flight. The caller's guard against paying for
## the harvest below on every frame of a game where nothing is closing.
func closing_any() -> bool:
	return not _closing.is_empty()


func advance(delta: float) -> void:
	for cell in _closing:
		_closing[cell] = float(_closing[cell]) + delta


## Cells whose collapse has played out. The caller's cue to stop handing them to
## `draw_at` at all — after which `forget()` drops the bookkeeping. Allocates
## nothing on the overwhelmingly common frame where nothing is closing.
func done() -> Array:
	var out: Array = []
	for cell in _closing:
		if float(_closing[cell]) >= COLLAPSE_TIME:
			out.append(cell)
	return out


func forget(cell: Vector2i) -> void:
	_closing.erase(cell)
	_shapes.erase(cell)


## --- drawing --------------------------------------------------------------------

## One portal, centred on its cell.
##
## Centred rather than anchored to its foot the way a prop is: a prop stands on
## the ground and grows upward out of its cell, a hole lies *in* the ground, so
## its middle is the cell's middle.
##
## `now` is the frame's clock in seconds, sampled once by the caller — the same
## one the idle motion runs on, so nothing here has to ask the OS the time.
## `standing` is true on the single frame the player's step resolves onto the
## cell, before the screen swaps: the portal flares as it takes him.
func draw_at(canvas: CanvasItem, cell: Vector2i, tier: int, cam: Vector2,
		tile: int, zoom: int, now: float, standing: bool = false) -> void:
	var t := clampi(tier, 0, TIERS - 1)
	var shape: Dictionary = _shape_for(cell, t)
	var z := float(zoom)
	var centre := (Vector2(cell) + Vector2(0.5, 0.5)) * float(tile) * z - cam

	# Where the collapse has got to, 0 open and 1 shut.
	var close := 0.0
	if _closing.has(cell):
		close = clampf(float(_closing[cell]) / COLLAPSE_TIME, 0.0, 1.0)
		if close >= 1.0:
			return
	# Eased so the shut is a snap rather than a slide: it holds nearly open for
	# the first third and then goes, which is what closing feels like.
	var open := 1.0 - close * close * close
	var fade := 1.0 - close

	var full := float(MOUTH[t]) * z
	var mouth := full * open
	if mouth < 2.0:
		return

	var hue: Color = HUE[t]
	var phase := float(shape["phase"])
	# Standing in it is one frame before the screen swaps, but it is the frame
	# that has to sell "it took me", so it is worth a bool.
	var heat := 1.45 if standing else 1.0

	_draw_stain(canvas, centre, shape, mouth, full, hue, fade, t)
	_draw_hole(canvas, centre, shape, mouth, hue, fade)
	_draw_arms(canvas, centre, mouth, hue, phase, now, close, heat, t)
	_draw_rings(canvas, centre, shape, mouth, hue, phase, now, fade, heat, t)
	_draw_motes(canvas, centre, mouth, hue, phase, now, fade, z, t)
	_draw_core(canvas, centre, mouth, hue, phase, now, close, heat)
	_draw_rim(canvas, centre, shape, mouth, hue, fade)
	if close > 0.0:
		_draw_shockwave(canvas, centre, shape, full, hue, close)


## The ground is spoiled before the hole starts.
##
## Four nested ellipses of low alpha rather than one gradient: immediate mode
## has no radial fill, and stacking four is within a rounding error of the ramp
## for four draw calls and no texture. Then a ring of hard three-pixel blocks
## around the edge, which is the whole reason this reads as part of a pixel-art
## world rather than as vector art laid on top of one — it is the same dither
## the tileset's own material edges use.
func _draw_stain(canvas: CanvasItem, centre: Vector2, shape: Dictionary,
		mouth: float, full: float, hue: Color, fade: float, tier: int) -> void:
	if fade <= 0.01:
		return
	# The ellipse is the transform's job: draw_circle picks its segment count
	# from the radius it is handed, so the radius must be the real one and only
	# the vertical squash may be scaled away.
	canvas.draw_set_transform(centre, 0.0, Vector2(1.0, SQUASH))
	# Bruised rather than merely dark: the outer rings carry a little of the
	# tier's hue, so the ground reads as spoiled by *this* and not as a shadow
	# something is casting on it.
	for i in range(5):
		var r := mouth * (HALO - 0.084 * float(i))
		var k := float(i) / 4.0
		canvas.draw_circle(Vector2.ZERO, r, Color(
			0.045 + hue.r * 0.10 * (1.0 - k),
			0.036 + hue.g * 0.08 * (1.0 - k),
			0.075 + hue.b * 0.12 * (1.0 - k),
			(0.075 + 0.045 * k) * fade))
	canvas.draw_set_transform_matrix(Transform2D.IDENTITY)

	var blocks: PackedVector2Array = shape["stipple"]
	var alphas: PackedFloat32Array = shape["stipple_a"]
	var side := maxf(mouth * 0.042, 2.0)
	var half := Vector2(side, side) * 0.5
	for i in range(blocks.size()):
		var at := centre + blocks[i] * full
		canvas.draw_rect(Rect2(at - half, Vector2(side, side)),
			Color(hue.r * 0.42, hue.g * 0.38, hue.b * 0.52, alphas[i] * fade), true)

	# Cracks run *out* of the rim into ground that is still intact, which is the
	# difference between a hole in something and a pattern on it.
	var cracks: Array = shape["cracks"]
	var ink := Color(0.05, 0.04, 0.075, 0.8 * fade)
	var width := maxf(mouth * 0.035, 1.0)
	for c in cracks:
		var pts: PackedVector2Array = c
		_seg.resize(pts.size())
		for i in range(pts.size()):
			_seg[i] = centre + pts[i] * full
		canvas.draw_polyline(_seg, ink, width, false)
	if not cracks.is_empty():
		_shade_cracks(canvas, cracks, centre, full, tier)


## A one-pixel highlight along the south-east of each crack, so the ground is
## split rather than painted with a line.
func _shade_cracks(canvas: CanvasItem, cracks: Array, centre: Vector2,
		full: float, tier: int) -> void:
	if tier < 2:
		return
	var lip := Color(0.75, 0.72, 0.68, 0.16)
	var off := Vector2(1.0, 1.0)
	for c in cracks:
		var pts: PackedVector2Array = c
		_seg.resize(pts.size())
		for i in range(pts.size()):
			_seg[i] = centre + pts[i] * full + off
		canvas.draw_polyline(_seg, lip, 1.0, false)


## The hole itself: opaque, and the darkest thing in the frame.
##
## The overworld measures 11 to 122 in value, so owning true black is what makes
## this a hole and not a puddle. The inner south-east wall is lit and the outer
## edge is not, which is a pit; a mound is the other way round, and getting it
## backwards is the single cheapest way to make a crater look like a bump.
func _draw_hole(canvas: CanvasItem, centre: Vector2, shape: Dictionary,
		mouth: float, hue: Color, fade: float) -> void:
	var unit: PackedVector2Array = shape["unit"]
	for i in range(RIM_POINTS):
		_fill[i] = centre + unit[i] * mouth
	var void_col := Color(hue.r * 0.10 + 0.018, hue.g * 0.07 + 0.014,
		hue.b * 0.15 + 0.030, fade)
	canvas.draw_colored_polygon(_fill, void_col)

	var lit := Color(hue.r * 0.55 + 0.10, hue.g * 0.55 + 0.10,
		hue.b * 0.60 + 0.14, 0.42 * fade)
	var span := LIT_TO - LIT_FROM + 1
	_seg.resize(span)
	for i in range(span):
		_seg[i] = centre + unit[LIT_FROM + i] * (mouth * 0.90)
	canvas.draw_polyline(_seg, lit, maxf(mouth * 0.075, 1.5), false)


## The swirl. Spiral arms whose lag grows toward the core, turning as one.
##
## Every term is either a constant turn rate or a full revolution, so the loop is
## seamless without anyone having to line up a first and last frame. The phase
## is per cell: two portals in the same view must not turn in lockstep, which is
## the lesson already written down in Motion.gd and the difference between a
## world that is alive and one that is broken.
func _draw_arms(canvas: CanvasItem, centre: Vector2, mouth: float, hue: Color,
		phase: float, now: float, close: float, heat: float, tier: int) -> void:
	var arms := int(ARMS[tier])
	# It accelerates as it shuts — the last thing a hole does is swallow itself.
	var spin := float(SPIN[tier]) * (1.0 + 5.0 * close)
	var twist := float(TWIST[tier])
	var turn := -now * spin * TAU + phase
	var bright := Color(hue.r * 0.55 + 0.45, hue.g * 0.55 + 0.45,
		hue.b * 0.55 + 0.45)
	var fade := 1.0 - close
	# Two passes over the same points: a wide dim one that gives the arm body and
	# a narrow bright one that gives it an edge. One pass at either width is a
	# wire or a smear; the pair is a limb of something.
	var wide := maxf(mouth * 0.17, 3.0)
	var thin := maxf(mouth * 0.05, 1.5)
	for a in range(arms):
		var base := turn + float(a) * TAU / float(arms)
		for s in range(ARM_STEPS):
			var u := 0.10 + 0.90 * float(s) / float(ARM_STEPS - 1)
			var ang := base + twist * pow(u, 0.85)
			var r := mouth * u * 0.97
			_arm[s] = centre + Vector2(cos(ang) * r, sin(ang) * r * SQUASH)
			# Brightest where it is being swallowed, dissolving into the rim, so
			# the eye is dragged inward rather than round.
			var alpha := (0.95 - 0.74 * u) * fade * heat
			_armc[s] = Color(bright.r, bright.g, bright.b, minf(alpha * 0.22, 1.0))
		canvas.draw_polyline_colors(_arm, _armc, wide, false)
		for s in range(ARM_STEPS):
			var c := _armc[s]
			_armc[s] = Color(c.r, c.g, c.b, minf(c.a * 4.1, 1.0))
		canvas.draw_polyline_colors(_arm, _armc, thin, false)


## Concentric distortion, travelling inward. This is the term that says "pulled
## in" rather than "spinning", and it is the one the reference leads with.
func _draw_rings(canvas: CanvasItem, centre: Vector2, shape: Dictionary,
		mouth: float, hue: Color, phase: float, now: float, fade: float,
		heat: float, tier: int) -> void:
	var unit: PackedVector2Array = shape["unit"]
	var rate := float(RING_RATE[tier])
	var width := maxf(mouth * 0.030, 1.0)
	for k in range(RINGS):
		# fract(), so the ring that vanishes at the core is the same ring that
		# reappears at the rim: no seam, no bookkeeping.
		var u := 1.0 - fposmod(now * rate + float(k) / float(RINGS)
			+ phase * 0.159, 1.0)
		var r := mouth * (0.06 + 0.92 * u)
		var alpha := 0.24 * u * fade * heat
		for i in range(RIM_POINTS):
			_ring[i] = centre + unit[i] * r
		_ring[RIM_POINTS] = _ring[0]
		canvas.draw_polyline(_ring, Color(hue.r, hue.g, hue.b, minf(alpha, 1.0)),
			width, false)


## Specks of the world falling in. Three-pixel blocks, not dots — the same unit
## as the stipple, so the two read as the same material.
func _draw_motes(canvas: CanvasItem, centre: Vector2, mouth: float, hue: Color,
		phase: float, now: float, fade: float, zoom: float, tier: int) -> void:
	var count := int(MOTES[tier])
	var side := maxf(zoom, 2.0)
	var half := Vector2(side, side) * 0.5
	var pale := Color(hue.r * 0.4 + 0.6, hue.g * 0.4 + 0.6, hue.b * 0.4 + 0.6)
	for i in range(count):
		var u := fposmod(now * 0.42 + float(i) * 0.6180339 + phase * 0.159, 1.0)
		var r := mouth * (1.0 - u) * 0.98
		var ang := phase + float(i) * 2.399 + u * TAU * 1.25
		var at := centre + Vector2(cos(ang) * r, sin(ang) * r * SQUASH)
		# Fades in as it leaves the rim and out as the core takes it.
		var alpha := 0.85 * fade * minf(1.0, u * 5.0) * minf(1.0, (1.0 - u) * 4.0)
		canvas.draw_rect(Rect2(at - half, Vector2(side, side)),
			Color(pale.r, pale.g, pale.b, alpha), true)


## The bright core, breathing on its own cell phase.
func _draw_core(canvas: CanvasItem, centre: Vector2, mouth: float, hue: Color,
		phase: float, now: float, close: float, heat: float) -> void:
	# It brightens as it shuts. The hole does not fade out politely; it swallows
	# the last of itself and goes.
	var flare := 1.0 + 2.6 * close * close
	var breath := 1.0 + 0.14 * sin(now * 3.1 + phase)
	var r := mouth * 0.155 * breath * flare
	canvas.draw_set_transform(centre, 0.0, Vector2(1.0, SQUASH))
	var glow := Color(hue.r * 0.5 + 0.5, hue.g * 0.5 + 0.5, hue.b * 0.5 + 0.5,
		minf(0.85 * heat, 1.0))
	canvas.draw_circle(Vector2.ZERO, r * 1.75,
		Color(glow.r, glow.g, glow.b, 0.14 * heat))
	canvas.draw_circle(Vector2.ZERO, r, glow)
	canvas.draw_circle(Vector2.ZERO, r * 0.46,
		Color(1.0, 0.98, 0.99, minf(0.9 * heat, 1.0)))
	canvas.draw_set_transform_matrix(Transform2D.IDENTITY)


## The torn edge. It does not turn — only the contents do, which is what stops
## the whole object reading as a wheel.
func _draw_rim(canvas: CanvasItem, centre: Vector2, shape: Dictionary,
		mouth: float, hue: Color, fade: float) -> void:
	var unit: PackedVector2Array = shape["unit"]
	for i in range(RIM_POINTS):
		_ring[i] = centre + unit[i] * mouth
	_ring[RIM_POINTS] = _ring[0]
	canvas.draw_polyline(_ring,
		Color(hue.r * 0.45, hue.g * 0.45, hue.b * 0.52, 0.75 * fade),
		maxf(mouth * 0.045, 1.5), false)


## The close, seen from outside: a ring of the world snapping back over the hole.
func _draw_shockwave(canvas: CanvasItem, centre: Vector2, shape: Dictionary,
		full: float, hue: Color, close: float) -> void:
	if close < 0.42:
		return
	var u := (close - 0.42) / 0.58
	var unit: PackedVector2Array = shape["unit"]
	var r := full * (0.65 + 1.15 * u)
	for i in range(RIM_POINTS):
		_ring[i] = centre + unit[i] * r
	_ring[RIM_POINTS] = _ring[0]
	canvas.draw_polyline(_ring,
		Color(hue.r * 0.55 + 0.45, hue.g * 0.55 + 0.45, hue.b * 0.55 + 0.45,
			0.75 * (1.0 - u)),
		maxf(full * 0.055 * (1.0 - u * 0.55), 2.0), false)


## --- the static half ------------------------------------------------------------

## Everything about one portal that never changes: the torn outline, where the
## dither sits, where the cracks run, and its phase. Built on first sight and
## kept, because there are twenty-nine anomalies in the world and the shape of
## one is a fact about its cell rather than about this frame.
##
## The unit ring starts at due east and turns clockwise on screen, radius 1 at
## tier-0 jaggedness, with SQUASH already folded in — so a point on screen is
## `centre + unit[i] * radius` and nothing downstream has to know about the
## foreshortening.
func _shape_for(cell: Vector2i, tier: int) -> Dictionary:
	var got: Variant = _shapes.get(cell)
	if got != null and int((got as Dictionary)["tier"]) == tier:
		return got
	var jag := float(JAG[tier])
	var unit := PackedVector2Array()
	unit.resize(RIM_POINTS)
	for i in range(RIM_POINTS):
		var a := TAU * float(i) / float(RIM_POINTS)
		# Two harmonics rather than one hash per point: a per-point random walk
		# gives a fuzzy circle, and a tear has lobes.
		var wob := 1.0 \
			+ jag * sin(a * 3.0 + _noise(cell, 1) * TAU) \
			+ jag * 0.6 * sin(a * 5.0 + _noise(cell, 2) * TAU) \
			+ jag * 0.35 * (_noise(cell, 10 + i) - 0.5)
		unit[i] = Vector2(cos(a) * wob, sin(a) * wob * SQUASH)

	var n := int(STIPPLE[tier])
	var stipple := PackedVector2Array()
	var stipple_a := PackedFloat32Array()
	stipple.resize(n)
	stipple_a.resize(n)
	for i in range(n):
		var a := TAU * _noise(cell, 100 + i)
		# Biased outward, so the dither thins as it leaves the rim rather than
		# forming an even freckling.
		var u := _noise(cell, 200 + i)
		var r := 1.0 + (HALO - 1.0) * (1.0 - u * u)
		stipple[i] = Vector2(cos(a) * r, sin(a) * r * SQUASH)
		stipple_a[i] = 0.22 + 0.44 * (1.0 - u)

	var cracks: Array = []
	var count := int(CRACKS[tier])
	for c in range(count):
		var a := TAU * (float(c) / float(count) + 0.13 * _noise(cell, 300 + c))
		var pts := PackedVector2Array()
		pts.resize(3)
		var r := 0.94
		var ang := a
		for s in range(3):
			pts[s] = Vector2(cos(ang) * r, sin(ang) * r * SQUASH)
			r += 0.16 + 0.26 * _noise(cell, 400 + c * 4 + s)
			ang += (_noise(cell, 500 + c * 4 + s) - 0.5) * 0.5
		cracks.append(pts)

	var shape := {
		"tier": tier,
		"unit": unit,
		"stipple": stipple,
		"stipple_a": stipple_a,
		"cracks": cracks,
		"phase": _noise(cell, 7) * TAU,
	}
	_shapes[cell] = shape
	return shape


## Deterministic 0..1 from a cell and a salt.
##
## Its own salt space rather than HJMotion.phase_for()'s or HJLighting's: a
## portal, a swaying bush and a guttering lamp on the same cell must not share a
## heartbeat, and a portal's *shape* must not be derived from the same number as
## its phase or the biggest tears would all be the ones that turn fastest.
static func _noise(cell: Vector2i, salt: int) -> float:
	var h := (cell.x * 374761393) ^ (cell.y * 668265263) ^ (salt * 1274126177)
	h = (h ^ (h >> 13)) * 1274126177
	return float(absi(h ^ (h >> 16)) % 65521) / 65521.0
