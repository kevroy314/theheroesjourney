class_name HJUI
extends RefCounted
## Widget builders. Every colour comes from Palette, so a theme swap restyles
## the whole app. Sizes are tuned for a 720x1280 portrait canvas: nothing
## tappable is ever shorter than TAP.

const TAP := 92.0
const PAD := 18
const RADIUS := 14

# Pixelify's x-height is 0.45em against the system font's ~0.52, so the same
# nominal size reads noticeably smaller. These are tuned for the pixel face.
const FS_TITLE := 56
const FS_HEAD := 36
const FS_BODY := 29
const FS_SMALL := 25
const FS_TINY := 21


## Font sizes pass through the debug ui_scale knob so text size can be tuned on
## the device instead of through a rebuild.
static func fs(size: int) -> int:
	return maxi(9, int(round(size * Debug.knob("ui_scale"))))


## Opacity for one UI layer: its own knob times the master. "debug" is exempt —
## the tool has to stay readable while it dims everything else.
##
## This is a stopgap for judging art behind the UI. The real answer is a UI that
## belongs to the art rather than sitting on top of it in boxes.
static var building_debug := false


static func alpha_for(kind: String) -> float:
	# The debug panel is the thing doing the dimming, so it never dims itself —
	# an opacity slider you cannot read at low opacity is not a slider.
	if kind == "debug" or building_debug:
		return 1.0
	return clampf(Debug.knob("%s_opacity" % kind) * Debug.knob("ui_opacity"), 0.0, 1.0)


static func tint(colour: Color, kind: String) -> Color:
	return Color(colour.r, colour.g, colour.b, colour.a * alpha_for(kind))


static func stylebox(fill: Color, radius: int = RADIUS, border: Color = Color(0, 0, 0, 0), border_w: int = 0, kind: String = "panel") -> StyleBoxFlat:
	var sb := StyleBoxFlat.new()
	sb.bg_color = tint(fill, kind)
	sb.corner_radius_top_left = radius
	sb.corner_radius_top_right = radius
	sb.corner_radius_bottom_left = radius
	sb.corner_radius_bottom_right = radius
	if border_w > 0:
		sb.border_color = tint(border, "border")
		sb.set_border_width_all(border_w)
	sb.content_margin_left = PAD
	sb.content_margin_right = PAD
	sb.content_margin_top = PAD
	sb.content_margin_bottom = PAD
	return sb


static func flat(fill: Color, radius: int = RADIUS, border: Color = Color(0, 0, 0, 0), border_w: int = 0, kind: String = "panel") -> StyleBoxFlat:
	var sb := stylebox(fill, radius, border, border_w, kind)
	sb.content_margin_left = 0
	sb.content_margin_right = 0
	sb.content_margin_top = 0
	sb.content_margin_bottom = 0
	return sb


static func panel(role: String = "panel", border_role: String = "") -> PanelContainer:
	var p := PanelContainer.new()
	var border := Palette.c(border_role) if border_role != "" else Color(0, 0, 0, 0)
	p.add_theme_stylebox_override("panel", stylebox(Palette.c(role), RADIUS, border, 2 if border_role != "" else 0))
	return p


## The display face is now the default for everything, not just headings.
##
## The earlier split — pixel titles over system-font prose — was the safe call
## and it read as two apps stapled together: a pixel-art room with a settings
## screen laid over it. One face everywhere is the whole point. Knob to 0 to
## compare against the system font.
static func wants_display(_size: int = 0) -> bool:
	return Debug.knob("pixel_font") > 0.5


## Puts the display face on any control that draws text.
static func face(control: Control) -> void:
	if not wants_display():
		return
	var f := Palette.display_font()
	if f != null:
		control.add_theme_font_override("font", f)


static func label(text: String, size: int = FS_BODY, role: String = "text", align: int = HORIZONTAL_ALIGNMENT_LEFT) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", fs(size))
	face(l)
	# Pixel faces set tight by default; prose needs the line to breathe.
	l.add_theme_constant_override("line_spacing", 6)
	l.add_theme_color_override("font_color", tint(Palette.c(role), "text"))
	l.horizontal_alignment = align
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return l


## kind: primary | ghost | danger | quiet
static func button(text: String, kind: String = "ghost", enabled: bool = true) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size.y = TAP
	b.add_theme_font_size_override("font_size", fs(FS_BODY))
	face(b)
	b.focus_mode = Control.FOCUS_NONE
	# STOP would swallow a drag that started on the button and leave lists of
	# buttons unscrollable; PASS keeps the press and lets the scroller pan.
	b.mouse_filter = Control.MOUSE_FILTER_PASS
	b.disabled = not enabled

	var fill := Palette.c("panel_alt")
	var fg := Palette.c("text")
	var border := Palette.c("line")
	match kind:
		"primary":
			fill = Palette.c("accent")
			fg = Palette.c("bg")
			border = Palette.c("accent")
		"danger":
			fill = Palette.ca("danger", 0.18)
			fg = Palette.c("danger")
			border = Palette.ca("danger", 0.7)
		"quiet":
			fill = Palette.ca("panel_alt", 0.0)
			fg = Palette.c("muted")
			border = Palette.ca("line", 0.6)

	b.add_theme_stylebox_override("normal", stylebox(fill, RADIUS, border, 2, "button"))
	b.add_theme_stylebox_override("hover", stylebox(fill.lightened(0.06), RADIUS, border, 2, "button"))
	b.add_theme_stylebox_override("pressed", stylebox(fill.darkened(0.15), RADIUS, border, 2, "button"))
	b.add_theme_stylebox_override("disabled", stylebox(Palette.ca("panel_alt", 0.5), RADIUS, Palette.ca("line", 0.4), 2, "button"))
	var caption := tint(fg, "text")
	b.add_theme_color_override("font_color", caption)
	b.add_theme_color_override("font_hover_color", caption)
	b.add_theme_color_override("font_pressed_color", caption)
	b.add_theme_color_override("font_disabled_color", tint(Palette.ca("muted", 0.45), "text"))
	return b


## A pixel icon from assets/icons, tinted by the palette.
##
## Snapped to a multiple of 16 and filtered NEAREST: these are authored on a
## 16-grid, and any other size turns them to mush.
static func icon(id: String, px: int = 32, role: String = "text") -> TextureRect:
	var t := TextureRect.new()
	var path := "res://assets/icons/%s.png" % id
	if ResourceLoader.exists(path):
		t.texture = load(path)
	var snapped := maxi(16, int(round(px / 16.0)) * 16)
	t.custom_minimum_size = Vector2(snapped, snapped)
	t.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	t.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	t.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	t.modulate = tint(Palette.c(role), "text")
	t.mouse_filter = Control.MOUSE_FILTER_IGNORE
	t.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	return t


static func has_icon(id: String) -> bool:
	return id != "" and ResourceLoader.exists("res://assets/icons/%s.png" % id)


## A 9-slice frame from assets/frames, tinted by the palette.
##
## TILE rather than STRETCH: the chalk edge is broken on purpose, and stretching
## it smears the breaks into streaks. Tiling repeats the strokes instead.
static func nine(kind: String, colour: Color) -> NinePatchRect:
	var n := NinePatchRect.new()
	var path := "res://assets/frames/%s.png" % kind
	if ResourceLoader.exists(path):
		n.texture = load(path)
	n.patch_margin_left = 16
	n.patch_margin_right = 16
	n.patch_margin_top = 16
	n.patch_margin_bottom = 16
	n.axis_stretch_horizontal = NinePatchRect.AXIS_STRETCH_MODE_TILE
	n.axis_stretch_vertical = NinePatchRect.AXIS_STRETCH_MODE_TILE
	n.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	n.modulate = colour
	n.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return n


static func vbox(separation: int = 12) -> VBoxContainer:
	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", separation)
	v.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return v


static func hbox(separation: int = 12) -> HBoxContainer:
	var h := HBoxContainer.new()
	h.add_theme_constant_override("separation", separation)
	h.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return h


static func margins(l: int, t: int, r: int, b: int) -> MarginContainer:
	var m := MarginContainer.new()
	m.add_theme_constant_override("margin_left", l)
	m.add_theme_constant_override("margin_top", t)
	m.add_theme_constant_override("margin_right", r)
	m.add_theme_constant_override("margin_bottom", b)
	m.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	m.size_flags_vertical = Control.SIZE_EXPAND_FILL
	return m


static func spacer(height: float = 0.0) -> Control:
	var c := Control.new()
	if height > 0.0:
		c.custom_minimum_size.y = height
	else:
		c.size_flags_vertical = Control.SIZE_EXPAND_FILL
	return c


static func rule() -> ColorRect:
	var r := ColorRect.new()
	r.color = tint(Palette.ca("line", 0.7), "border")
	r.custom_minimum_size.y = 2
	return r


static func bar(value: float, maximum: float, role: String = "good", height: float = 22.0) -> ProgressBar:
	var p := ProgressBar.new()
	p.max_value = maxf(1.0, maximum)
	p.value = clampf(value, 0.0, p.max_value)
	p.show_percentage = false
	p.custom_minimum_size.y = height
	p.add_theme_stylebox_override("background", flat(Palette.ca("bg", 0.85), 8))
	p.add_theme_stylebox_override("fill", flat(Palette.c(role), 8, Color(0, 0, 0, 0), 0, "button"))
	return p


static func set_bar(p: ProgressBar, value: float, maximum: float, role: String) -> void:
	p.max_value = maxf(1.0, maximum)
	p.value = clampf(value, 0.0, p.max_value)
	p.add_theme_stylebox_override("fill", flat(Palette.c(role), 8, Color(0, 0, 0, 0), 0, "button"))


static func chip(caption: String, value: String, role: String = "accent", icon_id: String = "") -> PanelContainer:
	var p := panel("panel_alt")
	var sb: StyleBoxFlat = p.get_theme_stylebox("panel")
	sb.content_margin_top = 8
	sb.content_margin_bottom = 8
	sb.content_margin_left = 12
	sb.content_margin_right = 12
	var v := vbox(0)
	# A chip is a fixed-width cell in a row of them, so a caption long enough to
	# wrap pushes its orphan onto the value line and the chip reads "MOV / E 8".
	# Captions here are one short word by design; clip rather than wrap.
	var cap := label(caption.to_upper(), FS_TINY, "muted")
	cap.autowrap_mode = TextServer.AUTOWRAP_OFF
	cap.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	v.add_child(cap)
	var value_label := label(value, FS_BODY, role)
	v.add_child(value_label)

	# The mark carries the meaning; the caption is there until the mark is learned.
	if has_icon(icon_id):
		var row := hbox(8)
		row.add_child(icon(icon_id, 32, role))
		row.add_child(v)
		p.add_child(row)
	else:
		p.add_child(v)
	p.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	p.set_meta("value_label", value_label)
	return p


static func set_chip(p: PanelContainer, value: String, role: String = "") -> void:
	if p == null or not p.has_meta("value_label"):
		return
	var l: Label = p.get_meta("value_label")
	if is_instance_valid(l):
		l.text = value
		if role != "":
			l.add_theme_color_override("font_color", tint(Palette.c(role), "text"))


static func scroll() -> ScrollContainer:
	var s := ScrollContainer.new()
	s.size_flags_vertical = Control.SIZE_EXPAND_FILL
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	s.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	# follow_focus is for keyboard traversal, which this app does not have. Left
	# on, any control that takes focus on touch yanks the list to it — you scroll,
	# something under your thumb takes focus, and the list snaps back.
	s.follow_focus = false
	return s


## A slider that can live inside a scrolling list.
##
## Godot's Slider grabs the mouse wheel to change its value and takes focus on
## press. In a panel that is mostly sliders, both are fatal: the wheel adjusts
## whatever it is over instead of scrolling, and the focus grab makes the
## scroller jump. Same shape of bug as the cards that would not scroll — a child
## eating the events the scroller needed.
static func slider(min_value: float, max_value: float, step: float, value: float) -> HSlider:
	var s := HSlider.new()
	s.min_value = min_value
	s.max_value = max_value
	s.step = step
	s.value = value
	s.scrollable = false
	s.focus_mode = Control.FOCUS_NONE
	s.custom_minimum_size.y = 52
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return s


static func header(title: String, subtitle: String, on_back: Callable = Callable()) -> PanelContainer:
	var p := panel("panel")
	var v := vbox(6)
	var top := hbox(10)
	top.add_child(label(title, FS_HEAD, "text"))
	if on_back.is_valid():
		var back := button("Back", "quiet")
		back.custom_minimum_size = Vector2(120, 62)
		back.size_flags_horizontal = Control.SIZE_SHRINK_END
		back.pressed.connect(on_back)
		top.add_child(back)
	v.add_child(top)
	if subtitle != "":
		v.add_child(label(subtitle, FS_SMALL, "muted"))
	p.add_child(v)
	return p


static func run_header(title: String, subtitle: String) -> HJRunHeader:
	return HJRunHeader.new(title, subtitle)


## A panel that reports taps — Button cannot hold a multi-line themed layout.
##
## Two things it has to get right, both of which it once got wrong:
##
## 1. It fires on *release*, not press, and only if the pointer barely moved.
##    Firing on press means a finger starting a scroll immediately activates
##    whatever it landed on.
## 2. It does not consume the press or the drag. A ScrollContainer can only pan
##    if the events reach it, so accepting the press here made every list that
##    is covered in cards unscrollable except through the gaps between them.
##
## With `pointing/emulate_touch_from_mouse` on, one press arrives as both a touch
## and a mouse event, so only the family that started a press may finish it.
class TapCard extends PanelContainer:
	signal tapped

	const DRAG_SLOP := 12.0

	func _init() -> void:
		# PASS, not STOP: STOP consumes the event even when _gui_input does not
		# handle it, which stops a ScrollContainer above from ever seeing the
		# drag. This is the whole reason card-covered lists would not scroll.
		mouse_filter = Control.MOUSE_FILTER_PASS

	var _pressing := false
	var _source := ""
	var _travel := 0.0
	var _rest_scale := Vector2.ONE

	## Presses give under the thumb. The card may already be rotated and scaled
	## by whoever built it, so the resting scale is captured rather than assumed.
	func _squash(down: bool) -> void:
		if Debug.knob("motion") <= 0.0:
			return
		if pivot_offset == Vector2.ZERO:
			pivot_offset = size * 0.5
		if down:
			_rest_scale = scale
		var target := _rest_scale * (0.965 if down else 1.0)
		create_tween().tween_property(self, "scale", target, 0.07)

	func _gui_input(event: InputEvent) -> void:
		if event is InputEventScreenTouch:
			_press("touch", event.pressed)
		elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
			_press("mouse", event.pressed)
		elif _pressing and event is InputEventScreenDrag and _source == "touch":
			_travel += event.relative.length()
		elif _pressing and event is InputEventMouseMotion and _source == "mouse":
			_travel += event.relative.length()

	func _press(source: String, is_down: bool) -> void:
		if is_down:
			if _pressing:
				return          # the duplicate from the other input family
			_pressing = true
			_source = source
			_travel = 0.0
			_squash(true)
			return
		if not _pressing or _source != source:
			return
		_pressing = false
		_source = ""
		_squash(false)
		if _travel < DRAG_SLOP:
			# Only a real tap is consumed; a drag is left for the scroller.
			accept_event()
			tapped.emit()
