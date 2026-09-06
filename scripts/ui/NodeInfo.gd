class_name HJNodeInfo
extends Object
## What a node is going to ask for, and what it is going to pay, worked out
## *before* the player commits to it.
##
## Everything here is a preview of arithmetic that lives somewhere else —
## `Game.tap_node`, `Game.complete_task`, `HJSurvey.answer`. That duplication is
## the one real risk in this file: a preview that drifts from the payout is
## worse than no preview at all, because the player made a route decision on it.
## So each function names the site it mirrors, and each one uses the same public
## calls (`Rules.value`, `Meta.streak_multiplier`) rather than a private copy of
## the numbers. The right long-term fix is for `Game.complete_task` to call
## `task_grit()` instead of computing its own; see the note in the issue.
##
## Where the answer is genuinely not knowable — a loot roll, a Mirror, a Spite
## that may take rather than give — this returns nothing and the card stays
## quiet. Promising a number we cannot keep is the failure mode worth avoiding.

## Grit is only shown where the payout is deterministic. These are those types.
const PAYS := ["task", "cache", "choice"]


## The axis a task node will ask for, or "" when it genuinely is not fixed.
##
## `$choose:<axis>` and `$other:<axis>` pin the axis while leaving the movement
## open, which is exactly the case the player wants marked: they do not know
## whether it is press-ups or a walk, but they do know it is legs and lungs.
## A bare `$choose:` pins nothing, and a hand-authored multi-option node could
## in principle straddle two axes; both come back "".
static func axis_of(node: Dictionary) -> String:
	var token := String(node.get("task", {}).get("movement", ""))
	for prefix in ["$choose:", "$other:"]:
		if token.begins_with(prefix):
			var named := token.trim_prefix(prefix)
			return named
	var options: Array = Game.movement_options(node)
	if options.is_empty():
		return ""
	var first: Dictionary = options[0]
	var axis := String(first.get("axis", ""))
	for option in options:
		var movement: Dictionary = option
		if String(movement.get("axis", "")) != axis:
			return ""
	return axis


## Icon id for a node's mark: the axis for a task that has one, the node type
## otherwise. `assets/icons` carries all six axes already.
static func mark_of(node: Dictionary, fallback: String) -> String:
	if String(node.get("type", "")) == "task":
		var axis := axis_of(node)
		if axis != "" and HJUI.has_icon(axis):
			return axis
	return fallback


## Mirrors `Game.complete_task`: base grit times the run multiplier times the
## streak. The partial-scale penalty is deliberately *not* applied — it is a
## choice the player has not made yet, so this is what the node pays for doing
## it as written, which is the honest headline.
## What a task pays. **The only implementation** — `Game.complete_task` calls
## this rather than keeping its own copy, because a preview that promises one
## number while the payer computes another is worse than no preview at all, and
## two copies of an arithmetic chain drift the first time anybody tunes it.
##
## `scaled` is the partial-credit case; `axis_override` is for the payer, which
## knows the axis of the movement the player actually chose. A preview only has
## the node's token, and for `$same` that is not yet an answer.
static func task_grit(run: HJRun, node: Dictionary, scaled: bool = false,
		axis_override: String = "") -> int:
	var axis := axis_override if axis_override != "" else axis_of(node)
	var ctx: Dictionary = run.ctx({"axis": axis}) if axis != "" else run.ctx()
	var multiplier: float = Rules.value("run.grit_mult", ctx, 1.0) * Meta.streak_multiplier()
	if scaled:
		multiplier *= clampf(Rules.value("task.partial_grit", ctx, 0.6), 0.0, 1.0)
	return maxi(1, int(round(float(node.get("grit", 5)) * multiplier)))


## Mirrors the `cache` arm of `Game.tap_node`.
static func cache_grit(run: HJRun, node: Dictionary) -> int:
	var multiplier: float = Rules.value("loot.cache_mult", run.ctx(), 1.0)
	return int(round(float(node.get("grit", 10)) * multiplier))


## Mirrors `HJSurvey.option_grit` across every option. A question whose answers
## pay differently returns a spread, because that spread is the decision.
static func choice_grit(node: Dictionary) -> Vector2i:
	var options: Array = node.get("options", [])
	if options.is_empty():
		return Vector2i(int(node.get("grit", 4)), int(node.get("grit", 4)))
	var low := 1 << 30
	var high := -(1 << 30)
	for entry in options:
		var option: Dictionary = entry
		var value: int = HJSurvey.option_grit(node, option)
		low = mini(low, value)
		high = maxi(high, value)
	return Vector2i(low, high)


## The reward line for a card: "+7", "+4–9", or "" when nothing is promised.
static func reward_text(run: HJRun, node: Dictionary) -> String:
	if run == null:
		return ""
	match String(node.get("type", "")):
		"task":
			return "+%d" % task_grit(run, node)
		"cache":
			return "+%d" % cache_grit(run, node)
		"choice":
			var span := choice_grit(node)
			if span.x == span.y:
				return "+%d" % span.x
			return "+%d–%d" % [span.x, span.y]
	return ""
