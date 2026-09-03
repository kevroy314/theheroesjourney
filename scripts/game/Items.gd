class_name HJItems
extends RefCounted
## The verbs items can perform.
##
## An item is data — a name, a price, a `use` string — and this is the table
## that turns that string into something happening. It lives apart from Game
## because adding an item should mean touching content and one match arm, not
## reading a thousand-line orchestrator to find where the arms are kept.
##
## Every arm returns having either consumed the item or explained why it could
## not. `use` returns false for "nothing happened", which is what stops the
## Stores screen charging for a no-op.

var g: Node   ## the Game autoload


func _init(game: Node) -> void:
	g = game


func use(id: String) -> bool:
	var item := Content.item(id)
	if item.is_empty() or Meta.item_count(id) <= 0:
		return false

	match String(item.get("use", "")):
		"resume_run":
			# Consumed when the loop closes rather than tapped — `where: "auto"`.
			# The item was written for chapters ("begin again at the chapter you
			# reached") and did nothing at all, because nothing implemented the
			# verb. Under zone levels it means something better: the loop still
			# resets the world, but you wake where you were standing instead of
			# walking back out from town.
			# `has_active_run()` is false here: this fires from end_run, after the
			# run is marked finished, which is the whole point of `where: "auto"`.
			# Testing it would have set the destination to "nowhere" every single
			# time and the item would have looked implemented and done nothing.
			Meta.resume_at = g.run.world_pos if g.run != null else Vector2i(-1, -1)
			Meta.save_game()
			g.say("Second Wind. You will wake where you stood.", "good")
		"keep_streak":
			if not Meta.spend_rest_token():
				g.say("Nothing to protect today.", "warn")
				return false
			g.say("Rest counts. %s: %d days." % [Palette.word("streak"), Meta.streak], "good")
			return true
		"extend_deadline":
			if not g.has_active_run():
				return false
			Meta.take_item(id)
			g.run.deadline_unix += HJClock.hours_to_seconds(float(item.get("amount", 12)))
			Notify.sync()
			g.say("The hour hand slips back. %s left."
				% HJClock.format_remaining(g.run.seconds_left()), "good")
		"ward":
			if not g.has_active_run():
				return false
			Meta.take_item(id)
			g.run.ward = true
			g.say("Tonic ready. The next setback will slide off.", "good")
		"skip_to_threshold":
			if not g.has_active_run() or _tasks_done_here() <= 0:
				g.say("Do at least one thing here first.", "warn")
				return false
			Meta.take_item(id)
			for node_id in g.run.area.get("order", []):
				if String(g.run.node(String(node_id)).get("type", "")) == "threshold":
					g.say("You walk straight for the door.", "warn")
					g.tap_node(String(node_id))
					break
		"reveal_area":
			if not g.has_active_run():
				return false
			Meta.take_item(id)
			g.run.revealed = true
			g.say("The room gives up its corners.", "good")
		"full_scale":
			if not g.has_active_run():
				return false
			Meta.take_item(id)
			g.run.full_scale = true
			g.say("Take the easier version. It costs you nothing.", "good")
		"guarantee_kind_spite":
			if not g.has_active_run():
				return false
			Meta.take_item(id)
			g.run.kind_spite = true
			g.say("If they find you now, it will be the good half.", "good")
		"reveal_echo":
			Meta.take_item(id)
			g.outcomes.give_echo()
			return true
		_:
			return false

	g.changed()
	return true


## The Skeleton Key will not open a door you have not walked to.
func _tasks_done_here() -> int:
	var n := 0
	for id in g.run.completed:
		if String(g.run.node(String(id)).get("type", "")) == "task":
			n += 1
	return n
