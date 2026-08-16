class_name HJMotes
extends Control
## Dust in the air, drifting up through the light.
##
## Idle motion is what separates a place from a picture of one. This is the
## cheapest honest version: a couple of dozen specks that rise slowly and sway,
## drawn straight to the canvas. No particle system, no texture, no payload.
##
## They fade in at the bottom and out at the top, so a mote never pops.

const COUNT := 22
const RISE := 11.0          ## px per second upward
const SWAY := 14.0          ## px of horizontal wander
const DRAW_HZ := 20.0       ## repaint rate; motes move slowly enough not to need 60

var _seeds: Array[float] = []
var _time := 0.0
var _since_draw := 0.0
var _colour := Color(1, 1, 1, 0.5)


func _init(colour: Color = Color(1, 1, 1, 0.5)) -> void:
	_colour = colour
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_preset(Control.PRESET_FULL_RECT)
	for i in range(COUNT):
		_seeds.append(float(i) * 0.6180339887)


func _process(delta: float) -> void:
	_time += delta
	_since_draw += delta
	if _since_draw < 1.0 / DRAW_HZ:
		return
	_since_draw = 0.0
	queue_redraw()


func _draw() -> void:
	var view := size
	if view.x <= 0.0 or view.y <= 0.0:
		return
	for i in range(COUNT):
		var seed_value := _seeds[i]
		var span := view.y + 120.0
		# Each mote has its own speed so they never form ranks.
		var rate := RISE * (0.55 + fmod(seed_value * 7.3, 1.0))
		var y := view.y - fmod(_time * rate + seed_value * span, span)
		var x := fmod(seed_value * 9973.0, view.x) \
			+ sin(_time * (0.25 + fmod(seed_value * 3.1, 0.4)) + seed_value * 40.0) * SWAY
		if y < -20.0 or y > view.y + 20.0:
			continue

		# Fade at both ends of the travel so nothing appears or vanishes abruptly.
		var edge := minf(1.0, minf(y, view.y - y) / 90.0)
		var twinkle := 0.55 + 0.45 * sin(_time * 1.6 + seed_value * 22.0)
		var c := _colour
		c.a *= edge * twinkle
		if c.a <= 0.01:
			continue
		var radius := 1.5 + fmod(seed_value * 5.0, 1.0)
		draw_circle(Vector2(x, y), radius, c)
