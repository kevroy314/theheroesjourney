extends HJScreen
## The Mind Palace: home base, main menu, and a small placement puzzle.
##
## The only thing you carry between loops is yourself, so home is a place inside
## your own head. Rooms are bought with Resolve and placed on a tight grid —
## tight on purpose, because two rooms that pay a bonus for touching cannot all
## touch at once.

const MAX_CELL := 200.0
const GAP := 10

static var arranging := false
static var holding := ""      ## room id picked up, waiting for a cell


func register() -> String:
	return "palace"


func build() -> void:
	Meta.ensure_palace()
	var v := page(12)

	var head := HJUI.panel("panel")
	var hv := HJUI.vbox(10)
	var top := HJUI.hbox(10)
	top.add_child(HJUI.label("The Mind Palace", HJUI.FS_HEAD, "text"))
	var back := HJUI.button("Back", "quiet")
	back.custom_minimum_size = Vector2(120, 62)
	back.size_flags_horizontal = Control.SIZE_SHRINK_END
	back.pressed.connect(func(): Game.goto("title"))
	top.add_child(back)
	hv.add_child(top)

	var chips := HJUI.hbox(10)
	chips.add_child(HJUI.chip(Palette.word("resolve"), str(Meta.resolve), "accent", "resolve"))
	chips.add_child(HJUI.chip(Palette.word("streak"), "%d d" % Meta.streak, "accent_2", "streak"))
	chips.add_child(HJUI.chip("Rooms", "%d/%d" % [Meta.room_grid.size(), Content.rooms.size()], "muted"))
	hv.add_child(chips)
	head.add_child(hv)
	v.add_child(head)

	var scroll := HJUI.scroll()
	var body := HJUI.vbox(14)
	scroll.add_child(body)
	v.add_child(scroll)

	if holding != "":
		var hint := HJUI.panel("panel", "accent")
		hint.add_child(HJUI.label("Carrying %s — tap an empty space to set it down." %
			Content.room(holding).get("name", holding), HJUI.FS_SMALL, "accent"))
		body.add_child(hint)
	elif arranging:
		var hint2 := HJUI.panel("panel", "accent_2")
		hint2.add_child(HJUI.label("Tap a room to pick it up and move it.", HJUI.FS_SMALL, "accent_2"))
		body.add_child(hint2)

	body.add_child(_grid())

	var arrange := HJUI.button("Done arranging" if arranging else "Rearrange", "ghost")
	arrange.custom_minimum_size.y = 68
	arrange.pressed.connect(func() -> void:
		arranging = not arranging
		holding = ""
		refresh())
	body.add_child(arrange)

	_bonuses(body)
	_unplaced(body)
	_market(body)

	if Game.has_active_run():
		var resume := HJUI.button("Carry on", "primary")
		resume.pressed.connect(func(): Game.goto("area"))
		v.add_child(resume)
	else:
		var start := HJUI.button("Wake up", "primary")
		start.pressed.connect(func(): Game.start_run())
		v.add_child(start)


# --- the grid ------------------------------------------------------------------

func _grid() -> Control:
	var size_n := Meta.palace_size
	var available: float = minf(get_viewport_rect().size.x, 720.0) - 32.0
	var cell: float = minf(MAX_CELL, (available - float(GAP * (size_n - 1))) / float(size_n))

	var centre := HBoxContainer.new()
	centre.alignment = BoxContainer.ALIGNMENT_CENTER
	centre.size_flags_horizontal = Control.SIZE_EXPAND_FILL

	var grid := GridContainer.new()
	grid.columns = size_n
	grid.add_theme_constant_override("h_separation", GAP)
	grid.add_theme_constant_override("v_separation", GAP)
	centre.add_child(grid)

	for y in range(size_n):
		for x in range(size_n):
			grid.add_child(_cell(x, y, cell))
	return centre


func _cell(x: int, y: int, cell_size: float) -> Control:
	var id := Meta.room_at(x, y)
	var room := Content.room(id)
	var card := HJUI.TapCard.new()
	card.custom_minimum_size = Vector2(cell_size, cell_size)

	var fill := Palette.ca("bg", 0.55)
	var border := Palette.ca("line", 0.5)
	var glyph_role := "muted"

	if id != "":
		fill = Palette.c("panel_alt")
		border = Palette.c("accent") if not arranging else Palette.c("accent_2")
		glyph_role = "accent"
	elif holding != "":
		border = Palette.c("accent_2")

	var sb := HJUI.flat(fill, 12, border, 3 if (id != "" or holding != "") else 2)
	card.add_theme_stylebox_override("panel", sb)

	# A VBox that fills the cell and centres its own children — nesting this in a
	# CenterContainer instead shrink-wraps the labels to nothing.
	var v := HJUI.vbox(2)
	v.alignment = BoxContainer.ALIGNMENT_CENTER
	v.size_flags_vertical = Control.SIZE_EXPAND_FILL
	if id == "":
		v.add_child(HJUI.label("+" if holding != "" else "·", int(cell_size * 0.3), "muted", HORIZONTAL_ALIGNMENT_CENTER))
	else:
		v.add_child(HJUI.label(String(room.get("glyph", "·")), int(cell_size * 0.26), glyph_role, HORIZONTAL_ALIGNMENT_CENTER))
		var name_label := HJUI.label(String(room.get("name", id)).replace("The ", ""),
			HJUI.FS_TINY, "text", HORIZONTAL_ALIGNMENT_CENTER)
		name_label.autowrap_mode = TextServer.AUTOWRAP_OFF
		v.add_child(name_label)
	card.add_child(v)

	card.tapped.connect(func() -> void: _tap_cell(x, y))
	return card


func _tap_cell(x: int, y: int) -> void:
	var id := Meta.room_at(x, y)

	if holding != "":
		if id == "":
			Meta.place_room(holding, x, y)
			holding = ""
			refresh()
		return

	if id == "":
		return

	if arranging:
		if Content.room(id).get("starter", false):
			Game.say("The Atrium is the one room that stays put.", "warn")
			return
		holding = id
		Meta.store_room(x, y)
		refresh()
		return

	var screen := String(Content.room(id).get("screen", ""))
	if screen == "":
		Game.say(String(Content.room(id).get("desc", "")), "info")
		return
	Game.goto(screen)


# --- sections ------------------------------------------------------------------

func _bonuses(body: VBoxContainer) -> void:
	var bonuses := Meta.palace_bonuses()
	var card := HJUI.panel("panel", "accent_2" if not bonuses.is_empty() else "")
	var cv := HJUI.vbox(6)
	cv.add_child(HJUI.label("ADJACENCY", HJUI.FS_TINY, "muted"))
	if bonuses.is_empty():
		cv.add_child(HJUI.label("Nothing is touching anything yet. Rooms pay a bonus when the right two sit side by side.", HJUI.FS_SMALL, "muted"))
	else:
		var seen: Array = []
		for bonus in bonuses:
			var pair: Array = [bonus["a"], bonus["b"]]
			pair.sort()
			var key := "%s|%s" % pair
			if seen.has(key):
				continue
			seen.append(key)
			var row := HJUI.hbox(8)
			row.add_child(HJUI.label("%s + %s" % [
				Content.room(String(bonus["a"])).get("name", ""),
				Content.room(String(bonus["b"])).get("name", "")], HJUI.FS_SMALL, "accent_2"))
			cv.add_child(row)
			cv.add_child(HJUI.label(String(bonus["desc"]), HJUI.FS_TINY, "muted"))
	card.add_child(cv)
	body.add_child(card)


func _unplaced(body: VBoxContainer) -> void:
	var spare := Meta.unplaced_rooms()
	if spare.is_empty():
		return
	body.add_child(HJUI.label("WAITING TO BE PLACED", HJUI.FS_SMALL, "accent"))
	for id in spare:
		var room := Content.room(String(id))
		var card := HJUI.panel("panel", "accent")
		var cv := HJUI.vbox(6)
		cv.add_child(HJUI.label("%s  %s" % [room.get("glyph", ""), room.get("name", id)], HJUI.FS_BODY, "text"))
		var take := HJUI.button("Pick up", "primary")
		take.custom_minimum_size.y = 70
		var room_id := String(id)
		take.pressed.connect(func() -> void:
			holding = room_id
			refresh())
		cv.add_child(take)
		card.add_child(cv)
		body.add_child(card)


func _market(body: VBoxContainer) -> void:
	var buyable: Array = Content.rooms.filter(func(r): return not Meta.rooms_owned.has(r.get("id", "")))
	if not buyable.is_empty():
		body.add_child(HJUI.label("ROOMS YOU COULD BUILD", HJUI.FS_SMALL, "muted"))
	for room in buyable:
		var cost := Meta.price(int(room.get("cost", 0)))
		var afford := Meta.resolve >= cost
		var card := HJUI.panel("panel", "accent" if afford else "")
		var cv := HJUI.vbox(6)
		cv.add_child(HJUI.label("%s  %s" % [room.get("glyph", ""), room.get("name", "?")], HJUI.FS_BODY, "text" if afford else "muted"))
		cv.add_child(HJUI.label(String(room.get("desc", "")), HJUI.FS_SMALL, "muted"))
		for neighbour_id in room.get("adjacency", {}).keys():
			var bonus: Dictionary = room["adjacency"][neighbour_id]
			cv.add_child(HJUI.label("next to %s — %s" % [
				Content.room(String(neighbour_id)).get("name", neighbour_id), bonus.get("desc", "")],
				HJUI.FS_TINY, "accent_2"))
		var buy := HJUI.button("Build — %d %s" % [cost, Palette.word("resolve")], "primary" if afford else "ghost", afford)
		buy.custom_minimum_size.y = 70
		var room_id := String(room.get("id", ""))
		buy.pressed.connect(func() -> void:
			if Meta.buy_room(room_id):
				holding = room_id
				Game.say("%s built. Find it a place." % Content.room(room_id).get("name", ""), "good")
				refresh())
		cv.add_child(buy)
		card.add_child(cv)
		body.add_child(card)

	var expand := Meta.expand_cost()
	if expand >= 0:
		var afford_expand := Meta.resolve >= expand
		var card2 := HJUI.panel("panel", "accent" if afford_expand else "")
		var cv2 := HJUI.vbox(6)
		cv2.add_child(HJUI.label(String(Content.palace.get("expand_name", "Widen the Palace")), HJUI.FS_BODY, "text"))
		cv2.add_child(HJUI.label("A bigger grid: %dx%d becomes %dx%d. More room to sit things next to each other." % [
			Meta.palace_size, Meta.palace_size, Meta.palace_size + 1, Meta.palace_size + 1], HJUI.FS_SMALL, "muted"))
		var go := HJUI.button("Widen — %d %s" % [expand, Palette.word("resolve")], "primary" if afford_expand else "ghost", afford_expand)
		go.custom_minimum_size.y = 70
		go.pressed.connect(func() -> void:
			if Meta.expand_palace():
				Game.say("The walls move outward.", "good"))
		cv2.add_child(go)
		card2.add_child(cv2)
		body.add_child(card2)
