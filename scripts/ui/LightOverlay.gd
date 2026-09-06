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
	# The quad only has to be re-issued when the rect changes or the whole pass
	# switches on and off. Uniforms are read at render time, so pushing a light
	# list does not need a redraw — asking for one every frame would rebuild the
	# canvas command list sixty times a second to draw the same rectangle.
	resized.connect(queue_redraw)


func has_shader() -> bool:
	return _material.shader != null


## Called once per frame by the renderer. `count` says how many of the packed
## slots are live; the rest are stale and the shader never reads them.
func submit(positions: PackedVector4Array, colours: PackedVector4Array,
		count: int, view: Vector2) -> void:
	if not has_shader():
		return
	var mix := HJLighting.ambient_mix()
	# Nothing to darken and nothing to light. Skip the fill entirely rather than
	# drawing a transparent quad — at noon in a world whose tileset declares no
	# lamps this system must cost exactly nothing.
	var live := count > 0 or mix > 0.0005
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

	_material.set_shader_parameter("light_count", count)
	if count > 0:
		_material.set_shader_parameter("light_pos", positions)
		_material.set_shader_parameter("light_col", colours)


func _draw() -> void:
	if _live and has_shader():
		draw_rect(Rect2(Vector2.ZERO, size), Color.WHITE)
