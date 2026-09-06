class_name HJTutorial
extends RefCounted
## The first thirty minutes, and only the first thirty minutes.
##
## Every beat here fires **once in the lifetime of a save** and then this file
## stops mattering. That is the whole justification for it being one place
## rather than a flag scattered across six screens: a tutorial is a sequence of
## one-shots, and one-shots that live next to the systems they nudge are how you
## end up with `if Meta.loops == 0` in the movement code.
##
## Once-ness is `Meta.reveal()`, which returns true only the first time it is
## asked. So "do this once, and tell me if that was news" is a single call, and
## no beat needs a boolean of its own on the save.
##
## The beats are documented in docs/FIRST-THIRTY.md. Numbers below refer to it.

var g: Node   ## the Game autoload


func _init(game: Node) -> void:
	g = game


## Beat 1. A player who has not walked anywhere has no step budget, and a
## tutorial that opens with "you cannot move" is not a tutorial. So walking is
## free until they cross the threshold, and it is a *visible* buff rather than a
## silent exemption — the mark beside the Steps counter is the only evidence the
## rule exists, and the moment it disappears is the moment the rule changes.
func on_run_start() -> void:
	if not Meta.revealed.has("beat:left_house"):
		Buffs.apply("white_room")


## Beat 5. Crossing out of the house is the busiest moment in the game: three
## separate things happen, and they happen together on purpose. The boon breaks,
## the Hearth opens, and Spite is standing there.
func note_moved(cell: Vector2i) -> void:
	if not g.has_active_run():
		return
	if HJWorld.shared().is_indoors(cell):
		return
	if not Meta.reveal("beat:left_house"):
		return

	# 1. Steps start costing steps. Buffs.trigger breaks anything watching for
	#    this event, so a later indoor-only buff needs no code here.
	Buffs.trigger("outdoors")

	# 2. The Hearth. It has been visible in the Palace since the first launch —
	#    the player has seen the shape of it — and this is the moment it becomes
	#    a thing they are told to go and buy.
	g.say("The Hearth is open to you. Build it in the Mind Palace.", "good")

	# 3. Spite, on the doorstep, first run only. `once: true` on the
	#    conversation plus its own persisted seen-set means this cannot repeat
	#    even if the beat flag were somehow lost.
	if Dialogue.available("spite_doorstep"):
		Dialogue.open("spite_doorstep")


## Beat 2. The first anomaly does not let you walk back out.
##
## Every later one does — leaving early is a priced choice, not a failure, and
## that is the difficulty curve. But the first one is where the player learns
## what an anomaly *is*, and a player who backs out of it having learned nothing
## has been taught only that the button works.
func holds_you_in() -> bool:
	return g.has_active_run() \
		and not g.run.anomaly.is_empty() \
		and Meta.anomalies_closed == 0
