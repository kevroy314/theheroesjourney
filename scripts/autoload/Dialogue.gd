extends Node
## Someone is talking to you.
##
## A conversation is data: a speaker, a graph of nodes, each node a few lines
## and then either a way on or a set of replies. This file is the state machine
## that walks it; `DialogueScreen` is one way of rendering the state, and not
## the only one it has to be.
##
## Two things it deliberately does *not* invent:
##
##   * **conditions.** A reply's `when` is the same dictionary a modifier's
##     `when` is, evaluated by `Rules.passes` against the run context. The repo
##     has one condition evaluator and it stays that way, so `zone_gte` means
##     the same thing on a trinket and in a sentence.
##   * **effects.** A line or a reply hands its `effects` to
##     `Objectives.apply_effects`, which delegates `grit` and `deadline` back to
##     `Game.apply_effects`. Nothing pays grit twice in two ways.
##
## What is new is only the shape: an ordered set of lines, and branches.
##
## `seen` is persisted in its own small file so a `once: true` conversation is
## once across the whole save, not once per run. `Meta.wipe()` should call
## `Dialogue.wipe()` — see the report.

signal changed()                              ## the visible line moved
signal finished(dialogue_id: String)          ## the conversation ended

## The screen key this expects to be registered under in Main.SCREENS. Nothing
## here registers it; `open()` will fail loudly until somebody does.
const SCREEN := "dialogue"

const PATH := "user://dialogue.json"
const VERSION := 1

var path := PATH
var seen: Dictionary = {}      ## dialogue id -> true, once it has run to the end

var _id := ""
var _node_id := ""
var _line := 0
var _fired: Dictionary = {}    ## node ids whose effects have already run


func _ready() -> void:
	load_store()


# --- definitions ---------------------------------------------------------------

func definition(id: String) -> Dictionary:
	return Content.dialogues.get(id, {})


func speaker(id: String) -> Dictionary:
	return Content.speakers.get(id, {})


func node_of(dialogue_id: String, node_id: String) -> Dictionary:
	for n in definition(dialogue_id).get("nodes", []):
		if String((n as Dictionary).get("id", "")) == node_id:
			return n
	return {}


## Is this conversation available to start? A `once` conversation that has
## already run is not.
func available(id: String) -> bool:
	var doc := definition(id)
	if doc.is_empty():
		return false
	return not (bool(doc.get("once", false)) and seen.has(id))


# --- running one ---------------------------------------------------------------

func active() -> bool:
	return _id != ""


func current_id() -> String:
	return _id


## Begin a conversation. Does not change screen — the caller decides whether
## this one is worth interrupting for. Returns false if it does not exist, is
## already spent, or is empty.
func start(id: String) -> bool:
	if not available(id):
		return false
	var doc := definition(id)
	var first := String(doc.get("start", ""))
	if first == "" and not (doc.get("nodes", []) as Array).is_empty():
		first = String((doc["nodes"][0] as Dictionary).get("id", ""))
	if node_of(id, first).is_empty():
		push_warning("Dialogue: '%s' has no start node" % id)
		return false
	_id = id
	_fired = {}
	_enter(first)
	return true


## Start it and go there. Needs `Main.SCREENS` to carry a "dialogue" entry.
func open(id: String) -> bool:
	if not start(id):
		return false
	Game.goto(SCREEN)
	return true


## Everything a screen needs to draw the current beat, in one dictionary so the
## screen never reaches into this file's state.
##
##   speaker / speaker_name / portrait / mood / accent
##   text            the line on screen now
##   line / lines    1-based position within the node
##   replies         [{ index, text }], empty until the last line of the node
##   can_continue    true when a tap should advance rather than choose
##   done            true when there is nothing left (the conversation ended)
func current() -> Dictionary:
	if _id == "":
		return {"done": true}
	var node := node_of(_id, _node_id)
	var lines: Array = node.get("lines", [])
	var speaker_id := String(node.get("speaker", definition(_id).get("speaker", "")))
	var who := speaker(speaker_id)
	var mood := String(node.get("mood", who.get("mood", "")))
	var last := _line >= lines.size() - 1
	var replies := visible_replies() if last else []
	return {
		"dialogue": _id,
		"node": _node_id,
		"speaker": speaker_id,
		"speaker_name": String(who.get("name", speaker_id)),
		"portrait": portrait_path(speaker_id, mood),
		"mood": mood,
		"accent": String(who.get("accent", "accent")),
		"text": "" if lines.is_empty() else String(lines[mini(_line, lines.size() - 1)]),
		"line": _line + 1,
		"lines": lines.size(),
		"replies": replies,
		"can_continue": replies.is_empty(),
		"done": false,
	}


## The replies whose `when` passes right now. Index is the position in the
## node's own list, so `choose()` takes the same number back.
func visible_replies() -> Array:
	var out: Array = []
	var node := node_of(_id, _node_id)
	var all: Array = node.get("replies", [])
	for i in range(all.size()):
		var reply: Dictionary = all[i]
		if not Rules.passes(reply.get("when", {}), context()):
			continue
		out.append({"index": i, "text": String(reply.get("text", "…"))})
	return out


## The run context conditions are evaluated against. Outside a run there is no
## HJRun to ask, and a conversation on the title screen should still resolve
## rather than crash, so the shape is filled in with the honest defaults.
func context() -> Dictionary:
	var run: HJRun = Game.run
	if run != null:
		return run.ctx()
	return {"zone": Meta.deepest_ring, "area": "", "trinkets": [], "tags": []}


## Tap-through. Moves to the next line, and past the last line follows the
## node's `next` — or ends, when the node has neither `next` nor replies.
func advance() -> void:
	if _id == "":
		return
	var node := node_of(_id, _node_id)
	var lines: Array = node.get("lines", [])
	if _line < lines.size() - 1:
		_line += 1
		changed.emit()
		return
	if not visible_replies().is_empty():
		return          # the player owes an answer
	var next := String(node.get("next", ""))
	if next == "" or node_of(_id, next).is_empty():
		_end()
		return
	_enter(next)


## Take reply `index`, as numbered by `visible_replies()`.
func choose(index: int) -> void:
	if _id == "":
		return
	var all: Array = node_of(_id, _node_id).get("replies", [])
	if index < 0 or index >= all.size():
		return
	var reply: Dictionary = all[index]
	if not Rules.passes(reply.get("when", {}), context()):
		return
	Objectives.apply_effects(reply.get("effects", []))
	var goto_id := String(reply.get("goto", ""))
	if goto_id == "" or node_of(_id, goto_id).is_empty():
		_end()
		return
	_enter(goto_id)


## Walk away mid-conversation. Does not mark it seen, so a forced encounter
## interrupted by the app closing is still owed.
func stop() -> void:
	_id = ""
	_node_id = ""
	_line = 0
	changed.emit()


func _enter(node_id: String) -> void:
	_node_id = node_id
	_line = 0
	var node := node_of(_id, node_id)
	# Once per conversation, not once per visit: a node reached twice through a
	# loop in the graph must not hand out the item twice.
	if not _fired.has(node_id):
		_fired[node_id] = true
		Objectives.apply_effects(node.get("effects", []))
	changed.emit()
	if bool(node.get("end", false)) and (node.get("lines", []) as Array).is_empty():
		_end()


func _end() -> void:
	var ended := _id
	if ended != "":
		seen[ended] = true
		save_store()
	_id = ""
	_node_id = ""
	_line = 0
	changed.emit()
	if ended != "":
		finished.emit(ended)


# --- the portrait seam ---------------------------------------------------------

## Where a speaker's art *will* live. None of it exists yet — Spite's design is
## unresolved — so this returns a path that is very likely absent and every
## caller must cope with that. The screen draws a lettered plate instead.
## Keeping the naming decided now means the art drops in without a code change.
func portrait_path(speaker_id: String, mood: String = "") -> String:
	var who := speaker(speaker_id)
	var stem := String(who.get("portrait", speaker_id))
	if stem == "":
		return ""
	if mood != "":
		return "res://assets/portraits/%s_%s.png" % [stem, mood]
	return "res://assets/portraits/%s.png" % stem


func has_portrait(speaker_id: String, mood: String = "") -> bool:
	var p := portrait_path(speaker_id, mood)
	return p != "" and ResourceLoader.exists(p)


# --- persistence ---------------------------------------------------------------

func use_path(new_path: String) -> void:
	path = new_path
	seen = {}
	load_store()


func load_store() -> void:
	seen = {}
	if not FileAccess.file_exists(path):
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Dictionary):
		return
	if int((parsed as Dictionary).get("version", 0)) != VERSION:
		return
	for id in ((parsed as Dictionary).get("seen", []) as Array):
		seen[String(id)] = true


func save_store() -> void:
	var tmp := path + ".tmp"
	var f := FileAccess.open(tmp, FileAccess.WRITE)
	if f == null:
		push_warning("Dialogue: could not write %s" % tmp)
		return
	f.store_string(JSON.stringify({"version": VERSION, "seen": seen.keys()}, "  "))
	f.close()
	var dir := DirAccess.open(path.get_base_dir())
	if dir == null or dir.rename(tmp.get_file(), path.get_file()) != OK:
		push_warning("Dialogue: could not replace %s" % path)


## Called from Meta.wipe(): a fresh save has not met anybody.
func wipe() -> void:
	seen = {}
	stop()
	save_store()


# --- self-check ----------------------------------------------------------------

## Everything wrong with the loaded conversations, as human-readable lines.
##
## The schema checks shape. This checks the two things it cannot: that every
## `goto` / `next` / `start` names a node in its own graph, and that every
## `when` speaks the vocabulary `Rules.passes` implements. Both fail silently
## otherwise — a dangling goto ends the conversation early and looks like
## authoring, and an unknown condition makes `Rules.passes` warn once and then
## pass, so the gated reply is simply always there.
func problems() -> Array[String]:
	var out: Array[String] = []
	var when_keys: Array = Content.schema().get("vocabulary", {}).get("when_keys", [])
	for id in Content.dialogues.keys():
		var doc: Dictionary = Content.dialogues[id]
		var where := "dialogue '%s'" % String(id)
		var ids: Dictionary = {}
		for n in doc.get("nodes", []):
			ids[String((n as Dictionary).get("id", ""))] = true
		if not ids.has(String(doc.get("start", ""))):
			out.append("%s: start '%s' names no node here" % [where, String(doc.get("start", ""))])
		if not Content.speakers.has(String(doc.get("speaker", ""))):
			out.append("%s: speaker '%s' is not defined" % [where, String(doc.get("speaker", ""))])
		for n in doc.get("nodes", []):
			var node: Dictionary = n
			var node_where := "%s node '%s'" % [where, String(node.get("id", "?"))]
			var next := String(node.get("next", ""))
			if next != "" and not ids.has(next):
				out.append("%s: next '%s' names no node here" % [node_where, next])
			var replies: Array = node.get("replies", [])
			if next != "" and not replies.is_empty():
				out.append("%s: has both `next` and replies, so `next` is unreachable"
					% node_where)
			if next == "" and replies.is_empty() and not bool(node.get("end", false)):
				out.append("%s: no next, no replies and not marked `end`, so it stops "
					% node_where + "the conversation without saying so")
			for r in replies:
				var reply: Dictionary = r
				var goto_id := String(reply.get("goto", ""))
				if goto_id != "" and not ids.has(goto_id):
					out.append("%s: reply '%s' goes to '%s', which names no node here"
						% [node_where, String(reply.get("text", "?")), goto_id])
				for key in (reply.get("when", {}) as Dictionary).keys():
					if not when_keys.has(String(key)):
						out.append("%s: reply condition '%s' is not implemented by Rules.passes"
							% [node_where, String(key)])
	return out
