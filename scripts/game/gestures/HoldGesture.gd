class_name HJGestureHold
extends HJGesture
## Press and keep pressing. The original, and the one everything falls back to.
##
## The right punctuation for the soft axes — rest, mind, bond. You have just
## been still, or been with someone; the confirm should not ask you to thrash.
## It is also the accessible default: a single sustained press is the least
## demanding thing a touchscreen can ask for, which is why the "always hold"
## setting resolves every task to this.

var _down := false
var _held := 0.0


func label() -> String:
	return "Hold to confirm"


func hint() -> String:
	return "Press and keep pressing."


func press(down: bool) -> void:
	_down = down
	if not down:
		# Letting go is starting over. A hold accumulated across three separate
		# taps is a tap, and the whole point is that it is not one.
		_held = 0.0
		progress = 0.0


func tick(delta: float) -> void:
	if done:
		return
	var need: float = maxf(0.1, Rules.value("task.hold_seconds", {}, 1.2))
	if _down:
		_held += delta
	progress = clampf(_held / need, 0.0, 1.0)
	if _held >= need:
		done = true


func reset() -> void:
	_down = false
	_held = 0.0
	progress = 0.0
	done = false
