class_name HJLightOverlay
extends Control
## The one quad that carries the world's light.
##
## A child of the tile renderer rather than part of its _draw, and that is the
## whole reason it exists as a node: a CanvasItem has exactly one material, so
## a shaded pass over the finished frame has to be a *different* CanvasItem.
## Children draw after their parent's entire _draw — the same fact that makes
## props impossible to draw as child nodes is what makes this trivial.
##
## It owns no state of its own. TileWorld hands it a light list in local pixels
## once per frame and it does nothing else.

const SHADER := "res://assets/shaders/world_light.gdshader"

var _material := ShaderMaterial.new()
var _live := false          ## false when the frame is a no-op; skips the draw

## Last values pushed for the uniforms that rarely move. set_shader_parameter is
## a call into the rendering server per parameter, and four of the seven change
## only when the clock does or the control is resized.
var _last_view := Vector2.ZERO
var _last_mix := -1.0
var _last_colour := Color(-1, -1, -1)
var _last_day := Color(-1, -1, -1)

## The frame's shafts, packed the same way the light list is and for the same
## reason — this runs every frame and must not allocate.
##
## Unlike the lights, these are gathered HERE rather than handed over. A lamp is
## a point and the renderer already flattens it to screen pixels; a shaft is a
## direction, a length measured against the walls and a frame to stripe it with,
## and none of that survives being reduced to a circle. See _camera() for the
## one thing this pass needs from the renderer and does not have.
var _spos: PackedVector4Array = PackedVector4Array()   ## xy mouth px, z length px, w gain
var _scol: PackedVector4Array = PackedVector4Array()   ## rgb colour, a half-width px
var _sform: PackedVector4Array = PackedVector4Array()  ## xy direction, z spread, w bars
## 0 a sunbeam, 1 a moonbeam. One value for the frame, not one per beam: there is
## one body in the sky and every shaft in the list came from it.
var _ssoft := 0.0
var _last_soft := -1.0
## The rest of the frame's sky optics. See _gather_shafts().
var _owiden := 1.0
var _ospread := 1.0
var _obars := 1.0
var _otint := Color.TRANSPARENT
var _scount := 0
var _last_scount := -1
var _warned := false
## Cached reach of the longest declared aperture; -1 means none is declared.
var _margin := 0


func _init() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_preset(Control.PRESET_FULL_RECT)
	var shader: Shader = load(SHADER)
	if shader == null:
		push_warning("HJLightOverlay: %s missing — the world will render unlit" % SHADER)
		return
	_material.shader = shader
	material = _material
	_material.set_shader_parameter("glow", HJLighting.GLOW)
	_spos.resize(HJLighting.MAX_SHAFTS)
	_scol.resize(HJLighting.MAX_SHAFTS)
	_sform.resize(HJLighting.MAX_SHAFTS)
	# The quad only has to be re-issued when the rect changes or the whole pass
	# switches on and off. Uniforms are read at render time, so pushing a light
	# list does not need a redraw — asking for one every frame would rebuild the
	# canvas command list sixty times a second to draw the same rectangle.
	resized.connect(queue_redraw)


func has_shader() -> bool:
	return _material.shader != null


## Called once per frame by the renderer. `count` says how many of the packed
## slots are live; the rest are stale and the shader never reads them.
## `cam` is the renderer's camera offset in local pixels and `scale` its pixels
## per tile — the projection the shaft pass works in. Both optional and last, so
## the existing four-argument call still compiles; see _projection() for what
## happens when they are not passed and why that is a stopgap.
func submit(positions: PackedVector4Array, colours: PackedVector4Array,
		count: int, view: Vector2, cam: Vector2 = Vector2.INF,
		scale: float = 0.0) -> void:
	if not has_shader():
		return
	var mix := HJLighting.ambient_mix()
	var day := HJLighting.daylight()
	_gather_shafts(view, cam, scale)
	# Nothing to darken, nothing to light and no sun to add. Skip the fill
	# entirely rather than drawing a transparent quad — at the two minutes either
	# side of sunrise, in a world whose tileset declares no lamps, this system
	# must cost exactly nothing.
	#
	# `day` is in the test because it is the one term that is at its LARGEST when
	# the other two are at zero: leaving it out meant the overlay switched itself
	# off at precisely the hour the daylight lift was supposed to be doing all
	# the work, and midday came out unlit.
	var live := count > 0 or _scount > 0 or mix > 0.0005 or day.r > 0.0005
	if live != _live:
		_live = live
		queue_redraw()
	if not live:
		return

	if view != _last_view:
		_last_view = view
		_material.set_shader_parameter("view_size", view)
	if not is_equal_approx(mix, _last_mix):
		_last_mix = mix
		_material.set_shader_parameter("ambient_mix", mix)
	var colour := HJLighting.ambient_colour()
	if colour != _last_colour:
		_last_colour = colour
		_material.set_shader_parameter("ambient_colour", colour)
	# Pushed as a Vector3 rather than a Color: the uniform is a vec3 and handing
	# a Color to a vec3 costs a conversion in the rendering server every time it
	# moves, which for a value that changes on every clock tick is worth the one
	# line here.
	if day != _last_day:
		_last_day = day
		_material.set_shader_parameter("daylight", Vector3(day.r, day.g, day.b))

	_material.set_shader_parameter("light_count", count)
	if count > 0:
		_material.set_shader_parameter("light_pos", positions)
		_material.set_shader_parameter("light_col", colours)

	# The count is pushed only when it moves, so a tileset that declares no
	# aperture never touches these uniforms at all: shaft_count keeps the 0 it
	# was compiled with and the fragment loop breaks on its first test.
	if _scount != _last_scount:
		_last_scount = _scount
		_material.set_shader_parameter("shaft_count", _scount)
	if _scount > 0:
		_material.set_shader_parameter("shaft_pos", _spos)
		_material.set_shader_parameter("shaft_col", _scol)
		_material.set_shader_parameter("shaft_form", _sform)
		if not is_equal_approx(_ssoft, _last_soft):
			_last_soft = _ssoft
			_material.set_shader_parameter("shaft_soft", _ssoft)


func _draw() -> void:
	if _live and has_shader():
		draw_rect(Rect2(Vector2.ZERO, size), Color.WHITE)


## --- shafts --------------------------------------------------------------------

## Every aperture that can throw light into the view, packed for the shader.
##
## Culling is the same shape as the light gather: HJLighting buckets the
## apertures once at load, this touches the buckets the view overlaps, and the
## rest is arithmetic on the handful that survive. The trace down each beam is
## refreshed here rather than on a timer so an aperture nobody can see never
## pays for one.
func _gather_shafts(view: Vector2, given: Vector2, given_scale: float) -> void:
	_scount = 0
	if not HJLighting.shafts or view.x <= 0.0 or view.y <= 0.0:
		return
	# Whichever body is in the sky, if either is. `sky_gain()` is the sun's gain
	# by day and the moon's by night, and it is zero for the few minutes either
	# side of a horizon when neither is up — at which point nothing below runs and
	# the pass costs what it did before shafts existed.
	var gain := HJLighting.sky_gain()
	if gain <= 0.002:
		return
	# Cached rather than asked for: the reach of the longest aperture in the
	# tileset is a fact about the manifest, and -1 also stands in for "no
	# aperture is declared at all", which is the whole degrade path.
	if _margin == 0:
		_margin = HJLighting.shaft_margin_tiles() if HJLighting.any_shafts() else -1
	if _margin < 0:
		return
	var scale := given_scale if given_scale > 0.0 else _scale()
	if scale <= 0.0:
		_complain()
		return
	var cam := given if given.x < INF else _camera(view, scale)
	if cam.x >= INF:
		return

	var margin := _margin
	var from := Vector2i(
		maxi(0, int(floor(cam.x / scale)) - margin),
		maxi(0, int(floor(cam.y / scale)) - margin))
	var to := Vector2i(
		maxi(0, int(ceil((cam.x + view.x) / scale)) + margin),
		maxi(0, int(ceil((cam.y + view.y) / scale)) + margin))

	# The traces are only re-run when the sun has actually moved, and that is one
	# comparison for the whole world rather than one per aperture: a player
	# walking round a house at a fixed hour never enters the branch.
	var stamp := HJLighting.sky_stamp()
	var stale := HJLighting.shafts_are_stale(stamp)
	var travel := HJLighting.sky_travel()
	var reach := HJLighting.sky_reach()
	var reveal := HJLighting.sky_reveal()
	# What the body in the sky does to an aperture's declared optics. Read once
	# for the frame rather than per beam: it is a fact about the hour.
	#
	# Members rather than arguments, the same call _light_pass() makes about its
	# two motion terms: _emit_shaft runs once per beam and threading five more
	# floats through it costs more to pass than the widening costs to apply.
	_ssoft = HJLighting.sky_soft()
	_owiden = HJLighting.sky_widen()
	_ospread = HJLighting.sky_spread()
	_obars = 1.0 - HJLighting.sky_bars()
	_otint = HJLighting.sky_tint()
	for bucket in HJLighting.shaft_buckets_over(from, to):
		for source in bucket:
			var entry: Dictionary = source
			if stale:
				HJLighting.refresh_shaft(entry, stamp, travel, reach, reveal)
			# The beam's own tile box against the view, before any float touches
			# it. A bucket is sixteen tiles square and most of what one hands
			# back throws its light somewhere the player cannot see.
			var lo: Vector2i = entry["lo"]
			var hi: Vector2i = entry["hi"]
			if hi.x < from.x or hi.y < from.y or lo.x > to.x or lo.y > to.y:
				continue
			_emit_shaft(entry, cam, scale, gain, view)


## One aperture: tiles to overlay pixels, a cull, and one slot filled.
func _emit_shaft(entry: Dictionary, cam: Vector2, scale: float, gain: float,
		view: Vector2) -> void:
	var span := float(entry["span"])
	if span <= 0.0:
		return
	var strength := gain * float(entry["gate"]) * float(entry["gain"])
	if strength <= 0.004:
		return

	var cell: Vector2i = entry["cell"]
	var dir: Vector2 = entry["dir"]
	# The beam starts where it leaves the masonry, not at the middle of the wall
	# cell — otherwise its first tile is drawn inside the wall it came through.
	var lead: Vector2 = entry["from"]
	var mouth := (Vector2(cell) + Vector2(0.5, 0.5) + lead) * scale - cam
	var length := span * scale
	# The aperture's declared optics, as the body in the sky has them. A window is
	# the same hole at midnight as at noon; what changes is the light going
	# through it, so the widening lives here and not in the manifest.
	var half := float(entry["half"]) * _owiden * scale
	var spread := float(entry["spread"]) * _ospread
	# Panes. A moon draws no mullions — at this little light on a floor this dark
	# the eye reads a wash, not a frame, and drawn bars read as banding.
	var bars := float(entry["bars"]) * _obars

	# Off screen by more than its own reach. The bucket hands back everything
	# within sixteen tiles and a beam is a segment, so this is the segment's box
	# grown by the widest the beam ever gets.
	var tip := mouth + dir * length
	var pad := half + length * spread
	if maxf(mouth.x, tip.x) + pad < 0.0 or maxf(mouth.y, tip.y) + pad < 0.0 \
			or minf(mouth.x, tip.x) - pad > view.x \
			or minf(mouth.y, tip.y) - pad > view.y:
		return

	var slot := _scount
	if slot >= HJLighting.MAX_SHAFTS:
		# Full. Drop whichever beam starts furthest from the middle of the view,
		# for the same reason the light list does: the one the player is standing
		# in is the one that must survive.
		var centre := view * 0.5
		var worst := -1
		var worst_d := mouth.distance_squared_to(centre)
		for i in range(HJLighting.MAX_SHAFTS):
			var d: float = Vector2(_spos[i].x, _spos[i].y).distance_squared_to(centre)
			if d > worst_d:
				worst_d = d
				worst = i
		if worst < 0:
			return
		slot = worst
	else:
		_scount += 1

	# Night gets its own colour outright rather than the aperture's cooled down.
	# The prop's `color` is a fact about its glass in daylight; a moonlit floor is
	# not that colour dimmed, it is a different colour.
	var tint: Color = entry["tint"]
	if _otint.a > 0.0:
		tint = _otint
	_spos[slot] = Vector4(mouth.x, mouth.y, length, strength)
	_scol[slot] = Vector4(tint.r, tint.g, tint.b, half)
	_sform[slot] = Vector4(dir.x, dir.y, spread, bars)


## --- the projection -------------------------------------------------------------
##
## SEAM — and the one thing this pass wants from HJTileWorld. submit() takes the
## camera offset and the tile scale as optional last arguments, so the fix is
## two words at the single call site in _light_pass():
##
##     _light.submit(_lpos, _lcol, _lcount, size, cam, scale)
##
## and everything below here is then dead code and should go with it.
##
## Why it is needed at all: a lamp reaches the overlay already flattened to
## screen pixels, because a circle survives that. A beam does not — it has a
## bearing, a length measured against the walls it is going to hit, and a frame
## to stripe it with, all of which are facts about the map. So the pass has to
## work in world space, and it needs the two numbers that map world space onto
## this quad.
##
## Reading them back off the renderer is a second copy of a rule, which is
## precisely what this codebase keeps saying not to do, and a copy that would
## drift in silence. Two things keep it honest until the seam is wired:
##
##   * the constants are READ from the renderer's own script rather than copied
##     into this file, so TILE and ZOOM cannot disagree. Reflection rather than
##     `HJTileWorld.TILE` on purpose: naming the class here would make the
##     overlay depend on the renderer that owns it, which is a cycle, and it
##     would drag the renderer's own dependencies — Steps, Critters, Content —
##     into anything that wants to draw a lit quad.
##   * the camera rule is guarded, not assumed. If the renderer stops offering
##     `_character_px()` the shafts switch off and say so once, rather than
##     drawing themselves in the wrong place.
var _tile := 0.0
var _zoom := 0.0


## Pixels per tile on screen, read from the renderer's own constants.
func _scale() -> float:
	if _tile > 0.0:
		return _tile * _zoom
	var parent := get_parent()
	if parent == null:
		return 0.0
	var script := parent.get_script() as Script
	if script == null:
		return 0.0
	var consts: Dictionary = script.get_script_constant_map()
	_tile = float(consts.get("TILE", 0.0))
	_zoom = float(consts.get("ZOOM", 0.0))
	return _tile * _zoom


## The camera offset, recomputed from the same three facts the renderer uses:
## where the character is, how big the view is, how big the map is.
func _camera(view: Vector2, scale: float) -> Vector2:
	var parent := get_parent()
	if parent == null or not parent.has_method("_character_px"):
		_complain()
		return Vector2.INF
	var world := HJWorld.shared()
	if world == null or not world.loaded:
		return Vector2.INF
	var extent := Vector2(world.w, world.h) * scale
	var focus: Vector2 = (Vector2(parent.call("_character_px"))
		+ Vector2(_tile, _tile) * 0.5) * _zoom
	var cam := focus - view * 0.5
	cam.x = clampf(cam.x, 0.0, maxf(0.0, extent.x - view.x))
	cam.y = clampf(cam.y, 0.0, maxf(0.0, extent.y - view.y))
	if extent.x < view.x:
		cam.x = -(view.x - extent.x) * 0.5
	if extent.y < view.y:
		cam.y = -(view.y - extent.y) * 0.5
	return cam


## Said once, not once a frame. Losing the shafts is worth a line in the log;
## sixty lines a second is worth nothing.
func _complain() -> void:
	if _warned:
		return
	_warned = true
	push_warning("HJLightOverlay: the renderer offers no projection — light "
		+ "shafts are off. Pass `cam` and `scale` to submit().")


## How many shafts the last frame packed. For harnesses and the debug overlay;
## the renderer does not need it.
func shaft_count() -> int:
	return _scount
