class_name HJWheel
extends Control
## The Wheel, drawn radially: six spokes, three rings, and a centre that only
## opens when every spoke has moved. A player who only ever trains gets a long
## spike and a locked middle — the shape argues for balance without any copy.

const RING_RADII := [0.30, 0.52, 0.74]
const LABEL_RADIUS := 0.90
const NODE_RADIUS := 11.0


func _init() -> void:
	custom_minimum_size.y = 430
	size_flags_horizontal = Control.SIZE_EXPAND_FILL


func _ready() -> void:
	resized.connect(queue_redraw)
	Events.meta_changed.connect(queue_redraw)


func _draw() -> void:
	var axes := Content.axes()
	if axes.is_empty():
		return
	var centre := size * 0.5
	var span := minf(size.x, size.y) * 0.5

	for r in RING_RADII:
		draw_arc(centre, span * r, 0.0, TAU, 64, Palette.ca("line", 0.35), 1.5, true)

	for axis in axes:
		var angle := deg_to_rad(float(axis.get("angle", 0)))
		var direction := Vector2(cos(angle), sin(angle))
		var reached := Meta.axis_ring(String(axis["id"]))
		draw_line(centre, centre + direction * span * float(RING_RADII[2]), Palette.ca("line", 0.45), 1.5, true)

		for i in range(RING_RADII.size()):
			var point := centre + direction * span * float(RING_RADII[i])
			var earned := reached >= i + 1
			var claimed := Meta.claimed.has("%s_%d" % [axis["id"], i + 1])
			if earned:
				draw_circle(point, NODE_RADIUS, Palette.c("accent") if claimed else Palette.ca("accent", 0.45))
				draw_arc(point, NODE_RADIUS, 0.0, TAU, 24, Palette.c("accent"), 2.5, true)
			else:
				draw_arc(point, NODE_RADIUS, 0.0, TAU, 24, Palette.ca("muted", 0.5), 2.0, true)

		var font := ThemeDB.fallback_font
		var label := String(axis.get("name", "")).to_upper()
		var text_size := font.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, 18)
		var label_point := centre + direction * span * LABEL_RADIUS - text_size * 0.5 + Vector2(0, text_size.y * 0.35)
		draw_string(font, label_point, label, HORIZONTAL_ALIGNMENT_LEFT, -1, 18,
			Palette.c("accent") if reached > 0 else Palette.c("muted"))

	# The centre.
	var open := Meta.wheel_met(Content.achievements.get("centre", {}))
	var claimed_centre := Meta.balance_unlocked()
	if claimed_centre:
		draw_circle(centre, span * 0.16, Palette.ca("accent", 0.25))
	draw_arc(centre, span * 0.16, 0.0, TAU, 48,
		Palette.c("accent") if open else Palette.ca("muted", 0.6), 3.0, true)
	var font2 := ThemeDB.fallback_font
	var word := "BALANCE" if open else "LOCKED"
	var word_size := font2.get_string_size(word, HORIZONTAL_ALIGNMENT_LEFT, -1, 17)
	draw_string(font2, centre - word_size * 0.5 + Vector2(0, word_size.y * 0.35), word,
		HORIZONTAL_ALIGNMENT_LEFT, -1, 17, Palette.c("accent") if open else Palette.c("muted"))
