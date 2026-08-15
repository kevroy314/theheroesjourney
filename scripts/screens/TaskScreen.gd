extends HJScreen
## Commit → do → confirm.
##
## The app cannot know whether you did the push-up, and pretending otherwise
## produces either surveillance or theatre. So: committing is one tap, confirming
## is a deliberate hold, and the hold stays disabled until enough time has
## plausibly passed. A speed bump for honesty, never an accusation.

var _movement: Dictionary = {}
var _scale_index: int = -1        ## -1 = full movement, 0+ = index into scaling
var _hold: float = 0.0
var _holding: bool = false

var _timer_label: Label
var _timer_bar: ProgressBar
var _confirm: Button
var _hold_bar: ProgressBar
var _scale_row: VBoxContainer


func build() -> void:
	var run: HJRun = Game.run
	if run == null or run.pending_node == "":
		Game.resync_screen.call_deferred("task")
		return

	var node := run.node(run.pending_node)
	var options := Game.movement_options(node)

	# Nothing picked yet and more than one way to do it — ask first.
	if run.pending_movement == "" and options.size() > 1:
		_build_picker(node, options)
		return

	if run.pending_movement == "":
		if options.is_empty():
			Game.say("No movement available for this. Unlock a pack in Camp.", "warn")
			Game.skip_task()
			return
		run.pending_movement = String(options[0].get("id", ""))
	if run.pending_started == 0:
		run.pending_started = HJClock.now()
		Game.save_run()

	_movement = Content.movement(run.pending_movement)
	_build_active(node)


# --- movement picker -----------------------------------------------------------

func _build_picker(node: Dictionary, options: Array) -> void:
	var v := page(14)
	v.add_child(HJUI.header(String(node.get("label", "Task")), "Pick how you'll do it", func(): Game.skip_task()))

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	for option in options:
		var movement: Dictionary = option
		var units := Game.task_units(node, movement)
		var card := HJUI.panel("panel", "accent")
		var cv := HJUI.vbox(6)
		var row := HJUI.hbox(10)
		row.add_child(HJUI.label(String(movement.get("name", "?")), HJUI.FS_BODY, "text"))
		row.add_child(HJUI.label("%d %s" % [units, HJAreaGraph._plural(String(movement.get("unit", "rep")), units)],
			HJUI.FS_SMALL, "accent", HORIZONTAL_ALIGNMENT_RIGHT))
		cv.add_child(row)
		cv.add_child(HJUI.label(String(movement.get("cue", "")), HJUI.FS_TINY, "muted"))

		var pick := HJUI.button("Choose", "ghost")
		pick.custom_minimum_size.y = 74
		var movement_id := String(movement.get("id", ""))
		pick.pressed.connect(func() -> void:
			Game.run.pending_movement = movement_id
			Game.run.pending_started = HJClock.now()
			Game.save_run()
			refresh())
		cv.add_child(pick)
		card.add_child(cv)
		list.add_child(card)


# --- the task itself -----------------------------------------------------------

func _build_active(node: Dictionary) -> void:
	var run: HJRun = Game.run
	var units := Game.task_units(node, _movement)
	var unit_name := HJAreaGraph._plural(String(_movement.get("unit", "rep")), units)

	var v := page(12)
	v.add_child(HJUI.header(String(node.get("label", "Task")), String(node.get("text", ""))))

	var scroll := HJUI.scroll()
	var body := HJUI.vbox(14)
	scroll.add_child(body)
	v.add_child(scroll)

	# What you are doing, in the largest type on the screen.
	var ask := HJUI.panel("panel_alt", "accent")
	var av := HJUI.vbox(8)
	av.add_child(HJUI.label(_headline(units, unit_name), HJUI.FS_TITLE, "accent", HORIZONTAL_ALIGNMENT_CENTER))
	av.add_child(HJUI.label(String(_movement.get("name", "")), HJUI.FS_BODY, "text", HORIZONTAL_ALIGNMENT_CENTER))
	if String(_movement.get("cue", "")) != "":
		av.add_child(HJUI.label(String(_movement["cue"]), HJUI.FS_SMALL, "muted", HORIZONTAL_ALIGNMENT_CENTER))
	ask.add_child(av)
	body.add_child(ask)

	# Scaling. Framed as a normal choice, never as a failure.
	var scaling: Array = _movement.get("scaling", [])
	if not scaling.is_empty():
		var scale_panel := HJUI.panel("panel")
		_scale_row = HJUI.vbox(8)
		_scale_row.add_child(HJUI.label("Take an easier version if you need it — it counts.", HJUI.FS_TINY, "muted"))
		var full := _scale_button("As written: %s" % _movement.get("name", ""), -1)
		_scale_row.add_child(full)
		for i in range(scaling.size()):
			_scale_row.add_child(_scale_button(String(scaling[i]), i))
		scale_panel.add_child(_scale_row)
		body.add_child(scale_panel)

	# The plausibility gate.
	var gate := HJUI.panel("panel")
	var gv := HJUI.vbox(8)
	_timer_label = HJUI.label("", HJUI.FS_SMALL, "muted")
	gv.add_child(_timer_label)
	_timer_bar = HJUI.bar(0, 1, "accent", 14)
	gv.add_child(_timer_bar)
	gate.add_child(gv)
	body.add_child(gate)

	# Confirm: a hold, so a workout cannot be finished by drumming a thumb.
	_hold_bar = HJUI.bar(0, 1, "good", 8)
	v.add_child(_hold_bar)

	_confirm = HJUI.button("Hold to confirm", "primary", false)
	_confirm.button_down.connect(func() -> void: _holding = true)
	_confirm.button_up.connect(func() -> void:
		_holding = false
		_hold = 0.0)
	v.add_child(_confirm)

	var couldnt := HJUI.button("I couldn't do this one", "quiet")
	couldnt.custom_minimum_size.y = 70
	couldnt.pressed.connect(_on_couldnt)
	v.add_child(couldnt)

	set_process(true)
	_update_gate()


func _headline(units: int, unit_name: String) -> String:
	if _scale_index >= 0:
		return "%d %s" % [units, unit_name]
	return "%d %s" % [units, unit_name]


func _scale_button(text: String, index: int) -> Button:
	var chosen := index == _scale_index
	var b := HJUI.button(text, "primary" if chosen else "ghost")
	b.custom_minimum_size.y = 64
	b.pressed.connect(func() -> void:
		_scale_index = index
		refresh())
	return b


func _required_seconds() -> int:
	var run: HJRun = Game.run
	return Game.task_seconds(run.node(run.pending_node), _movement)


func _elapsed() -> int:
	var run: HJRun = Game.run
	return maxi(0, HJClock.now() - run.pending_started)


func _process(delta: float) -> void:
	if _confirm == null or not is_instance_valid(_confirm):
		return
	_update_gate()

	if _holding and not _confirm.disabled:
		_hold += delta
		var need := Rules.value("task.hold_seconds", {}, 1.2)
		HJUI.set_bar(_hold_bar, _hold, need, "good")
		if _hold >= need:
			_holding = false
			_hold = 0.0
			set_process(false)
			_complete(false)
	elif _hold > 0.0:
		_hold = 0.0
		HJUI.set_bar(_hold_bar, 0, 1, "good")


func _update_gate() -> void:
	var need := _required_seconds()
	var elapsed := _elapsed()
	HJUI.set_bar(_timer_bar, elapsed, need, "good" if elapsed >= need else "accent")
	if elapsed >= need:
		_timer_label.text = "Ready when you are."
		_timer_label.add_theme_color_override("font_color", Palette.c("good"))
		if _confirm.disabled:
			_confirm.disabled = false
			_confirm.text = "Hold to confirm"
	else:
		_timer_label.text = "Confirm unlocks in %s" % HJClock.format_remaining(need - elapsed)
		_timer_label.add_theme_color_override("font_color", Palette.c("muted"))
		_confirm.text = "Go on, then"


func _on_couldnt() -> void:
	set_process(false)
	_complete(true)


func _complete(scaled: bool) -> void:
	var run: HJRun = Game.run
	if run == null or run.pending_node == "":
		return
	var was_scaled := scaled or _scale_index >= 0
	var movement_id := run.pending_movement
	run.pending_movement = ""
	run.pending_started = 0
	if scaled:
		Game.say("Logged as far as you got. That still counts.", "info")
	Game.complete_task(movement_id, was_scaled)
