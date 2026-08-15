class_name HJUI
extends RefCounted
## Widget builders. Every colour comes from Palette, so a theme swap restyles
## the whole app. Sizes are tuned for a 720x1280 portrait canvas: nothing
## tappable is ever shorter than TAP.

const TAP := 92.0
const PAD := 18
const RADIUS := 14

const FS_TITLE := 54
const FS_HEAD := 34
const FS_BODY := 27
const FS_SMALL := 22
const FS_TINY := 19


## Font sizes pass through the debug ui_scale knob so text size can be tuned on
## the device instead of through a rebuild.
static func fs(size: int) -> int:
	return maxi(9, int(round(size * Debug.knob("ui_scale"))))


static func stylebox(fill: Color, radius: int = RADIUS, border: Color = Color(0, 0, 0, 0), border_w: int = 0) -> StyleBoxFlat:
	var sb := StyleBoxFlat.new()
	sb.bg_color = fill
	sb.corner_radius_top_left = radius
	sb.corner_radius_top_right = radius
	sb.corner_radius_bottom_left = radius
	sb.corner_radius_bottom_right = radius
	if border_w > 0:
		sb.border_color = border
		sb.set_border_width_all(border_w)
	sb.content_margin_left = PAD
	sb.content_margin_right = PAD
	sb.content_margin_top = PAD
	sb.content_margin_bottom = PAD
	return sb


static func flat(fill: Color, radius: int = RADIUS, border: Color = Color(0, 0, 0, 0), border_w: int = 0) -> StyleBoxFlat:
	var sb := stylebox(fill, radius, border, border_w)
	sb.content_margin_left = 0
	sb.content_margin_right = 0
	sb.content_margin_top = 0
	sb.content_margin_bottom = 0
	return sb


static func panel(role: String = "panel", border_role: String = "") -> PanelContainer:
	var p := PanelContainer.new()
	var border := Palette.c(border_role) if border_role != "" else Color(0, 0, 0, 0)
	p.add_theme_stylebox_override("panel", stylebox(Palette.ca(role, Debug.knob("panel_opacity")), RADIUS, border, 2 if border_role != "" else 0))
	return p


static func label(text: String, size: int = FS_BODY, role: String = "text", align: int = HORIZONTAL_ALIGNMENT_LEFT) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", fs(size))
	l.add_theme_color_override("font_color", Palette.c(role))
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
	b.focus_mode = Control.FOCUS_NONE
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

	b.add_theme_stylebox_override("normal", stylebox(fill, RADIUS, border, 2))
	b.add_theme_stylebox_override("hover", stylebox(fill.lightened(0.06), RADIUS, border, 2))
	b.add_theme_stylebox_override("pressed", stylebox(fill.darkened(0.15), RADIUS, border, 2))
	b.add_theme_stylebox_override("disabled", stylebox(Palette.ca("panel_alt", 0.5), RADIUS, Palette.ca("line", 0.4), 2))
	b.add_theme_color_override("font_color", fg)
	b.add_theme_color_override("font_hover_color", fg)
	b.add_theme_color_override("font_pressed_color", fg)
	b.add_theme_color_override("font_disabled_color", Palette.ca("muted", 0.45))
	return b


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
	r.color = Palette.ca("line", 0.7)
	r.custom_minimum_size.y = 2
	return r


static func bar(value: float, maximum: float, role: String = "good", height: float = 22.0) -> ProgressBar:
	var p := ProgressBar.new()
	p.max_value = maxf(1.0, maximum)
	p.value = clampf(value, 0.0, p.max_value)
	p.show_percentage = false
	p.custom_minimum_size.y = height
	p.add_theme_stylebox_override("background", flat(Palette.ca("bg", 0.85), 8))
	p.add_theme_stylebox_override("fill", flat(Palette.c(role), 8))
	return p


static func set_bar(p: ProgressBar, value: float, maximum: float, role: String) -> void:
	p.max_value = maxf(1.0, maximum)
	p.value = clampf(value, 0.0, p.max_value)
	p.add_theme_stylebox_override("fill", flat(Palette.c(role), 8))


static func chip(caption: String, value: String, role: String = "accent") -> PanelContainer:
	var p := panel("panel_alt")
	var sb: StyleBoxFlat = p.get_theme_stylebox("panel")
	sb.content_margin_top = 8
	sb.content_margin_bottom = 8
	sb.content_margin_left = 14
	sb.content_margin_right = 14
	var v := vbox(0)
	v.add_child(label(caption.to_upper(), FS_TINY, "muted"))
	var value_label := label(value, FS_BODY, role)
	v.add_child(value_label)
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
			l.add_theme_color_override("font_color", Palette.c(role))


static func scroll() -> ScrollContainer:
	var s := ScrollContainer.new()
	s.size_flags_vertical = Control.SIZE_EXPAND_FILL
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	s.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	s.follow_focus = true
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
## With `pointing/emulate_touch_from_mouse` on, one press arrives as both a touch
## and a mouse event. Arming on release means a single press emits once, whether
## the platform sends one family or both.
class TapCard extends PanelContainer:
	signal tapped

	var _armed := true

	func _gui_input(event: InputEvent) -> void:
		var is_down := false
		var is_up := false
		if event is InputEventScreenTouch:
			is_down = event.pressed
			is_up = not event.pressed
		elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
			is_down = event.pressed
			is_up = not event.pressed
		else:
			return
		accept_event()
		if is_down and _armed:
			_armed = false
			tapped.emit()
		elif is_up:
			_armed = true
