extends Control
## App shell: paints the background, keeps the playfield in a phone-shaped
## column, swaps screens, renders toasts, and drives the one-second tick that
## the deadline countdowns run on.

const SCREENS := {
	"title": preload("res://scripts/screens/TitleScreen.gd"),
	"palace": preload("res://scripts/screens/MindPalaceScreen.gd"),
	"gym": preload("res://scripts/screens/GymScreen.gd"),
	"workshop": preload("res://scripts/screens/WorkshopScreen.gd"),
	"stores": preload("res://scripts/screens/StoresScreen.gd"),
	"hearth": preload("res://scripts/screens/HearthScreen.gd"),
	"observatory": preload("res://scripts/screens/ObservatoryScreen.gd"),
	"journey": preload("res://scripts/screens/JourneyScreen.gd"),
	"area": preload("res://scripts/screens/AreaScreen.gd"),
	"overworld": preload("res://scripts/screens/OverworldScreen.gd"),
	"worldmap": preload("res://scripts/screens/WorldMapScreen.gd"),
	"task": preload("res://scripts/screens/TaskScreen.gd"),
	"boon": preload("res://scripts/screens/BoonScreen.gd"),
	"event": preload("res://scripts/screens/EventScreen.gd"),
	"summary": preload("res://scripts/screens/SummaryScreen.gd"),
	"codex": preload("res://scripts/screens/CodexScreen.gd"),
	"wheel": preload("res://scripts/screens/WheelScreen.gd"),
	"inventory": preload("res://scripts/screens/InventoryScreen.gd"),
}

const FRAME_WIDTH := 720.0

var bg: ColorRect
var frame: PanelContainer
var host: MarginContainer
var toasts: VBoxContainer
var current: Control = null
var _tick_accumulator := 0.0
var _swapping := false


func _ready() -> void:
	set_anchors_preset(Control.PRESET_FULL_RECT)

	bg = ColorRect.new()
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(bg)

	frame = PanelContainer.new()
	frame.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(frame)

	# A container (not a plain Control): containers size their children, so a
	# screen added long after layout still gets the full frame rect.
	host = MarginContainer.new()
	host.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	host.size_flags_vertical = Control.SIZE_EXPAND_FILL
	frame.add_child(host)

	toasts = VBoxContainer.new()
	toasts.mouse_filter = Control.MOUSE_FILTER_IGNORE
	# Top, not bottom: the bottom of the screen is the thumb zone where the
	# primary action buttons live, and a toast must never sit on top of them.
	toasts.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	toasts.offset_left = 20
	toasts.offset_right = -20
	toasts.offset_top = 16
	toasts.offset_bottom = 240
	toasts.grow_vertical = Control.GROW_DIRECTION_END
	toasts.alignment = BoxContainer.ALIGNMENT_BEGIN
	toasts.add_theme_constant_override("separation", 6)
	add_child(toasts)

	Events.screen_changed.connect(_on_screen_changed)
	Events.theme_changed.connect(_restyle)
	Events.logged.connect(_toast)

	# Above every screen, and it owns its own visibility.
	add_child(HJDebugOverlay.new())
	Debug.knob_changed.connect(_on_knob_changed)

	Game.boot()
	_restyle()
	_apply_brightness()

	if _selftest_requested():
		call_deferred("_run_selftest")


func _process(delta: float) -> void:
	_tick_accumulator += delta
	if _tick_accumulator < 1.0:
		return
	_tick_accumulator = 0.0
	Events.tick.emit()
	Game.tick()


func _selftest_requested() -> bool:
	return OS.get_cmdline_args().has("--selftest") or OS.get_cmdline_user_args().has("--selftest")


func _run_selftest() -> void:
	var code: int = await HJSelfTest.run_all(self)
	get_tree().quit(code)


func _on_knob_changed(id: String, _value: float) -> void:
	if id == "brightness":
		_apply_brightness()


## Multiplies the whole playfield. Below 1 darkens, above 1 lifts — enough to
## judge art in daylight without rebuilding.
func _apply_brightness() -> void:
	var b := Debug.knob("brightness")
	frame.modulate = Color(b, b, b, 1.0)


func _restyle() -> void:
	bg.color = Palette.c("bg")
	var sb := HJUI.flat(Palette.c("bg"), 0)
	if get_viewport_rect().size.x > FRAME_WIDTH + 40.0:
		sb.border_color = Palette.ca("line", 0.7)
		sb.set_border_width_all(2)
	frame.add_theme_stylebox_override("panel", sb)


func _on_screen_changed(screen_name: String) -> void:
	# A screen's build() can decide it is the wrong screen and redirect. Without
	# this guard that redirect lands mid-swap and tears the tree apart.
	if _swapping:
		_on_screen_changed.call_deferred(screen_name)
		return
	_swapping = true
	if current != null:
		host.remove_child(current)
		current.queue_free()
		current = null
	var script: Script = SCREENS.get(screen_name, null)
	if script == null:
		push_error("Main: unknown screen '%s'" % screen_name)
		_swapping = false
		return
	current = script.new()
	# Before add_child: _ready() builds the screen, and the build needs to know
	# which room it is standing in.
	current.screen_id = screen_name
	host.add_child(current)
	_swapping = false


func _toast(text: String, kind: String) -> void:
	if text.strip_edges() == "":
		return
	var role := "text"
	match kind:
		"good": role = "good"
		"bad": role = "danger"
		"warn": role = "warn"

	var p := HJUI.panel("panel_alt", role)
	var sb: StyleBoxFlat = p.get_theme_stylebox("panel")
	sb.content_margin_top = 10
	sb.content_margin_bottom = 10
	p.modulate.a = 0.0
	p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	p.add_child(HJUI.label(text, HJUI.FS_SMALL, role, HORIZONTAL_ALIGNMENT_CENTER))
	toasts.add_child(p)

	while toasts.get_child_count() > 3:
		var oldest := toasts.get_child(0)
		toasts.remove_child(oldest)
		oldest.queue_free()

	# Bound to the panel, so trimming an old toast kills its tween with it.
	var tween := p.create_tween()
	tween.tween_property(p, "modulate:a", 1.0, 0.12)
	tween.tween_interval(2.1)
	tween.tween_property(p, "modulate:a", 0.0, 0.35)
	tween.tween_callback(p.queue_free)


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_GO_BACK_REQUEST:
		_go_back()


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		_go_back()


func _go_back() -> void:
	match Game.screen:
		"palace": Game.goto("title")
		"codex", "wheel", "gym", "workshop", "stores", "hearth", "observatory": Game.goto("palace")
		"inventory": Game.goto("area") if Game.has_active_run() else Game.goto("palace")
		"overworld": Game.goto("worldmap")
		"worldmap": Game.goto("area")
		"task": Game.skip_task()
