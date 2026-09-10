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
##     "light": { "radius": 4.5, "color": "#FFC880", "flicker": 0.15,
##                "kind": "lamp" }
##
##   radius   in tiles, float
##   color    hex, the colour *at the source*
##   flicker  0.0-1.0, 0 is a steady lamp and 1 is a guttering candle
##   kind     what SORT of light it is, and therefore when it burns. Optional;
##            "lamp" if absent, because a lamp is the common case and the
##            behaviour the pass had before kinds existed. See `gain_for()`.
##
## Absent, the prop emits nothing and the world renders as it always did.

const MANIFEST := "res://assets/tiles/tiles.json"

## Hard ceiling on lights fed to the shader in one frame. Must match
## MAX_LIGHTS in assets/shaders/world_light.gdshader.
##
## Was twelve, sized when the only emitters in the world were seven lampposts,
## six street lamps and the props inside one house. Every building in the town
## now carries lit windows, and the gather rectangle is the viewport grown by
## the longest reach — about 25 cells square — which on the high street holds
## more than twelve. Past the ceiling the renderer drops whichever emitter is
## furthest from the middle of the view, so what the player saw was lamps
## switching on and off as they walked, one street back.
##
## Twenty is not expensive. The fragment loop breaks at `light_count`, so a
## frame with three lamps in it costs three iterations at twenty exactly as it
## did at twelve; what grows is the uniform block, by 128 bytes.
const MAX_LIGHTS := 20


## --- the clock -------------------------------------------------------------------
##
## 0.0 midnight, 0.25 dawn, 0.5 noon, 0.75 dusk.
##
## WHY THIS IS NOT STILL A SEAM
##
## It was a static 0.27 with a note saying #33 would move it one day. That is a
## defensible way to ship a ramp and an indefensible way to ship a *time of day*:
## every hour below this line was correct and none of it was ever reached,
## because nothing in the running game ever wrote the variable. The first
## complaint about the lighting not being time-of-day dependent was really a
## complaint about the clock being stopped, and no amount of tuning the ramp
## would have answered it.
##
## So the value moves on its own now, and it moves in one of three ways:
##
##   CLOCK_FIXED   nothing advances it. What the self-test and every screenshot
##                 harness use, because a picture of an hour has to be of the
##                 hour it asked for. `set_hour()` selects this.
##   CLOCK_LOCAL   the player's own wall clock, 1:1. Thematically the right
##                 answer for an app about how you spend your days, and almost
##                 certainly what #33 will settle on — but you see exactly one
##                 hour per session, which is indistinguishable from a stopped
##                 clock over five minutes of play.
##   CLOCK_CYCLE   a compressed day, *anchored to the real local hour at
##                 startup*. Opens matching your wall clock and then visibly
##                 moves. This is the default, and it is the stopgap: it is the
##                 only setting under which a player who is not looking for the
##                 feature still sees it.
##
## When #33 lands it should set `clock_mode = CLOCK_FIXED` once and write
## `time_of_day` every tick; nothing else here has to change.
enum { CLOCK_FIXED, CLOCK_LOCAL, CLOCK_CYCLE }

static var clock_mode: int = CLOCK_CYCLE

## One in-game day in real seconds, for CLOCK_CYCLE. Twenty-four minutes is a
## minute an hour: a three-minute walk crosses three hours, which is enough to
## watch a shaft swing across a floor and not enough to strobe.
static var cycle_seconds: float = 1440.0

static var time_of_day: float = 0.27

## The clock is sampled at most this often. Three accessors read the hour every
## frame and they must all agree within that frame, or the ambient cache thrashes
## three times a frame for a value that moved by a millionth.
const CLOCK_TICK_MS := 100

static var _clock_read_at: int = -CLOCK_TICK_MS
static var _cycle_origin: float = -1.0


## The hour the player's own clock says it is, 0..1.
static func local_hour() -> float:
	var t := Time.get_time_dict_from_system()
	return (float(t["hour"]) + float(t["minute"]) / 60.0
		+ float(t["second"]) / 3600.0) / 24.0


## Pin the hour and stop it moving. The one call a harness, a debug slider or a
## cutscene should make — assigning `time_of_day` while a cycle is running is a
## write the next frame silently undoes.
static func set_hour(fraction: float) -> void:
	clock_mode = CLOCK_FIXED
	time_of_day = fposmod(fraction, 1.0)


## The debug slider, if it is holding one.
##
## Read at the point of use, the way every other knob in this project is, rather
## than pushed in from wherever the overlay lives — so dragging it lights the
## next frame and letting go hands the day back to whatever mode was running.
## Below zero means "not holding it", which is the default.
static func _knob_hour() -> float:
	return Debug.knob("hour")


## Advance the hour if anything is driving it. Called from the accessors rather
## than from a _process somewhere, so this file stays a RefCounted with no node
## to own it and a build that never draws the world never asks the OS the time.
static func _advance() -> void:
	# The debug slider wins while it is being held. Checked here rather than
	# pushed in from the overlay, so dragging it lights the next frame and
	# letting go hands the day straight back to whatever mode was running —
	# without the slider having to know what that was.
	var held := _knob_hour()
	if held >= 0.0:
		time_of_day = fposmod(held, 1.0)
		return
	if clock_mode == CLOCK_FIXED:
		return
	var now := Time.get_ticks_msec()
	if now - _clock_read_at < CLOCK_TICK_MS:
		return
	_clock_read_at = now
	if clock_mode == CLOCK_LOCAL:
		time_of_day = local_hour()
		return
	if _cycle_origin < 0.0:
		# Anchored, not started from the default. Opening the game at nine in the
		# evening and being handed early morning is the same wrongness as a
		# stopped clock, only harder to notice.
		_cycle_origin = local_hour() - float(now) * 0.001 / maxf(cycle_seconds, 1.0)
	time_of_day = fposmod(
		_cycle_origin + float(now) * 0.001 / maxf(cycle_seconds, 1.0), 1.0)

## Off switches, both for the "it must degrade" clause and for a settings menu
## later. With `enabled = false` the overlay is not even created.
static var enabled: bool = true

## Anomalies as emitters. A hole in reality that lights nothing looks painted
## on; a cold violet pool under it is the cheapest possible way to say "this is
## not part of the world". Off makes the world exactly as bright as before.
static var anomaly_glow: bool = true
const ANOMALY_COLOUR := Color(0.45, 0.32, 0.95)
## Tiles, at tier 0; grows 0.7 per tier, so 3.2 to 5.0 across the five.
##
## Was 2.4 and +0.5, sized when a portal was a 17-29px decal. The portal is now
## 60-104px of mouth plus a stain reaching 1.33 tiles at tier 0 and 2.31 at tier
## 4 — so most of the old pool fell *inside* the hole and the light stopped
## reading as something the portal was doing to the ground around it.
const ANOMALY_RADIUS := 3.2
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


## --- daylight --------------------------------------------------------------------
##
## WHY THE RAMP ABOVE CANNOT DO THIS, AND WHY IT LOOKED LIKE IT COULD
##
## The ramp was written as a night effect and it is a good one: it takes the art
## away and hands it back. What nobody noticed is that its noon stop is a no-op,
## and a no-op at noon means *midday is whatever the tileset happens to be*. The
## tileset is dark — cold turf, wet slate, brown earth, all of it authored to sit
## under a night overlay — so the whole town measured mean 46 of 255 at eleven in
## the morning against 40 at midnight. Five grey levels between noon and
## midnight. Every screenshot anyone took read as dusk, at every hour, and the
## first thing blamed for it was the lamps.
##
## The lamps were a real fault and a small one. This is the large one, and it is
## not fixable by tuning the ramp: raising the noon mix moves every pixel toward
## one colour, so it brightens and flattens in exactly equal measure. Noon needs
## the opposite — the same spread, higher. See the note on `daylight` in
## assets/shaders/world_light.gdshader for why that has to be an add.
##
## Keep the night alone. Below 0.25 and above 0.76 this term is exactly zero and
## the overlay does what it always did.

## What a full sun adds, as a fraction of white. Sized against the measurement:
## the unlit town is mean 38, and 0.26 of white puts noon at about 104 with the
## art's own contrast intact — a bright day rather than a bleached one.
const DAYLIGHT_LIFT := 0.26

## Sunlight is not white, and here it must not be: an add of pure grey raises
## every channel equally, which desaturates in proportion to how much it lifts,
## and the town came out under a flat haze. Warm enough that the lift itself
## reads as sun on the ground rather than as fog — cold turf goes olive under it
## instead of going grey, which is the tell that decided the number.
const DAYLIGHT_COLOUR := Color(1.0, 0.955, 0.850)

## How much of that is in the sky, keyframed on the hour. Two things are being
## said here that a curve on the sun's elevation could not say on its own:
##
##   * it starts LATE and ends EARLY. At 0.25 the sun is on the horizon and the
##     world is lit by the sky, which is what the blue AMBIENT stop already
##     draws; adding sunlight there would erase the dawn. The lift only starts
##     once the sun is properly up, which is also where AMBIENT starts letting go.
##   * the shoulders are long. The interesting hours are the ones between, and a
##     day that goes dark-to-bright in twenty minutes has no morning in it.
const DAYLIGHT := [
	[0.00, 0.00],
	[0.22, 0.00],   # the last of the true dark
	[0.27, 0.13],   # first light: thin, and the blue AMBIENT stop still owns it
	[0.33, 0.42],
	[0.40, 0.80],   # the light comes up fast through the first two hours
	[0.52, 1.00],   # noon
	[0.62, 0.90],
	[0.68, 0.58],
	[0.74, 0.16],   # the golden hour: AMBIENT is going warm as this lets go
	[0.78, 0.00],   # last light, on the same stop AMBIENT calls dusk
	[1.00, 0.00],
]

## What a lamp is worth at the moment the sky first needs it, against 1.0 in a
## dead-black hour. See _settle().
const LAMP_DUSK := 0.62


## --- what sort of light it is ----------------------------------------------------
##
## WHY A KIND AND NOT A SECOND NUMBER PER PROP
##
## "Fade the lamps out by day" is one rule, and it belongs here so that every
## light-flagged prop inherits it without the art having to remember. But it is
## not true of every light, and the counter-examples are not edge cases — they
## are the three lights the town actually has:
##
##   * a street lamp is lit by somebody at dusk and put out at dawn. In full sun
##     it is a cold lump of brass. This is the one the ramp already meant.
##   * a hearth, a forge, a stove, a campfire is a FIRE. Nobody puts the kitchen
##     range out because the sun came up. It is washed out at noon the way any
##     small source is next to daylight, but it never goes to nothing, and under
##     a roof at midday it is still the brightest thing in the room.
##   * a lit window is not a light at all, it is EVIDENCE OF AN OCCUPANT. It says
##     somebody is home. On at dusk when they come in, banked to one lamp when
##     they go to bed, dark all day when the house is empty — and a street of
##     windows that all behave that way is most of what makes a town read as
##     inhabited rather than as a diorama.
##
## Three behaviours, so three words, declared by the art in the same catalogue
## that already declares radius and colour. The alternative — a `day_gain` float
## on every emitter — pushes the model out to 30 prop entries that would then
## disagree with each other the first time anyone added a lamp.
##
## The vocabulary is reconciled against data/schema.json in both directions by
## tools/validate_data.py, reading the `match` in `gain_for()` below. A fourth
## kind means a fourth arm there and a fourth word in the schema, and the
## validator fails until both exist.

## What a light is if it does not say. "lamp" is the behaviour every emitter in
## the tileset had before kinds existed, so an entry that stays silent renders
## exactly as it did — which is the only safe default for a key being added to a
## contract that already has readers.
const DEFAULT_KIND := "lamp"

## The daylight switch, against the sun's height rather than against the ambient
## ramp — and that split is the fix for the defect this whole section exists for.
##
## The ramp is a *mood*: it is symmetric about noon, it never reaches zero until
## 0.52, and at 0.45 it still reports mix 0.09, which the old single curve turned
## into a quarter-strength lamp. A quarter of a street lamp at a quarter past
## eleven in the morning is exactly the "burning in full sun" tell. The sun's
## elevation is not a mood, it is a fact, and it says plainly that by mid-morning
## there is no lamp on earth competing with it.
##
## So: the ramp keeps saying how DARK it is (which is what separates dusk from
## midnight, and the elevation cannot — it is flat zero all night), and the
## elevation says how much of that the sun takes back. Neither term can do the
## other's job, which is why there are two.
const SUN_WASH_LOW := 0.05     ## below this the sun has lost; lamps burn freely
const SUN_WASH_HIGH := 0.45    ## above this it has won outright

## What a fire is worth once the sun has washed it out completely. Not zero: a
## forge at noon still glows, and a stove in a kitchen is the reason the room is
## not black. Sized so that outdoors at midday it is a warm smudge you have to
## be next to, and indoors — where the wash is suppressed entirely, see below —
## it is untouched.
const FIRE_BY_DAY := 0.35

## When there is somebody behind the window, 0..1. Keyframed on the hour, same
## idiom as AMBIENT above, because "who is home" is a schedule and a schedule is
## a table — writing it as arithmetic would be four smoothsteps nobody could
## read back as a day in a person's life.
const OCCUPIED := [
	[0.00, 0.20],   # the small hours: one lamp left burning at the back
	[0.18, 0.20],
	[0.24, 1.00],   # up before the sun; the kitchen window is the first lit
	[0.34, 1.00],
	[0.42, 0.00],   # out for the day, and the house goes dark behind them
	[0.62, 0.00],
	[0.72, 1.00],   # home, and the whole street comes on within the half hour
	[0.90, 1.00],
	[0.97, 0.20],   # abed
	[1.00, 0.20],
]


## What a lamp is worth at this hour.
##
## The depth-of-night term, and the base every kind is scaled from. Tied to the
## ambient rather than to the clock directly so the two can never disagree: as
## the world stops needing lighting, the lamps stop providing it, and at noon
## (mix 0) this is exactly zero and the whole pass becomes a no-op.
##
## On its own this was never enough — see SUN_WASH_LOW. `gain_for()` is what
## callers with a kind in hand should ask; this is still the honest answer for
## the lights that have no kind because no prop declares them: the anomalies and
## the character's own.
static func lamp_gain() -> float:
	_resample()
	return _cache_gain


## What a light of this kind is worth at this hour, 0..1.
##
## The one place the three behaviours are spelled out, so a prop becomes a fire
## by gaining a word in assets/tiles/tiles.json and nothing else changes.
## tools/validate_data.py reads these arms as the engine's half of the
## `light_kinds` vocabulary; keep them string literals on their own lines.
static func gain_for(kind: String) -> float:
	_resample()
	match kind:
		"lamp":
			return _cache_lamp
		"fire":
			return _cache_fire
		"window":
			return _cache_window
	# A word the manifest invented and this file has never heard of. The
	# validator refuses to let one ship, so reaching here means somebody hand-
	# edited tiles.json — and a lamp that behaves like a lamp is a better answer
	# than a lamp that does not light.
	return _cache_lamp


## The sampled ramp, recomputed only when the hour actually moves. Three calls a
## frame walk this list otherwise, and each one allocated a result to return.
static var _cache_at: float = -1.0
static var _cache_indoors := false
static var _cache_mix: float = 0.0
static var _cache_colour: Color = Color.BLACK
static var _cache_gain: float = 0.0
## The three kinds, resolved with the rest of the ramp rather than on demand.
## `gain_for()` is asked once per emitter per frame and a town corner holds a
## dozen; working the sun's height out a dozen times for a value that changes
## once per clock tick is the same waste the ambient cache was written to stop.
static var _cache_lamp: float = 0.0
static var _cache_fire: float = 0.0
static var _cache_window: float = 0.0
static var _cache_day: Color = Color.BLACK


static func _resample() -> void:
	_advance()
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
	# Two terms, because one could not say both things.
	#
	# The first is the switch: a lamp is worth nothing at noon and the pass is a
	# no-op there, which is what the old single smoothstep(0, 0.34) bought.
	#
	# The second is the one it was missing. That curve reached 1.0 at mix 0.34 and
	# stayed there for the entire dark half of the day, so a lit window at dusk and
	# the same window at midnight were the same window — and they are not. At dusk
	# it is competing with the sky and at midnight it is the only thing in the
	# room. LAMP_DUSK is what a lamp is worth while there is still a sky to lose
	# to; it reaches full only once the sky is gone.
	_cache_gain = smoothstep(0.0, 0.20, _cache_mix) * lerpf(
		LAMP_DUSK, 1.0, smoothstep(0.20, 0.78, _cache_mix))

	# And the third: how much of that the sun takes straight back off again.
	#
	# Zero indoors, deliberately, and this is the "sheltered" term the comment on
	# lamp_gain() used to promise. The sun does not reach under a roof, so a
	# floor lamp and a stove keep burning at noon in a room the ambient has
	# already floored at INTERIOR_MIX — which is the case the very first minute
	# of the game is made of. It is coarse in the same way `indoors` itself is:
	# it is a fact about where the CHARACTER is standing, not about each light,
	# so standing in the house also spares the street lamps outside it. That is
	# the same approximation the whole-frame darkening already makes, and it
	# fails in the same direction — toward the room you are actually looking at.
	var wash := 0.0 if indoors else _wash_at(time_of_day)
	# A lamp somebody lights at dusk and puts out at dawn. The wash IS the
	# switch, and because it is a smoothstep over a stretch of the sun's climb
	# rather than a threshold on the clock, coming on and going out both take a
	# few minutes of game time instead of happening between two frames.
	_cache_lamp = _cache_gain * (1.0 - wash)
	# A fire does not care what time it is. It is still smaller than the sun.
	_cache_fire = _cache_gain * lerpf(1.0, FIRE_BY_DAY, wash)
	# A window is a lamp behind glass that is only lit while somebody is in.
	_cache_window = _cache_lamp * _ramp(OCCUPIED, time_of_day)

	# The sun on the ground. Zero indoors for the same reason the wash is: the
	# roof is between. Without that, the room the run opens in would come up to
	# full daylight at noon with the ambient still floored at INTERIOR_MIX under
	# it, which is a lit room and a dark tint fighting each other.
	var lift := 0.0 if indoors else _ramp(DAYLIGHT, time_of_day) * DAYLIGHT_LIFT
	_cache_day = Color(DAYLIGHT_COLOUR.r * lift, DAYLIGHT_COLOUR.g * lift,
		DAYLIGHT_COLOUR.b * lift)


## Linear sample of a keyframed [time, value] table on the 0..1 day. Sorted, and
## the last stop must repeat the first's value at 1.0 so the day loops.
static func _ramp(table: Array, at: float) -> float:
	var u := fposmod(at, 1.0)
	var previous: Array = table[0]
	for stop in table:
		var entry: Array = stop
		var when: float = float(entry[0])
		if u <= when:
			var was: float = float(previous[0])
			var span: float = maxf(when - was, 0.0001)
			return lerpf(float(previous[1]), float(entry[1]),
				clampf((u - was) / span, 0.0, 1.0))
		previous = entry
	return float(previous[1])


## How thoroughly the sun drowns a small light right now, 0 (not at all) to 1
## (completely). The public form; `_wash_at` is the same curve without a clock
## read, for the ramp that is already holding the hour still.
static func sun_wash() -> float:
	_advance()
	return _wash_at(time_of_day)


static func _wash_at(u: float) -> float:
	return smoothstep(SUN_WASH_LOW, SUN_WASH_HIGH, sin(PI * _arc_at(u)))


## How much of the ambient replaces the art right now, 0..1.
static func ambient_mix() -> float:
	_resample()
	return _cache_mix


## What the unlit world is tinted toward right now.
static func ambient_colour() -> Color:
	_resample()
	return _cache_colour


## What the sun adds to every pixel right now, already scaled by the hour.
## Black outside daylight hours and black indoors, at which point the shader
## line it feeds is an add of zero.
static func daylight() -> Color:
	_resample()
	return _cache_day


## --- the manifest --------------------------------------------------------------
##
## plane value (atlas slot + 1, the same byte the world's prop plane stores) ->
## { radius: float, colour: Color, flicker: float }.
static var _by_plane: Dictionary = {}
## The same for the second prop plane (#83). A candle is on the clutter plane
## because a candle stands ON a table rather than instead of one, and a candle
## that stopped lighting the room the day it moved planes would be a bug with
## no trail back to this file. Separate dictionary because the two planes are
## numbered independently: props 5 and clutter 5 are different things.
static var _by_clutter: Dictionary = {}
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
			_claim(_by_plane, plane, entry["light"])
		if entry.has("shaft"):
			_claim_shaft(plane, entry["shaft"], entry.get("light", {}))

	# Clutter emits light too, but it cannot be an APERTURE: a shaft is the
	# optics of a hole in a wall, and the clutter plane is what lies on the
	# floor in front of one. So lights are read from both planes and shafts
	# from the prop plane only.
	var clutter: Dictionary = (parsed as Dictionary).get("clutter", {})
	for row in clutter.get("list", []):
		if not (row is Dictionary):
			continue
		var entry: Dictionary = row
		if entry.has("light"):
			_claim(_by_clutter, int(entry.get("plane", 0)), entry["light"])


static func _claim(into: Dictionary, plane: int, spec: Variant) -> void:
	if plane <= 0 or not (spec is Dictionary):
		return
	var light: Dictionary = spec
	var radius: float = float(light.get("radius", 0.0))
	if radius <= 0.0:
		return
	into[plane] = {
		"radius": radius,
		"colour": _colour(String(light.get("color", "#FFFFFF"))),
		"flicker": clampf(float(light.get("flicker", 0.0)), 0.0, 1.0),
		# Read as written and resolved at draw time rather than mapped to an
		# enum here: `gain_for()` is the single place that knows what a word
		# means, and an unknown one has to survive as far as that so it can fall
		# back to a lamp instead of failing the load of the whole manifest.
		"kind": String(light.get("kind", DEFAULT_KIND)),
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
	return not (_by_plane.is_empty() and _by_clutter.is_empty())


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
	_sky_at = -1.0


static func index_world(world: HJWorld) -> void:
	if _indexed:
		return
	_indexed = true
	load_manifest()
	if world == null or not world.loaded:
		return
	if _by_plane.is_empty() and _by_clutter.is_empty() and _shaft_by_plane.is_empty():
		return
	var props: PackedByteArray = world.props
	if props.size() != world.w * world.h:
		return
	# Read once outside the loop, and allowed to be empty: an older world file
	# with no clutter plane should light the world it does have rather than
	# refuse to index at all.
	var clutter: PackedByteArray = world.clutter
	var has_clutter := clutter.size() == world.w * world.h
	# Kept so the shaft traces can ask the map where the walls are without every
	# caller having to hand the world back in. The same instance HJWorld.shared()
	# returns; nothing here holds it past invalidate().
	_world = world
	for y in range(world.h):
		var row: int = y * world.w
		for x in range(world.w):
			var plane: int = props[row + x]
			# The clutter byte on the same cell, read here so a cell carrying a
			# stove AND a candle contributes both. Zero on the great majority
			# of cells, and the two zero tests below are what keep this a
			# one-off pass over 65,536 cells rather than 65,536 allocations.
			var lit: int = clutter[row + x] if has_clutter else 0
			if plane == 0 and lit == 0:
				continue
			var cell := Vector2i(x, y)
			var key := Vector2i(x / BUCKET, y / BUCKET)
			if plane != 0:
				var spec: Dictionary = _by_plane.get(plane, {})
				if not spec.is_empty():
					_bucket_light(key, cell, spec)
				var aperture: Dictionary = _shaft_by_plane.get(plane, {})
				if not aperture.is_empty():
					_place_shaft(world, cell, key, aperture)
			if lit != 0:
				var glow: Dictionary = _by_clutter.get(lit, {})
				if not glow.is_empty():
					_bucket_light(key, cell, glow)


static func _bucket_light(key: Vector2i, cell: Vector2i, spec: Dictionary) -> void:
	var entry := {
		"cell": cell,
		"radius": float(spec["radius"]),
		"colour": spec["colour"],
		"flicker": float(spec["flicker"]),
		"phase": phase_for(cell),
		"kind": String(spec["kind"]),
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
	_advance()
	return _arc_at(time_of_day)


## The same curve for an hour handed in, with no clock read.
##
## Split out because the ambient ramp needs the sun from *inside* `_resample()`,
## which has already advanced the clock a few lines earlier — calling the public
## accessor there would advance it a second time in the middle of sampling it,
## and the whole point of the ramp cache is that the hour holds still while it
## is being read.
static func _arc_at(u: float) -> float:
	return clampf((fposmod(u, 1.0) - 0.25) / 0.5, 0.0, 1.0)


## How high the sun stands, 0 on either horizon and 1 at noon.
static func sun_height() -> float:
	return sin(PI * sun_arc())


## What a lit window is worth at noon, against 1.0 at the golden hour.
##
## This was 0.0 and the argument for it was good and the result was wrong. A sun
## at the zenith does not come through a window *sideways* — true — so the curve
## fell to nothing well before noon, which meant that for the eight hours of the
## day a player is most likely to be playing, a room with four windows had no
## light coming through any of them. The whole of "time of day dependent"
## reduced, in practice, to two short windows the stopped clock never reached.
##
## A real room at midday does have a bright patch under the window; it is short
## and steep rather than long and raking, and `sun_reach()` already says so by
## itself. So the hold is what stays, and the *shape* is what changes.
const MIDDAY_HOLD := 0.55


## What a shaft is worth at this hour.
##
## The mirror of `lamp_gain()`, and deliberately the opposite shape. A lamp is
## worth nothing when the sun is up; a shaft is worth nothing when the sun is
## *down*, and least when it is overhead. The curve rises just after sunrise,
## peaks while the sun is low, sags to MIDDAY_HOLD across the middle of the day,
## and comes back before dusk on its own from the same arc — which is why there
## is no separate evening term: an evening shaft through a west window is the
## same phenomenon seen from the other end of the day.
static func shaft_gain() -> float:
	if not shafts:
		return 0.0
	var e := sun_height()
	return smoothstep(0.02, 0.14, e) * lerpf(1.0, MIDDAY_HOLD,
		smoothstep(0.30, 0.72, e))


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


## --- the moon -------------------------------------------------------------------
##
## WHY THE MOON IS A SECOND BODY AND NOT A BLUE SUN
##
## The cheap version of night light is to keep the sun's arc, tint it blue and
## turn it down. It does not read. Three things are wrong with it and each one is
## visible in a single frame:
##
##   * the bearing. Tinting the sun's shaft blue puts the moon wherever the sun
##     is, so at midnight — the hour a moonbeam matters most — there is no sun in
##     the arc at all and the beam simply is not drawn. The moon has to have its
##     own arc across its own half of the day, and then a bearing at any given
##     hour that is nothing like the sun's, for free, because it is a different
##     body on a different clock.
##   * the edge. Sunlight through a mullioned window draws the mullions. Moon
##     light is a twentieth as bright landing on a surface that is already almost
##     black, and the eye reads no frame in it at all — just a pale wash on the
##     floor by the window. So the panes are switched off, the wedge is widened,
##     and the across-profile loses its plateau entirely (see `soft` in
##     world_light.gdshader). That last one is the whole tell: a sun shaft has a
##     bright core with soft shoulders, a moon shaft is soft all the way through.
##   * the colour. Not the warm pane colour the prop declares, cooled — the
##     prop's tint is a fact about *its glass in daylight*. Night gets its own
##     colour outright.
##
## Everything below is the same three-way split the sun uses: the world owns the
## body, the prop owns the aperture, the map owns the geometry. The trace code,
## the bucket index and the shader loop are shared and know nothing about which
## body is in the sky.

## Off switch of its own, so "the shafts are wrong" and "the night is wrong" can
## be bisected separately.
static var moonlight: bool = true

## How bright a full moon is against the golden hour. A twentieth is roughly the
## honest figure and a twentieth is also invisible — the first pass shipped 0.26
## and the difference between moonlight on and moonlight off was a sheen you had
## to be told to look for. This is a beam spread over four times the area of a
## sun shaft, so it needs the level to survive the widening.
const MOON_LEVEL := 0.46

## Cold, and not fully saturated — a moonlit floor is desaturated, not blue.
const MOON_COLOUR := Color(0.63, 0.74, 1.0)

## The beam, against the sun's declared optics for the same aperture.
const MOON_WIDEN := 1.8        ## half-width at the mouth
const MOON_SPREAD := 1.8       ## and how fast it opens further
## The moon's own reach curve, in place of the sun's REACH_LOW/REACH_HIGH.
##
## The sun's arc collapses to 0.45 at the zenith, and applying that to the moon
## made a midnight beam three tiles long — which at this brightness is a smudge
## on the sill and nothing on the floor. A high moon does foreshorten, but it is
## also the only light in the room, so the beam has to be long enough to be a
## beam. Flatter, and never as long as a raking sun.
const MOON_REACH_LOW := 0.95
const MOON_REACH_HIGH := 0.72
## A dim, diffuse source collimates harder toward the aperture's own normal —
## and it is also what stops a moonbeam skimming a wall it can never light.
const MOON_REVEAL := 0.82

## The night half of the day, 0 at moonrise and 1 at moonset. Deliberately the
## same shape as `sun_arc()` half a day out of phase, so the two bodies hand over
## exactly at the horizons and neither is ever in the sky with the other.
static func moon_arc() -> float:
	_advance()
	return clampf(fposmod(time_of_day - 0.75, 1.0) / 0.5, 0.0, 1.0)


static func moon_height() -> float:
	return sin(PI * moon_arc())


static func moon_gain() -> float:
	if not (shafts and moonlight):
		return 0.0
	return smoothstep(0.02, 0.20, moon_height()) * MOON_LEVEL


static func moon_travel() -> Vector2:
	var a := deg_to_rad(lerpf(SUN_FROM, SUN_TO, moon_arc()))
	return Vector2(cos(a), sin(a))


static func moon_reach() -> float:
	return lerpf(MOON_REACH_LOW, MOON_REACH_HIGH, moon_height())


## Offset past every stamp the sun can produce, so the hour the sky changes hands
## invalidates every trace in the world exactly once. Without it a beam traced
## against a 90-degree sun would be reused for a 90-degree moon whose reveal term
## and reach are different.
const MOON_STAMP_BASE := 1000.0

static func moon_stamp() -> float:
	return MOON_STAMP_BASE + round(lerpf(SUN_FROM, SUN_TO, moon_arc()) / TRACE_QUANTUM)


## --- whichever body is up --------------------------------------------------------
##
## The renderer asks the sky, not the sun. One of these is live at a time and
## both are zero for the few minutes either side of a horizon, which is a real
## thing that happens at dawn and is worth not papering over.
##
## Cached, for exactly the reason the ambient ramp is. The first version worked
## these out from `time_of_day` on every call, and the gather asks six of these
## questions a frame — each of which resolved the body, which resolved both
## gains, which is four transcendentals and two smoothsteps apiece. That measured
## 90 microseconds a frame for an answer that changes when the hour does. The
## optics dictionary is worse than that: it was one allocation per frame in a
## file whose every other structure is packed flat to avoid exactly that.
enum { SKY_NONE, SKY_SUN, SKY_MOON }

static var _sky_at: float = -1.0
static var _sky_flags := 0
static var _sky_body: int = SKY_NONE
static var _sky_gain: float = 0.0
static var _sky_travel: Vector2 = Vector2.RIGHT
static var _sky_reach: float = 1.0
static var _sky_stamp: float = 0.0
static var _sky_reveal: float = SUN_REVEAL
## The optics the active body imposes on an aperture's declared ones. Flat
## statics and not a dictionary, for the reason _place_shaft() gives about its
## own entries: these are read once per beam per frame, and five Variant probes
## per beam measured more than the whole rest of the gather.
##
##   widen   multiplies half-width at the mouth
##   spread  multiplies half-width gained per tile
##   bars    0 keeps the aperture's own mullions, 1 erases them
##   soft    0 a cored beam, 1 a wash with no core at all
##   tint    Color.TRANSPARENT means "keep the aperture's own"
static var _sky_widen: float = 1.0
static var _sky_spread: float = 1.0
static var _sky_bars: float = 0.0
static var _sky_soft: float = 0.0
static var _sky_tint: Color = Color.TRANSPARENT


static func _sky_refresh() -> void:
	_advance()
	var flags := (1 if shafts else 0) | (2 if moonlight else 0)
	if is_equal_approx(_sky_at, time_of_day) and _sky_flags == flags:
		return
	_sky_at = time_of_day
	_sky_flags = flags
	var sun := shaft_gain()
	if sun > 0.002:
		_sky_body = SKY_SUN
		_sky_gain = sun
		_sky_travel = sun_travel()
		_sky_reach = sun_reach()
		_sky_stamp = sun_stamp()
		_sky_reveal = SUN_REVEAL
		_sky_widen = 1.0
		_sky_spread = 1.0
		_sky_bars = 0.0
		_sky_soft = 0.0
		_sky_tint = Color.TRANSPARENT
		return
	var moon := moon_gain()
	if moon > 0.002:
		_sky_body = SKY_MOON
		_sky_gain = moon
		_sky_travel = moon_travel()
		_sky_reach = moon_reach()
		_sky_stamp = moon_stamp()
		_sky_reveal = MOON_REVEAL
		_sky_widen = MOON_WIDEN
		_sky_spread = MOON_SPREAD
		_sky_bars = 1.0
		_sky_soft = 1.0
		_sky_tint = MOON_COLOUR
		return
	_sky_body = SKY_NONE
	_sky_gain = 0.0


static func sky_body() -> int:
	_sky_refresh()
	return _sky_body


static func sky_gain() -> float:
	_sky_refresh()
	return _sky_gain


static func sky_travel() -> Vector2:
	_sky_refresh()
	return _sky_travel


static func sky_reach() -> float:
	_sky_refresh()
	return _sky_reach


static func sky_stamp() -> float:
	_sky_refresh()
	return _sky_stamp


static func sky_reveal() -> float:
	_sky_refresh()
	return _sky_reveal


## See _sky_widen and friends. Read once per frame, not once per beam.
static func sky_widen() -> float:
	_sky_refresh()
	return _sky_widen


static func sky_spread() -> float:
	_sky_refresh()
	return _sky_spread


static func sky_bars() -> float:
	_sky_refresh()
	return _sky_bars


static func sky_soft() -> float:
	_sky_refresh()
	return _sky_soft


static func sky_tint() -> Color:
	_sky_refresh()
	return _sky_tint


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
		reach: float, reveal: float = SUN_REVEAL) -> void:
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
		dir = (travel + inward * reveal).normalized()
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
