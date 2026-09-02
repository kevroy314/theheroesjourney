class_name HJDebugOverlay
extends CanvasLayer
## The debug bubble and its panel. Lives above every screen.
##
## The bubble is draggable — press and move to reposition it, press and release
## without moving to open the panel. That distinction is the whole trick: a
## floating control that can be moved out of the way is useless if moving it
## also fires it.

const BUBBLE_SIZE := 78.0
const DRAG_SLOP := 10.0     ## px of movement before a press stops counting as a tap

const SECTIONS := ["Knobs", "God", "Do", "Report"]

var bubble: Bubble
var panel: PanelContainer
var _body: VBoxContainer
var _section := "Knobs"


func _init() -> void:
	layer = 10


func _ready() -> void:
	bubble = Bubble.new()
	bubble.custom_minimum_size = Vector2(BUBBLE_SIZE, BUBBLE_SIZE)
	bubble.size = Vector2(BUBBLE_SIZE, BUBBLE_SIZE)
	bubble.tapped.connect(func(): Debug.set_open(not Debug.open))
	bubble.moved.connect(_on_bubble_moved)
	add_child(bubble)
	_style_bubble()

	Debug.visibility_changed.connect(_sync)
	Events.theme_changed.connect(_restyle)
	get_viewport().size_changed.connect(_clamp_bubble)

	_place_bubble()
	_sync()


func _place_bubble() -> void:
	var view := get_viewport().get_visible_rect().size
	if Debug.bubble_pos.x < 0.0:
		Debug.bubble_pos = Vector2(view.x - BUBBLE_SIZE - 14.0, view.y * 0.42)
	bubble.position = Debug.bubble_pos
	_clamp_bubble()


func _clamp_bubble() -> void:
	var view := get_viewport().get_visible_rect().size
	bubble.position = Vector2(
		clampf(bubble.position.x, 4.0, maxf(4.0, view.x - BUBBLE_SIZE - 4.0)),
		clampf(bubble.position.y, 4.0, maxf(4.0, view.y - BUBBLE_SIZE - 4.0)))


func _on_bubble_moved() -> void:
	_clamp_bubble()
	Debug.bubble_pos = bubble.position
	Debug.save_settings()


func _style_bubble() -> void:
	HJUI.building_debug = true
	var sb := HJUI.flat(Palette.ca("panel_alt", 0.94), int(BUBBLE_SIZE / 2), Palette.c("accent"), 3)
	bubble.add_theme_stylebox_override("panel", sb)
	for child in bubble.get_children():
		bubble.remove_child(child)
		child.queue_free()

	var label := Label.new()
	label.text = "dbg"
	label.add_theme_font_size_override("font_size", 22)
	label.add_theme_color_override("font_color", Palette.c("accent"))
	label.autowrap_mode = TextServer.AUTOWRAP_OFF
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bubble.add_child(label)
	bubble.size = Vector2(BUBBLE_SIZE, BUBBLE_SIZE)
	HJUI.building_debug = false


func _restyle() -> void:
	_style_bubble()
	if Debug.open:
		_build_panel()


func _sync() -> void:
	bubble.visible = Debug.bubble_visible
	if Debug.open:
		_build_panel()
	elif panel != null:
		panel.queue_free()
		panel = null


# --- the panel -----------------------------------------------------------------

func _build_panel() -> void:
	HJUI.building_debug = true
	_build_panel_inner()
	HJUI.building_debug = false


func _build_panel_inner() -> void:
	if panel != null:
		panel.queue_free()
	panel = PanelContainer.new()
	panel.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	panel.offset_top = -int(get_viewport().get_visible_rect().size.y * 0.66)
	panel.offset_left = 8
	panel.offset_right = -8
	panel.offset_bottom = -8
	panel.add_theme_stylebox_override("panel", HJUI.stylebox(Palette.ca("panel", 0.97), 16, Palette.c("accent"), 2))
	add_child(panel)

	var v := HJUI.vbox(10)
	panel.add_child(v)

	var top := HJUI.hbox(10)
	top.add_child(HJUI.label("Debug", HJUI.FS_HEAD, "accent"))
	var close := HJUI.button("Close", "quiet")
	close.custom_minimum_size = Vector2(120, 56)
	close.size_flags_horizontal = Control.SIZE_SHRINK_END
	close.pressed.connect(func(): Debug.set_open(false))
	top.add_child(close)
	v.add_child(top)

	# Sections, not one long roll. All four at once was ~3000px of content in a
	# 570px window: everything was four screens of dragging away from everything
	# else, which is not a debug tool, it is an endurance test.
	var tabs := HJUI.hbox(6)
	for entry in SECTIONS:
		var section := String(entry)
		var t := HJUI.button(section, "primary" if section == _section else "quiet")
		t.custom_minimum_size = Vector2(0, 54)
		t.add_theme_font_size_override("font_size", HJUI.fs(HJUI.FS_SMALL))
		t.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var picked := section
		t.pressed.connect(func() -> void:
			_section = picked
			_build_panel())
		tabs.add_child(t)
	v.add_child(tabs)

	var scroll := HJUI.scroll()
	_body = HJUI.vbox(12)
	scroll.add_child(_body)
	v.add_child(scroll)

	match _section:
		"Knobs": _knobs()
		"God": _god()
		"Do": _actions()
		"Report": _report()


func _knobs() -> void:
	_body.add_child(HJUI.label("KNOBS — read the number, tell me the number", HJUI.FS_TINY, "muted"))
	for def in Debug.KNOBS:
		_body.add_child(_knob_row(def))

	var reset := HJUI.button("Reset knobs", "quiet")
	reset.custom_minimum_size.y = 58
	reset.pressed.connect(func() -> void:
		Debug.reset_knobs()
		Events.theme_changed.emit()
		_build_panel())
	_body.add_child(reset)


func _knob_row(def: Dictionary) -> PanelContainer:
	var id := String(def["id"])
	var card := HJUI.panel("panel_alt")
	var cv := HJUI.vbox(4)

	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(String(def["name"]), HJUI.FS_SMALL, "text"))
	var value_label := HJUI.label("%.2f" % Debug.knob(id), HJUI.FS_BODY, "accent", HORIZONTAL_ALIGNMENT_RIGHT)
	row.add_child(value_label)
	cv.add_child(row)

	var slider := HJUI.slider(float(def["min"]), float(def["max"]),
		float(def.get("step", 0.01)), Debug.knob(id))
	cv.add_child(slider)

	cv.add_child(HJUI.label(String(def.get("hint", "")), HJUI.FS_TINY, "muted"))

	var needs_rebuild: bool = def.get("rebuild", false)
	slider.value_changed.connect(func(value: float) -> void:
		value_label.text = "%.2f" % value
		Debug.set_knob(id, value))
	if needs_rebuild:
		# Rebuilding every screen on every slider frame would stutter; wait for
		# the finger to come off.
		slider.drag_ended.connect(func(_changed: bool) -> void:
			Events.theme_changed.emit()
			_build_panel())

	card.add_child(cv)
	return card


func _god() -> void:
	_body.add_child(HJUI.label("GOD MODE", HJUI.FS_TINY, "muted"))
	var card := HJUI.panel("panel_alt", "warn" if Debug.god else "")
	var cv := HJUI.vbox(8)
	cv.add_child(HJUI.label(
		"Nothing costs anything, everything is unlocked, every Wheel node is claimable."
		if Debug.god else
		"Free purchases, everything unlocked, any screen reachable.",
		HJUI.FS_TINY, "warn" if Debug.god else "muted"))
	var toggle := HJUI.button("Turn god mode off" if Debug.god else "Turn god mode on",
		"primary" if Debug.god else "ghost")
	toggle.custom_minimum_size.y = 66
	toggle.pressed.connect(func() -> void:
		Debug.set_god(not Debug.god)
		_build_panel())
	cv.add_child(toggle)
	card.add_child(cv)
	_body.add_child(card)

	if Debug.god:
		_body.add_child(HJUI.label("JUMP TO SCREEN", HJUI.FS_TINY, "muted"))
		var grid := GridContainer.new()
		grid.columns = 3
		grid.add_theme_constant_override("h_separation", 6)
		grid.add_theme_constant_override("v_separation", 6)
		for name in Debug.SCREENS:
			var b := HJUI.button(String(name), "primary" if Game.screen == name else "ghost")
			b.custom_minimum_size.y = 54
			b.add_theme_font_size_override("font_size", HJUI.FS_TINY)
			b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			var target := String(name)
			b.pressed.connect(func() -> void:
				# Some screens need run state to exist at all; make one first.
				if target in ["area", "task", "boon", "overworld"] and not Game.has_active_run():
					Game.start_run()
				Debug.set_open(false)
				Game.goto(target))
			grid.add_child(b)
		_body.add_child(grid)


func _actions() -> void:
	_body.add_child(HJUI.label("ACTIONS", HJUI.FS_TINY, "muted"))
	var grid := GridContainer.new()
	grid.columns = 2
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)

	var actions := [
		["+100 Resolve", func(): Debug.give_resolve(100)],
		["+200 steps", func(): Steps.grant(200)],
		["Unlock all", func(): Debug.unlock_everything()],
		["Open task gate", func(): Debug.finish_task()],
		["Reveal area", func(): Debug.reveal_area()],
		["+12 hours", func(): Debug.add_hours(12)],
		["Expire deadline", func(): Debug.expire_deadline()],
	]
	for entry in actions:
		var b := HJUI.button(String(entry[0]), "ghost")
		b.custom_minimum_size.y = 62
		b.add_theme_font_size_override("font_size", HJUI.FS_SMALL)
		b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		b.pressed.connect(entry[1])
		grid.add_child(b)
	_body.add_child(grid)

	var hide := HJUI.button("Hide bubble until reload", "quiet")
	hide.custom_minimum_size.y = 58
	hide.pressed.connect(func() -> void:
		Debug.bubble_visible = false
		Debug.set_open(false))
	_body.add_child(hide)


func _report() -> void:
	_body.add_child(HJUI.label("REPORT", HJUI.FS_TINY, "muted"))

	var card := HJUI.panel("panel_alt")
	var cv := HJUI.vbox(8)
	cv.add_child(HJUI.label(
		"Copies the full game state as JSON. Paste it into the chat and I can see exactly what you saw. A screenshot is captured alongside it; once this repo is on GitHub these become issues directly.",
		HJUI.FS_TINY, "muted"))

	var copy := HJUI.button("Copy state", "primary")
	copy.custom_minimum_size.y = 66
	copy.pressed.connect(func() -> void:
		DisplayServer.clipboard_set(Debug.report_text("copied from debug panel"))
		Game.say("State copied to clipboard.", "good"))
	cv.add_child(copy)

	var shot := HJUI.button("Copy state + screenshot", "ghost")
	shot.custom_minimum_size.y = 62
	shot.pressed.connect(_capture)
	cv.add_child(shot)

	card.add_child(cv)
	_body.add_child(card)

	var state := HJUI.panel("panel")
	var sv := HJUI.vbox(2)
	sv.add_child(HJUI.label("CURRENT", HJUI.FS_TINY, "muted"))
	for line in _summary_lines():
		sv.add_child(HJUI.label(line, HJUI.FS_TINY, "text"))
	state.add_child(sv)
	_body.add_child(state)


func _capture() -> void:
	# Hide the panel for the grab so the screenshot shows the game, not the tool.
	panel.visible = false
	bubble.visible = false
	await RenderingServer.frame_post_draw
	var path := Debug.capture_screenshot()
	panel.visible = true
	bubble.visible = Debug.bubble_visible
	var note := "screenshot: %s" % (path if path != "" else "capture failed")
	DisplayServer.clipboard_set(Debug.report_text(note))
	Game.say("State copied. %s" % note, "good" if path != "" else "warn")


func _summary_lines() -> Array:
	var lines: Array = ["screen: %s" % Game.screen]
	if Game.run != null:
		lines.append("chapter %d · %s" % [Game.run.chapter, Game.run.area.get("id", "")])
		lines.append("grit %d · left %s" % [Game.run.grit, HJClock.format_remaining(Game.run.seconds_left())])
		lines.append("pending: %s" % (Game.run.pending_node if Game.run.pending_node != "" else "—"))
	else:
		lines.append("no run")
	lines.append("resolve %d · streak %d · loops %d" % [Meta.resolve, Meta.streak, Meta.loops])
	return lines


## Press to drag, tap to open. A floating control you cannot move is a floating
## control in the way.
##
## `pointing/emulate_touch_from_mouse` means one physical press arrives twice —
## once as a touch event and once as a mouse event. Both families are handled so
## this works with the setting on or off, but only the family that *started* a
## press is allowed to continue or end it, otherwise every tap fires twice and
## every drag moves at double speed.
class Bubble extends Panel:
	signal tapped
	signal moved

	var _pressing := false
	var _source := ""
	var _travel := 0.0

	func _gui_input(event: InputEvent) -> void:
		if event is InputEventScreenTouch:
			_press("touch", event.pressed)
			accept_event()
		elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
			_press("mouse", event.pressed)
			accept_event()
		elif event is InputEventScreenDrag and _source == "touch":
			_drag(event.relative)
			accept_event()
		elif event is InputEventMouseMotion and _source == "mouse":
			_drag(event.relative)
			accept_event()

	func _press(source: String, is_down: bool) -> void:
		if is_down:
			if _pressing:
				return          # the duplicate from the other input family
			_pressing = true
			_source = source
			_travel = 0.0
			return
		if not _pressing or _source != source:
			return
		_pressing = false
		_source = ""
		if _travel < HJDebugOverlay.DRAG_SLOP:
			tapped.emit()
		else:
			moved.emit()

	func _drag(relative: Vector2) -> void:
		position += relative
		_travel += relative.length()
		moved.emit()
