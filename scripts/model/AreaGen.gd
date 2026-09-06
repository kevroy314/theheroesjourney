class_name HJAreaGen
extends RefCounted
## Turns an authored area definition into a playable instance: the fixed spine
## as written, plus whatever side nodes the slot tables rolled this time.

const SIDE_PREFIX := "side_"


static func build(area_def: Dictionary, rng: RandomNumberGenerator, ctx: Dictionary) -> Dictionary:
	var nodes: Dictionary = {}
	var order: Array = []

	for n in area_def.get("nodes", []):
		var node: Dictionary = (n as Dictionary).duplicate(true)
		node["side_of"] = ""
		nodes[node["id"]] = node
		order.append(node["id"])

	var entry := String(order[0]) if order.size() > 0 else ""

	# Side nodes. Each slot rolls independently; area.slot_bonus grants extra
	# guaranteed rolls on top (Wanderer's Charm, the Wanderer trait).
	var bonus := Rules.value_int("area.slot_bonus", ctx, 0)
	var slots: Array = area_def.get("slots", [])
	var index := 0
	for slot_variant in slots:
		var slot: Dictionary = slot_variant
		var rolls := 1
		var guaranteed := false
		if bonus > 0:
			bonus -= 1
			guaranteed = true
		if not guaranteed and rng.randf() > float(slot.get("chance", 0.5)):
			continue
		for _i in range(rolls):
			var picked := _pick(slot.get("table", []), rng)
			if picked.is_empty():
				continue
			index += 1
			var node := _make_side(picked, String(slot.get("attach", entry)), index)
			nodes[node["id"]] = node
			order.append(node["id"])

	return {
		"id": area_def.get("id", ""),
		"name": area_def.get("name", "Area"),
		"intro": area_def.get("intro", ""),
		"outro": area_def.get("outro", ""),
		# What the memory claims about itself. Carried through the build because
		# the screen frames the whole area with it, and an area instance that
		# does not know what it is claiming cannot be framed.
		"truth": area_def.get("truth", ""),
		"entry": entry,
		"nodes": nodes,
		"order": order,
	}


static func _make_side(picked: Dictionary, attach: String, index: int) -> Dictionary:
	var node: Dictionary = picked.duplicate(true)
	node.erase("w")
	node["id"] = "%s%d" % [SIDE_PREFIX, index]
	node["side_of"] = attach
	node["next"] = []
	if not node.has("label"):
		node["label"] = _default_label(String(node.get("type", "cache")))
	if node.get("type", "") == "task" and node.has("movement"):
		node["task"] = { "movement": node["movement"], "units": node.get("units", 1) }
	return node


static func _default_label(type_id: String) -> String:
	match type_id:
		"echo": return "Something Half-Remembered"
		"cache": return "Worth Picking Up"
		"mirror": return "A Reflection"
		"trinket": return "A Charm"
		"spite": return "Spite"
	return "Aside"


static func _pick(table: Array, rng: RandomNumberGenerator) -> Dictionary:
	var total := 0.0
	for entry in table:
		total += float(entry.get("w", 1))
	if total <= 0.0:
		return {}
	var roll := rng.randf() * total
	for entry in table:
		roll -= float(entry.get("w", 1))
		if roll <= 0.0:
			return entry
	return table[table.size() - 1]


# --- graph queries -------------------------------------------------------------

## Nodes that must be finished before `id` opens.
static func predecessors(area: Dictionary, id: String) -> Array:
	var out: Array = []
	for other_id in area.get("nodes", {}).keys():
		var other: Dictionary = area["nodes"][other_id]
		if (other.get("next", []) as Array).has(id):
			out.append(other_id)
	return out


## Which branch of a `select_next` fork the run has earned.
##
## `exclusive_next` is the *player* choosing: they tap one branch and the
## siblings close. `select_next` is the *memory* choosing: the branches are
## tried in the order they are written and the first whose `when` passes is the
## one that opens. That is the whole mechanism behind the survey ending in an
## action the answers picked rather than in a sixth question — the answers are
## run tags, `when` is the condition language that already reads tags, and
## nothing new had to be invented to join them up.
##
## Returns "" when the fork is not a select_next one, or when nothing matched.
## Nothing matching means every branch closes, so a fork like this must end in a
## branch carrying no `when` at all.
static func chosen_branch(run: HJRun, fork_id: String) -> String:
	var fork := run.node(fork_id)
	if not bool(fork.get("select_next", false)):
		return ""
	for nxt in fork.get("next", []):
		var id := String(nxt)
		if Rules.passes(run.node(id).get("when", {}), run.ctx()):
			return id
	return ""


## A road the run has shut: this node's own `when` fails, or a fork above it
## picked a different branch.
##
## Only ever true once something upstream is actually finished. Before that a
## node is not shut, it is simply not reached yet, and the difference matters on
## screen: a card that says "not what you said" before you have said anything
## has told the player how the fork ends before they answer it.
static func is_closed(run: HJRun, id: String) -> bool:
	if run.is_done(id) or run.locked.has(id):
		return false
	var node := run.node(id)
	if node.is_empty():
		return false
	var decided := false
	for pred in predecessors(run.area, id):
		if not run.is_done(pred):
			continue
		decided = true
		if bool(run.node(pred).get("select_next", false)) \
				and chosen_branch(run, pred) != id:
			return true
	if not decided:
		return false
	return not Rules.passes(node.get("when", {}), run.ctx())


static func is_available(run: HJRun, id: String) -> bool:
	if run.is_done(id) or run.locked.has(id):
		return false
	var node := run.node(id)
	if node.is_empty():
		return false
	if is_closed(run, id):
		return false
	var side_of := String(node.get("side_of", ""))
	if side_of != "":
		return run.is_done(side_of)
	for pred in predecessors(run.area, id):
		# A locked predecessor is a road not taken, not a road still to walk —
		# without this an exclusive fork strands everything downstream of it.
		# A closed one is the same thing decided by the run rather than by the
		# player, and strands its downstream in exactly the same way.
		if not run.is_done(pred) and not run.locked.has(pred) and not is_closed(run, pred):
			return false
	return true


## Side nodes stay hidden until their anchor is done, unless a Lens is burning.
static func is_visible(run: HJRun, id: String) -> bool:
	if run.revealed or Rules.value_int("area.reveal_sides", run.ctx(), 0) > 0:
		return true
	var node := run.node(id)
	var side_of := String(node.get("side_of", ""))
	if side_of == "":
		return true
	return run.is_done(side_of) or run.is_done(id)


static func available_ids(run: HJRun) -> Array:
	var out: Array = []
	for id in run.area.get("order", []):
		if is_available(run, String(id)):
			out.append(String(id))
	return out
