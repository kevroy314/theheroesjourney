class_name HJMotion
extends RefCounted
## Idle motion: what moves in the world when nothing is happening.
##
## `docs/AESTHETIC-EDA.md` puts this first on the liveness list, and it is the
## only item on it with no implementation: *static sprites make a world feel
## paused*. The overworld was still apart from the player, and a still world
## reads as a screenshot of a world.
##
## Two halves, deliberately kept apart from the renderer, exactly as HJLighting
## is:
##
##   * a **contract a prop kind may declare**, read out of the tileset manifest
##     rather than hardcoded, so the next thing that sways is a data change and
##     not a patch to the draw loop;
##
##   * the **wave arithmetic** — one function per motion, per source, per frame,
##     with the phase derived from the cell so nothing is ever in lockstep.
##
## The contract a prop entry may carry, beside the `light` block #49 added:
##
##     "sway": { "amount": 1.6, "speed": 1.05 }
##     "sway": { "amount": 0.8, "speed": 2.4, "mode": "breathe" }
##
##   amount  world pixels the *tip* travels either side of rest. The profile
##           below normalises it against the sprite's real height, so the same
##           number means the same visible lean on a tuft of grass and on a
##           tree.
##   speed   cycles per second.
##   mode    "sway" (default) bends horizontally about the base, and `amount` is
##           sideways travel. "breathe" stretches vertically about the base with
##           no lean at all, and `amount` is how far the tip rises — which is
##           what a flame does and what a candlestick must not do.
##
## Absent, the prop is drawn by exactly the code path it was drawn by before any
## of this existed — one `draw_texture_rect_region`, no transform, no arithmetic.
##
## WHY THE PHASE IS A HASH OF THE CELL. Synchronised sway does not read as wind,
## it reads as a fault in the display — worse than stillness, because stillness
## at least reads as a decision. Every source's phase comes from where it
## stands, so it keeps its own rhythm as you walk past it and two tufts side by
## side never agree. The same argument HJLighting.flicker() makes about torches.

const MANIFEST := "res://assets/tiles/tiles.json"

## Layout of props.png. Must match `props` in the manifest; the renderer knows
## the same three numbers and there is no third copy.
const PROP_W := 64
const PROP_H := 96
const PROP_COLS := 8

## Off switch. With `enabled = false` nothing here is consulted and the world is
## as still as it was before the feature existed. The `motion` debug knob is the
## player-facing version of this and is applied as a scale, not a branch — see
## `gain()`.
static var enabled: bool = true

enum { SWAY, BREATHE }

## How many horizontal bands a moving prop is drawn in.
##
## One band is a straight lean: the whole sprite shears about its base, so a
## tree's trunk swings as far as its canopy. Real stalks bend, so the profile is
## quadratic in height — and a quadratic needs subdividing, because a band is
## drawn with one affine transform and an affine transform is a straight line.
##
## Four is where it stops being visible, and the bands share their edge vertices
## exactly (both x and y are functions of the source row alone), so there is no
## seam to hide.
##
## But four is only worth paying for on something tall. A tuft of grass is ten
## pixels from root to tip, and over ten pixels the difference between the
## quadratic and a straight lean is a third of a pixel — while grass is most of
## what is on screen, so this is where the pass's cost actually lives. The count
## is therefore chosen per prop from its measured height in index_atlas().
##
## Fixed per prop rather than per frame on purpose: a band count that changed
## with the amplitude would re-shape the sprite mid-swing, and a shape that pops
## is worse than a shape that is slightly wrong.
const BANDS := 4
const BAND_HEIGHT := 14           ## sprite pixels each band after the first buys


## --- the ambient wind ----------------------------------------------------------
##
## A gust is the thing that makes a field of grass read as weather rather than
## as a screensaver. It is a *travelling* envelope — a slow diagonal wave across
## the map that modulates amplitude — so a gust crosses a meadow instead of
## arriving everywhere at once.
##
## This is the one term that is deliberately shared between props. Shared
## *phase* is the failure mode; shared amplitude with independent phase is what
## wind actually looks like.
const GUST_SPEED := 0.31          ## how fast the front crosses the world
const GUST_WAVELENGTH := 0.17     ## radians per tile along the diagonal
const GUST_FLOOR := 0.58          ## amplitude between gusts; never fully still


## --- water ---------------------------------------------------------------------
##
## Water is 22.9% of the overworld — the largest single surface, and the one
## whose stillness is hardest to forgive, because water is the one material a
## viewer knows for certain is never still.
##
## Named rather than numbered: the renderer resolves these against `order` in
## the manifest, so re-ordering the tileset cannot silently point the shimmer at
## sand.
const SHIMMER_MATERIALS := ["water", "ocean"]

## Glints per water cell. Two is enough for a surface to read as moving and
## keeps the worst case (a viewport that is nothing but sea) at about 140 extra
## rectangles, which is less than the terrain pass already issues.
const GLINTS := 2
const GLINT_SPEED := 0.80         ## crest cycles per second
const GLINT_DRIFT := 1.7          ## world pixels per second the crests travel
const GLINT_WAVELENGTH := Vector2(0.55, 0.85)   ## radians per tile, x and y
## The colour of a crest catching the sky. The water plate is two dithered
## near-blacks with sparse (49, 59, 67) highlights, so a glint is that highlight
## lifted, not a white speck: a white speck on this palette reads as snow.
const GLINT_COLOUR := Color(0.44, 0.55, 0.63)
const GLINT_ALPHA := 0.55


## The `motion` debug knob, which #69 argues is really an accessibility setting.
##
## Applied as a multiplier on every amplitude rather than as a branch, so there
## is exactly one place it can be forgotten and it cannot half-apply: at zero
## every wave below evaluates to zero, every prop takes the untransformed draw
## path, and the world is precisely as still as it was before this file existed.
static func gain() -> float:
	if not enabled:
		return 0.0
	return clampf(Debug.knob("motion"), 0.0, 1.0)


## --- the manifest --------------------------------------------------------------
##
## plane value (atlas slot + 1, the same byte the world's prop plane stores) ->
## { mode: int, amount: float, speed: float, top: int, base: int }.
static var _by_plane: Dictionary = {}
static var _shimmer_ids: Dictionary = {}    ## material id -> true
static var _read := false


static func load_manifest() -> void:
	if _read:
		return
	_read = true
	var file := FileAccess.open(MANIFEST, FileAccess.READ)
	if file == null:
		return                      # no tileset, no motion, no complaint
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	file.close()
	if not (parsed is Dictionary):
		return
	var doc: Dictionary = parsed

	var order: Array = doc.get("order", [])
	for name in SHIMMER_MATERIALS:
		var id := order.find(name)
		if id >= 0:
			_shimmer_ids[id] = true

	var props: Dictionary = doc.get("props", {})
	for row in props.get("list", []):
		if not (row is Dictionary):
			continue
		var entry: Dictionary = row
		if entry.has("sway"):
			_claim(int(entry.get("plane", 0)), entry["sway"])


static func _claim(plane: int, spec: Variant) -> void:
	if plane <= 0 or not (spec is Dictionary):
		return
	var sway: Dictionary = spec
	var amount: float = float(sway.get("amount", 0.0))
	var speed: float = float(sway.get("speed", 0.0))
	if amount <= 0.0 or speed <= 0.0:
		return
	_by_plane[plane] = {
		"mode": BREATHE if String(sway.get("mode", "sway")) == "breathe" else SWAY,
		"amount": amount,
		"speed": speed,
		# Filled in by index_atlas(). Until then the whole frame is assumed to
		# be art, which is wrong but harmless — it under-bends rather than
		# tearing anything.
		"top": 0,
		"base": PROP_H,
		"bands": BANDS,
	}


static func any() -> bool:
	load_manifest()
	return not _by_plane.is_empty()


## The motion a prop plane declares, or an empty dictionary. Hot: called once
## per visible prop per frame, so it is a single hash lookup and nothing else.
static func for_plane(plane: int) -> Dictionary:
	return _by_plane.get(plane, {})


static func shimmers(material: int) -> bool:
	return _shimmer_ids.has(material)


## --- how tall is it, actually --------------------------------------------------
##
## A prop is a 64x96 frame and almost none of it is art: a tuft of grass is
## twenty pixels standing on the bottom edge, and a tree is fifty-five. If the
## bend profile ran over the frame instead of over the sprite, `amount` would
## mean something different for every prop and every entry in the manifest would
## have to be hand-tuned against art nobody can see from the JSON.
##
## So the atlas is measured once, at load, and only for the planes that declare
## motion — forty-odd `get_region` + `get_used_rect` pairs, both of which are
## native. That is the "amplitude scaled by how tall the prop is" the issue asks
## for, derived rather than authored.
##
## Degrades: if the image cannot be read back (a driver that will not hand back
## a compressed texture), every prop keeps the whole-frame default and still
## moves, just less.
static var _scanned := false


static func index_atlas(atlas: Texture2D) -> void:
	if _scanned:
		return
	_scanned = true
	load_manifest()
	if _by_plane.is_empty() or atlas == null:
		return
	var img := atlas.get_image()
	if img == null:
		return
	if img.is_compressed() and img.decompress() != OK:
		return
	for plane in _by_plane:
		var slot: int = int(plane) - 1
		var frame := Rect2i((slot % PROP_COLS) * PROP_W, (slot / PROP_COLS) * PROP_H,
			PROP_W, PROP_H)
		if frame.position.y + PROP_H > img.get_height():
			continue
		var used := img.get_region(frame).get_used_rect()
		if used.size.y <= 1:
			continue                # empty slot, or a single row: nothing to bend
		var spec: Dictionary = _by_plane[plane]
		spec["top"] = used.position.y
		spec["base"] = used.position.y + used.size.y
		spec["bands"] = clampi(used.size.y / BAND_HEIGHT + 1, 1, BANDS)


## Call after the tileset is regenerated; nothing does yet.
static func invalidate() -> void:
	_read = false
	_scanned = false
	_by_plane.clear()
	_shimmer_ids.clear()


## --- the waves -----------------------------------------------------------------

## A stable per-cell phase in radians.
##
## Its own salt rather than HJLighting.phase_for()'s, so a flickering lamp and a
## swaying bush standing on the same cell do not share a heartbeat.
static func phase_for(cell: Vector2i) -> float:
	var h := absi((cell.x * 374761393) ^ (cell.y * 668265263) ^ 0x5F3A7)
	return float(h % 62831) * 0.0001


## The travelling amplitude envelope, 0.58..1.0.
static func gust(cell: Vector2i, t: float) -> float:
	var front := t * GUST_SPEED - float(cell.x + cell.y) * GUST_WAVELENGTH
	return GUST_FLOOR + (1.0 - GUST_FLOOR) * (0.5 + 0.5 * sin(front))


## Signed displacement of the tip, in world pixels.
##
## Two harmonics rather than one: a single sine is a metronome, and the ear
## hears it in the eye. The second is deliberately not an integer multiple, so
## the pair never repeats over any interval a player would sit and watch.
static func sway(cell: Vector2i, spec: Dictionary, t: float, knob: float) -> float:
	if int(spec["mode"]) != SWAY:
		return 0.0
	var amount: float = float(spec["amount"]) * knob
	if amount <= 0.0:
		return 0.0
	var a := t * float(spec["speed"]) * TAU + phase_for(cell)
	var wave := sin(a) * 0.78 + sin(a * 2.31 + 1.7) * 0.22
	return amount * wave * gust(cell, t)


## Vertical travel of the tip, in world pixels. Zero unless the prop breathes.
##
## A flame is not a metronome, so this is three rates, none of them a multiple
## of another: it gutters rather than pulsing. There is deliberately no bob
## term — the whole thing is a stretch anchored at the base, because a candle
## that rises off the table is a levitating candle, and no gust term, because a
## flame in a room is not weather.
##
## And no horizontal lean: BREATHE is what the flame does, and the candlestick
## under it is not supposed to be waving about.
static func breathe(cell: Vector2i, spec: Dictionary, t: float, knob: float) -> float:
	if int(spec["mode"]) != BREATHE:
		return 0.0
	var amount: float = float(spec["amount"]) * knob
	if amount <= 0.0:
		return 0.0
	var a := t * float(spec["speed"]) * TAU + phase_for(cell)
	return amount * (sin(a) * 0.55 + sin(a * 2.13 + 1.1) * 0.30
		+ sin(a * 3.71 + 4.2) * 0.15)


## One glint on one water cell: where it is inside the tile, how wide, and how
## bright. Returns (x, y, width, alpha) in world pixels; alpha 0 means the crest
## is on its way back down and nothing should be drawn.
##
## The phase is a diagonal function of the cell plus a per-glint jitter, so
## crests arrive as a front crossing the sea rather than as every cell twinkling
## independently — the same argument as the gust, for the same reason.
static func glint(x: int, y: int, i: int, t: float, tile: int) -> Vector4:
	var h := absi((x * 73856093) ^ (y * 19349663) ^ ((i + 1) * 83492791))
	var jitter := float(h % 997) * 0.0063
	var swell := sin(t * GLINT_SPEED * TAU - (float(x) * GLINT_WAVELENGTH.x
		+ float(y) * GLINT_WAVELENGTH.y) + jitter)
	if swell <= 0.0:
		return Vector4.ZERO
	swell = swell * swell
	var span := float(tile)
	var gx := float(h % 23)
	var gy := fposmod(float((h / 23) % 29) + t * GLINT_DRIFT, span - 1.0)
	var wide := 3.0 + 4.0 * swell
	if gx + wide > span:
		wide = span - gx
	return Vector4(gx, gy, wide, swell * GLINT_ALPHA)
