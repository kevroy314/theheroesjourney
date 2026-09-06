class_name HJLighting
extends RefCounted
## The atmosphere model: what colour the world is at this hour, and what a lamp
## does to it.
##
## Two halves, deliberately kept apart from the renderer:
##
##   * an **ambient ramp** — a keyframed gradient sampled by `time_of_day`, which
##     is the pixel-art convention of *palette cycling* rather than re-drawn
##     day and night art. The literature is unanimous on this: you do not paint
##     a night tileset, you fade the palette. A global ramp is that idea with a
##     shader instead of a CLUT.
##
##   * a **light list** — every emitter near the viewport, read from the tileset
##     manifest rather than hardcoded, so a prop becomes a lamp by gaining three
##     numbers in `assets/tiles/tiles.json` and nothing here changes.
##
## The contract a prop entry may carry:
##
##     "light": { "radius": 4.5, "color": "#FFC880", "flicker": 0.15 }
##
##   radius   in tiles, float
##   color    hex, the colour *at the source*
##   flicker  0.0-1.0, 0 is a steady lamp and 1 is a guttering candle
##
## Absent, the prop emits nothing and the world renders as it always did.

const MANIFEST := "res://assets/tiles/tiles.json"

## Hard ceiling on lights fed to the shader in one frame. Must match
## MAX_LIGHTS in assets/shaders/world_light.gdshader. Twelve is far more than a
## 7x7-tile viewport can hold and still leaves the uniform block tiny.
const MAX_LIGHTS := 12


## --- the clock seam ------------------------------------------------------------
##
## 0.0 midnight, 0.25 dawn, 0.5 noon, 0.75 dusk. The game opens in early
## morning, which is why the default is 0.27 and not 0.5.
##
## SEAM FOR #33 (the world clock, which does not exist yet). When it lands it
## should own this value and write it once per tick:
##
##     HJLighting.time_of_day = Clock.fraction_of_day()
##
## Nothing else should set it. Until then it is a settable property with a
## sensible default, exactly as issue #49 asks, and the renderer reads it every
## frame so a debug slider can drive it live.
static var time_of_day: float = 0.27

## Off switches, both for the "it must degrade" clause and for a settings menu
## later. With `enabled = false` the overlay is not even created.
static var enabled: bool = true

## Anomalies as emitters. A hole in reality that lights nothing looks painted
## on; a cold violet pool under it is the cheapest possible way to say "this is
## not part of the world". Off makes the world exactly as bright as before.
static var anomaly_glow: bool = true
const ANOMALY_COLOUR := Color(0.45, 0.32, 0.95)
const ANOMALY_RADIUS := 2.4      ## tiles, at tier 0; grows half a tile per tier
const ANOMALY_FLICKER := 0.30

## A legibility floor, not a lantern.
##
## Darkness as the default state is the look, but a player who cannot see the
## tile in front of them cannot walk, and this world has no torch item to hand
## out. So the character carries a weak, wide, almost colourless light that
## fades with the same daylight gain as everything else. At 0.45 it never reads
## as "the hero glows" — it reads as your eyes having adjusted.
##
## Set to 0.0 to turn it off entirely; a real carried-light item should drive
## add_light("lantern", ...) on the renderer instead of raising this.
static var player_light: float = 0.45
const PLAYER_RADIUS := 3.2
const PLAYER_COLOUR := Color(0.78, 0.76, 0.72)

## Inside is not outside.
##
## The user's first note on lighting was "a simple light in a room projecting
## out can really make a scene pop", and the run opens in a house — so the one
## place this has to be right on day one is an interior at nine in the morning,
## where the sun is up and the room is still dim. A global hour cannot say that.
##
## The world already draws a rectangle round each room for the Boon of the White
## Room, so the renderer sets this while the character stands in one and the
## ambient takes a floor: never brighter than a dim room, and neutral rather
## than the blue of a night sky, because a ceiling is not weather.
##
## This is the coarse version — the whole frame darkens, not just the cells
## under the roof. Doing it properly means handing the room rectangles to the
## shader, which is worth it once there is more than one building.
static var indoors: bool = false
const INTERIOR_MIX := 0.40
const INTERIOR_COLOUR := Color(0.085, 0.080, 0.115)


## --- the ambient ramp ----------------------------------------------------------
##
## Each stop is [time, mix, colour].
##
##   mix    how much of the ambient colour replaces the art, 0..1. 0 is a
##          complete no-op: at noon the overlay writes nothing at all.
##   colour what the unlit world is mixed *toward*. Note these are not simply
##          dark — the pre-dawn stop is a fairly bright desaturated blue,
##          because "cool blue shadow" is a shift in hue, not just a dimming,
##          and mixing toward something near-black only ever produces mud.
##
## Sampled with a plain lerp between neighbouring stops. Keep them sorted.
const AMBIENT := [
	[0.00, 0.78, Color(0.055, 0.075, 0.165)],   # midnight
	[0.20, 0.72, Color(0.070, 0.100, 0.220)],   # the hour before anything
	[0.27, 0.52, Color(0.130, 0.160, 0.310)],   # early morning — where we start
	[0.34, 0.28, Color(0.330, 0.265, 0.250)],   # low sun, long and warm
	[0.45, 0.09, Color(0.540, 0.510, 0.450)],
	[0.52, 0.00, Color(0.600, 0.580, 0.520)],   # noon: the overlay is a no-op
	[0.68, 0.08, Color(0.560, 0.450, 0.360)],
	[0.78, 0.30, Color(0.430, 0.245, 0.200)],   # dusk, the warm one
	[0.86, 0.58, Color(0.170, 0.165, 0.330)],   # the blue half hour
	[1.00, 0.78, Color(0.055, 0.075, 0.165)],   # midnight again, so it loops
]

## How hard a light adds on top of the art it reveals. This is the only global
## brightness knob; everything else about a lamp comes from its own entry.
const GLOW := 0.34


## What a lamp is worth at this hour.
##
## A street light blazing at noon is the single most obviously wrong thing this
## system can do, and no amount of ramp tuning hides it — the sun is simply
## brighter than the lamp. Tied to the ambient rather than to the clock directly
## so the two can never disagree: as the world stops needing lighting, the lamps
## stop providing it, and at noon (mix 0) the gain is exactly zero and the whole
## pass becomes a no-op.
##
## The cost of doing it this way is that an interior lamp also fades at midday,
## because nothing here knows about roofs yet. When the house has an inside,
## this is where a "sheltered" term belongs.
static func lamp_gain() -> float:
	_resample()
	return _cache_gain


## The sampled ramp, recomputed only when the hour actually moves. Three calls a
## frame walk this list otherwise, and each one allocated a result to return.
static var _cache_at: float = -1.0
static var _cache_indoors := false
static var _cache_mix: float = 0.0
static var _cache_colour: Color = Color.BLACK
static var _cache_gain: float = 0.0


static func _resample() -> void:
	if is_equal_approx(_cache_at, time_of_day) and _cache_indoors == indoors:
		return
	_cache_at = time_of_day
	_cache_indoors = indoors
	var u := fposmod(time_of_day, 1.0)
	var previous: Array = AMBIENT[0]
	for stop in AMBIENT:
		var entry: Array = stop
		var at: float = float(entry[0])
		if u <= at:
			var was: float = float(previous[0])
			var span: float = maxf(at - was, 0.0001)
			var k: float = clampf((u - was) / span, 0.0, 1.0)
			_settle(lerpf(float(previous[1]), float(entry[1]), k),
				Color(previous[2]).lerp(Color(entry[2]), k))
			return
		previous = entry
	_settle(float(previous[1]), Color(previous[2]))


static func _settle(mix: float, colour: Color) -> void:
	_cache_mix = mix
	_cache_colour = colour
	if indoors:
		_cache_mix = maxf(mix, INTERIOR_MIX)
		_cache_colour = colour.lerp(INTERIOR_COLOUR, 0.75)
	_cache_gain = smoothstep(0.0, 0.34, _cache_mix)


## How much of the ambient replaces the art right now, 0..1.
static func ambient_mix() -> float:
	_resample()
	return _cache_mix


## What the unlit world is tinted toward right now.
static func ambient_colour() -> Color:
	_resample()
	return _cache_colour


## --- the manifest --------------------------------------------------------------
##
## plane value (atlas slot + 1, the same byte the world's prop plane stores) ->
## { radius: float, colour: Color, flicker: float }.
static var _by_plane: Dictionary = {}
static var _max_radius: float = 0.0
static var _read := false


static func load_manifest() -> void:
	if _read:
		return
	_read = true
	var file := FileAccess.open(MANIFEST, FileAccess.READ)
	if file == null:
		return                      # no tileset, no lights, no complaint
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	file.close()
	if not (parsed is Dictionary):
		return
	var props: Dictionary = (parsed as Dictionary).get("props", {})
	var list: Array = props.get("list", [])

	# A prop with no `light` key emits nothing, and a tileset with no lights at
	# all leaves this dictionary empty — at which point the renderer's scan never
	# runs and the world looks exactly as it did before any of this existed.
	for row in list:
		if not (row is Dictionary):
			continue
		var entry: Dictionary = row
		var plane := int(entry.get("plane", 0))
		if entry.has("light"):
			_claim(plane, entry["light"])
		if entry.has("shaft"):
			_claim_shaft(plane, entry["shaft"], entry.get("light", {}))


static func _claim(plane: int, spec: Variant) -> void:
	if plane <= 0 or not (spec is Dictionary):
		return
	var light: Dictionary = spec
	var radius: float = float(light.get("radius", 0.0))
	if radius <= 0.0:
		return
	_by_plane[plane] = {
		"radius": radius,
		"colour": _colour(String(light.get("color", "#FFFFFF"))),
		"flicker": clampf(float(light.get("flicker", 0.0)), 0.0, 1.0),
	}
	_max_radius = maxf(_max_radius, radius)


## Tolerant on purpose: a typo in a hex string should give a white lamp, not a
## parse error buried in a draw loop.
static func _colour(hex: String) -> Color:
	var text := hex.strip_edges()
	if text.is_empty():
		return Color.WHITE
	return Color.html(text) if Color.html_is_valid(text) else Color.WHITE


static func any_lights() -> bool:
	load_manifest()
	return not _by_plane.is_empty()


## How far outside the viewport a light can still reach, in tiles. Emitters this
## far off screen have to be gathered anyway or a pool would pop into being at
## the edge of the view as you walk toward it.
static func margin_tiles() -> int:
	load_manifest()
	return int(ceil(maxf(_max_radius, ANOMALY_RADIUS + 2.0))) + 1


## --- the index -----------------------------------------------------------------
##
## Where every emitter in the world is, bucketed into 16x16-tile squares.
##
## The first version of this walked the visible rectangle grown by the longest
## reach — about 900 cells — and asked the world for the prop on each one. That
## measured 2.4 ms a frame on a desktop, which is a third of a phone's budget
## spent deciding that eight hundred patches of grass are not lamps. Almost all
## of it was work whose answer never changes: props do not move.
##
## So the plane is walked exactly once and only the lit cells are kept. A frame
## then touches the six buckets the view overlaps and iterates the handful of
## lamps inside them. The one-off pass over 65,536 cells costs about as much as
## loading a texture and happens while the screen is being built.
const BUCKET := 16

static var _buckets: Dictionary = {}     ## Vector2i bucket -> Array of sources
static var _indexed := false


## Call again after the world is regenerated; nothing does yet.
static func invalidate() -> void:
	_indexed = false
	_buckets.clear()
	_shaft_buckets.clear()
	traced_at = -1.0


static func index_world(world: HJWorld) -> void:
	if _indexed:
		return
	_indexed = true
	load_manifest()
	if world == null or not world.loaded:
		return
	if _by_plane.is_empty() and _shaft_by_plane.is_empty():
		return
	var props: PackedByteArray = world.props
	if props.size() != world.w * world.h:
		return
	# Kept so the shaft traces can ask the map where the walls are without every
	# caller having to hand the world back in. The same instance HJWorld.shared()
	# returns; nothing here holds it past invalidate().
	_world = world
	for y in range(world.h):
		var row: int = y * world.w
		for x in range(world.w):
			var plane: int = props[row + x]
			if plane == 0:
				continue
			var cell := Vector2i(x, y)
			var key := Vector2i(x / BUCKET, y / BUCKET)
			var spec: Dictionary = _by_plane.get(plane, {})
			if not spec.is_empty():
				var entry := {
					"cell": cell,
					"radius": float(spec["radius"]),
					"colour": spec["colour"],
					"flicker": float(spec["flicker"]),
					"phase": phase_for(cell),
				}
				if _buckets.has(key):
					(_buckets[key] as Array).append(entry)
				else:
					_buckets[key] = [entry]
			var aperture: Dictionary = _shaft_by_plane.get(plane, {})
			if not aperture.is_empty():
				_place_shaft(world, cell, key, aperture)


## Every emitter whose bucket overlaps a tile rectangle. Returns arrays, not
## copies — the caller reads and does not keep them.
static func buckets_over(from: Vector2i, to: Vector2i) -> Array:
	var out: Array = []
	if _buckets.is_empty():
		return out
	for by in range(from.y / BUCKET, to.y / BUCKET + 1):
		for bx in range(from.x / BUCKET, to.x / BUCKET + 1):
			var found: Variant = _buckets.get(Vector2i(bx, by))
			if found != null:
				out.append(found)
	return out


## --- flicker -------------------------------------------------------------------
##
## Computed per source on the CPU rather than in the shader: it is one value per
## light per frame instead of one per pixel, and it keeps the fragment program
## down to arithmetic with no noise lookups.
##
## The seed is what matters. Two torches sharing a phase pulse in lockstep,
## which reads as a fault in the display rather than as fire — worse than no
## flicker at all. Every source gets its own offset from its own position.
static func flicker(amount: float, seed: float, t: float) -> float:
	if amount <= 0.0:
		return 1.0
	# Two rates layered: a fast gutter and a slow breath, same shape as the
	# title-plate lamp in assets/shaders/lamplight.gdshader.
	var fast := _wobble(t * 6.5 + seed)
	var slow := _wobble(t * 1.7 + seed * 3.7 + 11.0)
	var flame := fast * 0.55 + slow * 0.45
	return clampf(1.0 + (flame - 0.5) * 2.0 * amount, 0.2, 1.45)


static func _hash1(n: float) -> float:
	return fposmod(sin(n * 12.9898) * 43758.5453, 1.0)


static func _wobble(x: float) -> float:
	# Spelled out rather than inferred: the global floor() takes a Variant, so
	# `var i := floor(x)` infers Variant and every arithmetic line after it
	# becomes a parse error a long way from the cause.
	var i: float = floor(x)
	var f: float = x - i
	f = f * f * (3.0 - 2.0 * f)
	return lerpf(_hash1(i), _hash1(i + 1.0), f)


## A stable per-cell phase, so a lamp keeps its rhythm as you walk past it.
static func phase_for(cell: Vector2i) -> float:
	var h := absi((cell.x * 73856093) ^ (cell.y * 19349663))
	return float(h % 9973) * 0.0011


## --- the sun, and what it does through a hole -----------------------------------
##
## WHERE A SHAFT LIVES, AND WHY IT IS SPLIT IN THREE
##
## The obvious two answers are both wrong on their own.
##
##   * "The world owns it — the sun is at this bearing." Simple, but then every
##     hole in the world throws the same beam, and the renderer has to guess
##     which props are holes. It cannot: a window and a bookshelf are both just
##     a byte in the prop plane.
##
##   * "The prop owns it — `shaft: { bearing: ... }`." Authorable, but it lets a
##     window on the north wall claim a different sun from the one on the east
##     wall, which is the failure the brief names: a sun in a different place for
##     each window is worse than no sun at all.
##
## So it is split by what each side actually knows:
##
##   the WORLD owns the sun     — one bearing and one gain for the whole map,
##                                derived from `time_of_day` and from nothing
##                                else. There is exactly one of these.
##   the PROP owns the aperture — that it is a hole at all, how far it throws,
##                                how wide, and how many panes its frame is
##                                divided into. That is a fact about the art,
##                                which is what the manifest is for, and it is
##                                the same contract `light` and `sway` use. A
##                                doorway or a gap in a roof becomes a shaft by
##                                gaining the key and nothing here changes.
##   the GEOMETRY owns the rest — which way the aperture faces and how far the
##                                beam gets before it hits a wall. Neither the
##                                art nor the clock can know that; only the map
##                                can, and it is read from the map.
##
## The contract a prop entry may carry, beside `light`:
##
##     "shaft": { "length": 10.0, "width": 0.42, "spread": 0.14, "bars": 2 }
##
##   length   how far the beam reaches at its longest, in tiles, before walls
##   width    half-width where it leaves the aperture, in tiles
##   spread   extra half-width per tile travelled — a beam widens as it goes
##   bars     panes across the aperture; 2 is one mullion, 0 is an open hole
##   color    optional #RRGGBB; defaults to the prop's own `light` colour
##   intensity optional 0..1 scale, default 1.0
##
## Absent, the prop throws nothing, `any_shafts()` is false, the overlay never
## pushes a uniform and the shader's loop breaks on its first iteration. A build
## with no shaft declaration anywhere renders exactly as it did before this
## existed — which is the point of putting the declaration in the manifest
## rather than in a list of prop ids in here.

## Off switch, matching `enabled` and `anomaly_glow`.
static var shafts: bool = true

## Hard ceiling on shafts fed to the shader in one frame. Must match MAX_SHAFTS
## in assets/shaders/world_light.gdshader. The house has four windows and a
## 7x7-tile viewport sees at most two of them; four leaves headroom for a room
## with a wall of glass without making the fragment loop something a phone
## notices.
const MAX_SHAFTS := 4

## The bearing sweep, in degrees of screen space with +x east and +y south.
##
## This is a compass, not a lens: 155 degrees is west-south-west, 25 degrees is
## east-south-east, and the sun crosses between them through due south at noon.
## The arc is deliberately kept in the southern half. A top-down map draws only
## the floor, so a beam travelling up-screen goes behind the wall it just came
## through and vanishes — which is geometrically honest and reads as a bug. The
## floor is the only surface there is, so the light is thrown onto it.
const SUN_FROM := 155.0
const SUN_TO := 25.0

## How much the aperture collimates the beam toward its own normal.
##
## Real windows do this — a beam through a deep reveal leaves closer to the
## wall's normal than to the sun's bearing — and it is also the term that makes
## the effect legible: without it, a window in the north wall at sunrise throws
## a beam that skims along the wall it is set in and never reaches the floor.
## At 0.0 the bearing is the sun's alone; at 1.0 the sun stops mattering.
const SUN_REVEAL := 0.6

## Beam length against sun height: low sun, long shaft.
const REACH_LOW := 1.0
const REACH_HIGH := 0.45

## Ray march. A quarter tile is four samples per cell, which is finer than the
## walls are thick and coarse enough that a ten-tile trace is forty lookups.
const TRACE_STEP := 0.25
## How much masonry the beam may pass through on the way out before the aperture
## is declared blocked. A window sits IN a wall, so the first samples along the
## beam are always inside that wall; without this every shaft would measure zero.
const TRACE_LEAD := 3.0
## Below this a shaft is not worth drawing — a beam one tile long on a floor is
## a smudge, not a shaft.
const TRACE_MIN := 1.2

## The bearing is quantised before the traces are re-run. The occlusion of a
## beam is a function of the map and the bearing, and the map does not move; so
## once the world clock lands and `time_of_day` advances every tick, this is
## what stops it re-marching every window every frame. Two degrees over a 130
## degree sweep is 65 recomputes for a whole day.
const TRACE_QUANTUM := 2.0

const SHAFT_COLOUR := Color(1.0, 0.906, 0.761)     ## #FFE7C2, first light


## Where the sun is in its arc: 0 at sunrise, 1 at sunset, pinned at the ends
## through the night so nothing downstream has to special-case darkness.
static func sun_arc() -> float:
	return clampf((fposmod(time_of_day, 1.0) - 0.25) / 0.5, 0.0, 1.0)


## How high the sun stands, 0 on either horizon and 1 at noon.
static func sun_height() -> float:
	return sin(PI * sun_arc())


## What a shaft is worth at this hour.
##
## The mirror of `lamp_gain()`, and deliberately the opposite shape. A lamp is
## worth nothing when the sun is up; a shaft is worth nothing when the sun is
## *down* — and also nothing when it is overhead, because a sun at the zenith
## does not come through a window sideways, it comes through a skylight. So the
## curve rises just after sunrise, peaks while the sun is low, and is gone well
## before noon. It comes back before dusk on its own, from the same arc, which
## is why there is no separate evening term: an evening shaft through a west
## window is the same phenomenon seen from the other end of the day.
static func shaft_gain() -> float:
	if not shafts:
		return 0.0
	var e := sun_height()
	return smoothstep(0.02, 0.14, e) * (1.0 - smoothstep(0.30, 0.62, e))


## Which way the light travels across the ground, as a unit vector in screen
## space. Not where the sun is — where its light is going.
static func sun_travel() -> Vector2:
	var a := deg_to_rad(lerpf(SUN_FROM, SUN_TO, sun_arc()))
	return Vector2(cos(a), sin(a))


## Reach multiplier for the hour: a low sun throws a long beam.
static func sun_reach() -> float:
	return lerpf(REACH_LOW, REACH_HIGH, sun_height())


## The quantised bearing the traces were last run against.
static func sun_stamp() -> float:
	return round(lerpf(SUN_FROM, SUN_TO, sun_arc()) / TRACE_QUANTUM)


## --- apertures -----------------------------------------------------------------
##
## plane value -> the prop's declared optics. Parallel to `_by_plane`, and kept
## separate rather than folded into it because the two are independent: a prop
## may be a lamp, a hole, both, or neither, and `window_lit` is both — the pool
## on the sill is its `light`, the beam on the floor is its `shaft`.
static var _shaft_by_plane: Dictionary = {}
## Every aperture standing in the world, bucketed exactly like the emitters.
static var _shaft_buckets: Dictionary = {}
## The map the traces walk. Set by index_world; see there.
static var _world: HJWorld = null


static func _claim_shaft(plane: int, spec: Variant, light: Variant) -> void:
	if plane <= 0 or not (spec is Dictionary):
		return
	var shaft: Dictionary = spec
	var length: float = float(shaft.get("length", 0.0))
	var width: float = float(shaft.get("width", 0.0))
	if length <= 0.0 or width <= 0.0:
		return
	# A shaft with no colour of its own takes the prop's lamp colour, because the
	# pane you can see and the beam it throws should not disagree about what
	# colour the morning is. With neither, first light.
	var tint := SHAFT_COLOUR
	if shaft.has("color"):
		tint = _colour(String(shaft.get("color", "")))
	elif light is Dictionary and (light as Dictionary).has("color"):
		tint = _colour(String((light as Dictionary).get("color", "")))
	_shaft_by_plane[plane] = {
		"length": length,
		"width": width,
		"spread": maxf(float(shaft.get("spread", 0.0)), 0.0),
		"bars": maxf(float(shaft.get("bars", 0.0)), 0.0),
		"colour": tint,
		"intensity": clampf(float(shaft.get("intensity", 1.0)), 0.0, 1.0),
	}


static func any_shafts() -> bool:
	load_manifest()
	return not _shaft_by_plane.is_empty()


## One aperture, placed. The expensive half of this — which way it faces — is
## a fact about the map and not about the hour, so it is settled once here and
## never asked again; only the trace down the beam depends on the sun.
static func _place_shaft(world: HJWorld, cell: Vector2i, key: Vector2i,
		spec: Dictionary) -> void:
	# Flat, not nested. Every field here is read once per aperture per frame, and
	# a nested `spec` dictionary meant fifteen Variant probes per window rather
	# than eight — the same reason the emitter list is packed rather than a list
	# of dictionaries. The optics are copied out of the manifest entry once.
	var tint: Color = spec["colour"]
	var entry := {
		"cell": cell,
		"inward": _inward(world, cell),
		"reach": float(spec["length"]),
		"half": float(spec["width"]),
		"spread": float(spec["spread"]),
		"bars": float(spec["bars"]),
		"gain": float(spec["intensity"]),
		"tint": tint,
		# Filled by refresh(); -1 means "never traced".
		"stamp": -1.0,
		"from": Vector2.ZERO,      ## mouth offset from the cell centre, in tiles
		"dir": Vector2.RIGHT,
		"span": 0.0,               ## mouth to far wall, in tiles
		"gate": 0.0,
		# The beam's tile-space bounding box, so a frame can reject an aperture
		# whose light cannot reach the view with four integer compares and no
		# floating point at all. Only the bearing moves it.
		"lo": cell,
		"hi": cell,
	}
	if _shaft_buckets.has(key):
		(_shaft_buckets[key] as Array).append(entry)
	else:
		_shaft_buckets[key] = [entry]


## Which way an aperture faces, as a unit vector, or ZERO for one that faces
## every way at once.
##
## A window prop stands ON the wall cell, not on the floor beside it — the art
## is drawn low in its slot for exactly that reason — so the wall it is set in
## is the cell it occupies and the sides of that cell tell you the rest. The
## side that is open AND indoors is the inside; a hole with no solid neighbour
## at all is a skylight or a gap in a hedge and has no normal to speak of, so it
## takes the sun's own bearing.
static func _inward(world: HJWorld, cell: Vector2i) -> Vector2:
	const SIDES := [Vector2i(0, 1), Vector2i(0, -1), Vector2i(1, 0), Vector2i(-1, 0)]
	var best := Vector2.ZERO
	var score := 0
	var open := 0
	for side in SIDES:
		var next: Vector2i = cell + side
		if _blocked(world, next.x, next.y):
			continue
		open += 1
		var rank := 2 if world.is_indoors(next) else 1
		if rank > score:
			score = rank
			best = Vector2(side)
	if open >= 4:
		return Vector2.ZERO
	return best


## Walls only, and deliberately not world.walkable().
##
## walkable() is the movement question, and it answers with three things a beam
## has no opinion about: the prop collision plane, so a chair would cast a
## room-length shadow; and _shut(), which consults a Game tag, so an unbought
## door would stop the sun and the light in the house would change when the
## player spent Grit. What stops a shaft is masonry, and masonry is the cell's
## material.
static func _blocked(world: HJWorld, x: int, y: int) -> bool:
	return world.solid.has(world.at(x, y))


## --- the trace -----------------------------------------------------------------
##
## What this buys, and what it costs.
##
## A beam that crosses an interior wall into the next room is the one failure
## that cannot be tuned away — it does not look like light, it looks like a
## decal. So the length of every beam is measured against the map: out through
## the masonry the aperture is set in, across whatever floor is there, and stop
## at the next wall.
##
## What it does NOT do, on purpose:
##
##   * furniture. A table does not break the beam. Per-cell shadow casting off
##     the prop plane would mean a second trace per aperture and a silhouette
##     the shader cannot express as a wedge, and the wedge is what makes this
##     one instruction instead of a shadow map.
##   * width. The trace is a single ray down the middle, so a beam whose far end
##     has widened past a doorway will spill a few pixels through the jamb. Three
##     rays would fix it and cost three times as much; at the widths declared
##     here the error is smaller than the beam's own soft edge.
##   * anything per frame. The answer only changes when the bearing does, and
##     the bearing is quantised to two degrees, so a walking player pays nothing
##     at all and a moving clock pays for one march every few seconds.
static func refresh_shaft(entry: Dictionary, stamp: float, travel: Vector2,
		reach: float) -> void:
	if is_equal_approx(float(entry["stamp"]), stamp):
		return
	entry["stamp"] = stamp
	var cell: Vector2i = entry["cell"]
	var inward: Vector2 = entry["inward"]
	var gate := 1.0
	var dir := travel
	if inward != Vector2.ZERO:
		# How squarely the sun faces this hole. A west window at sunrise gets
		# nothing, and that is not a special case — it is this dot product.
		gate = smoothstep(0.05, 0.55, travel.dot(inward))
		if gate <= 0.002:
			entry["gate"] = 0.0
			entry["span"] = 0.0
			entry["lo"] = cell
			entry["hi"] = cell
			return
		dir = (travel + inward * SUN_REVEAL).normalized()
	entry["dir"] = dir
	entry["gate"] = gate
	var span := _trace(cell, dir, float(entry["reach"]) * reach)
	entry["from"] = dir * span.x
	entry["span"] = span.y - span.x
	# The box the beam can touch: the segment, grown by the widest it ever gets.
	var tip := dir * span.y
	var pad := ceili(float(entry["half"]) + span.y * float(entry["spread"])) + 1
	entry["lo"] = cell + Vector2i(
		floori(minf(0.0, tip.x)) - pad, floori(minf(0.0, tip.y)) - pad)
	entry["hi"] = cell + Vector2i(
		ceili(maxf(0.0, tip.x)) + pad, ceili(maxf(0.0, tip.y)) + pad)


## Returns (distance to the first floor, distance to the far wall), in tiles.
## Both zero when the aperture is walled in or the beam has nowhere to fall.
static func _trace(cell: Vector2i, dir: Vector2, reach: float) -> Vector2:
	if _world == null or reach <= 0.0:
		return Vector2.ZERO
	var origin := Vector2(cell) + Vector2(0.5, 0.5)
	var mouth := -1.0
	var t := TRACE_STEP
	while t <= reach:
		var p := origin + dir * t
		if _blocked(_world, int(floor(p.x)), int(floor(p.y))):
			if mouth >= 0.0:
				break                       # the far wall: this is where it ends
			if t > TRACE_LEAD:
				return Vector2.ZERO         # still in masonry: the sun cannot get in
		elif mouth < 0.0:
			mouth = t
		t += TRACE_STEP
	if mouth < 0.0 or t - TRACE_STEP - mouth < TRACE_MIN:
		return Vector2.ZERO
	return Vector2(mouth, minf(t - TRACE_STEP, reach))


## The bearing every aperture was last traced against. The frame compares this
## once instead of asking each aperture in turn, so a player walking around a
## house under a still sun makes no call into refresh_shaft() whatsoever.
static var traced_at: float = -1.0


static func shafts_are_stale(stamp: float) -> bool:
	if is_equal_approx(traced_at, stamp):
		return false
	traced_at = stamp
	return true


## Every aperture whose bucket overlaps a tile rectangle, same contract as
## buckets_over() — with the difference that the array is reused between frames
## rather than allocated, because unlike the emitters this one is walked by a
## pass that owns it and does not keep it.
static var _shaft_scratch: Array = []


static func shaft_buckets_over(from: Vector2i, to: Vector2i) -> Array:
	var out: Array = _shaft_scratch
	out.clear()
	if _shaft_buckets.is_empty():
		return out
	for by in range(from.y / BUCKET, to.y / BUCKET + 1):
		for bx in range(from.x / BUCKET, to.x / BUCKET + 1):
			var found: Variant = _shaft_buckets.get(Vector2i(bx, by))
			if found != null:
				out.append(found)
	return out


## How far outside the viewport an aperture can still throw light, in tiles.
static var _max_shaft: float = 0.0


static func shaft_margin_tiles() -> int:
	load_manifest()
	if _max_shaft <= 0.0:
		for plane in _shaft_by_plane:
			var spec: Dictionary = _shaft_by_plane[plane]
			_max_shaft = maxf(_max_shaft, float(spec["length"]))
	return int(ceil(_max_shaft)) + 1
