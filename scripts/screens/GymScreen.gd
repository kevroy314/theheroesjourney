extends HJScreen
## The Gym: every movement you know, racked and labelled, and the ones still
## behind glass. Doubles as the wiki, the unlock list and the shop — packs open
## in tiers as the journey gets further.

static var axis_filter := ""


func build() -> void:
	var v := page(12)
	v.add_child(HJUI.header("The Gym",
		"%d of %d movements unlocked" % [Content.unlocked_movements().size(), Content.movements.size()],
		func(): Game.goto("palace")))

	var filters := HJUI.hbox(8)
	filters.add_child(_filter("All", ""))
	for axis in Content.axes():
		filters.add_child(_filter(String(axis["name"]), String(axis["id"])))
	v.add_child(filters)

	var scroll := HJUI.scroll()
	var list := HJUI.vbox(12)
	scroll.add_child(list)
	v.add_child(scroll)

	for pack_id in Content.pack_order:
		var card := _pack_card(String(pack_id))
		if card != null:
			list.add_child(card)


func _filter(text: String, id: String) -> Button:
	var b := HJUI.button(text, "primary" if axis_filter == id else "ghost")
	b.custom_minimum_size.y = 58
	b.add_theme_font_size_override("font_size", HJUI.FS_SMALL)
	b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	b.pressed.connect(func() -> void:
		axis_filter = id
		refresh())
	return b


func _pack_card(pack_id: String) -> PanelContainer:
	var pack: Dictionary = Content.packs[pack_id]
	var movements: Array = []
	for m in Content.movements.values():
		if String(m.get("pack", "")) != pack_id:
			continue
		if axis_filter != "" and String(m.get("axis", "")) != axis_filter:
			continue
		movements.append(m)
	if movements.is_empty():
		return null

	var owned := Meta.pack_unlocked(pack_id)
	var needed := int(pack.get("min_chapter", 1))
	var reached := Meta.chapters_reached >= needed
	var cost := Meta.price(int(pack.get("cost", 0)))
	var afford := Meta.resolve >= cost

	var card := HJUI.panel("panel", "good" if owned else ("accent" if (reached and afford) else ""))
	var cv := HJUI.vbox(8)

	var row := HJUI.hbox(10)
	row.add_child(HJUI.label(String(pack.get("name", pack_id)), HJUI.FS_BODY, "text" if owned else "muted"))
	row.add_child(HJUI.label("unlocked" if owned else "locked", HJUI.FS_SMALL,
		"good" if owned else "muted", HORIZONTAL_ALIGNMENT_RIGHT))
	cv.add_child(row)
	cv.add_child(HJUI.label(String(pack.get("desc", "")), HJUI.FS_SMALL, "muted"))

	movements.sort_custom(func(a, b): return String(a.get("name", "")) < String(b.get("name", "")))
	for m in movements:
		cv.add_child(_movement_row(m, owned))

	if not owned:
		if not reached:
			var locked := HJUI.button("Opens at Chapter %d" % needed, "ghost", false)
			locked.custom_minimum_size.y = 70
			cv.add_child(locked)
		else:
			var buy := HJUI.button("Unlock — %d %s" % [cost, Palette.word("resolve")], "primary" if afford else "ghost", afford)
			buy.custom_minimum_size.y = 70
			var id := pack_id
			var pack_name := String(pack.get("name", id))
			buy.pressed.connect(func() -> void:
				if Meta.unlock(id, cost):
					Game.say("%s unlocked." % pack_name, "good"))
			cv.add_child(buy)

	card.add_child(cv)
	return card


func _movement_row(m: Dictionary, owned: bool) -> PanelContainer:
	var units := int(m.get("set", 1))
	var panel := HJUI.panel("panel_alt")
	var sb: StyleBoxFlat = panel.get_theme_stylebox("panel")
	sb.content_margin_top = 10
	sb.content_margin_bottom = 10
	var v := HJUI.vbox(2)

	var row := HJUI.hbox(8)
	row.add_child(HJUI.label(String(m.get("name", "?")), HJUI.FS_SMALL, "text" if owned else "muted"))
	row.add_child(HJUI.label("a set is %d %s" % [units, HJAreaGraph._plural(String(m.get("unit", "rep")), units)],
		HJUI.FS_TINY, "accent" if owned else "muted", HORIZONTAL_ALIGNMENT_RIGHT))
	v.add_child(row)
	v.add_child(HJUI.label("%s · %s" % [Content.axis_name(String(m.get("axis", ""))), m.get("cue", "")],
		HJUI.FS_TINY, "muted"))

	var scaling: Array = m.get("scaling", [])
	if owned and not scaling.is_empty():
		v.add_child(HJUI.label("easier: %s" % ", ".join(scaling), HJUI.FS_TINY, "accent_2"))

	var done := int(Meta.axis_tasks.get(String(m.get("axis", "")), 0))
	if owned and done > 0:
		v.add_child(HJUI.label("%d %s tasks logged" % [done, Content.axis_name(String(m.get("axis", ""))).to_lower()],
			HJUI.FS_TINY, "muted"))

	panel.add_child(v)
	return panel
