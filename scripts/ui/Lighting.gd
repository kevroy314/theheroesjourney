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
	return smoothstep(0.0, 0.34, ambient_mix())


## How much of the ambient replaces the art right now, 0..1.
static func ambient_mix(t: float = -1.0) -> float:
	var s := _sample(t)
	return float(s[0])


## What the unlit world is tinted toward right now.
static func ambient_colour(t: float = -1.0) -> Color:
	var s := _sample(t)
	return s[1]


static func _sample(t: float) -> Array:
	var u := fposmod(time_of_day if t < 0.0 else t, 1.0)
	var previous: Array = AMBIENT[0]
	for stop in AMBIENT:
		var entry: Array = stop
		var at: float = float(entry[0])
		if u <= at:
			var was: float = float(previous[0])
			var span: float = maxf(at - was, 0.0001)
			var k: float = clampf((u - was) / span, 0.0, 1.0)
			return [lerpf(float(previous[1]), float(entry[1]), k),
				Color(previous[2]).lerp(Color(entry[2]), k)]
		previous = entry
	return [float(previous[1]), Color(previous[2])]


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
		if entry.has("light"):
			_claim(int(entry.get("plane", 0)), entry["light"])


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


static func index_world(world: HJWorld) -> void:
	if _indexed:
		return
	_indexed = true
	load_manifest()
	if _by_plane.is_empty() or world == null or not world.loaded:
		return
	var props: PackedByteArray = world.props
	if props.size() != world.w * world.h:
		return
	for y in range(world.h):
		var row: int = y * world.w
		for x in range(world.w):
			var plane: int = props[row + x]
			if plane == 0:
				continue
			var spec: Dictionary = _by_plane.get(plane, {})
			if spec.is_empty():
				continue
			var key := Vector2i(x / BUCKET, y / BUCKET)
			var cell := Vector2i(x, y)
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
