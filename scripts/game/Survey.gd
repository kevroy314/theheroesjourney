class_name HJSurvey
extends RefCounted
## What happens when a `choice` node is answered.
##
## A choice node is the one card in the game that asks instead of demanding. It
## has no timer, no exertion and no honesty gate, because those three exist to
## make a claimed push-up plausible and there is nothing to make plausible about
## a sentence you finished about yourself. So none of this goes through
## `Game.complete_task`: no movement, no axis, no streak, no scaling.
##
## An answer lands in two places, deliberately different:
##
##   * **Run tags**, through the node and option `grants` that already existed.
##     `Rules.passes` reads them as `has_tag`/`lacks_tag`, so an answer is
##     immediately a condition the rest of the area can consult — which is how
##     the survey ends in an action the answers picked.
##   * **`Meta.self_description`**, under the key the node names in `remember`.
##     Tags die with the loop and the point of asking is to still know next
##     time. What you admitted about yourself is inside you, so it comes along.
##
## Statics rather than an instance on Game: this holds nothing between calls,
## and the screen and the self-test are the only callers.

## Every answer to a choice node pays the same. Paying more for one of them
## would be pricing honesty, and the survey is the one place in this game that
## must not do that — so `grit` sits on the node, and an option may only
## override it for reasons that are not "this is the better answer".
static func option_grit(node: Dictionary, option: Dictionary) -> int:
	return int(option.get("grit", node.get("grit", 4)))


## Does this node take typed input anywhere in its options?
static func takes_text(node: Dictionary) -> bool:
	for option in node.get("options", []):
		if String((option as Dictionary).get("input", "")) == "text":
			return true
	return false


## Answer the node the run is sitting on.
##
## `typed` is only read when the chosen option is the text one; every other
## option ignores it, which is what makes "I do not remember" a real answer
## rather than a way of skipping the question.
static func answer(node_id: String, option_index: int, typed: String = "") -> void:
	var run: HJRun = Game.run
	if run == null or run.finished or run.pending_node != node_id:
		return
	var node := run.node(node_id)
	if String(node.get("type", "")) != "choice":
		return
	var options: Array = node.get("options", [])
	if option_index < 0 or option_index >= options.size():
		return
	var option: Dictionary = options[option_index]

	for tag in node.get("grants", []):
		if not run.tags.has(tag):
			run.tags.append(tag)
	for tag in option.get("grants", []):
		if not run.tags.has(tag):
			run.tags.append(tag)

	var key := String(node.get("remember", ""))
	if key != "":
		Meta.self_description[key] = _kept(node, option, typed)
		Meta.save_game()

	Game.add_grit(option_grit(node, option))
	run.pending_node = ""
	# After the tags, so a `select_next` fork downstream is resolved against the
	# answer that was just given rather than against the one before it.
	Game.finish_node(node_id)
	Game.changed()
	Game.goto("area")


## What gets written down and kept.
##
## For a question answered by typing, the answer *is* the text, and an empty one
## is still an answer — a player who would not say has said something, and "" is
## how that is recorded. Everywhere else the tag is the answer, because a tag is
## the thing later content can actually read.
static func _kept(node: Dictionary, option: Dictionary, typed: String) -> String:
	if takes_text(node):
		if String(option.get("input", "")) == "text":
			return typed.strip_edges()
		return ""
	var grants: Array = option.get("grants", [])
	if not grants.is_empty():
		return String(grants[0])
	return String(option.get("text", ""))
