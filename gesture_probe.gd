extends SceneTree
## Temporary harness. Autoload identifiers are not in scope for a --script run,
## so everything goes through /root lookups; the classes under test resolve
## normally because they are compiled after the autoloads exist.


var M: Node
var G: Node
var C: Node
var TaskScreenScript: GDScript
var Gestures: GDScript
var Prefs: GDScript
var HoldScript: GDScript
var TapScript: GDScript
var _log: Array[String] = []


func _fail(msg: String) -> void:
	_log.append("FAIL " + msg)
	print("FAIL " + msg)


func _ok(msg: String) -> void:
	_log.append("ok   " + msg)
	print("ok   " + msg)


func _initialize() -> void:
	await process_frame
	M = root.get_node("/root/Meta")
	G = root.get_node("/root/Game")
	C = root.get_node("/root/Content")
	TaskScreenScript = load("res://scripts/screens/TaskScreen.gd")
	Gestures = load("res://scripts/game/Gestures.gd")
	Prefs = load("res://scripts/game/Prefs.gd")
	HoldScript = load("res://scripts/game/gestures/HoldGesture.gd")
	TapScript = load("res://scripts/game/gestures/TapRapidGesture.gd")
	print("--- gesture probe ---")
	OS.delay_msec(1)

	var cases := {
		"pushup": "tap_rapid", "water": "tap_rapid", "veg": "tap_rapid",
		"breathe": "hold", "bedtime": "hold", "message": "hold",
		"plank": "hold", "carry": "hold", "walk5": "tap_rapid",
	}
	for id in cases:
		var movement: Dictionary = C.movement(String(id))
		var got: String = Gestures.for_movement(movement)
		if got == String(cases[id]):
			_ok("%-9s -> %s" % [id, got])
		else:
			_fail("%s -> %s, wanted %s" % [id, got, cases[id]])

	Prefs.set_flag("hold_confirm", true)
	if Gestures.for_movement(C.movement("pushup")) == "hold":
		_ok("hold_confirm forces hold on a tap_rapid movement")
	else:
		_fail("hold_confirm did not override")
	Prefs.set_flag("hold_confirm", false)

	Prefs.set_flag("timers_on", true)
	var on: float = Prefs.gate_mult({})
	if is_equal_approx(on, 1.0):
		_ok("timers on  -> gate_mult 1.0")
	else:
		_fail("timers on -> gate_mult %f" % on)
	Prefs.set_flag("timers_on", false)
	var off: float = Prefs.gate_mult({})
	if is_equal_approx(off, 0.0):
		_ok("timers off -> gate_mult 0.0")
	else:
		_fail("timers off -> gate_mult %f" % off)
	Prefs.set_flag("timers_on", true)

	await _drive("hold", "breathe")
	await _drive("tap_rapid", "pushup")
	await _drive_slow_taps()
	await _drive_timers_off()

	for line in _log:
		print(line)
	var failed := false
	for line in _log:
		if line.begins_with("FAIL"):
			failed = true
	print("PROBE %s" % ("FAIL" if failed else "PASS"))
	quit(1 if failed else 0)


func _open_task(movement_id: String, aged: int) -> Node:
	G.start_run(12345)
	var run: Object = G.run
	# Walk into the nearest anomaly, the way SelfTest does; a run starts out in
	# the world rather than in an area.
	var cell := _nearest_anomaly(run)
	if cell.x < 0:
		_fail("no anomaly to enter")
		return null
	G.enter_anomaly(cell)
	run = G.run
	var node_id := ""
	var nodes: Dictionary = run.area.get("nodes", {})
	for key in nodes.keys():
		var record: Dictionary = nodes[key]
		if String(record.get("type", "")) == "task":
			node_id = String(key)
			break
	if node_id == "":
		_fail("no task node in the first area")
		return null
	run.pending_node = node_id
	run.pending_movement = movement_id
	run.pending_started = HJClock.now() - aged
	var screen: Node = TaskScreenScript.new()
	screen.screen_id = "task"
	root.add_child(screen)
	await process_frame
	await process_frame
	return screen


func _drive(want: String, movement_id: String) -> void:
	var screen: Node = await _open_task(movement_id, 6000)
	if screen == null:
		return
	var gesture: Object = screen.get("_gesture")
	if gesture == null:
		_fail("%s: no gesture built" % want)
		return
	var confirm: Button = screen.get("_confirm")
	if confirm.disabled:
		_fail("%s: confirm still disabled long after the wait" % want)
	var right: bool = (gesture.get_script() == TapScript) if want == "tap_rapid" else (gesture.get_script() == HoldScript)
	if not right:
		_fail("%s: wrong gesture class" % want)
	_ok("%s: button reads \"%s\"" % [want, confirm.text])

	var before: int = int(M.stats.get("tasks", 0))
	if want == "tap_rapid":
		# Seven a second, which is about what a thumb and about what
		# `adb shell input tap` manage. Each tap is emitted twice, the way one
		# thumb arrives as both a touch and a mouse event, and must count once.
		var taps := 0
		while taps < 30 and int(M.stats.get("tasks", 0)) == before:
			confirm.emit_signal("button_down")
			confirm.emit_signal("button_down")
			screen._process(0.016)
			confirm.emit_signal("button_up")
			confirm.emit_signal("button_up")
			for f in range(8):
				screen._process(0.016)
			taps += 1
		_ok("tap_rapid: filled in %d taps at 7/s (%.1fs)" % [taps, taps * 0.144])
	else:
		confirm.emit_signal("button_down")
		for i in range(120):
			screen._process(0.016)

	await process_frame
	var after: int = int(M.stats.get("tasks", 0))
	if after > before:
		_ok("%s: completed the task (%s)" % [want, movement_id])
	else:
		_fail("%s: did not complete — progress %.2f done %s" % [want, gesture.progress, gesture.done])
	screen.queue_free()
	await process_frame


## Tapping slowly must never arrive, however long you keep at it. That decay is
## the only thing separating "tap fast" from "tap".
func _drive_slow_taps() -> void:
	var screen: Node = await _open_task("pushup", 6000)
	if screen == null:
		return
	var confirm: Button = screen.get("_confirm")
	var gesture: Object = screen.get("_gesture")
	var before: int = int(M.stats.get("tasks", 0))
	for i in range(40):                      # 40 taps, one every 700ms
		confirm.emit_signal("button_down")
		confirm.emit_signal("button_up")
		for f in range(44):
			screen._process(0.016)
	var after: int = int(M.stats.get("tasks", 0))
	if after == before and not gesture.done:
		_ok("tap_rapid: 40 slow taps never fill it (progress %.2f)" % gesture.progress)
	else:
		_fail("tap_rapid: slow tapping completed the task")
	screen.queue_free()
	await process_frame


func _drive_timers_off() -> void:
	Prefs.set_flag("timers_on", false)
	var screen: Node = await _open_task("walk5", 0)   # 5 minutes of wait, normally
	if screen == null:
		return
	var confirm: Button = screen.get("_confirm")
	if confirm != null and not confirm.disabled:
		_ok("timers off: a five-minute walk confirms straight away")
	else:
		_fail("timers off: confirm still gated")
	if screen.get("_timer_bar") == null:
		_ok("timers off: no countdown panel drawn at all")
	else:
		_fail("timers off: countdown panel still there")
	var gesture: Object = screen.get("_gesture")
	var before: int = int(M.stats.get("tasks", 0))
	var n := 0
	while n < 30 and int(M.stats.get("tasks", 0)) == before:
		confirm.emit_signal("button_down")
		screen._process(0.016)
		confirm.emit_signal("button_up")
		for f in range(8):
			screen._process(0.016)
		n += 1
	if int(M.stats.get("tasks", 0)) > before:
		_ok("timers off: the gesture still has to be performed, and it completes")
	else:
		_fail("timers off: gesture did not complete (progress %.2f)" % gesture.progress)
	screen.queue_free()
	await process_frame

	Prefs.set_flag("timers_on", true)
	var screen2: Node = await _open_task("walk5", 0)
	var confirm2: Button = screen2.get("_confirm")
	if confirm2 != null and confirm2.disabled:
		_ok("timers on: the same walk is gated again — \"%s\"" % confirm2.text)
	else:
		_fail("timers on: confirm was not gated")
	# A press that lands while the gate is shut must bank nothing.
	confirm2.emit_signal("button_down")
	for i in range(120):
		screen2._process(0.016)
	var g2: Object = screen2.get("_gesture")
	if is_zero_approx(g2.progress):
		_ok("timers on: holding through the countdown banks no progress")
	else:
		_fail("timers on: gesture progressed while gated (%.2f)" % g2.progress)
	screen2.queue_free()
	await process_frame


func _nearest_anomaly(run: Object) -> Vector2i:
	var shared: Object = _world()
	var best := Vector2i(-1, -1)
	var best_d := 1 << 30
	for entry in shared.anomalies:
		var a: Dictionary = entry
		var cell := Vector2i(int(a.get("x", 0)), int(a.get("y", 0)))
		var d: int = int(a.get("tier", 0))
		if d < best_d:
			best_d = d
			best = cell
	return best


func _world() -> Object:
	var script: GDScript = load("res://scripts/ui/World.gd")
	return script.shared()
