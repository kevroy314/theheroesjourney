class_name HJGesture
extends RefCounted
## One way of saying "yes, I did that".
##
## A gesture is the deliberate act at the end of a task — not proof, and never
## meant to be. The app cannot know whether you did the push-up, and a gesture
## that were genuinely hard to fake would only be a worse version of the same
## lie. What it stops is a mis-tap completing a workout, and what it adds is a
## beat of physical punctuation that matches the thing you just did: you hold
## after stillness, you drum after effort.
##
## Subclasses own two numbers — how far along the player is, and whether that
## is far enough. Everything else (the bar, the button, the completion call)
## belongs to the screen, so a new gesture is a new file and a line in
## HJGestures.KINDS rather than a branch in TaskScreen.

## 0..1, drawn straight onto the confirm bar.
var progress: float = 0.0
## Set once the gesture has been performed. The screen reads it and completes.
var done: bool = false


## What the confirm button says once the wait (if any) is over.
func label() -> String:
	return "Confirm"


## One quiet line telling the player what to do with their thumb. Empty for a
## gesture whose label already says it.
func hint() -> String:
	return ""


## The confirm button went down or came up. Called for real presses only —
## the screen does not forward anything that happens while the gate is shut.
func press(_down: bool) -> void:
	pass


## One frame of the gesture, while the gate is open.
func tick(_delta: float) -> void:
	pass


## Back to nothing. Called whenever the screen stops trusting the current
## attempt — the gate closing, the task completing, a rebuild.
func reset() -> void:
	progress = 0.0
	done = false
