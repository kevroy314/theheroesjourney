class_name HJGritFx
extends Object
## The two numbers the player is not currently watching change: Grit, and the
## clock.
##
## Both move while the screen that would show the movement is being torn down —
## a task is completed on the task screen, an anomaly resets the deadline on the
## way *into* the next one — so by the time the area screen exists again the
## change has already happened and there is nothing to animate from. Screens
## rebuild wholesale on `run_changed`, so an instance variable cannot remember
## the old value either.
##
## Hence a static ledger. It holds what the UI is currently *showing*, which
## lags the truth by the length of one tween, and a short-lived pulse the graph
## can claim to float a number off the card that paid. Every consumer calls
## `pump()` first; it is idempotent, so it does not matter who gets there first.

## How long a pulse stays claimable. Long enough to survive a screen swap and a
## rebuild, short enough that a number never floats up out of nowhere because
## the player left the app open on some other screen for a minute.
const WINDOW_MSEC := 2500

## A deadline that moved by less than this is bookkeeping, not a reprieve.
const DEADLINE_FLOOR := 1800

## Layout has not settled on the frame a screen is built, so a number anchored
## to a card has to wait for it. Two frames' worth, rounded up.
const SETTLE := 0.05

static var _seen_run: int = 0          ## run.started_unix, so a new run resets
static var _seen_grit: int = -1        ## last true value observed
static var _seen_deadline: int = 0

static var shown_grit: int = 0         ## what the counter reads right now
static var pending_grit: int = 0       ## change the graph has not floated yet
static var pending_node: String = ""   ## which card paid it
static var _pending_at: int = 0

static var pending_deadline: int = 0   ## seconds the clock jumped forward by
static var _deadline_at: int = 0


## Notice what has changed since last time. Safe to call from anywhere, as often
## as you like.
static func pump(run: HJRun) -> void:
	if run == null:
		return
	if run.started_unix != _seen_run or _seen_grit < 0:
		_seen_run = run.started_unix
		_seen_grit = run.grit
		shown_grit = run.grit
		_seen_deadline = run.deadline_unix
		pending_grit = 0
		pending_deadline = 0
		return

	if run.grit != _seen_grit:
		pending_grit += run.grit - _seen_grit
		pending_node = String(run.completed.back()) if not run.completed.is_empty() else ""
		_pending_at = Time.get_ticks_msec()
		_seen_grit = run.grit

	var jump := run.deadline_unix - _seen_deadline
	if jump >= DEADLINE_FLOOR:
		pending_deadline = jump
		_deadline_at = Time.get_ticks_msec()
	if run.deadline_unix != _seen_deadline:
		_seen_deadline = run.deadline_unix


static func _fresh(stamp: int) -> bool:
	return stamp > 0 and Time.get_ticks_msec() - stamp <= WINDOW_MSEC


## Take the grit pulse, if there is one worth showing. Returns 0 otherwise, and
## clears the pulse either way so it cannot play twice.
static func claim_grit() -> int:
	var amount := pending_grit if _fresh(_pending_at) else 0
	pending_grit = 0
	_pending_at = 0
	return amount


## Take the deadline pulse, in seconds. Same contract.
static func claim_deadline() -> int:
	var amount := pending_deadline if _fresh(_deadline_at) else 0
	pending_deadline = 0
	_deadline_at = 0
	return amount


static func motion() -> bool:
	return Debug.knob("motion") > 0.0


## A number that leaves, rising off whatever control paid it.
##
## Gains read up and green; losses read down and red. Direction alone is not
## enough on a phone at arm's length and colour alone is not enough for anyone
## who cannot separate the two, so it is direction, colour and an explicit sign.
##
## The label is parented to the anchor and set `top_level`, which is what keeps
## it out of the container's layout pass — Godot's `Container` skips top-level
## children — and lets it be positioned in the one frame the card and the page
## both agree on.
static func float_number(anchor: Control, amount: int, suffix: String = "") -> void:
	if anchor == null or not is_instance_valid(anchor) or amount == 0 or not motion():
		return
	var tree := anchor.get_tree()
	if tree == null:
		return
	tree.create_timer(SETTLE).timeout.connect(
		func() -> void: _spawn_number(anchor, amount, suffix))


static func _spawn_number(anchor: Control, amount: int, suffix: String) -> void:
	if anchor == null or not is_instance_valid(anchor) or not anchor.is_inside_tree():
		return
	var gain := amount > 0
	var label := HJUI.label("%+d%s" % [amount, suffix], HJUI.FS_BODY,
		"good" if gain else "danger", HORIZONTAL_ALIGNMENT_CENTER)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.z_index = 40
	anchor.add_child(label)
	label.top_level = true
	label.size = Vector2(140.0, 40.0)

	var centre := anchor.get_global_position() + anchor.size * 0.5
	var start := centre - Vector2(70.0, 20.0)
	label.global_position = start
	label.modulate.a = 0.0

	var rise := -58.0 if gain else 44.0
	var tween := label.create_tween()
	tween.tween_property(label, "modulate:a", 1.0, 0.12)
	tween.parallel().tween_property(label, "global_position:y", start.y + rise, 0.78) \
		.set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	tween.parallel().tween_property(label, "modulate:a", 0.0, 0.42).set_delay(0.36)
	tween.tween_callback(label.queue_free)


## Count a label from one integer to another. Applies the final value at once
## when motion is off, so the knob still means what it says.
static func count_to(node: Node, from_value: int, to_value: int, apply: Callable) -> void:
	if node == null or not is_instance_valid(node):
		return
	if not motion() or from_value == to_value:
		apply.call(to_value)
		return
	# A count that takes the same time whether it moved by 2 or by 200 reads as
	# a stutter on the small one. Scale it, with a floor and a ceiling.
	var span := absi(to_value - from_value)
	var duration := clampf(0.18 + 0.5 * minf(1.0, float(span) / 20.0), 0.18, 0.7)
	apply.call(from_value)
	var tween := node.create_tween()
	tween.tween_method(func(v: float) -> void: apply.call(int(round(v))),
		float(from_value), float(to_value), duration) \
		.set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)


## A chip that has just gained something: one swell and a brief brightening.
## Deliberately short — this fires next to a counter that is already counting,
## and two things insisting at once is one thing too many.
static func flash(control: Control) -> void:
	if control == null or not is_instance_valid(control) or not motion():
		return
	control.pivot_offset = control.size * 0.5
	var tween := control.create_tween()
	tween.tween_property(control, "scale", Vector2(1.07, 1.07), 0.16) \
		.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	tween.parallel().tween_property(control, "modulate", Color(1.5, 1.45, 1.2), 0.16)
	tween.tween_property(control, "scale", Vector2.ONE, 0.44) \
		.set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	tween.parallel().tween_property(control, "modulate", Color.WHITE, 0.44)
