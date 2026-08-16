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

## Cards are sized to what they say and centred, never stretched to the frame.
## A column of full-width rounded rectangles is a settings screen no matter what
## texture you put on it — the width itself is the tell. Chalk on a floor is
## whatever size the thing you wrote needed to be.
const CARD_MIN := 200.0
const CARD_MAX := 360.0
const NUDGE := 26.0         ## how far off centre a card may sit
const TILT := 0.034         ## radians, about 2 degrees
const FRAME := 720.0        ## logical canvas width the layout has to fit inside
const GUTTER := 44.0        ## page margins plus a little air at each edge

var run: HJRun
var _rows: Array = []       ## Array of Array[Control], top to bottom
var _cards: Dictionary = {} ## node id -> card


func _init(run_ref: HJRun) -> void:
	run = run_ref
	add_theme_constant_override("separation", 34)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL


func _ready() -> void:
	_build()
	sort_children.connect(queue_redraw)


## A stable pseudo-random in [0,1) for a node. Stable is the point: the jitter
## has to survive a rebuild or the whole board twitches every time anything
## changes, which reads as a rendering fault rather than a hand.
static func _wobble(id: String, salt: int) -> float:
	var h := hash(id + "/" + str(salt))
	return float(h % 10007) / 10007.0


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
		row_box.add_theme_constant_override("separation", 12)
		row_box.alignment = BoxContainer.ALIGNMENT_CENTER
		row_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		# Cards are free to be whatever width their text wants, but a row still
		# has to fit the frame. Without this the widest row silently stretches
		# the whole column past the viewport and every label on the screen wraps
		# against a rect nobody can see.
		var row_ids: Array = by_row[key]
		var count := row_ids.size()
		var budget := (FRAME - GUTTER - 12.0 * float(count - 1)) / float(count) - NUDGE

		var controls: Array = []
		for id in by_row[key]:
			var node_id := String(id)
			var card := _make_card(node_id, budget)
			# Off-centre by a stable amount. Containers own position, so the nudge
			# has to be margin rather than a poke at the card's own transform.
			var lean := (_wobble(node_id, 3) - 0.5) * 2.0 * NUDGE
			var holder := HJUI.margins(int(maxf(0.0, lean)), 0, int(maxf(0.0, -lean)), 0)
			holder.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
			holder.size_flags_vertical = Control.SIZE_SHRINK_CENTER
			holder.add_child(card)
			row_box.add_child(holder)
			controls.append(card)
			_cards[node_id] = card
		_rows.append(controls)
		add_child(row_box)


func _make_card(id: String, budget: float = CARD_MAX) -> Control:
	var node := run.node(id)
	var type_id := String(node.get("type", "free"))
	var done := run.is_done(id)
	var locked := run.locked.has(id)
	var available := HJAreaGen.is_available(run, id)
	var visible_now := HJAreaGen.is_visible(run, id)

	var card := HJUI.TapCard.new()
	card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	card.size_flags_vertical = Control.SIZE_SHRINK_CENTER

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
	sb.content_margin_top = 14
	sb.content_margin_bottom = 14
	sb.content_margin_left = 16
	sb.content_margin_right = 16
	# One of four hands, picked by the node's own id, so neighbours differ but a
	# node keeps its box across rebuilds.
	card.add_child(HJUI.nine("chalk_%d" % (hash(id) % 4), border))

	# Sized to what it says — the long "choose · 16 options" nodes get to be wide
	# and the bare ones stay small. Title and subtitle are set at different sizes,
	# so they are measured at different rates rather than by raw character count.
	var wanted := 104.0 \
		+ maxf(float(title.length()) * 12.5, float(sub.length()) * 9.5) \
		+ _wobble(id, 1) * 40.0
	var ceiling := maxf(CARD_MIN, minf(CARD_MAX, budget))
	# Height wanders a little too. Boxes that are all exactly one height read as
	# rows in a table however rough their edges are.
	card.custom_minimum_size = Vector2(
		clampf(wanted, CARD_MIN, ceiling), 92.0 + _wobble(id, 4) * 18.0)

	# A hand-drawn box is never quite square to the wall. Rotation is applied
	# after the container has sized the card, since containers own size but not
	# transform.
	var tilt := (_wobble(id, 2) - 0.5) * 2.0 * TILT
	card.resized.connect(func() -> void:
		card.pivot_offset = card.size * 0.5
		card.rotation = tilt)

	# Written down one after another, top of the tree first, the way you would
	# actually chalk a plan onto a floor.
	if Debug.knob("motion") > 0.0:
		card.modulate.a = 0.0
		card.ready.connect(func() -> void:
			var delay := 0.035 * float(_cards.size())
			var tween := card.create_tween()
			tween.tween_interval(delay)
			tween.tween_property(card, "modulate:a", 1.0, 0.16))

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


## Where a card sits in this control's own space. The card is two containers
## deep and none of the ancestors rotate, so subtracting origins is enough.
func _rect_of(card: Control) -> Rect2:
	return Rect2(card.get_global_position() - get_global_position(), card.size)


## The links, following the real `next` edges rather than joining every card in
## one row to every card in the next. With full-width boxes that shortcut was
## invisible; with narrow centred ones it would draw a lie.
func _draw() -> void:
	if run == null or _cards.is_empty():
		return
	for id in _cards:
		var from_card: Control = _cards[id]
		if not is_instance_valid(from_card):
			continue
		var a := _rect_of(from_card)
		for nxt in run.node(String(id)).get("next", []):
			var to_card: Control = _cards.get(String(nxt), null)
			if to_card == null or not is_instance_valid(to_card):
				continue
			var b := _rect_of(to_card)
			if b.position.y <= a.position.y:
				continue        # a side node hanging off its anchor, not a step down
			var done := run.is_done(String(id))
			var role := "accent" if done else "muted"
			var alpha := 0.85 if done else 0.55
			_chalk_line(
				Vector2(a.position.x + a.size.x * 0.5, a.position.y + a.size.y),
				Vector2(b.position.x + b.size.x * 0.5, b.position.y),
				Palette.ca(role, alpha), String(id) + String(nxt))


## A line drawn the way the boxes are: short strokes with gaps and a wandering
## middle, not a straight rule. The wander is hashed off the edge's own name so
## it holds still between frames.
func _chalk_line(from: Vector2, to: Vector2, colour: Color, seed_key: String) -> void:
	var span := to - from
	var normal := Vector2(-span.y, span.x).normalized()
	var bow := (_wobble(seed_key, 5) - 0.5) * 18.0
	var steps := 14
	var prev := from
	for i in range(1, steps + 1):
		var t := float(i) / float(steps)
		var arc := sin(t * PI) * bow
		var point := from + span * t + normal * arc
		# Skip roughly one stroke in five: chalk does not lay down continuously.
		if _wobble(seed_key, 20 + i) > 0.2:
			draw_line(prev, point, colour, 3.0, false)
		prev = point
