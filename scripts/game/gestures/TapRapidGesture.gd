class_name HJGestureTapRapid
extends HJGesture
## Drum on it. The punctuation for the energetic axes — move, water, fuel.
##
## A count with a leak in it: every tap adds one, and the total drains at
## `task.tap_decay` a second, so tapping slowly never arrives however long you
## keep at it. That is the only thing the decay is for. It is still a speed
## bump — two seconds of thumb, tuned to cost about what the hold costs — and
## anyone determined to lie to a fitness app can tap six times.
##
## Nobody should be locked out of a task by their hands. The "always hold"
## setting turns every task back into HJGestureHold, and the "I couldn't do
## this one" button never goes through a gesture at all.

var _down := false
var _taps := 0.0


func label() -> String:
	return "Tap fast to confirm"


func hint() -> String:
	return "Keep tapping — it drains if you stop."


func press(down: bool) -> void:
	# pointing/emulate_touch_from_mouse delivers one press as both a touch and a
	# mouse event, so the button can report going down twice for one thumb. A
	# tap is counted on the *transition* into pressed and the duplicate, which
	# arrives without an intervening release, is free.
	if down == _down:
		return
	_down = down
	if down:
		_taps += 1.0


func tick(delta: float) -> void:
	if done:
		return
	var need: float = maxf(1.0, Rules.value("task.tap_count", {}, 5))
	var decay: float = maxf(0.0, Rules.value("task.tap_decay", {}, 1.5))
	_taps = maxf(0.0, _taps - decay * delta)
	progress = clampf(_taps / need, 0.0, 1.0)
	if _taps >= need:
		done = true


func reset() -> void:
	_down = false
	_taps = 0.0
	progress = 0.0
	done = false
