class_name HJAreaGraph
extends VBoxContainer
## The area as a tree you walk down: entry at the top, the door at the bottom,
## branches side by side. Layout is done by containers and the link lines are
## drawn from the cards' real rects, so nothing here can drift out of step.

signal node_tapped(id: String)

## Node type -> icon in assets/icons. A node with no mark falls back to the
## theme's glyph, so a theme can still ship its own vocabulary.
const NODE_ICONS := {
	"task": "task", "threshold": "threshold", "echo": "echo", "cache": "cache",
	"mirror": "mirror", "trinket": "charm", "spite": "spite", "warden": "warden",
}

var run: HJRun
var _rows: Array = []       ## Array of Array[Control], top to bottom
var _cards: Dictionary = {} ## node id -> card


func _init(run_ref: HJRun) -> void:
	run = run_ref
	add_theme_constant_override("separation", 26)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL


func _ready() -> void:
	_build()
	sort_children.connect(queue_redraw)


func _depths() -> Dictionary:
	var depth: Dictionary = {}
	var entry := String(run.area.get("entry", ""))
	if entry == "":
		return depth
	var frontier: Array = [entry]
	depth[entry] = 0
	var guard := 0
	while frontier.size() > 0 and guard < 500:
		guard += 1
		var id: String = frontier.pop_front()
		for nxt in run.node(id).get("next", []):
			var next_id := String(nxt)
			var d := int(depth[id]) + 1
			if not depth.has(next_id) or int(depth[next_id]) < d:
				depth[next_id] = d
				frontier.append(next_id)
	# Side nodes ride along with whatever they hang off.
	for id in run.area.get("order", []):
		var node := run.node(String(id))
		var anchor := String(node.get("side_of", ""))
		if anchor != "" and depth.has(anchor):
			depth[String(id)] = int(depth[anchor])
	return depth


func _build() -> void:
	var depth := _depths()
	var by_row: Dictionary = {}
	for id in run.area.get("order", []):
		var key := int(depth.get(String(id), 0))
		var row: Array = by_row.get(key, [])
		row.append(String(id))
		by_row[key] = row

	var keys: Array = by_row.keys()
	keys.sort()
	for key in keys:
		var row_box := HBoxContainer.new()
		row_box.add_theme_constant_override("separation", 14)
		row_box.alignment = BoxContainer.ALIGNMENT_CENTER
		row_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var controls: Array = []
		for id in by_row[key]:
			var card := _make_card(String(id))
			row_box.add_child(card)
			controls.append(card)
			_cards[String(id)] = card
		_rows.append(controls)
		add_child(row_box)


func _make_card(id: String) -> Control:
	var node := run.node(id)
	var type_id := String(node.get("type", "free"))
	var done := run.is_done(id)
	var locked := run.locked.has(id)
	var available := HJAreaGen.is_available(run, id)
	var visible_now := HJAreaGen.is_visible(run, id)

	var card := HJUI.TapCard.new()
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.custom_minimum_size.y = 104

	var fill := Palette.c("panel")
	var border := Palette.ca("line", 0.7)
	var title_role := "muted"
	var glyph := Palette.glyph(type_id)
	var title := String(node.get("label", "?"))
	var sub := _descriptor(node)

	if not visible_now:
		glyph = Palette.glyph("locked")
		title = "Something Here"
		sub = "not yet"
		fill = Palette.ca("panel", 0.5)
	elif done:
		glyph = Palette.glyph("done")
		title_role = "good"
		border = Palette.ca("good", 0.5)
		sub = "done"
	elif locked:
		fill = Palette.ca("panel", 0.5)
		sub = "the other way"
	elif available:
		fill = Palette.c("panel_alt")
		border = Palette.c("accent")
		title_role = "text"
	else:
		fill = Palette.ca("panel", 0.7)

	if type_id == "threshold" and not done:
		border = Palette.c("accent_2") if available else border
	if type_id == "warden":
		border = Palette.c("danger")
		title_role = "danger" if available else title_role

	# The box is chalk: scratched onto the floor of a room the loop is going to
	# take back. The fill is a wash rather than a panel, so the room reads
	# through it — you are looking at marks on the boards, not at a widget.
	var wash := Color(fill.r, fill.g, fill.b, fill.a * 0.55)
	card.add_theme_stylebox_override("panel", HJUI.stylebox(wash, 4, Color(0, 0, 0, 0), 0))
	var sb: StyleBoxFlat = card.get_theme_stylebox("panel")
	sb.content_margin_top = 12
	sb.content_margin_bottom = 12
	sb.content_margin_left = 14
	sb.content_margin_right = 14
	card.add_child(HJUI.nine("chalk", border))

	var v := HJUI.vbox(2)
	var top := HJUI.hbox(8)
	var mark_role := "accent" if available else "muted"
	var mark_id := "done" if done else String(NODE_ICONS.get(type_id, ""))
	if not visible_now:
		mark_id = ""
	if HJUI.has_icon(mark_id):
		if done:
			mark_role = "good"
		top.add_child(HJUI.icon(mark_id, 32, mark_role))
	else:
		var glyph_label := HJUI.label(glyph, HJUI.FS_BODY, mark_role)
		glyph_label.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		top.add_child(glyph_label)
	top.add_child(HJUI.label(title, HJUI.FS_SMALL, title_role))
	v.add_child(top)
	if sub != "":
		v.add_child(HJUI.label(sub, HJUI.FS_TINY, "muted"))
	card.add_child(v)

	if available:
		var node_id := id
		card.tapped.connect(func() -> void: node_tapped.emit(node_id))
	else:
		card.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return card


## Short "what does this ask of me" line under a node's name.
func _descriptor(node: Dictionary) -> String:
	match String(node.get("type", "")):
		"task":
			var options := Game.movement_options(node)
			if options.is_empty():
				return "a movement"
			if options.size() > 1:
				return "choose · %d options" % options.size()
			var movement: Dictionary = options[0]
			var units := Game.task_units(node, movement)
			return "%s · %d %s" % [movement.get("name", "?"), units, _plural(String(movement.get("unit", "rep")), units)]
		"threshold": return "the way out"
		"echo": return Palette.word("echo").to_lower()
		"cache": return "something to pocket"
		"mirror": return "a reflection"
		"trinket": return Palette.word("trinket").to_lower()
		"spite": return "someone is here"
		"warden": return "the end of the loop"
	return ""


static func _plural(unit: String, count: int) -> String:
	if count == 1:
		return unit
	if unit.ends_with("s"):
		return unit
	return unit + "s"


func _draw() -> void:
	if run == null or _rows.size() < 2:
		return
	for row_index in range(_rows.size() - 1):
		for card in _rows[row_index]:
			var from := Vector2(
				card.get_parent().position.x + card.position.x + card.size.x * 0.5,
				card.get_parent().position.y + card.position.y + card.size.y)
			for other in _rows[row_index + 1]:
				var to := Vector2(
					other.get_parent().position.x + other.position.x + other.size.x * 0.5,
					other.get_parent().position.y + other.position.y)
				draw_line(from, to, Palette.ca("line", 0.55), 2.0, true)
