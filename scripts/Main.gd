extends Control
## App shell: paints the background, keeps the playfield in a phone-shaped
## column, swaps screens, renders toasts, and drives the one-second tick that
## the deadline countdowns run on.

const SCREENS := {
	"title": preload("res://scripts/screens/TitleScreen.gd"),
	# The Menu is the fourth wall and holds nothing but preferences, so it *is*
	# the settings screen rather than a list with one entry on it. Everywhere you
	# can actually go is reached through HJUI.nav_bar and the Mind Palace.
	"menu": preload("res://scripts/screens/SettingsScreen.gd"),
	"palace": preload("res://scripts/screens/MindPalaceScreen.gd"),
	"gym": preload("res://scripts/screens/GymScreen.gd"),
	"workshop": preload("res://scripts/screens/WorkshopScreen.gd"),
	"stores": preload("res://scripts/screens/StoresScreen.gd"),
	"hearth": preload("res://scripts/screens/HearthScreen.gd"),
	"dialogue": preload("res://scripts/screens/DialogueScreen.gd"),
	"observatory": preload("res://scripts/screens/ObservatoryScreen.gd"),
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

## How tall a band the toast column is allowed to fill before it starts trimming.
## What the movement pad and the action button occupy at the bottom of the play
## screen: the pad is about 260px and `_act` another 84, plus its margin. A
## toast anchored below this covers the control the player is reaching for.
const CONTROLS_BAND := 360.0
const TOAST_BAND := 240.0
## How much of the width the offset column takes. Wide enough for a sentence at
## FS_SMALL, narrow enough that the right-hand end of whatever it is covering —
## the nav bar, the Grit chip — is still readable underneath it.
const TOAST_NARROW := 0.62

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
	toasts.add_theme_constant_override("separation", 6)
	add_child(toasts)
	_place_toasts()

	Events.screen_changed.connect(_on_screen_changed)
	Events.theme_changed.connect(_restyle)
	# Moving the column moves the toasts already in it, so the setting takes
	# effect on the notification currently on screen rather than on the next one.
	Events.meta_changed.connect(_place_toasts)
	Events.logged.connect(_toast)
	Events.unlocked.connect(_unlock_toast)

	# Above every screen, and it owns its own visibility.
	add_child(HJDebugOverlay.new())
	Debug.knob_changed.connect(_on_knob_changed)

	# Before Game.boot(), and it returns rather than falling through. A world
	# shot wants the autoloads and the world file and nothing else: booting would
	# load the player's run, possibly trip a deadline and write the save, for a
	# tool whose whole contract is that it never touches any of that. See the
	# header of scripts/WorldShot.gd.
	if HJWorldShot.requested():
		call_deferred("_run_worldshot")
		return

	Game.boot()
	_restyle()
	_apply_brightness()

	if _selftest_requested():
		call_deferred("_run_selftest")


## Where the toast column sits, from Meta.ui_toast_pos.
##
## Neither edge of a phone screen is free, which is why this is a preference and
## not a fix. The top strip is the run header, the Steps/Grit chips and the buff
## pills — so a full-width toast at the top covers the very numbers it is
## usually talking about. The bottom strip is the thumb zone: the primary action
## button, and on the overworld the movement pad under it. Covering information
## you can read again in a second is a smaller harm than covering a control you
## are reaching for, and _unlock_toast is itself tappable, so at the bottom it
## can sit on the action button and take the tap meant for it.
##
##   "bottom"    a band above the bottom edge, newest nearest the thumb
##   "top_left"  narrow and left-aligned: clips the header instead of blanketing it
##   "top"       the original full-width strip
func _place_toasts() -> void:
	toasts.anchor_left = 0.0
	toasts.anchor_right = 1.0
	toasts.offset_left = 20.0
	toasts.offset_right = -20.0
	toasts.grow_horizontal = Control.GROW_DIRECTION_END
	match Meta.ui_toast_pos:
		"bottom":
			# Above the controls, not at the screen edge.
			#
			# The bottom of the play screen is the action button and the movement
			# pad — roughly 350px of them — so anchoring to the very bottom put
			# the toast on top of the primary control and, because the unlock
			# toast opts back into mouse events, let it eat the tap meant for it.
			# "Bottom" means the bottom of the *world view*: the lowest place a
			# notification can sit and still be out of the way of a thumb.
			toasts.anchor_top = 1.0
			toasts.anchor_bottom = 1.0
			toasts.offset_top = -(TOAST_BAND + CONTROLS_BAND)
			toasts.offset_bottom = -CONTROLS_BAND
			# The newest line sits lowest, closest to where the eye already is,
			# and older ones ride up out of the way.
			toasts.grow_vertical = Control.GROW_DIRECTION_BEGIN
			toasts.alignment = BoxContainer.ALIGNMENT_END
		"top_left":
			toasts.anchor_right = TOAST_NARROW
			toasts.anchor_top = 0.0
			toasts.anchor_bottom = 0.0
			toasts.offset_right = -8.0
			toasts.offset_top = 16.0
			toasts.offset_bottom = 16.0 + TOAST_BAND
			toasts.grow_vertical = Control.GROW_DIRECTION_END
			toasts.alignment = BoxContainer.ALIGNMENT_BEGIN
		_:
			toasts.anchor_top = 0.0
			toasts.anchor_bottom = 0.0
			toasts.offset_top = 16.0
			toasts.offset_bottom = 16.0 + TOAST_BAND
			toasts.grow_vertical = Control.GROW_DIRECTION_END
			toasts.alignment = BoxContainer.ALIGNMENT_BEGIN


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


func _run_worldshot() -> void:
	var code: int = await HJWorldShot.run_shot(self)
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
	_trim_and_fade(p)


## An unlock: the same strip, but it takes you there.
##
## The toast column is MOUSE_FILTER_IGNORE so a status line never eats a tap
## meant for the screen underneath. This one opts back in, for itself only, and
## it lingers — three seconds is enough to read a status line and not enough to
## notice a thing is tappable, decide to tap it, and reach it.
func _unlock_toast(text: String, screen: String) -> void:
	if text.strip_edges() == "":
		return
	var card := HJUI.TapCard.new()
	card.add_theme_stylebox_override("panel", HJUI.stylebox(
		Palette.c("panel_alt"), HJUI.RADIUS, Palette.c("accent"), 2))
	card.modulate.a = 0.0

	var row := HJUI.hbox(10)
	if HJUI.has_icon("resolve"):
		row.add_child(HJUI.icon("resolve", 32, "accent"))
	var body := HJUI.vbox(2)
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_child(HJUI.label(text, HJUI.FS_SMALL, "accent"))
	if screen != "":
		body.add_child(HJUI.label("Tap to go there", HJUI.FS_TINY, "muted"))
	row.add_child(body)
	card.add_child(row)

	if screen != "":
		card.tapped.connect(func() -> void:
			card.queue_free()
			Game.goto(screen))
	toasts.add_child(card)
	_trim_and_fade(card, 5.0)


func _trim_and_fade(p: Control, linger: float = 2.1) -> void:
	while toasts.get_child_count() > 3:
		var oldest := toasts.get_child(0)
		toasts.remove_child(oldest)
		oldest.queue_free()

	# Bound to the panel, so trimming an old toast kills its tween with it.
	var tween := p.create_tween()
	tween.tween_property(p, "modulate:a", 1.0, 0.12)
	tween.tween_interval(linger)
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
		"menu": Game.goto("title")
		"task": Game.skip_task()
