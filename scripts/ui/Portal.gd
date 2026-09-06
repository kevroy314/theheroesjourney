extends RefCounted
## An anomaly: a hole in the world, drawn rather than shipped.
##
## The reference (docs/AESTHETIC-EDA.md §7) is Chrono Trigger's gate — a large
## circular swirl several tiles across, concentric distortion travelling inward,
## a bright core, and the character visibly standing *inside* it as it takes
## him. What this replaces was a 72x72 sprite strip whose mouth was 17 to 29
## pixels wide: half a tile at tier 0, still narrower than the character at tier
## 4. It read as a decal you step on, which is the complaint.
##
## Three decisions worth the words.
##
## **Size.** The character is 32x48 on a 32 tile, so "the size of the character
## model" is the floor, not the target. The mouth here is 60x40 world pixels at
## tier 0 — already wider than he is and about as tall — and 104x69 at tier 4,
## three tiles across, with the stain reaching four and a half. Because the
## pull-in is automatic, the player never sees it from on top of it: the last
## frame he gets is from the tile next door, so it has to be big enough to be
## the thing he was walking towards.
##
## **Drawn, not shipped.** Every frame of this is arithmetic on the clock. A
## 24-frame strip at this size would be a megabyte of payload and still a 12fps
## loop; this is continuous, seamless by construction — every term is either a
## `fposmod` or a whole revolution — and free to retune. It also makes tier a
## set of numbers rather than five rows of baked art, so a tier 4 genuinely
## spins faster than a tier 0 instead of merely looking different.
##
## **Baked once, moved every frame.** Almost none of a portal actually changes:
## the torn outline, the bruise on the ground, the cracks, the shape of the arms
## and the disc of the core are all fixed the moment you know the cell and the
## tier. Only where they point changes. So each is built once as a small 2D mesh
## in screen pixels and then drawn with one call under a transform — the swirl
## is literally one mesh turned by the clock. Issued as individual polylines
## instead it measured 580us a portal, which would have made it the most
## expensive object in the game by a factor of two; baked, it is a fifth of that.
## The pattern is HJLighting's: work out the facts about the world once, and let
## the frame do arithmetic only.
##
## Deliberately not a node, for the reason `_draw_scenery` exists: a Control's
## children draw *after* the whole of the parent's `_draw`, and
## `show_behind_parent` puts them before all of it. There is no ordering that
## lands a shaded quad between the ground pass and the Y-sorted scenery pass, so
## a portal built as a child would either hide under the grass or paint over the
## character's legs when he stands in it. Called from inside the row loop it
## inherits the Y-sort for free: stand south of a tear and you are standing in
## it, which is what the reference is a picture of.
##
## No `class_name`: a helper for one renderer, reached by preload.
##
##     const Portal := preload("res://scripts/ui/Portal.gd")
##     var _portals := Portal.new()

const TIERS := 5

## Half-width of the mouth, in world pixels. The tile is 32.
##
## Read them as tiles: 1.9 across at tier 0 rising to 3.25 at tier 4. The stain
## reaches HALO further, so the whole object spans 2.7 to 4.6 tiles.
const MOUTH := [30.0, 35.0, 41.0, 46.0, 52.0]

## Vertical foreshortening. The world is drawn from a raised three-quarter
## angle — props stand up out of their cell, the character is a tile and a half
## tall — so a circular hole in the ground is an ellipse on screen. 0.66 is the
## ratio the art this replaces used, which is the one everything else was drawn
## against.
const SQUASH := 0.66

## Stain radius as a multiple of the mouth: how far the ground is spoiled.
const HALO := 1.42

## How far a portal reaches beyond its own cell, in tiles, rounded up. The
## scenery pass overscans by this much or one pops into being as you walk toward
## it. From the tier-4 halo: 52*1.42/32 = 2.31 across, times SQUASH = 1.53 down.
const REACH_X := 3
const REACH_Y := 2

## Points around the rim. Enough that the tear reads as torn rather than
## faceted, few enough that a ring of them is cheap.
const RIM_POINTS := 26
## The run of rim points facing the camera and the light — east through south.
## The ring starts at due east and turns clockwise on screen, y being down.
const LIT_FROM := 2
const LIT_TO := 12
## Rings are faint and travelling; they do not need the rim's resolution.
const RING_POINTS := 24

const ARM_STEPS := 14

## Per tier. Arms and twist are shape; spin, churn and crack count are violence.
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
## Vector2i -> the baked half of one portal. Bounded by the number of anomalies
## in the world, which is twenty-nine, and only the ones actually seen are in it.
var _baked: Dictionary = {}


## --- the animation clock --------------------------------------------------------

## Start the one shot. Idempotent: calling it twice does not restart the close.
func collapse(cell: Vector2i) -> void:
	if not _closing.has(cell):
		_closing[cell] = 0.0


func closing(cell: Vector2i) -> bool:
	return _closing.has(cell)


## True while any one shot is in flight — the caller's guard against paying for
## the harvest below on the frames where nothing is closing, which is all of them.
func closing_any() -> bool:
	return not _closing.is_empty()


func advance(delta: float) -> void:
	for cell in _closing:
		_closing[cell] = float(_closing[cell]) + delta


## Cells whose collapse has played out: the caller's cue to stop handing them to
## `draw_at` at all, after which `forget()` drops the bookkeeping.
func done() -> Array:
	var out: Array = []
	for cell in _closing:
		if float(_closing[cell]) >= COLLAPSE_TIME:
			out.append(cell)
	return out


func forget(cell: Vector2i) -> void:
	_closing.erase(cell)
	_baked.erase(cell)


## --- drawing --------------------------------------------------------------------

## One portal, centred on its cell.
##
## Centred rather than anchored to its foot the way a prop is: a prop stands on
## the ground and grows upward out of its cell, a hole lies *in* the ground, so
## its middle is the cell's middle.
##
## `now` is the frame's clock in seconds, sampled once by the caller — the same
## one the idle motion runs on, so nothing here asks the OS the time. `standing`
## is true on the frame the player's step resolves onto the cell, before the
## screen swaps: the portal flares as it takes him.
func draw_at(canvas: CanvasItem, cell: Vector2i, tier: int, cam: Vector2,
		tile: int, zoom: int, now: float, standing: bool = false) -> void:
	var t := clampi(tier, 0, TIERS - 1)
	var b: Dictionary = _bake(cell, t, zoom)
	var centre := (Vector2(cell) + Vector2(0.5, 0.5)) * float(tile) * float(zoom) - cam

	# Where the collapse has got to: 0 open, 1 shut.
	var close := 0.0
	if _closing.has(cell):
		close = clampf(float(_closing[cell]) / COLLAPSE_TIME, 0.0, 1.0)
		if close >= 1.0:
			return
	# Cubed, so the shut is a snap rather than a slide — it holds nearly open for
	# the first third and then goes, which is what closing feels like.
	var open := 1.0 - close * close * close
	var fade := 1.0 - close
	var full := float(b["full"])
	var mouth := full * open
	if mouth < 2.0:
		return

	# The bruise does not shrink with the hole, it fades: ground that was spoiled
	# stays spoiled right up to the moment the world closes over it.
	canvas.draw_mesh(b["stain"], null, Transform2D(0.0, Vector2.ONE, 0.0, centre),
		Color(1.0, 1.0, 1.0, fade))
	canvas.draw_mesh(b["body"], null,
		Transform2D(0.0, Vector2(open, open), 0.0, centre),
		Color(1.0, 1.0, 1.0, fade))

	# The swirl: one baked mesh, turned. Squash *after* the turn, so the ellipse
	# stays flat on the ground instead of tumbling with the arms — which is why
	# this is a composed matrix and not Transform2D's own rotate-and-scale.
	var spin := float(SPIN[t]) * (1.0 + 5.0 * close)   # it accelerates as it shuts
	var turn := -now * spin * TAU + float(b["phase"])
	var flat := Transform2D(Vector2(1.0, 0.0), Vector2(0.0, SQUASH), centre)
	var swirl := flat * Transform2D(turn, Vector2(open, open), 0.0, Vector2.ZERO)
	canvas.draw_mesh(b["arms"], null, swirl, Color(1.0, 1.0, 1.0, fade))
	if standing:
		# Modulate cannot brighten past white, so the flare as it takes him is a
		# second pass. One frame, and it is the frame that has to sell "it took
		# me" before the screen swaps.
		canvas.draw_mesh(b["arms"], null, swirl, Color(1.0, 1.0, 1.0, 0.55))

	_draw_rings(canvas, b, centre, mouth, HUE[t], now, fade, t)
	_draw_motes(canvas, b, centre, mouth, now, fade, float(zoom), t)

	# The core brightens as it shuts: a hole does not fade out politely, it
	# swallows the last of itself and goes.
	var flare := 1.0 + 2.6 * close * close
	var breath := 1.0 + 0.14 * sin(now * 3.1 + float(b["phase"]))
	var r := mouth * 0.155 * breath * flare
	canvas.draw_mesh(b["core"], null,
		Transform2D(0.0, Vector2(r, r * SQUASH), 0.0, centre),
		Color(1.0, 1.0, 1.0, fade))

	if close >= 0.42:
		_draw_shockwave(canvas, b, centre, full, HUE[t], close)


## Concentric distortion, travelling inward. This is the term that says "pulled
## in" rather than "spinning", and it is the one the reference leads with.
##
## One baked band, drawn three times at three radii. A ring thins as it shrinks
## because the mesh scales its own width — which is what a ring being crushed
## does, and by the radius where the thinning would matter its alpha has already
## taken it to nothing.
func _draw_rings(canvas: CanvasItem, b: Dictionary, centre: Vector2, mouth: float,
		hue: Color, now: float, fade: float, tier: int) -> void:
	var band: ArrayMesh = b["band"]
	var rate := float(RING_RATE[tier])
	var phase := float(b["phase"]) * 0.159
	for k in range(RINGS):
		# fposmod, so the ring that vanishes at the core is the ring that
		# reappears at the rim: no seam and no bookkeeping.
		var u := 1.0 - fposmod(now * rate + float(k) / float(RINGS) + phase, 1.0)
		var r := mouth * (0.06 + 0.92 * u)
		canvas.draw_mesh(band, null,
			Transform2D(0.0, Vector2(r, r * SQUASH), 0.0, centre),
			Color(hue.r, hue.g, hue.b, 0.24 * u * fade))


## Specks of the world falling in. Three-pixel blocks, not dots — the same unit
## as the stipple on the ground, so the two read as the same material.
##
## The angle is an index into the baked rim rather than a fresh cos/sin pair: a
## mote then rides the torn edge it fell from, and trigonometry inside a
## per-frame loop is arithmetic this can actually feel.
func _draw_motes(canvas: CanvasItem, b: Dictionary, centre: Vector2, mouth: float,
		now: float, fade: float, zoom: float, tier: int) -> void:
	var count := int(MOTES[tier])
	var unit: PackedVector2Array = b["unit"]
	var pale: Color = b["mote"]
	var side := maxf(zoom, 2.0)
	var half := Vector2(side, side) * 0.5
	var phase := float(b["phase"])
	for i in range(count):
		var u := fposmod(now * 0.42 + float(i) * 0.6180339 + phase * 0.159, 1.0)
		var slot := int(fposmod(phase + float(i) * 2.399 + u * 1.25, 1.0)
			* float(RIM_POINTS)) % RIM_POINTS
		var at := centre + unit[slot] * (mouth * (1.0 - u) * 0.98)
		# In as it leaves the rim, out as the core takes it.
		var alpha := 0.85 * fade * minf(1.0, u * 5.0) * minf(1.0, (1.0 - u) * 4.0)
		canvas.draw_rect(Rect2(at - half, Vector2(side, side)),
			Color(pale.r, pale.g, pale.b, alpha), true)


## The close, seen from outside: a ring of the world snapping back over the hole.
func _draw_shockwave(canvas: CanvasItem, b: Dictionary, centre: Vector2,
		full: float, hue: Color, close: float) -> void:
	var u := (close - 0.42) / 0.58
	var r := full * (0.65 + 1.15 * u)
	canvas.draw_mesh(b["band"], null,
		Transform2D(0.0, Vector2(r, r * SQUASH), 0.0, centre),
		Color(hue.r * 0.55 + 0.45, hue.g * 0.55 + 0.45, hue.b * 0.55 + 0.45,
			0.75 * (1.0 - u)))


## --- the baked half -------------------------------------------------------------

## Everything about one portal that never moves, built on first sight.
##
## Four meshes in screen pixels, centred on the origin, so a frame supplies only
## a transform:
##
##   stain  the bruise, the dither and the cracks. Never scales, only fades.
##   body   the hole, its torn rim and the lit inner wall. Scales as it shuts.
##   arms   the swirl, in *unsquashed* space so it can be turned and then
##          flattened; the alpha ramp and the wide-under-narrow pair are baked.
##   core   a unit disc, scaled to the pulse.
##
## Plus the jagged unit rings, which the travelling rings, the motes and the
## shockwave still need as points.
func _bake(cell: Vector2i, tier: int, zoom: int) -> Dictionary:
	var got: Variant = _baked.get(cell)
	if got != null:
		var had: Dictionary = got
		if int(had["tier"]) == tier and int(had["zoom"]) == zoom:
			return had

	var full := float(MOUTH[tier]) * float(zoom)
	var hue: Color = HUE[tier]
	var jag := float(JAG[tier])
	var phase := _noise(cell, 7) * TAU

	# The torn outline, radius 1, starting due east and turning clockwise on
	# screen. Two harmonics and a nudge rather than one hash per point: a
	# per-point random walk gives a fuzzy circle, and a tear has lobes.
	var unit := PackedVector2Array()
	unit.resize(RIM_POINTS)
	var wobble := PackedFloat32Array()
	wobble.resize(RIM_POINTS)
	for i in range(RIM_POINTS):
		var a := TAU * float(i) / float(RIM_POINTS)
		var w := 1.0 \
			+ jag * sin(a * 3.0 + _noise(cell, 1) * TAU) \
			+ jag * 0.6 * sin(a * 5.0 + _noise(cell, 2) * TAU) \
			+ jag * 0.35 * (_noise(cell, 10 + i) - 0.5)
		wobble[i] = w
		unit[i] = Vector2(cos(a) * w, sin(a) * w * SQUASH)

	var out := {
		"tier": tier, "zoom": zoom, "full": full, "phase": phase,
		"unit": unit,
		"mote": Color(hue.r * 0.4 + 0.6, hue.g * 0.4 + 0.6, hue.b * 0.4 + 0.6),
		"stain": _bake_stain(cell, tier, full, hue),
		"body": _bake_body(unit, full, hue),
		"arms": _bake_arms(tier, full, wobble, hue),
		"core": _bake_core(hue),
		"band": _bake_band(cell, jag),
	}
	_baked[cell] = out
	return out


## The ground is spoiled before the hole starts: five nested ellipses of low
## alpha for the bruise, a ring of hard blocks for the dither that ties it to a
## pixel-art world, and cracks running *out* of the rim into ground that is
## still intact — which is the difference between a hole in something and a
## pattern on it.
func _bake_stain(cell: Vector2i, tier: int, full: float, hue: Color) -> ArrayMesh:
	var v := PackedVector2Array()
	var c := PackedColorArray()
	for i in range(5):
		var r := full * (HALO - 0.084 * float(i))
		var k := float(i) / 4.0
		# Bruised rather than merely dark, so the ground reads as spoiled by
		# *this* and not as a shadow something is casting on it.
		_disc(v, c, r, r * SQUASH, 44, Color(
			0.045 + hue.r * 0.10 * (1.0 - k),
			0.036 + hue.g * 0.08 * (1.0 - k),
			0.075 + hue.b * 0.12 * (1.0 - k),
			0.075 + 0.045 * k))

	var side := maxf(full * 0.042, 2.0)
	var speck := Color(hue.r * 0.42, hue.g * 0.38, hue.b * 0.52, 1.0)
	for i in range(int(STIPPLE[tier])):
		var a := TAU * _noise(cell, 100 + i)
		# Biased outward, so the dither thins as it leaves the rim rather than
		# freckling the whole annulus evenly.
		var u := _noise(cell, 200 + i)
		var r := full * (1.0 + (HALO - 1.0) * (1.0 - u * u))
		speck.a = 0.22 + 0.44 * (1.0 - u)
		_block(v, c, Vector2(cos(a) * r, sin(a) * r * SQUASH), side, speck)

	var count := int(CRACKS[tier])
	var ink := Color(0.05, 0.04, 0.075, 0.8)
	var lip := Color(0.75, 0.72, 0.68, 0.16)
	var width := maxf(full * 0.035, 1.0)
	for k in range(count):
		var r := 0.94
		var ang := TAU * (float(k) / float(count) + 0.13 * _noise(cell, 300 + k))
		var prev := Vector2.ZERO
		for s in range(3):
			var at := Vector2(cos(ang) * r, sin(ang) * r * SQUASH) * full
			if s > 0:
				_band(v, c, prev, at, width, ink, ink)
				if tier >= 2:
					# A one-pixel highlight on the south-east lip, so the ground
					# is split rather than drawn on.
					_band(v, c, prev + Vector2.ONE, at + Vector2.ONE, 1.0, lip, lip)
			prev = at
			r += 0.16 + 0.26 * _noise(cell, 400 + k * 4 + s)
			ang += (_noise(cell, 500 + k * 4 + s) - 0.5) * 0.5
	return _mesh(v, c)


## The hole itself: opaque, and the darkest thing in the frame.
##
## The overworld measures 11 to 122 in value, so owning true black is most of
## what makes this a hole and not a puddle. The rim does not turn — only the
## contents do, which is what stops the whole object reading as a wheel. And the
## inner south-east wall is lit while the outer edge is not, because that is a
## pit; a mound is the other way round, and getting it backwards is the cheapest
## possible way to make a crater look like a bump.
func _bake_body(unit: PackedVector2Array, full: float, hue: Color) -> ArrayMesh:
	var v := PackedVector2Array()
	var c := PackedColorArray()
	var void_col := Color(hue.r * 0.10 + 0.018, hue.g * 0.07 + 0.014,
		hue.b * 0.15 + 0.030, 1.0)
	for i in range(RIM_POINTS):
		v.append(Vector2.ZERO)
		v.append(unit[i] * full)
		v.append(unit[(i + 1) % RIM_POINTS] * full)
		c.append(void_col); c.append(void_col); c.append(void_col)

	var lit := Color(hue.r * 0.55 + 0.10, hue.g * 0.55 + 0.10, hue.b * 0.60 + 0.14,
		0.42)
	var lit_w := maxf(full * 0.075, 1.5)
	for i in range(LIT_FROM, LIT_TO):
		_band(v, c, unit[i] * (full * 0.90), unit[i + 1] * (full * 0.90),
			lit_w, lit, lit)

	var edge := Color(hue.r * 0.45, hue.g * 0.45, hue.b * 0.52, 0.75)
	var edge_w := maxf(full * 0.045, 1.5)
	for i in range(RIM_POINTS):
		_band(v, c, unit[i] * full, unit[(i + 1) % RIM_POINTS] * full,
			edge_w, edge, edge)
	return _mesh(v, c)


## The swirl: spiral arms whose lag grows toward the core.
##
## Built unsquashed, so `draw_at` can turn it and flatten the result. Two passes
## over the same points, wide and dim then narrow and bright: one pass at either
## width is a wire or a smear, and the pair is a limb of something. Brightest
## where it is being swallowed and dissolving into the rim, so the eye is
## dragged inward rather than round.
func _bake_arms(tier: int, full: float, wobble: PackedFloat32Array,
		hue: Color) -> ArrayMesh:
	var v := PackedVector2Array()
	var c := PackedColorArray()
	var arms := int(ARMS[tier])
	var twist := float(TWIST[tier])
	var bright := Color(hue.r * 0.55 + 0.45, hue.g * 0.55 + 0.45, hue.b * 0.55 + 0.45)
	var wide := maxf(full * 0.17, 3.0)
	var thin := maxf(full * 0.05, 1.5)
	for pass_i in range(2):
		var width := wide if pass_i == 0 else thin
		var gain := 0.22 if pass_i == 0 else 0.90
		for a in range(arms):
			var base := float(a) * TAU / float(arms)
			var prev := Vector2.ZERO
			var prev_col := Color.WHITE
			for s in range(ARM_STEPS):
				var u := 0.10 + 0.90 * float(s) / float(ARM_STEPS - 1)
				var ang := base + twist * pow(u, 0.85)
				# Radius modulated by the same torn profile as the rim, so the
				# arms are made of the same material as the edge rather than
				# being a clean spiral laid inside a ragged hole.
				var slot := int(fposmod(ang, TAU) / TAU * float(RIM_POINTS)) % RIM_POINTS
				var r := full * u * 0.97 * float(wobble[slot])
				var at := Vector2(cos(ang) * r, sin(ang) * r)
				var col := Color(bright.r, bright.g, bright.b,
					minf((0.95 - 0.74 * u) * gain, 1.0))
				if s > 0:
					_band(v, c, prev, at, width, prev_col, col)
				prev = at
				prev_col = col
	return _mesh(v, c)


## A closed band at unit radius, white, for the frame to scale and tint: the
## travelling rings and the shockwave are the same shape at different sizes.
## Unsquashed, because the transform that places it applies the foreshortening.
func _bake_band(cell: Vector2i, jag: float) -> ArrayMesh:
	var v := PackedVector2Array()
	var c := PackedColorArray()
	var prev := Vector2.ZERO
	for i in range(RING_POINTS + 1):
		var a := TAU * float(i % RING_POINTS) / float(RING_POINTS)
		var w := 1.0 + jag * 0.7 * sin(a * 3.0 + _noise(cell, 1) * TAU)
		var at := Vector2(cos(a) * w, sin(a) * w)
		if i > 0:
			_band(v, c, prev, at, 0.030, Color.WHITE, Color.WHITE)
		prev = at
	return _mesh(v, c)


## The bright core, as a unit disc the frame scales to the pulse.
func _bake_core(hue: Color) -> ArrayMesh:
	var v := PackedVector2Array()
	var c := PackedColorArray()
	var glow := Color(hue.r * 0.5 + 0.5, hue.g * 0.5 + 0.5, hue.b * 0.5 + 0.5, 1.0)
	_disc(v, c, 1.75, 1.75, 20, Color(glow.r, glow.g, glow.b, 0.14))
	_disc(v, c, 1.0, 1.0, 20, Color(glow.r, glow.g, glow.b, 0.85))
	_disc(v, c, 0.46, 0.46, 16, Color(1.0, 0.98, 0.99, 0.9))
	return _mesh(v, c)


## --- mesh plumbing --------------------------------------------------------------

## A filled ellipse as a triangle fan around the origin.
static func _disc(v: PackedVector2Array, c: PackedColorArray, rx: float, ry: float,
		segments: int, col: Color) -> void:
	var prev := Vector2(rx, 0.0)
	for i in range(1, segments + 1):
		var a := TAU * float(i) / float(segments)
		var at := Vector2(cos(a) * rx, sin(a) * ry)
		v.append(Vector2.ZERO); v.append(prev); v.append(at)
		c.append(col); c.append(col); c.append(col)
		prev = at


## An axis-aligned square, centred.
static func _block(v: PackedVector2Array, c: PackedColorArray, at: Vector2,
		side: float, col: Color) -> void:
	var h := side * 0.5
	var a := at + Vector2(-h, -h)
	var b := at + Vector2(h, -h)
	var d := at + Vector2(h, h)
	var e := at + Vector2(-h, h)
	v.append(a); v.append(b); v.append(d)
	v.append(a); v.append(d); v.append(e)
	for i in range(6):
		c.append(col)


## One segment of a thick line, as a quad with a colour at each end.
##
## Both ends are pushed out by half the width along the run, so consecutive
## segments overlap into a square joint. The alternative is mitring, which on a
## curve this smooth would be arithmetic spent hiding a seam nobody can see.
static func _band(v: PackedVector2Array, c: PackedColorArray, p: Vector2, q: Vector2,
		width: float, cp: Color, cq: Color) -> void:
	var run := q - p
	var span := run.length()
	if span < 0.0001:
		return
	var dir := run / span
	var side := Vector2(-dir.y, dir.x) * (width * 0.5)
	var a := p - dir * (width * 0.5)
	var b := q + dir * (width * 0.5)
	v.append(a - side); v.append(b - side); v.append(b + side)
	v.append(a - side); v.append(b + side); v.append(a + side)
	c.append(cp); c.append(cq); c.append(cq)
	c.append(cp); c.append(cq); c.append(cp)


static func _mesh(v: PackedVector2Array, c: PackedColorArray) -> ArrayMesh:
	var mesh := ArrayMesh.new()
	if v.is_empty():
		return mesh
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = v
	arrays[Mesh.ARRAY_COLOR] = c
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh


## Deterministic 0..1 from a cell and a salt.
##
## Its own salt space rather than HJMotion.phase_for()'s or HJLighting's: a
## portal, a swaying bush and a guttering lamp standing on the same cell must
## not share a heartbeat, and a portal's shape must not come off the same number
## as its phase, or the biggest tears would all be the ones that turn fastest.
static func _noise(cell: Vector2i, salt: int) -> float:
	var h := (cell.x * 374761393) ^ (cell.y * 668265263) ^ (salt * 1274126177)
	h = (h ^ (h >> 13)) * 1274126177
	return float(absi(h ^ (h >> 16)) % 65521) / 65521.0
