class_name HJMovePad
extends Control
## A round trackpad: press it, lean away from the middle, and the character
## walks whichever way you leaned. Release and he stops.
##
## The direction is measured from the pad's centre rather than from wherever the
## press landed, because the centre is the only landmark a thumb can find
## without looking — an origin that moves to meet you gives a different answer
## for the same gesture every time.
##
## Snapped, not analogue. The world is a grid, so a continuous heading would
## only be a less accurate way of saying one of four (or eight) things. What the
## radial shape buys over the d-pad is that changing direction is a lean rather
## than a lift-and-re-press.
##
## **Eight-way is a balance change, not only a control change.** A diagonal step
## covers two tiles of ground for one step of budget, so the same journey that
## costs seven steps on four-way costs four on eight-way. See the note in
## HJMoveControls.

signal direction_changed(direction: Vector2i)

## Comparable to the d-pad it replaces (3x84 + 2x8 = 268 across) so switching
## control in Settings does not resize the map underneath.
const SIZE := 260.0
## As a fraction of the radius. Big enough that resting a thumb in the middle is
## a deliberate stop rather than a twitchy compass, small enough that a short
## lean is heard.
const DEADZONE := 0.22

var _eight := false
## "" | "touch" | "mouse" — which input family owns the press in progress.
var _source := ""
var _knob := Vector2.ZERO            ## offset of the finger from the centre, px
var _dir := Vector2i.ZERO


func _init(eight_way: bool = false) -> void:
	_eight = eight_way
	custom_minimum_size = Vector2(SIZE, SIZE)
	# STOP, not PASS: the pad is not inside a scroller, and a lean that strays
	# off the edge must not turn into a page gesture halfway through a walk.
	mouse_filter = Control.MOUSE_FILTER_STOP


func direction() -> Vector2i:
	return _dir


## With `pointing/emulate_touch_from_mouse` on, one press arrives as both a
## touch and a mouse button, and the emulated mouse event arrives *first*. So
## this is the WorldMapScreen rule rather than the TapCard one: **touch always
## wins and may take a live press off the mouse**. The two arrive back to back
## with no motion between them, so the handover costs nothing, and the mouse
## path survives as the desktop fallback rather than as a competitor.
func _gui_input(event: InputEvent) -> void:
	if event is InputEventScreenTouch:
		var touch: InputEventScreenTouch = event
		if touch.pressed:
			_source = "touch"
			_aim(touch.position)
		elif _source == "touch":
			_stop()
		accept_event()
	elif event is InputEventScreenDrag and _source == "touch":
		_aim((event as InputEventScreenDrag).position)
		accept_event()
	elif event is InputEventMouseButton:
		var button: InputEventMouseButton = event
		if button.button_index != MOUSE_BUTTON_LEFT:
			return
		if button.pressed:
			if _source == "":
				_source = "mouse"
				_aim(button.position)
		elif _source == "mouse":
			_stop()
		accept_event()
	elif event is InputEventMouseMotion and _source == "mouse":
		_aim((event as InputEventMouseMotion).position)
		accept_event()


## Let go from anywhere. A release that lands outside the pad still has to stop
## the walk, and MOUSE_EXIT cannot do this job — with touch emulation the press
## itself drops hover, so an exit arrives immediately and the walk would end on
## the first frame. The screen feeds this from a global release handler.
func release() -> void:
	if _source == "":
		return
	_stop()


func _stop() -> void:
	_source = ""
	_knob = Vector2.ZERO
	if _dir != Vector2i.ZERO:
		_dir = Vector2i.ZERO
		direction_changed.emit(_dir)
	queue_redraw()


func _aim(point: Vector2) -> void:
	var radius := minf(size.x, size.y) * 0.5
	var lean := point - size * 0.5
	_knob = lean.limit_length(radius)

	var picked := Vector2i.ZERO
	if lean.length() >= radius * DEADZONE:
		var step := TAU / (8.0 if _eight else 4.0)
		var heading := Vector2.RIGHT.rotated(snappedf(lean.angle(), step))
		picked = Vector2i(roundi(heading.x), roundi(heading.y))
	if picked != _dir:
		_dir = picked
		direction_changed.emit(_dir)
	queue_redraw()


func _draw() -> void:
	var centre := size * 0.5
	var radius := minf(size.x, size.y) * 0.5
	var live := _source != ""

	draw_circle(centre, radius, Palette.ca("panel_alt", 0.9 if live else 0.55))
	draw_arc(centre, radius - 1.0, 0.0, TAU, 48,
		Palette.ca("accent" if live else "line", 0.8), 2.0, true)

	# The directions this pad actually has, as spokes. Four ticks or eight is
	# the whole difference between the two modes, and it is the only way to see
	# which one you are holding before you lean on it.
	var count := 8 if _eight else 4
	for i in range(count):
		var heading := Vector2.RIGHT.rotated(TAU * float(i) / float(count))
		var lit := _dir != Vector2i.ZERO \
			and Vector2i(roundi(heading.x), roundi(heading.y)) == _dir
		draw_line(centre + heading * radius * 0.42, centre + heading * radius * 0.82,
			Palette.ca("accent" if lit else "muted", 0.95 if lit else 0.35),
			4.0 if lit else 2.0, true)

	# The dead middle, drawn so that "resting here means stop" is visible rather
	# than discovered.
	draw_arc(centre, radius * DEADZONE, 0.0, TAU, 24, Palette.ca("line", 0.5), 1.0, true)

	var knob := centre + _knob
	draw_circle(knob, radius * 0.19, Palette.ca("accent" if live else "muted", 0.85))
	draw_arc(knob, radius * 0.19, 0.0, TAU, 24, Palette.ca("bg", 0.7), 2.0, true)
