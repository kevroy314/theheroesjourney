class_name HJOutcomes
extends RefCounted
## What a resolved node yields.
##
## Every branch of `Game.tap_node` that is not "open a task screen" ends up
## here: loot tables, echoes, the mirror, Spite, trinket offers, the Warden.
## They were all methods on Game, which made Game the file you had to read to
## answer any question at all — including "what does a cache actually pay?",
## which has nothing to do with run lifecycle.
##
## The split is by ownership, not by size. Game owns run state and screen
## transitions; this owns the content-driven consequences of touching a node.
## Everything here reaches back through `g` rather than the `Game` global, so
## the dependency is visible in the constructor instead of hidden in the body.
## `g` is typed `Node`, which makes everything reached through it a Variant —
## so anything derived from `g.rng` or `g.run` needs its type spelled out. `:=`
## has nothing to infer from and fails to *compile*, which is worse than it
## sounds: the class then does not exist, `HJOutcomes.new()` returns null, and
## the errors you actually see are a dozen "nonexistent function" calls a long
## way from the line at fault.

var g: Node   ## the Game autoload


func _init(game: Node) -> void:
	g = game


# --- loot ----------------------------------------------------------------------

## Roll one entry from a weighted table and hand it over.
func roll_loot(table_id: String) -> void:
	var table: Array = Content.loot.get(table_id, [])
	if table.is_empty():
		return
	var ctx: Dictionary = g.run.ctx()
	var total := 0.0
	var weights: Array = []
	for entry in table:
		var w := float(entry.get("w", 1))
		if entry.has("scaled_by"):
			w *= Rules.value(String(entry["scaled_by"]), ctx, 1.0)
		weights.append(w)
		total += w
	if total <= 0.0:
		return
	var roll: float = g.rng.randf() * total
	for i in range(table.size()):
		roll -= float(weights[i])
		if roll <= 0.0:
			_award(table[i])
			return


func _award(entry: Dictionary) -> void:
	match String(entry.get("type", "")):
		"grit":
			var amount := int(round(float(entry.get("amount", 5))
				* Rules.value("run.grit_mult", g.run.ctx(), 1.0)))
			g.add_grit(amount)
			g.say("+%d %s" % [amount, Palette.word("grit")], "good")
		"echo":
			give_echo()
		"trinket":
			offer_boons()
		"item":
			var item_id := Meta.random_item(g.rng)
			if item_id != "":
				Meta.give_item(item_id)
				g.say("Found: %s" % Content.item(item_id).get("name", item_id), "good")


# --- story -----------------------------------------------------------------------

func give_echo() -> void:
	var id := Meta.next_echo_id()
	if id == "":
		g.add_grit(10)
		g.say("Nothing new in it, but you pocket something anyway.", "info")
		return
	Meta.find_echo(id)
	if not g.run.echoes.has(id):
		g.run.echoes.append(id)
	var e := Content.echo(id)
	g.show_event({
		"kind": "echo",
		"title": String(e.get("title", Palette.word("echo"))),
		"text": String(e.get("text", "")),
		"footer": "%s %d of %d — kept in the Codex" % [Palette.word("echo"),
			int(e.get("order", 0)), Content.echoes.size()],
	})


func mirror() -> void:
	var lines := [
		"You catch yourself in the glass. The reflection arrives a beat after you do.",
		"For a moment the face is yours with twenty more years on it. Then it isn't.",
		"Your reflection finishes the movement slightly before you start it.",
	]
	g.show_event({
		"kind": "mirror",
		"title": "A Reflection",
		"text": String(lines[g.rng.randi_range(0, lines.size() - 1)]),
		"footer": Palette.data.get("mountain_line", ""),
	})
	_reveal_once("first_mirror")


# --- spite ---------------------------------------------------------------------

func spite() -> void:
	var data: Dictionary = Content.spite
	var events: Array = data.get("events", [])
	if events.is_empty():
		return

	if g.run.ward:
		g.run.ward = false
		g.show_event({"kind": "spite", "title": "Spite",
			"text": String(data.get("warded", "")), "footer": ""})
		return

	var kind_weight := Rules.value("spite.kind_weight", g.run.ctx(), 1.0)
	if g.run.kind_spite:
		kind_weight = 999.0
		g.run.kind_spite = false

	var total := 0.0
	var weights: Array = []
	for e in events:
		var w := float(e.get("weight", 1))
		if String(e.get("alter", "")) == "kind":
			w *= kind_weight
		weights.append(w)
		total += w

	var roll: float = g.rng.randf() * total
	var picked: Dictionary = events[events.size() - 1]
	for i in range(events.size()):
		roll -= float(weights[i])
		if roll <= 0.0:
			picked = events[i]
			break

	var alter_line := ""
	for alter in data.get("alters", []):
		if alter.get("id", "") == picked.get("alter", ""):
			alter_line = String(alter.get("line", ""))

	_apply_spite_effect(picked.get("effect", {}))
	g.show_event({
		"kind": "spite",
		"title": "Spite",
		"text": alter_line + "\n\n" + String(picked.get("text", "")),
		"footer": "",
	})
	_reveal_once("first_spite")


func _apply_spite_effect(effect: Dictionary) -> void:
	match String(effect.get("type", "")):
		"grit":
			var amount := int(effect.get("amount", 0))
			g.add_grit(amount)
			g.say("%+d %s" % [amount, Palette.word("grit")], "good" if amount > 0 else "bad")
		"item":
			var id := Meta.random_item(g.rng)
			if id != "":
				Meta.give_item(id)
				g.say("Spite left you a %s." % Content.item(id).get("name", id), "good")
		"steal_item":
			var held: Array = Meta.inventory.keys()
			if held.size() > 0:
				var id := String(held[g.rng.randi_range(0, held.size() - 1)])
				Meta.take_item(id)
				g.say("Your %s is gone." % Content.item(id).get("name", id), "bad")
		"trinket":
			offer_boons()
		"reveal_area":
			g.run.revealed = true
		"hide_area":
			g.run.revealed = false
		"deadline":
			g.run.deadline_unix += HJClock.hours_to_seconds(float(effect.get("amount", -1)))
			Notify.sync()


# --- the Warden ----------------------------------------------------------------

## The one node that can end a run rather than pay out.
func warden(id: String) -> void:
	if not Meta.seen_warden:
		Meta.seen_warden = true
		Meta.find_echo(String(Content.echo_reveals.get("reach_summit", "e14")))
		Meta.save_game()
		g.summary_event_then_end(
			"The Warden of the Loop",
			"They turn around, and it is your face, thirty years further on, and they are not surprised to see you.\n\n\"Every morning you got back,\" they say, \"you got back because I sent it. You are not being punished. You are being built.\"\n\nThey are kind about it. That is the worst part.\n\n\"Not yet,\" they say. \"Come back when you are looking after all of it.\"",
			"loop")
		return

	if not Meta.balance_unlocked():
		g.summary_event_then_end(
			"Not Yet",
			"The Warden looks at you for a long moment and shakes their head.\n\n\"You are strong in one direction. That is not the same as being ready.\"\n\nBalance the Wheel — every spoke off the mark — and the door will open.",
			"loop")
		return

	g.finish_node(id)
	g.show_event({
		"kind": "warden",
		"title": "The Loop Opens",
		"text": "\"There it is,\" they say, and they sound relieved, and they sound tired.\n\n\"You looked after all of it. That is the whole trick. I can stop now.\"\n\nThey step aside.",
		"footer": "",
	})


# --- boons ---------------------------------------------------------------------

func offer_boons(count: int = 3) -> void:
	var pool: Array = []
	for id in Content.trinkets.keys():
		if not g.run.trinkets.has(id):
			pool.append(id)
	if pool.is_empty():
		g.add_grit(15)
		return
	pool.shuffle()
	g.run.pending_boons = pool.slice(0, mini(count, pool.size()))
	g.goto("boon")


func take_boon(trinket_id: String) -> void:
	if trinket_id != "":
		g.run.trinkets.append(trinket_id)
		g.rebuild_rules()
		g.say("Gained %s." % Content.trinkets.get(trinket_id, {}).get("name", trinket_id), "good")
	g.run.pending_boons = []
	g.changed()
	g.goto("area")


## Hand over a story fragment the first time something happens, and never again.
func _reveal_once(key: String) -> void:
	var reveal := String(Content.echo_reveals.get(key, ""))
	if reveal != "" and not Meta.codex.has(reveal):
		Meta.find_echo(reveal)
